from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
import json
from pathlib import Path

app = FastAPI(title="Parts Search MVP")

BASE_DIR = Path(__file__).resolve().parent


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/search")
def search(
    part_type: str = Query(None),
    material: str = Query(None),
    inner_diameter: float = Query(None),
    outer_diameter: float = Query(None),
    standard: str = Query(None),
):
    with open(BASE_DIR / "mock_data.json", "r", encoding="utf-8") as f:
        parts = json.load(f)

    results = []
    for p in parts:
        if part_type and part_type.strip() and part_type.lower() not in p["name"].lower():
            continue
        if material and material.strip() and material.lower() not in p["material"].lower():
            continue
        if inner_diameter is not None and abs(p["inner_diameter"] - inner_diameter) > 0.01:
            continue
        if outer_diameter is not None and abs(p["outer_diameter"] - outer_diameter) > 0.01:
            continue
        if standard and standard.strip() and standard.lower() not in p["standard"].lower():
            continue
        results.append(p)

    return {"count": len(results), "matches": results}