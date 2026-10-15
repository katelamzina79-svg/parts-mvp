"""
Загрузка реального каталога из CSV (Excel: «Сохранить как» → CSV UTF-8).

    python import_catalog.py мой_каталог.csv            # добавить позиции к data/catalog.json
    python import_catalog.py мой_каталог.csv --replace  # заменить весь каталог
    python import_catalog.py --template                 # создать шаблон catalog_template.csv

Одна строка = одна позиция. Обязательные колонки: role (import / russian), category, brand, name.
Необязательные: id, material, standard, числовые параметры (inner_diameter, outer_diameter,
width, stroke, pressure, voltage, current, poles, flow, head, power, range_min, range_max),
текстовые (output, ip), предложение поставщика (supplier, city, verified, price, stock, lead_days),
связь аналога с оригиналом (analogue_of — id или точное название импортной позиции;
нужна только для eval.py).
Разделитель «,» или «;», десятичная запятая допускается.
"""
import csv
import json
import sys
from pathlib import Path

from nlp_matcher import CAT_SPECS

CATALOG = Path(__file__).resolve().parent / "data" / "catalog.json"
NUMERIC = ["inner_diameter", "outer_diameter", "width", "stroke", "pressure", "voltage", "current",
           "poles", "flow", "head", "power", "range_min", "range_max"]
TEXT = ["material", "standard", "output", "ip"]
REQUIRED = ["role", "category", "brand", "name"]
TEMPLATE = [
    "id,role,category,brand,name,material,standard,inner_diameter,outer_diameter,width,supplier,city,verified,price,stock,lead_days,analogue_of",
    ",import,Подшипник,SKF,Подшипник SKF 6205-2RS,Сталь,ISO 15,25,52,15,,,,,,,",
    ",russian,Подшипник,ГПЗ-1,Подшипник 6205-2RS ГПЗ-1 ГОСТ 8338-75,Сталь ШХ15,ГОСТ 8338-75,25,52,15,Пример-Снаб,Москва,да,420,150,3,Подшипник SKF 6205-2RS",
]


def num(v, line, col):
    try:
        return float(v.replace(",", ".").replace(" ", ""))
    except ValueError:
        raise SystemExit(f"Строка {line}: в колонке «{col}» не число: {v!r}")


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = f.readline()
        f.seek(0)
        delim = ";" if head.count(";") > head.count(",") else ","
        return list(csv.DictReader(f, delimiter=delim))


def main():
    args = sys.argv[1:]
    if "--template" in args:
        Path("catalog_template.csv").write_text("\n".join(TEMPLATE) + "\n", encoding="utf-8")
        print("Создан catalog_template.csv")
        return
    files = [a for a in args if not a.startswith("--")]
    if len(files) != 1:
        raise SystemExit(__doc__)
    rows = read_rows(files[0])
    if not rows:
        raise SystemExit("Файл пустой")
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        raise SystemExit(f"Нет обязательных колонок: {', '.join(missing)}")

    items = [] if "--replace" in args else json.loads(CATALOG.read_text(encoding="utf-8"))
    used = {x["id"] for x in items}
    counter = {"import": 0, "russian": 0}
    new, by_name = [], {}
    warnings = set()

    for n, r in enumerate(rows, start=2):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        role = r["role"].lower()
        if role not in counter:
            raise SystemExit(f"Строка {n}: role должен быть import или russian, а не {r['role']!r}")
        if not (r["category"] and r["name"] and r["brand"]):
            raise SystemExit(f"Строка {n}: category, brand и name обязательны")
        if r["category"] not in CAT_SPECS:
            warnings.add(r["category"])
        iid = r.get("id")
        if not iid:
            while True:
                counter[role] += 1
                iid = f"{role}_u{counter[role]:03d}"
                if iid not in used:
                    break
        if iid in used:
            raise SystemExit(f"Строка {n}: id {iid!r} уже существует")
        used.add(iid)
        it = {"id": iid, "role": role, "brand": r["brand"], "name": r["name"], "category": r["category"]}
        for k in TEXT:
            if r.get(k):
                it[k] = r[k]
        it.setdefault("material", "")
        it.setdefault("standard", "")
        for k in NUMERIC:
            if r.get(k):
                v = num(r[k], n, k)
                it[k] = int(v) if v.is_integer() else v
        if r.get("supplier") and r.get("price"):
            it["offers"] = [{
                "supplier": r["supplier"], "city": r.get("city", ""),
                "verified": r.get("verified", "").lower() in ("да", "yes", "true", "1", "+"),
                "price": int(num(r["price"], n, "price")),
                "stock": int(num(r.get("stock") or "0", n, "stock")),
                "lead_days": int(num(r.get("lead_days") or "0", n, "lead_days")),
            }]
        new.append((it, r.get("analogue_of", "")))
        by_name[it["name"]] = it

    existing = {x["id"]: x for x in items}
    for it, link in new:
        if link:
            orig = by_name.get(link) or existing.get(link) or next(
                (x for x in items if x["name"] == link), None)
            if orig is None:
                raise SystemExit(f"{it['name']}: analogue_of {link!r} не найден")
            it["original_ids"] = [orig["id"]]
            orig.setdefault("analogue_ids", []).append(it["id"])
    items.extend(it for it, _ in new)

    CATALOG.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    imp = sum(1 for x in items if x["role"] == "import")
    print(f"Добавлено {len(new)} позиций. В каталоге: {len(items)} ({imp} импортных, {len(items) - imp} российских).")
    if warnings:
        print("Внимание: категории без правил извлечения параметров (поиск пойдёт по названию и семантике): "
              + ", ".join(sorted(warnings)))


if __name__ == "__main__":
    main()
