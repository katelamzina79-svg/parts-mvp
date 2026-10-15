"""
Семантический слой Платформы КРИТ.

Два бэкенда:
  * e5      — нейросеть intfloat/multilingual-e5-base (sentence-transformers);
  * lexical — лёгкий запасной вариант на символьных n-граммах (только numpy),
              работает без интернета и без скачивания модели.

Выбор: переменная окружения KRIT_EMBEDDINGS = auto (по умолчанию) | e5 | lexical.
В режиме auto сначала пробуем e5, при любой ошибке загрузки переходим на lexical.
"""
import hashlib
import os
import re
import zlib
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

MODEL_NAME = "intfloat/multilingual-e5-base"
LEX_DIM = 4096

_backend = None          # "e5" | "lexical"
_model = None
_cache = {}              # backend -> (emb, ids)


def _init_backend():
    """Определяет бэкенд один раз за процесс."""
    global _backend, _model
    if _backend is not None:
        return _backend
    want = os.getenv("KRIT_EMBEDDINGS", "auto").lower()
    if want in ("auto", "e5"):
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[embeddings] Загружаю модель {MODEL_NAME}...")
            _model = SentenceTransformer(MODEL_NAME)
            _backend = "e5"
            print("[embeddings] Модель загружена.")
            return _backend
        except Exception as e:  # нет пакета, нет сети, нет места и т.д.
            if want == "e5":
                raise
            print(f"[embeddings] Нейросеть недоступна ({type(e).__name__}); "
                  f"использую lexical-режим.")
    _backend = "lexical"
    return _backend


def backend_name():
    return _init_backend()


# ---------------------------------------------------------------- lexical
def _lex_vec(text):
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    v = np.zeros(LEX_DIM, dtype=np.float32)
    for n in (3, 4):
        for i in range(len(t) - n + 1):
            v[zlib.crc32(t[i:i + n].encode("utf-8")) % LEX_DIM] += 1.0
    norm = np.linalg.norm(v)
    return v / norm if norm else v


# ------------------------------------------------------------------- общее
def _text_for(item):
    parts = [item.get("name", ""), item.get("category", ""), item.get("material", ""),
             item.get("brand", ""), item.get("standard", "")]
    return " ".join(p for p in parts if p)


def _signature(backend, texts):
    h = hashlib.sha1()
    h.update(backend.encode())
    h.update(MODEL_NAME.encode())
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def build_or_load(catalog):
    """Возвращает (матрица эмбеддингов, список id) в порядке каталога."""
    backend = _init_backend()
    ids = [x["id"] for x in catalog]
    texts = [_text_for(x) for x in catalog]
    sig = _signature(backend, texts)

    cached = _cache.get(backend)
    if cached and cached[2] == sig:
        return cached[0], cached[1]

    if backend == "lexical":
        emb = np.stack([_lex_vec(t) for t in texts])
    else:
        cache_path = DATA_DIR / f"embeddings_{backend}.npz"
        emb = None
        if cache_path.exists():
            try:
                data = np.load(cache_path, allow_pickle=False)
                if str(data["sig"]) == sig:
                    emb = data["emb"]
                    print(f"[embeddings] Загружено из кэша: {len(ids)} векторов")
            except Exception as e:
                print(f"[embeddings] Кэш не читается ({e}), пересчитываю...")
        if emb is None:
            print(f"[embeddings] Считаю эмбеддинги для {len(texts)} позиций...")
            emb = _model.encode(["passage: " + t for t in texts], show_progress_bar=True,
                                convert_to_numpy=True, normalize_embeddings=True)
            np.savez(cache_path, emb=emb, sig=np.array(sig))
            print(f"[embeddings] Сохранено в кэш: {cache_path}")

    _cache[backend] = (emb, ids, sig)
    return emb, ids


def encode_query(text):
    backend = _init_backend()
    if backend == "lexical":
        return _lex_vec(text)
    # e5 требует префикс "query: " для запроса и "passage: " для документов
    return _model.encode(["query: " + text], convert_to_numpy=True,
                         normalize_embeddings=True)[0]


def semantic_scores(query_text, catalog):
    """
    {item_id: косинусная близость} в «сыром» виде (-1..1).
    Нормировку по кандидатам делает nlp_matcher: у e5 все близости
    лежат в узком диапазоне, и без нормировки слой почти не различает позиции.
    """
    emb, ids = build_or_load(catalog)
    sims = emb @ encode_query(query_text)
    return {item_id: float(s) for item_id, s in zip(ids, sims)}
