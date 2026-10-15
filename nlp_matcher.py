"""
NLP-модуль Платформы КРИТ.
Двухслойный мэтчинг: rule-based извлечение характеристик + семантические эмбеддинги.
"""
import json
import re
from pathlib import Path

from rapidfuzz import fuzz

from embeddings import semantic_scores
from reference import BEARINGS

DATA = Path(__file__).resolve().parent / "data" / "catalog.json"

# Веса слоёв скоринга (сумма = 1). Учитываются только слои, по которым есть данные.
WEIGHTS = {
    "specs": 0.35,      # числовые и категориальные параметры
    "semantic": 0.30,   # близость описаний (эмбеддинги)
    "name": 0.10,       # нечёткое совпадение названий
    "article": 0.10,    # артикул/типоразмер найден в названии
    "standard": 0.05,
    "material": 0.05,
    "category": 0.05,
}

PARAM_FAIL_FACTOR = 0.75

# --------------------------------------------------------------- категории
CATEGORY_PATTERNS = {
    "Подшипник": r"подшипн|bearing|\b6[0236]\d{2}\b|\b(?:skf|fag|nsk|ntn|timken|koyo)\b",
    "Пневматика": r"пневм|цилиндр|dsnu|pneumat|\b(?:festo|smc|camozzi|parker)\b",
    "Электрика": r"автомат|выключател|реле|контактор|ic60|\b(?:schneider|abb|siemens|legrand)\b",
    "Уплотнение": r"манжет|уплотн|сальник|\bseal|baum|simrit|freudenberg|trelleborg",
    "Насос": r"насос|\bpump|\bcr\s*\d|grundfos|\bwilo\b|\bksb\b",
    "КИП": r"датчик|преобразовател|манометр|sensor|cerabar|endress|emerson|yokogawa",
}
CATEGORY_RE = {k: re.compile(v, re.IGNORECASE) for k, v in CATEGORY_PATTERNS.items()}

MATERIALS = [
    "Сталь ШХ15", "Нержавеющая сталь", "Нерж. сталь", "Сталь",
    "Бронза", "Латунь", "Резина NBR", "Резина", "Полимер", "Чугун", "Алюминий",
]

# ------------------------------------------------------------- спецификации
# ключ: (подпись, единица, режим сравнения)
#   abs   — допуск в мм (0/1/3 мм); rel — относительный допуск (5%/15%);
#   exact — только точное совпадение; eq — равенство строк; ip — IP кандидата не ниже запроса;
#   seal  — тип уплотнения подшипника (2RS ≡ 2RSH, ZZ ≡ 2Z)
SPEC_DEFS = {
    "inner_diameter": ("внутренний диаметр d", "мм", "abs"),
    "outer_diameter": ("наружный диаметр D", "мм", "abs"),
    "width": ("ширина B", "мм", "abs"),
    "stroke": ("ход", "мм", "abs"),
    "pressure": ("рабочее давление", "бар", "rel"),
    "voltage": ("напряжение", "В", "exact"),
    "current": ("номинальный ток", "А", "rel"),
    "poles": ("число полюсов", "", "exact"),
    "flow": ("подача", "м³/ч", "rel"),
    "head": ("напор", "м", "rel"),
    "power": ("мощность", "кВт", "rel"),
    "range_min": ("начало диапазона", "бар", "rel"),
    "range_max": ("верхний предел", "бар", "rel"),
    "output": ("выходной сигнал", "", "eq"),
    "ip": ("степень защиты", "", "ip"),
    "variant": ("исполнение (уплотнение)", "", "seal"),
}
CAT_SPECS = {
    "Подшипник": ["inner_diameter", "outer_diameter", "width", "variant"],
    "Пневматика": ["inner_diameter", "stroke", "pressure"],
    "Электрика": ["voltage", "current", "poles"],
    "Уплотнение": ["inner_diameter", "outer_diameter", "width"],
    "Насос": ["flow", "head", "power"],
    "КИП": ["range_min", "range_max", "output", "ip"],
}
LABEL_OVERRIDE = {("Пневматика", "inner_diameter"): "диаметр поршня"}
ALL_SPEC_KEYS = list(SPEC_DEFS)

