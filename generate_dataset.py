"""
Генератор датасета для Платформы КРИТ.
Создаёт 100 импортных позиций + по 2 российских аналога = 300+ позиций.
"""
import json
import random
from pathlib import Path

random.seed(42)

OUT = Path(__file__).resolve().parent / "data" / "catalog.json"
OUT.parent.mkdir(exist_ok=True)

items = []
counter = {"import": 0, "russian": 0}


def new_id(prefix):
    counter[prefix] += 1
    return f"{prefix}_{counter[prefix]:03d}"


# ---------- ПОДШИПНИКИ ----------
def gen_bearings(n):
    for _ in range(n):
        d = random.choice([20, 25, 30, 35, 40, 45, 50, 55, 60, 65])
        D = d + random.choice([20, 25, 28, 30, 32, 35, 40, 45])
        B = random.choice([12, 15, 17, 18, 20, 22, 25])
        code = f"{random.choice(['60', '62', '63'])}{random.randint(2, 30):02d}"
        suffix = random.choice(["", "-2RS", "-2RSH", "-ZZ", "-2Z", " C3"])
        import_brand = random.choice(["SKF", "FAG", "NSK", "NTN", "Timken", "KOYO"])
        ru_brands = random.sample(["ГПЗ-1", "ГПЗ-2", "ГПЗ-4", "ЕПК", "VBF"], 2)

        imp_id = new_id("import")
        ru_ids = []
        for b in ru_brands:
            rid = new_id("russian")
            items.append({
                "id": rid,
                "role": "russian",
                "brand": b,
                "name": f"Подшипник {code}{suffix} {b} ГОСТ 8338-75",
                "category": "Подшипник",
                "material": "Сталь ШХ15",
                "inner_diameter": d,
                "outer_diameter": D,
                "width": B,
                "standard": "ГОСТ 8338-75",
                "original_ids": [imp_id],
            })
            ru_ids.append(rid)

        items.append({
            "id": imp_id,
            "role": "import",
            "brand": import_brand,
            "name": f"Подшипник {import_brand} {code}{suffix}",
            "category": "Подшипник",
            "material": random.choice(["Сталь", "Сталь ШХ15", "Нержавеющая сталь"]),
            "inner_diameter": d,
            "outer_diameter": D,
            "width": B,
            "standard": random.choice(["ISO 15:2011", "DIN 625-1", "ISO 492:2014"]),
            "analogue_ids": ru_ids,
        })


# ---------- ПНЕВМАТИКА ----------
def gen_pneumatics(n):
    for _ in range(n):
        d = random.choice([16, 20, 25, 32, 40, 50, 63])
        stroke = random.choice([25, 50, 80, 100, 125, 160, 200])
        pressure = random.choice([6, 8, 10, 12])
        import_brand = random.choice(["Festo", "SMC", "Camozzi", "Parker"])
        ru_brands = random.sample(["Пневмоаппарат", "Камоззи-Рус", "Пневмостроймашина"], 2)

        imp_id = new_id("import")
        ru_ids = []
        for b in ru_brands:
            rid = new_id("russian")
            items.append({
                "id": rid,
                "role": "russian",
                "brand": b,
                "name": f"Цилиндр пневматический {d}x{stroke} {b} ГОСТ 15608-81",
                "category": "Пневматика",
                "material": "Алюминий",
                "inner_diameter": d,
                "stroke": stroke,
                "pressure": pressure,
                "standard": "ГОСТ 15608-81",
                "original_ids": [imp_id],
            })
            ru_ids.append(rid)

        items.append({
            "id": imp_id,
            "role": "import",
            "brand": import_brand,
            "name": f"Цилиндр пневматический {import_brand} DSNU-{d}-{stroke}",
            "category": "Пневматика",
            "material": "Алюминий",
            "inner_diameter": d,
            "stroke": stroke,
            "pressure": pressure,
            "standard": "ISO 6432",
            "analogue_ids": ru_ids,
        })


# ---------- ЭЛЕКТРИКА ----------
def gen_electrical(n):
    for _ in range(n):
        voltage = random.choice([230, 400, 690])
        current = random.choice([6, 10, 16, 25, 32, 40, 63, 100])
        poles = random.choice([1, 2, 3, 4])
        import_brand = random.choice(["Schneider", "ABB", "Siemens", "Legrand"])
        ru_brands = random.sample(["IEK", "EKF", "КЭАЗ", "Автоматика"], 2)

        imp_id = new_id("import")
        ru_ids = []
        for b in ru_brands:
            rid = new_id("russian")
            items.append({
                "id": rid,
                "role": "russian",
                "brand": b,
                "name": f"Автомат {b} {poles}P {current}A ГОСТ Р 50030",
                "category": "Электрика",
                "material": "Полимер",
                "voltage": voltage,
                "current": current,
                "poles": poles,
                "standard": "ГОСТ Р 50030",
                "original_ids": [imp_id],
            })
            ru_ids.append(rid)

        items.append({
            "id": imp_id,
            "role": "import",
            "brand": import_brand,
            "name": f"Автомат {import_brand} iC60N {poles}P {current}A",
            "category": "Электрика",
            "material": "Полимер",
            "voltage": voltage,
            "current": current,
            "poles": poles,
            "standard": "IEC 60947",
            "analogue_ids": ru_ids,
        })


