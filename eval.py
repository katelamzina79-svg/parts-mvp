"""
Оценка качества подбора аналогов (для отчёта по УГТ 3).

Тестовый запрос — название импортной позиции каталога, эталон — её analogue_ids.
Метрики: top-1 (первый ответ — эталонный аналог), top-3 (эталон в первых трёх),
среднее время подбора. Результат по категориям и общий.

Запуск:  KRIT_EMBEDDINGS=lexical python eval.py      (без нейросети)
         python eval.py                              (с нейросетью e5)

Ограничение: эталон строгий — аналог другого бренда с теми же размерами
засчитывается ошибкой, поэтому цифры слегка занижены.
"""
import json
import time
from collections import defaultdict

import embeddings
from nlp_matcher import find_analogues, load_catalog


def main():
    catalog = load_catalog()
    embeddings.build_or_load(catalog)
    imports = [x for x in catalog if x["role"] == "import" and x.get("analogue_ids")]

    stat = defaultdict(lambda: {"n": 0, "top1": 0, "top3": 0, "ms": 0.0})
    misses = []
    for it in imports:
        t0 = time.perf_counter()
        _, matches = find_analogues(it["name"], catalog, top_k=3)
        ms = (time.perf_counter() - t0) * 1000
        ids = [m["item"]["id"] for m in matches]
        gold = set(it["analogue_ids"])
        s = stat[it["category"]]
        s["n"] += 1
        s["ms"] += ms
        s["top1"] += bool(ids and ids[0] in gold)
        s["top3"] += bool(gold & set(ids))
        if not (gold & set(ids)):
            misses.append({"query": it["name"], "got": [m["item"]["name"] for m in matches]})

    total = {"n": 0, "top1": 0, "top3": 0, "ms": 0.0}
    print(f"Бэкенд эмбеддингов: {embeddings.backend_name()}")
    print(f"{'Категория':<12}{'N':>4}{'top-1':>9}{'top-3':>9}{'мс/запрос':>11}")
    for cat in sorted(stat):
        s = stat[cat]
        for k in total:
            total[k] += s[k]
        print(f"{cat:<12}{s['n']:>4}{s['top1']/s['n']:>9.0%}{s['top3']/s['n']:>9.0%}{s['ms']/s['n']:>11.1f}")
    n = total["n"]
    print(f"{'ИТОГО':<12}{n:>4}{total['top1']/n:>9.0%}{total['top3']/n:>9.0%}{total['ms']/n:>11.1f}")

    with open("eval_report.json", "w", encoding="utf-8") as f:
        json.dump({"backend": embeddings.backend_name(), "n": n,
                   "top1": total["top1"] / n, "top3": total["top3"] / n,
                   "avg_ms": total["ms"] / n, "misses": misses}, f, ensure_ascii=False, indent=2)
    print(f"Промахов top-3: {len(misses)} (подробно в eval_report.json)")


if __name__ == "__main__":
    main()
