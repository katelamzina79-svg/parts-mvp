"""
Проверка модели на реальной базе SKF (после import_skf.py и patch_nlp_matcher.py):

    python eval_skf.py

В базе нет эталонных аналогов (interchange_verified=False), поэтому top-k по analogue_ids,
как в eval.py, здесь не считается. Вместо этого:
  1. Приёмка из «О_данных»: запрос «6205» → d=25, D=52, B=15 (по каждой из 50 позиций).
  2. Геометрия подбора: у российских кандидатов в топ-3 совпадают d/D/B с позицией SKF
     (считается по тем позициям, для которых в каталоге вообще есть кандидат с такой геометрией).
  3. Опасные случаи: сколько раз в топ-1 попал кандидат с вердиктом «не взаимозаменяем».
  4. Полнота данных: какие поля пустые.
"""
import os

os.environ.setdefault("KRIT_EMBEDDINGS", "lexical")   # до импорта nlp_matcher

from nlp_matcher import diff_report, extract_features, find_analogues, load_catalog  # noqa: E402

DIMS = ("inner_diameter", "outer_diameter", "width")


def geom(x):
    return tuple(x.get(k) for k in DIMS)


def pct(a, b):
    return f"{a}/{b} = {100 * a / b:.0f}%" if b else "нет данных"


def main():
    catalog = load_catalog()
    skf = [x for x in catalog if str(x["id"]).startswith("KRIT-BRG-")]
    if not skf:
        raise SystemExit("В каталоге нет KRIT-BRG-*: сначала python import_skf.py характеристики.xlsx")
    russian = [x for x in catalog if x["role"] == "russian" and x["category"] == "Подшипник"]
    code_of = lambda x: x["name"].rsplit(" ", 1)[-1]

    ok_code = ok_name = 0
    reachable = top1 = top3 = bad_top1 = 0
    misses = []
    for x in skf:
        code = code_of(x)
        for q, bucket in ((code, "code"), (x["name"], "name")):
            f = extract_features(q)
            if (f["inner_diameter"], f["outer_diameter"], f["width"]) == geom(x):
                ok_code += bucket == "code"
                ok_name += bucket == "name"
        feats, res = find_analogues(x["name"], catalog, top_k=3)
        if any(geom(r) == geom(x) for r in russian):
            reachable += 1
            hits = [geom(r["item"]) == geom(x) for r in res]
            top1 += bool(hits and hits[0])
            top3 += any(hits)
            if not (hits and hits[0]):
                misses.append(x["name"])
        if res and diff_report(feats, res[0]["item"])[2]["code"] == "no":
            bad_top1 += 1

    n = len(skf)
    print(f"Позиций SKF в каталоге: {n}")
    print(f"1. Приёмка d/D/B по запросу «6205»:                {pct(ok_code, n)}")
    print(f"   то же по запросу «Подшипник SKF 6205»:         {pct(ok_name, n)}")
    print(f"2. Есть российский кандидат с той же геометрией:   {pct(reachable, n)}")
    print(f"   геометрия совпала в топ-1:                      {pct(top1, reachable)}")
    print(f"   геометрия совпала в топ-3:                      {pct(top3, reachable)}")
    if misses:
        print("   промахи: " + ", ".join(misses[:10]) + (" …" if len(misses) > 10 else ""))
    print(f"3. В топ-1 вердикт «не взаимозаменяем»:            {pct(bad_top1, n)}")
    for field in ("sealed_limiting_speed", "mass_kg", "dynamic_rating"):
        empty = [code_of(x) for x in skf if field not in x]
        print(f"4. Пустое поле {field}: {', '.join(empty) if empty else 'нет'}")
    print("Примечание: оценка относится к 50 базовым номерам SKF без суффиксов; "
          "аналоги и взаимозаменяемость в источнике не проверялись.")


if __name__ == "__main__":
    main()
