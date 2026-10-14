# parts-mvp
MVP проекта для акселератора Legal Tech 2.0

## Стек
- Backend: Python + FastAPI
- Frontend: HTML + JS
- Данные: JSON (пока), далее — 1С

## Запуск

```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi "uvicorn[standard]"
uvicorn main:app --reload