# ------------------------------------------------------------------- regex
NUM = r"(\d+(?:[.,]\d+)?)"
# d/D различаем по регистру: одиночные буквы — case-sensitive, слова — case-insensitive
RE_INNER_STRICT = re.compile(r"(?<![\w])(?:d|(?i:внутр\w*|inner))\s*[=:]\s*" + NUM)
RE_OUTER = re.compile(r"(?<![\w])(?:D|(?i:наружн\w*|outer))\s*[=:]\s*" + NUM)
RE_WIDTH = re.compile(r"(?<![\w])(?:B|H|(?i:ширин\w*|высот\w*|width))\s*[=:]\s*" + NUM)
RE_DXDXB = re.compile(NUM + r"\s*[хx×]\s*" + NUM + r"\s*[хx×]\s*" + NUM)
RE_DXD = re.compile(NUM + r"\s*[хx×]\s*" + NUM)
RE_STANDARD = re.compile(
    r"(ГОСТ(?:\s*Р)?\s*[\d\.\-]+|ISO\s*[\d\.:\-]+|DIN\s*[\d\.\-]+|IEC\s*[\d\.\-]+)", re.IGNORECASE)
RE_OUTPUT = re.compile(r"4\s*[-–]\s*20\s*мА|0\s*[-–]\s*10\s*В|\bHART\b|\bRS-?485\b", re.IGNORECASE)
RE_IP = re.compile(r"\bIP\s?(\d{2})\b", re.IGNORECASE)
RE_CURRENT = re.compile(r"(?<![\w.,])" + NUM + r"\s*[AА](?!\w)")
RE_POLES = re.compile(r"(?<![\w])([1-4])\s*[PР](?!\w)|(?<![\w])([1-4])\s*-?\s*(?i:полюс\w*)")
RE_VOLTAGE = re.compile(r"(?<![\w.,])(\d{2,3})\s*(?:В|V)(?!\w)")
RE_POWER = re.compile(r"(?<![\w.,])" + NUM + r"\s*(?i:кВт|kW)")
RE_FLOW = re.compile(NUM + r"\s*(?i:м³/ч|м3/ч|m3/h|куб\.?\s*м/ч)")
RE_HEAD = re.compile(r"(?<![\w.,])" + NUM + r"\s*м(?![\w³²/])")
RE_BAR = re.compile(NUM + r"\s*(?i:бар|bar)")
RE_RANGE = re.compile(r"(-?\d+)\s*(?:\.{2,3}|…|—|–|-)\s*(\d+)\s*(?i:бар|bar)")
RE_DSNU = re.compile(r"\bDSNU[-\s]*(\d+)[-–\s]+(\d+)", re.IGNORECASE)
RE_CR = re.compile(r"\bCR\s*(\d+)\s*[-–]\s*(\d+)", re.IGNORECASE)
RE_CERABAR = re.compile(r"\bCerabar\s*\w*?\s*(\d{2,4})\b|\bДМ[-\s]*(\d{2,4})\b", re.IGNORECASE)
RE_BEARING_CODE = re.compile(r"(?<![\w])(6[0236]\d{2})(?!\d)")
RE_SEAL = re.compile(r"(2RSH|2RS|2Z|ZZ)\b", re.IGNORECASE)
RE_TOKEN = re.compile(r"[A-Za-zА-Яа-я0-9][\w\-./]*")

_UNIT_TOKEN = re.compile(
    r"^(?:\d{1,3}|-?\d+[-–]\d+|\d+(?:[.,]\d+)?(?:[AАPРВV]|мА|кВт|kW|бар|bar|мм|м|В)|IP\d+|\d+[xх×]\d+.*)$",
    re.IGNORECASE)


def _num(s):
    return float(str(s).replace(",", "."))


def _norm_seal(v):
    v = (v or "").upper()
    return {"2RSH": "seal", "2RS": "seal", "ZZ": "shield", "2Z": "shield"}.get(v)


