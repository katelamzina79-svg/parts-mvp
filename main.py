from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import json

from nlp_matcher import load_catalog, find_analogues, diff_report

app = FastAPI(title="Платформа КРИТ — MVP")

BASE_DIR = Path(__file__).resolve().parent

CATALOG = load_catalog()


class MatchRequest(BaseModel):
    query: str
    top_k: int = 10


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/examples")
def examples():
    return {
        "examples": [
            "Подшипник SKF 6205-2RS, d=25, D=52, B=15, сталь",
            "Цилиндр пневматический Festo DSNU-25-100",
            "Автомат Schneider iC60N 3P 40A",
            "Манжета Simrit BAUM 30x47x7",
            "Датчик Endress+Hauser Cerabar 400 4-20 мА",
        ]
    }


@app.get("/api/catalog/stats")
def stats():
    imp = sum(1 for x in CATALOG if x["role"] == "import")
    ru = sum(1 for x in CATALOG if x["role"] == "russian")
    cats = sorted({x["category"] for x in CATALOG})
    return {"total": len(CATALOG), "import": imp, "russian": ru, "categories": cats}


@app.post("/api/match")
def match(req: MatchRequest):
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="Пустой запрос")
    feats, matches = find_analogues(req.query, CATALOG, top_k=req.top_k)

    out = []
    for m in matches:
        same, diff = diff_report(feats, m["item"])
        out.append({
            "id": m["item"]["id"],
            "name": m["item"]["name"],
            "brand": m["item"]["brand"],
            "category": m["item"]["category"],
            "material": m["item"]["material"],
            "standard": m["item"]["standard"],
            "score": m["score"],
            "same": same,
            "diff": diff,
        })

    return {"features": feats, "matches": out, "count": len(out)}