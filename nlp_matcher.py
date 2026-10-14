"""
NLP-модуль для Платформы КРИТ.
Извлекает характеристики из текста и подбирает российские аналоги.
"""
import json
import re
from pathlib import Path
from rapidfuzz import fuzz

DATA = Path(__file__).resolve().parent / "data" / "catalog.json"


# Какие категории есть в каталоге и по каким словам их узнаём
CATEGORY_KEYWORDS = {
    "Подшипник": ["подшипник", "bearing", "6205", "6206", "6305"],
    "Пневматика": ["пневмо", "цилиндр", "пневматич", "dsnu", "pneumatic"],
    "Электрика": ["автомат", "автоматич", "выключатель", "реле", "контактор", "ic60"],
    "Уплотнение": ["манжета", "уплотн", "сальник", "seal", "baum"],
    "Насос": ["насос", "pump", "cr ", "grundfos"],
    "КИП": ["датчик", "преобразователь", "манометр", "sensor", "cerabar"],
}

MATERIALS = [
    "Сталь ШХ15", "Нержавеющая сталь", "Нерж. сталь", "Сталь",
    "Бронза", "Латунь", "Резина NBR", "Резина", "Полимер", "Чугун", "Алюминий",
]

# Регулярки для извлечения параметров
RE_INNER = re.compile(r"(?:d|внутр\w*|inner)\s*[=:]\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
RE_OUTER = re.compile(r"(?<![\w])(?:D|наружн\w*|outer)\s*[=:]\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
RE_WIDTH = re.compile(r"(?:B|H|ширин\w*|высот\w*|width)\s*[=:]\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
RE_DXDXB = re.compile(r"(\d+(?:[.,]\d+)?)\s*[хx×]\s*(\d+(?:[.,]\d+)?)\s*[хx×]\s*(\d+(?:[.,]\d+)?)")
RE_STANDARD = re.compile(r"(ГОСТ(?:\s*Р)?\s*[\d\.\-]+|ISO\s*[\d\.:\-]+|DIN\s*[\d\.\-]+|IEC\s*[\d\.\-]+)", re.IGNORECASE)
RE_ARTICLE = re.compile(r"\b([A-ZА-Я]{0,4}[\d]{3,}[\w\-]*)\b", re.IGNORECASE)


def _to_float(s):
    return float(str(s).replace(",", "."))


def extract_features(text):
    """Извлекает характеристики из свободного текста."""
    feats = {
        "raw": text.strip(),
        "categories": [],
        "materials": [],
        "standard": None,
        "inner_diameter": None,
        "outer_diameter": None,
        "width": None,
        "article": None,
    }
    if not text:
        return feats

    low = text.lower()

    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in low for kw in kws):
            feats["categories"].append(cat)

    for m in MATERIALS:
        if m.lower() in low:
            feats["materials"].append(m)

    m = RE_INNER.search(text)
    if m:
        feats["inner_diameter"] = _to_float(m.group(1))
    m = RE_OUTER.search(text)
    if m:
        feats["outer_diameter"] = _to_float(m.group(1))
    m = RE_WIDTH.search(text)
    if m:
        feats["width"] = _to_float(m.group(1))

    # формат "25х52х15"
    if feats["inner_diameter"] is None:
        m = RE_DXDXB.search(text)
        if m:
            feats["inner_diameter"] = _to_float(m.group(1))
            feats["outer_diameter"] = _to_float(m.group(2))
            feats["width"] = _to_float(m.group(3))

    m = RE_STANDARD.search(text)
    if m:
        feats["standard"] = re.sub(r"\s+", " ", m.group(1)).strip()

    m = RE_ARTICLE.search(text)
    if m:
        feats["article"] = m.group(1).upper()

    return feats


def _score_numeric(q, c, keys):
    matched = 0
    total = 0
    for k in keys:
        qv = q.get(k)
        cv = c.get(k)
        if qv is None or cv is None:
            continue
        total += 1
        diff = abs(qv - cv)
        if diff < 0.01:
            matched += 1
        elif diff < 1.0:
            matched += 0.7
        elif diff < 3.0:
            matched += 0.3
    if total == 0:
        return None
    return matched / total


def score_candidate(feats, cand):
    """Оценка взаимозаменяемости 0–100."""
    scores = {}

    # Категория — жёсткий фильтр
    if feats["categories"]:
        if cand["category"] not in feats["categories"]:
            return 0
        scores["category"] = 1.0
    else:
        scores["category"] = None

    # Числовые параметры
    numeric_keys = ["inner_diameter", "outer_diameter", "width", "stroke", "pressure", "current", "flow", "head", "range_max"]
    scores["specs"] = _score_numeric(feats, cand, numeric_keys)

    # Стандарт
    if feats["standard"] and cand.get("standard"):
        q = feats["standard"].upper().replace(" ", "")
        c = cand["standard"].upper().replace(" ", "")
        scores["standard"] = 1.0 if q == c else 0.3
    else:
        scores["standard"] = None

    # Материал
    if feats["materials"]:
        if any(m.lower() in cand["material"].lower() for m in feats["materials"]):
            scores["material"] = 1.0
        else:
            scores["material"] = 0.3
    else:
        scores["material"] = None

    # Текстовое сходство
    scores["name"] = fuzz.token_set_ratio(feats["raw"], cand["name"]) / 100.0

    # Артикул
    if feats["article"]:
        art = feats["article"].upper()
        if art in cand["name"].upper():
            scores["article"] = 1.0
        else:
            parts = [p for p in re.findall(r"\d+", art) if len(p) >= 3]
            if parts and any(p in cand["name"] for p in parts):
                scores["article"] = 0.7
            else:
                scores["article"] = 0.0
    else:
        scores["article"] = None

    weights = {"category": 0.10, "specs": 0.35, "standard": 0.10, "material": 0.10, "name": 0.20, "article": 0.15}
    total = 0.0
    wsum = 0.0
    for k, w in weights.items():
        v = scores.get(k)
        if v is not None:
            total += v * w
            wsum += w
    if wsum == 0:
        return 0
    return round((total / wsum) * 100, 1)


def load_catalog():
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def find_analogues(query_text, catalog, top_k=10):
    """Главная функция: текст → список аналогов."""
    feats = extract_features(query_text)
    scored = []
    for item in catalog:
        if item["role"] != "russian":
            continue
        s = score_candidate(feats, item)
        if s > 0:
            scored.append({"item": item, "score": s})
    scored.sort(key=lambda x: -x["score"])
    return feats, scored[:top_k]


def diff_report(feats, candidate):
    """Что совпало, что различается — для UI."""
    same, diff = [], []
    for key, label in [
        ("inner_diameter", "внутренний диаметр"),
        ("outer_diameter", "наружный диаметр"),
        ("width", "ширина"),
    ]:
        q = feats.get(key)
        c = candidate.get(key)
        if q is None or c is None:
            continue
        if abs(q - c) < 0.01:
            same.append(f"{label}: {c}")
        else:
            diff.append(f"{label}: {q} → {c}")
    if feats["standard"] and candidate.get("standard"):
        if feats["standard"].upper().replace(" ", "") == candidate["standard"].upper().replace(" ", ""):
            same.append(f"стандарт: {candidate['standard']}")
        else:
            diff.append(f"стандарт: {feats['standard']} → {candidate['standard']}")
    return same, diff