def _variant(text):
    m = RE_SEAL.search(text or "")
    return m.group(1).upper() if m else None


def _ip_num(v):
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def _fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _norm_output(s):
    s = s.upper().replace("–", "-").replace(" ", "")
    if s.startswith("4-20"):
        return "4-20 мА"
    if s.startswith("0-10"):
        return "0-10 В"
    if s.startswith("RS"):
        return "RS-485"
    return s


# --------------------------------------------------------------- извлечение
def _pick_article(body):
    """Первый токен вида «буквы+цифры» (iC60N, DSNU-25-100, 6205-2RS) или длинное число."""
    cands = []
    for tok in RE_TOKEN.findall(body):
        tok = tok.rstrip(".-/")
        if not re.search(r"\d", tok) or _UNIT_TOKEN.match(tok):
            continue
        cands.append(tok)
    for tok in cands:
        if re.search(r"[A-Za-zА-Яа-я]", tok):
            return tok.upper()
    for tok in cands:
        if len(re.sub(r"\D", "", tok)) >= 4:
            return tok.upper()
    return None


def extract_features(text):
    feats = {"raw": (text or "").strip(), "categories": [], "materials": [],
             "standard": None, "article": None, "inferred": []}
    for k in ALL_SPEC_KEYS:
        feats[k] = None
    if not text:
        return feats

    low = text.lower()
    for cat, rx in CATEGORY_RE.items():
        if rx.search(text):
            feats["categories"].append(cat)
    cats = feats["categories"]

    def want(cat):
        return not cats or cat in cats

    for m in MATERIALS:
        if m.lower() in low:
            feats["materials"].append(m)

    def put(key, val):
        if feats[key] is None and val is not None:
            feats[key] = val

    m = RE_STANDARD.search(text)
    if m:
        feats["standard"] = re.sub(r"\s+", " ", m.group(1)).strip()
    body = RE_STANDARD.sub(" ", text)

    m = RE_OUTPUT.search(body)
    if m:
        put("output", _norm_output(m.group(0)))
    body = RE_OUTPUT.sub(" ", body)

    # размеры с метками (d=, D=, B=)
    m = RE_INNER_STRICT.search(body)
    if m:
        put("inner_diameter", _num(m.group(1)))
    m = RE_OUTER.search(body)
    if m:
        put("outer_diameter", _num(m.group(1)))
    m = RE_WIDTH.search(body)
    if m:
        put("width", _num(m.group(1)))

    # размеры вида 30x47x7 (уплотнения, подшипники) и 25x100 (цилиндры)
    if feats["inner_diameter"] is None:
        m = RE_DXDXB.search(body)
        if m:
            put("inner_diameter", _num(m.group(1)))
            put("outer_diameter", _num(m.group(2)))
            put("width", _num(m.group(3)))
        elif "Пневматика" in cats:
            m = RE_DXD.search(body)
            if m:
                put("inner_diameter", _num(m.group(1)))
                put("stroke", _num(m.group(2)))

    # пневматика
    if want("Пневматика"):
        m = RE_DSNU.search(body)
        if m:
            put("inner_diameter", _num(m.group(1)))
            put("stroke", _num(m.group(2)))
        if "Пневматика" in cats:
            m = RE_BAR.search(body)
            if m:
                put("pressure", _num(m.group(1)))

    # электрика
    if want("Электрика"):
        m = RE_POLES.search(body)
        if m:
            put("poles", _num(m.group(1) or m.group(2)))
        m = RE_CURRENT.search(body)
        if m:
            put("current", _num(m.group(1)))
        m = RE_VOLTAGE.search(body)
        if m:
            put("voltage", _num(m.group(1)))

    # насосы
    if want("Насос"):
        m = RE_CR.search(body)
        if m:
            put("flow", _num(m.group(1)))
            put("head", _num(m.group(2)))
            feats["article"] = f"CR {m.group(1)}-{m.group(2)}"
        m = RE_FLOW.search(body)
        if m:
            put("flow", _num(m.group(1)))
        m = RE_HEAD.search(body)
        if m and "Насос" in cats:
            put("head", _num(m.group(1)))
        m = RE_POWER.search(body)
        if m:
            put("power", _num(m.group(1)))

    # КИП
    if want("КИП"):
        m = RE_RANGE.search(body)
        if m:
            put("range_min", _num(m.group(1)))
            put("range_max", _num(m.group(2)))
        m = RE_CERABAR.search(body)
        if m:
            put("range_max", _num(m.group(1) or m.group(2)))
        if "КИП" in cats:
            m = RE_BAR.search(body)
            if m:
                put("range_max", _num(m.group(1)))
        m = RE_IP.search(body)
        if m:
            put("ip", "IP" + m.group(1))

    # подшипники: код -> стандартные размеры, если они не заданы явно
    if want("Подшипник"):
        put("variant", _variant(body) if re.search(r"\d{4}\s?-?\s?(?:2RSH|2RS|2Z|ZZ)\b", body, re.I) else None)
        m = RE_BEARING_CODE.search(body)
        if m and m.group(1) in BEARINGS:
            d, D, B = BEARINGS[m.group(1)]
            for key, val in (("inner_diameter", d), ("outer_diameter", D), ("width", B)):
                if feats[key] is None:
                    feats[key] = float(val)
                    feats["inferred"].append(key)

    if feats["article"] is None:
        feats["article"] = _pick_article(body)
    return feats


