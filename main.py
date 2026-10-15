import io
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import embeddings
from nlp_matcher import load_catalog, find_analogues, diff_report

BASE_DIR = Path(__file__).resolve().parent
CATALOG = load_catalog()
BY_ID = {x["id"]: x for x in CATALOG}

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_QUERY_CHARS = 1500


@asynccontextmanager
async def lifespan(app):
    embeddings.build_or_load(CATALOG)
    print(f"[startup] Эмбеддинги готовы (бэкенд: {embeddings.backend_name()}).")
    yield


app = FastAPI(title="Платформа КРИТ — MVP", lifespan=lifespan)


class MatchRequest(BaseModel):
    query: str
    top_k: int = 10


def best_offer(item):
    """Лучшее предложение: в наличии и подешевле; иначе с кратчайшим сроком."""
    offers = item.get("offers") or []
    if not offers:
        return None
    in_stock = [o for o in offers if o["stock"] > 0]
    if in_stock:
        return min(in_stock, key=lambda o: o["price"])
    return min(offers, key=lambda o: o["lead_days"])


def run_match(query, top_k=10):
    t0 = time.perf_counter()
    feats, matches = find_analogues(query, CATALOG, top_k=top_k)
    out = []
    for m in matches:
        it = m["item"]
        same, diff, verdict = diff_report(feats, it)
        out.append({
            "id": it["id"],
            "name": it["name"],
            "brand": it["brand"],
            "category": it["category"],
            "material": it["material"],
            "standard": it["standard"],
            "score": m["score"],
            "coverage": m["coverage"],
            "verdict": verdict,
            "same": same,
            "diff": diff,
            "offers": it.get("offers", []),
            "best_offer": best_offer(it),
        })
    return {
        "features": feats,
        "matches": out,
        "count": len(out),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/erp")
def erp():
    return FileResponse(BASE_DIR / "erp.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "embeddings": embeddings.backend_name(), "items": len(CATALOG)}


@app.get("/api/examples")
def examples():
    return {
        "examples": [
            "Подшипник SKF 6205-2RS, d=25, D=52, B=15, сталь",
            "Цилиндр пневматический Festo DSNU-25-100",
            "Автомат Schneider iC60N 3P 40A",
            "Манжета Simrit BAUM 30x47x7",
            "Датчик Endress+Hauser Cerabar 400 4-20 мА",
            "Насос Grundfos CR 16-50",
        ]
    }


@app.get("/api/catalog/stats")
def stats():
    imp = sum(1 for x in CATALOG if x["role"] == "import")
    ru = sum(1 for x in CATALOG if x["role"] == "russian")
    cats = sorted({x["category"] for x in CATALOG})
    sup = {o["supplier"] for x in CATALOG for o in x.get("offers", [])}
    return {"total": len(CATALOG), "import": imp, "russian": ru,
            "categories": cats, "suppliers": len(sup)}


@app.post("/api/match")
def match(req: MatchRequest):
    q = (req.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Пустой запрос")
    return run_match(q[:MAX_QUERY_CHARS], top_k=max(1, min(req.top_k, 50)))


@app.get("/api/erp/demo-request")
def erp_demo_request():
    """Демо-заявка на закупку: по одной импортной позиции из каждой категории."""
    qty = {"Подшипник": 20, "Пневматика": 4, "Электрика": 12, "Уплотнение": 50,
           "Насос": 2, "КИП": 3}
    lines, seen = [], set()
    for it in CATALOG:
        if it["role"] != "import" or it["category"] in seen:
            continue
        seen.add(it["category"])
        lines.append({
            "line_id": len(lines) + 1,
            "item_id": it["id"],
            "name": it["name"],
            "category": it["category"],
            "qty": qty.get(it["category"], 1),
            "offer": best_offer(it),
        })
    return {"number": "ЗП-000147", "lines": lines}


@app.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    """Загрузка PDF-паспорта/каталога: извлекаем текст, характеристики и подбираем аналоги."""
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 10 МБ")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Это не PDF-файл")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:5])
    except Exception:
        raise HTTPException(status_code=422, detail="Не удалось прочитать PDF")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="В PDF нет текстового слоя (скан). Для сканов нужен OCR — в MVP не реализован.")
    res = run_match(text[:MAX_QUERY_CHARS])
    res["text_preview"] = text[:400]
    res["filename"] = file.filename
    return res
