"""
Семантические эмбеддинги для каталога Платформы КРИТ.
Считает эмбеддинги один раз и кэширует в data/embeddings.npz.
"""
import json
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
CACHE_PATH = DATA_DIR / "embeddings.npz"

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

_model = None
_embeddings = None
_ids = None


def _load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[embeddings] Загружаю модель {MODEL_NAME}...")
        _model = SentenceTransformer(MODEL_NAME)
        print("[embeddings] Модель загружена.")
    return _model


def _text_for(item):
    """Текст, по которому считаем эмбеддинг — название + категория + материал + стандарт."""
    parts = [
        item.get("name", ""),
        item.get("category", ""),
        item.get("material", ""),
        item.get("brand", ""),
        item.get("standard", ""),
    ]
    return " | ".join(p for p in parts if p)


def build_or_load(catalog):
    """Возвращает (np.array эмбеддингов, list id) в том же порядке, что catalog."""
    global _embeddings, _ids

    if _embeddings is not None and _ids is not None:
        return _embeddings, _ids

    ids = [x["id"] for x in catalog]

    if CACHE_PATH.exists():
        try:
            data = np.load(CACHE_PATH, allow_pickle=True)
            cached_ids = list(data["ids"])
            if cached_ids == ids:
                _embeddings = data["emb"]
                _ids = cached_ids
                print(f"[embeddings] Загружено из кэша: {len(ids)} векторов")
                return _embeddings, _ids
            else:
                print("[embeddings] Каталог изменился, пересчитываю...")
        except Exception as e:
            print(f"[embeddings] Кэш битый ({e}), пересчитываю...")

    model = _load_model()
    texts = [_text_for(x) for x in catalog]
    print(f"[embeddings] Считаю эмбеддинги для {len(texts)} позиций...")
    emb = model.encode(texts, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)

    _embeddings = emb
    _ids = ids
    np.savez(CACHE_PATH, emb=emb, ids=np.array(ids, dtype=object))
    print(f"[embeddings] Сохранено в кэш: {CACHE_PATH}")
    return _embeddings, _ids


def encode_query(text):
    """Эмбеддинг одного запроса."""
    model = _load_model()
    v = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
    return v[0]


def semantic_scores(query_text, catalog):
    """
    Возвращает dict {item_id: cosine_similarity_0..1}.
    Так как эмбеддинги нормализованы, косинус = скалярное произведение.
    """
    emb, ids = build_or_load(catalog)
    q = encode_query(query_text)
    sims = emb @ q
    sims = (sims + 1) / 2  # [-1,1] -> [0,1]
    return {item_id: float(s) for item_id, s in zip(ids, sims)}