# ------------------------------------------------------------------ скоринг
def _cand_value(cand, key):
    if key == "variant":
        return _variant(cand.get("name"))
    return cand.get(key)


def _cmp_spec(mode, q, c):
    """Оценка совпадения одного параметра, 0..1."""
    if mode == "abs":
        d = abs(q - c)
        return 1.0 if d < 0.01 else 0.7 if d < 1 else 0.3 if d < 3 else 0.0
    if mode == "rel":
        r = abs(q - c) / max(abs(q), abs(c), 1e-9)
        return 1.0 if r < 1e-4 else 0.6 if r <= 0.05 else 0.25 if r <= 0.15 else 0.0
    if mode == "exact":
        return 1.0 if abs(q - c) < 1e-9 else 0.0
    if mode == "ip":
        qi, ci = _ip_num(q), _ip_num(c)
        return None if qi is None or ci is None else (1.0 if ci >= qi else 0.0)
    if mode == "seal":
        qn, cn = _norm_seal(q), _norm_seal(c)
        return None if qn is None or cn is None else (1.0 if qn == cn else 0.0)
    return 1.0 if str(q).upper() == str(c).upper() else 0.0


def _spec_pairs(feats, cand):
    """[(key, mode, q, c, оценка)] для параметров, известных и в запросе, и у кандидата."""
    keys = CAT_SPECS.get(cand.get("category"), ALL_SPEC_KEYS)
    out = []
    for k in keys:
        q, c = feats.get(k), _cand_value(cand, k)
        if q is None or c is None:
            continue
        s = _cmp_spec(SPEC_DEFS[k][2], q, c)
        if s is not None:
            out.append((k, SPEC_DEFS[k][2], q, c, s))
    return out


def _std_family(s):
    s = s.upper().replace(" ", "")
    for fam in ("ГОСТ", "ISO", "DIN", "IEC"):
        if s.startswith(fam):
            return fam
    return s