# ---------- УПЛОТНЕНИЯ ----------
def gen_seals(n):
    for _ in range(n):
        d = random.choice([20, 25, 30, 35, 40, 45, 50, 60])
        D = d + random.choice([10, 12, 15, 20])
        h = random.choice([7, 8, 10, 12])
        import_brand = random.choice(["Simrit", "Freudenberg", "Trelleborg"])
        ru_brands = random.sample(["РТИ-Балаково", "БРТ", "ВРШРЗ"], 2)

        imp_id = new_id("import")
        ru_ids = []
        for b in ru_brands:
            rid = new_id("russian")
            items.append({
                "id": rid,
                "role": "russian",
                "brand": b,
                "name": f"Манжета {d}x{D}x{h} {b} ГОСТ 8752-79",
                "category": "Уплотнение",
                "material": "Резина",
                "inner_diameter": d,
                "outer_diameter": D,
                "width": h,
                "standard": "ГОСТ 8752-79",
                "original_ids": [imp_id],
            })
            ru_ids.append(rid)

        items.append({
            "id": imp_id,
            "role": "import",
            "brand": import_brand,
            "name": f"Манжета {import_brand} BAUM {d}x{D}x{h}",
            "category": "Уплотнение",
            "material": "Резина NBR",
            "inner_diameter": d,
            "outer_diameter": D,
            "width": h,
            "standard": "DIN 3760",
            "analogue_ids": ru_ids,
        })


# ---------- НАСОСЫ ----------
def gen_pumps(n):
    for _ in range(n):
        flow = random.choice([6, 10, 16, 25, 40, 63, 100])
        head = random.choice([20, 32, 50, 80])
        power = random.choice([0.55, 0.75, 1.1, 1.5, 2.2, 4.0])
        import_brand = random.choice(["Grundfos", "Wilo", "KSB"])
        ru_brands = random.sample(["ГМС Ливгидромаш", "НПО Гидромашсервис", "Насосэнергомаш"], 2)

        imp_id = new_id("import")
        ru_ids = []
        for b in ru_brands:
            rid = new_id("russian")
            items.append({
                "id": rid,
                "role": "russian",
                "brand": b,
                "name": f"Насос центробежный {flow} м³/ч, {head} м, {power} кВт {b}",
                "category": "Насос",
                "material": "Чугун",
                "flow": flow,
                "head": head,
                "power": power,
                "standard": "ГОСТ 6134-2007",
                "original_ids": [imp_id],
            })
            ru_ids.append(rid)

        items.append({
            "id": imp_id,
            "role": "import",
            "brand": import_brand,
            "name": f"Насос {import_brand} CR {flow}-{head}",
            "category": "Насос",
            "material": "Нержавеющая сталь",
            "flow": flow,
            "head": head,
            "power": power,
            "standard": "ISO 9906",
            "analogue_ids": ru_ids,
        })


# ---------- КИП ----------
def gen_sensors(n):
    for _ in range(n):
        range_min = random.choice([-50, 0, 100, 200, 400])
        range_max = range_min + random.choice([100, 200, 400, 600])
        output = random.choice(["4-20 мА", "0-10 В", "HART", "RS-485"])
        ip = random.choice(["IP65", "IP67", "IP68"])
        import_brand = random.choice(["Endress+Hauser", "Emerson", "Yokogawa"])
        ru_brands = random.sample(["Метран", "ОВЕН", "Теплоприбор"], 2)

        imp_id = new_id("import")
        ru_ids = []
        for b in ru_brands:
            rid = new_id("russian")
            items.append({
                "id": rid,
                "role": "russian",
                "brand": b,
                "name": f"Датчик давления {b} ДМ-{range_max}, {output}, {ip}",
                "category": "КИП",
                "material": "Сталь",
                "range_min": range_min,
                "range_max": range_max,
                "output": output,
                "ip": ip,
                "standard": "ГОСТ 8.586",
                "original_ids": [imp_id],
            })
            ru_ids.append(rid)

        items.append({
            "id": imp_id,
            "role": "import",
            "brand": import_brand,
            "name": f"Датчик {import_brand} Cerabar {range_max} {output}",
            "category": "КИП",
            "material": "Нержавеющая сталь",
            "range_min": range_min,
            "range_max": range_max,
            "output": output,
            "ip": ip,
            "standard": "IEC 60770",
            "analogue_ids": ru_ids,
        })


# Генерируем по 20 импортных позиций на категорию → 20*6 = 120 импортных, 240 российских = 360 позиций
gen_bearings(20)
gen_pneumatics(20)
gen_electrical(20)
gen_seals(20)
gen_pumps(20)
gen_sensors(20)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)

imp = sum(1 for x in items if x["role"] == "import")
ru = sum(1 for x in items if x["role"] == "russian")
print(f"OK. Всего: {len(items)} позиций ({imp} импортных, {ru} российских)")
print(f"Файл: {OUT}")