# Платформа КРИТ — MVP

Двухслойный NLP-подбор российских аналогов импортных комплектующих.

## Как работает
1. Извлечение характеристик из текста (regex + словари).
2. Семантическое сопоставление через мультиязычную нейросеть `paraphrase-multilingual-MiniLM-L12-v2`.
3. Взвешенный скоринг: числа 25% + семантика 27% + fuzzy 15% + артикул 10% + стандарт 8% + материал 7% + категория 8%.

## Установка
```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi "uvicorn[standard]" rapidfuzz sentence-transformers
python generate_dataset.py
uvicorn main:app --reload