def score_candidate(feats, cand, sem_score):
    """Оценка взаимозаменяемости 0..100 и доля «доказательной базы» (coverage 0..1)."""
    scores = {}

    if feats["categories"]:
        if cand["category"] not in feats["categories"]:
            return 0, 0.0
        scores["category"] = 1.0

    pairs = _spec_pairs(feats, cand)
    if pairs:
        scores["specs"] = sum(p[4] for p in pairs) / len(pairs)

    # стандарт: разные семейства (ISO/DIN → ГОСТ) — это нормальный «перевод», не штрафуем
    if feats["standard"] and cand.get("standard"):
        q, c = feats["standard"], cand["standard"]
        if _std_family(q) == _std_family(c):
            same = q.upper().replace(" ", "") == c.upper().replace(" ", "")
            scores["standard"] = 1.0 if same else 0.3

    if feats["materials"]:
        mat = cand.get("material", "").lower()
        scores["material"] = 1.0 if any(m.lower() in mat for m in feats["materials"]) else 0.3

    scores["name"] = fuzz.token_set_ratio(feats["raw"], cand["name"]) / 100.0
    scores["semantic"] = sem_score

    # артикул: точное вхождение — плюс; отсутствие не штрафуем (аналог по определению
    # имеет другой артикул)
    if feats["article"] and feats["article"] in cand["name"].upper():
        scores["article"] = 1.0

    total = wsum = 0.0
    for k, w in WEIGHTS.items():
        v = scores.get(k)
        if v is not None:
            total += v * w
            wsum += w
    if wsum == 0:
        return 0, 0.0
    score = total / wsum * 100
    # Жёсткий штраф: несовпадение размера/параметра — это не «чуть хуже», а риск
    # несовместимости, поэтому каждый провалившийся параметр снижает итог на 25%.
    fails = sum(1 for p in pairs if p[4] < 0.3)
    score *= PARAM_FAIL_FACTOR ** fails
    return round(score, 1), round(wsum, 2)


def load_catalog():
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def _availability_key(item):
    offers = item.get("offers") or []
    in_stock = [o for o in offers if o["stock"] > 0]
    if in_stock:
        return (0, min(o["price"] for o in in_stock))
    return (1, min((o["lead_days"] for o in offers), default=999))


def find_analogues(query_text, catalog, top_k=10):
    feats = extract_features(query_text)
    sem_raw = semantic_scores(query_text, catalog)

    pool = [it for it in catalog if it["role"] == "russian"
            and (not feats["categories"] or it["category"] in feats["categories"])]
    # Нормировка семантики по кандидатам: у e5 сырые косинусы лежат в узком диапазоне
    vals = [sem_raw.get(it["id"], 0.0) for it in pool]
    lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
    span = (hi - lo) or 1.0

    scored = []
    for it in pool:
        sem = (sem_raw.get(it["id"], 0.0) - lo) / span
        s, cov = score_candidate(feats, it, sem)
        if s > 0:
            scored.append({"item": it, "score": s, "coverage": cov})
    scored.sort(key=lambda x: (-x["score"], _availability_key(x["item"])))
    return feats, scored[:top_k]


# --------------------------------------------------------------- объяснение
def _label(cat, key):
    return LABEL_OVERRIDE.get((cat, key)) or SPEC_DEFS[key][0]


def diff_report(feats, cand):
    """(совпадает, отличается, вердикт) по всем параметрам категории."""
    same, diff = [], []
    cat = cand.get("category")
    for k, mode, q, c, s in _spec_pairs(feats, cand):
        unit = SPEC_DEFS[k][1]
        u = f" {unit}" if unit else ""
        qv = _fmt(q) if not isinstance(q, str) else q
        cv = _fmt(c) if not isinstance(c, str) else c
        if k == "variant":
            qv, cv = q, _variant(cand.get("name"))
        if s >= 1.0:
            same.append(f"{_label(cat, k)}: {cv}{u}")
        else:
            diff.append(f"{_label(cat, k)}: {qv} → {cv}{u}")

    if feats["standard"] and cand.get("standard"):
        qs, cs = feats["standard"], cand["standard"]
        if qs.upper().replace(" ", "") == cs.upper().replace(" ", ""):
            same.append(f"стандарт: {cs}")
        elif _std_family(qs) == _std_family(cs):
            diff.append(f"стандарт: {qs} → {cs}")

    if diff:
        verdict = {"code": "check", "text": "Требует проверки инженером"}
    elif same:
        verdict = {"code": "full", "text": "Совпадает по всем найденным параметрам"}
    else:
        verdict = {"code": "unknown", "text": "Недостаточно данных для сравнения"}
    return same, diff, verdict
