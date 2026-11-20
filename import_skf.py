"""
Загрузка реальной базы подшипников SKF (характеристики.xlsx, лист «Каталог_50») в data/catalog.json.

    python import_skf.py характеристики.xlsx             # добавить / обновить позиции SKF
    python import_skf.py характеристики.xlsx --dry-run   # только проверка, файлы не меняются

Что делает:
  * добавляет позиции как role=import (id KRIT-BRG-001…), с реальными d/D/B, C, C0, частотами, массой
    и ссылкой на первоисточник (страница каталога SKF);
  * пишет data/skf_bearings.json {код: [d, D, B]} — nlp_matcher дополняет им reference.BEARINGS;
  * повторный запуск безопасен: прежние KRIT-BRG-* заменяются, остальной каталог не трогается;
  * аналоги НЕ создаются: в источнике их нет, interchange_verified=False у всех позиций;
  * пустые значения (например, частота уплотнённого исполнения у 6300) остаются пустыми — не додумываются.
"""
import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data" / "catalog.json"
BEARINGS_REF = ROOT / "data" / "skf_bearings.json"
SHEET = "Каталог_50"
PREFIX = "KRIT-BRG-"


def num(v):
    if v is None or str(v).strip() == "":
        return None
    f = float(str(v).replace(",", ".").replace(" ", ""))
    return int(f) if f.is_integer() else f


def txt(v):
    return "" if v is None else str(v).strip()


# начало заголовка в xlsx -> (поле каталога, преобразование)
COLS = [
    ("ID КРИТ", "id", txt),
    ("Артикул (базовый)", "code", txt),
    ("Серия", "series", txt),
    ("d —", "inner_diameter", num),
    ("D —", "outer_diameter", num),
    ("B —", "width", num),
    ("C —", "dynamic_rating", num),
    ("C₀", "static_rating", num),
    ("Справочная частота", "reference_speed", num),
    ("Предельная частота", "limiting_speed", num),
    ("Частота для уплотн", "sealed_limiting_speed", num),
    ("Масса по каталогу", "mass_kg", num),
    ("Статус сверки", "data_status", txt),
    ("Источник (URL)", "source_url", txt),
    ("Страница PDF", "source_page", num),
    ("Дата проверки", "checked_at", txt),
    ("Примечание", "data_notes", txt),
    ("Уровень подтверждения", "confirmation", txt),
]
REQUIRED = ["id", "code", "inner_diameter", "outer_diameter", "width"]


def read_xlsx(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    if SHEET not in wb.sheetnames:
        raise SystemExit(f"В файле нет листа «{SHEET}». Есть: {', '.join(wb.sheetnames)}")
    rows = list(wb[SHEET].iter_rows(values_only=True))
    head = [txt(h) for h in rows[0]]
    idx = {}
    for prefix, field, _ in COLS:
        hits = [i for i, h in enumerate(head) if h.startswith(prefix)]
        if not hits:
            raise SystemExit(f"Не найдена колонка «{prefix}…» на листе «{SHEET}»")
        idx[field] = hits[0]
    out = []
    for n, r in enumerate(rows[1:], start=2):
        if not any(c is not None for c in r):
            continue
        rec = {}
        for _, field, conv in COLS:
            rec[field] = conv(r[idx[field]])
        rec["_line"] = n
        out.append(rec)
    return out


def validate(recs):
    ids, codes = set(), set()
    for r in recs:
        n = r["_line"]
        for k in REQUIRED:
            if r[k] in (None, ""):
                raise SystemExit(f"Строка {n}: пустое обязательное поле {k}")
        if not re.fullmatch(r"\d{4}", r["code"]):
            raise SystemExit(f"Строка {n}: артикул {r['code']!r} не похож на базовый номер из 4 цифр")
        if not (0 < r["inner_diameter"] < r["outer_diameter"]) or r["width"] <= 0:
            raise SystemExit(f"Строка {n}: некорректные размеры d/D/B: "
                             f"{r['inner_diameter']}/{r['outer_diameter']}/{r['width']}")
        if r["id"] in ids or r["code"] in codes:
            raise SystemExit(f"Строка {n}: повтор id или артикула ({r['id']} / {r['code']})")
        ids.add(r["id"])
        codes.add(r["code"])


def to_item(r):
    it = {
        "id": r["id"], "role": "import", "brand": "SKF",
        "name": f"Подшипник SKF {r['code']}",
        "category": "Подшипник", "material": "", "standard": "",
        "series": r["series"],
    }
    for k in ("inner_diameter", "outer_diameter", "width", "dynamic_rating", "static_rating",
              "reference_speed", "limiting_speed", "sealed_limiting_speed", "mass_kg"):
        if r[k] is not None:          # пусто в источнике = поля нет в каталоге
            it[k] = r[k]
    it.update({
        "interchange_verified": False,
        "data_status": r["data_status"], "data_notes": r["data_notes"],
        "confirmation": r["confirmation"],
        "source_url": r["source_url"], "source_page": r["source_page"], "checked_at": r["checked_at"],
    })
    return it


def main():
    args = sys.argv[1:]
    files = [a for a in args if not a.startswith("--")]
    if len(files) != 1:
        raise SystemExit(__doc__)
    recs = read_xlsx(files[0])
    validate(recs)
    new = [to_item(r) for r in recs]

    items = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else []
    kept = [x for x in items if not str(x["id"]).startswith(PREFIX)]
    replaced = len(items) - len(kept)

    codes = {r["code"] for r in recs}
    dup = [x["name"] for x in kept if x["role"] == "import" and x.get("brand") == "SKF"
           and (m := re.search(r"(?<!\d)(\d{4})(?!\d)", x["name"])) and m.group(1) in codes]

    print(f"Прочитано {len(new)} позиций SKF; заменено прежних KRIT-BRG: {replaced}.")
    gaps = [x for x in new if "sealed_limiting_speed" not in x]
    if gaps:
        print("Пустое поле «частота для уплотнённого исполнения»: " + ", ".join(x["name"] for x in gaps))
    if dup:
        print(f"Внимание: в каталоге уже есть {len(dup)} синтетических импортных SKF с теми же номерами "
              "(остаются как есть, с их аналогами).")
    if "--dry-run" in args:
        print("--dry-run: файлы не изменены.")
        return

    CATALOG.parent.mkdir(exist_ok=True)
    CATALOG.write_text(json.dumps(kept + new, ensure_ascii=False, indent=2), encoding="utf-8")
    BEARINGS_REF.write_text(
        json.dumps({r["code"]: [r["inner_diameter"], r["outer_diameter"], r["width"]] for r in recs},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Готово. В каталоге: {len(kept) + len(new)} позиций. Справочник типоразмеров: {BEARINGS_REF.name}.")


if __name__ == "__main__":
    main()
