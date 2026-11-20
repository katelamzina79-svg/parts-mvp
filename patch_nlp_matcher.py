"""
Однократный патч nlp_matcher.py под реальные данные SKF (делает копию nlp_matcher.py.bak):
  1. reference.BEARINGS дополняется data/skf_bearings.json (50 реальных типоразмеров);
  2. новые параметры подшипника: динамическая C, статическая C0, предельная частота — сравнение «не ниже»;
  3. извлечение из текста запроса: «C=29,6 кН», «C0=19000», «предельная частота 20000 об/мин».
Запросы без этих параметров считаются как раньше (новые ключи пустые и в скоринге не участвуют).

    python patch_nlp_matcher.py
"""
import shutil
import sys
from pathlib import Path

P = Path(__file__).resolve().parent / "nlp_matcher.py"

EDITS = [
    # 1. справочник типоразмеров
    ("from reference import BEARINGS\n",
     "from reference import BEARINGS\n"
     "\n"
     "# реальные типоразмеры из базы SKF (import_skf.py) дополняют reference.BEARINGS\n"
     "_SKF_REF = Path(__file__).resolve().parent / \"data\" / \"skf_bearings.json\"\n"
     "if _SKF_REF.exists():\n"
     "    BEARINGS = {**BEARINGS, **{k: tuple(v) for k, v in\n"
     "                               json.loads(_SKF_REF.read_text(encoding=\"utf-8\")).items()}}\n"),
    # 2. параметры
    ('    "variant": ("исполнение (уплотнение)", "", "seal"),\n}',
     '    "variant": ("исполнение (уплотнение)", "", "seal"),\n'
     '    "dynamic_rating": ("динамическая грузоподъёмность C (не ниже)", "Н", "ge"),\n'
     '    "static_rating": ("статическая грузоподъёмность C₀ (не ниже)", "Н", "ge"),\n'
     '    "limiting_speed": ("предельная частота (не ниже)", "об/мин", "ge"),\n}'),
    ('    "Подшипник": ["inner_diameter", "outer_diameter", "width", "variant"],',
     '    "Подшипник": ["inner_diameter", "outer_diameter", "width", "variant",\n'
     '                  "dynamic_rating", "static_rating", "limiting_speed"],'),
    # 3. regex
    ('RE_SEAL = re.compile(r"(2RSH|2RS|2Z|ZZ)\\b", re.IGNORECASE)\n',
     'RE_SEAL = re.compile(r"(2RSH|2RS|2Z|ZZ)\\b", re.IGNORECASE)\n'
     'RE_DYN = re.compile(r"(?<![\\w])C\\s*[=:]\\s*" + NUM + r"\\s*((?i:кН|kN))?")\n'
     'RE_STAT = re.compile(r"(?<![\\w])C(?:0|₀)\\s*[=:]\\s*" + NUM + r"\\s*((?i:кН|kN))?")\n'
     'RE_LIMSPEED = re.compile(\n'
     '    r"(?i:предельн\\w*\\s+(?:частот\\w*|скорост\\w*)|limiting\\s+speed)\\s*[=:]?\\s*(\\d[\\d\\s]*\\d|\\d)\\s*(?i:об/мин|rpm)")\n'),
    # 4. извлечение
    ('    if want("Подшипник"):\n        put("variant"',
     '    if want("Подшипник"):\n'
     '        for key, rx in (("dynamic_rating", RE_DYN), ("static_rating", RE_STAT)):\n'
     '            m = rx.search(body)\n'
     '            if m:\n'
     '                put(key, _num(m.group(1)) * (1000 if m.group(2) else 1))\n'
     '        m = RE_LIMSPEED.search(body)\n'
     '        if m:\n'
     '            put("limiting_speed", _num(re.sub(r"\\s", "", m.group(1))))\n'
     '        put("variant"'),
]


def main():
    src = P.read_text(encoding="utf-8")
    if "dynamic_rating" in src:
        raise SystemExit("nlp_matcher.py уже пропатчен.")
    for old, _ in EDITS:
        if src.count(old) != 1:
            raise SystemExit(f"Не нашла ровно одно вхождение фрагмента (нашла {src.count(old)}):\n{old}\n"
                             "Файл отличается от ожидаемого — файл не изменён.")
    shutil.copy(P, P.with_suffix(".py.bak"))
    for old, new in EDITS:
        src = src.replace(old, new)
    P.write_text(src, encoding="utf-8")
    print("nlp_matcher.py обновлён (копия: nlp_matcher.py.bak).")


if __name__ == "__main__":
    sys.exit(main())
