# HerCare Backend

FastAPI backend for the HerCare women's health tracking app.

## Tech Stack
- FastAPI + Gunicorn/Uvicorn
- SQLAlchemy + PostgreSQL (Supabase)
- JWT Authentication (python-jose + bcrypt)

## Deploy to Render
See `render.yaml` for configuration.

## Environment Variables
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | JWT signing secret |

## Local Development
```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```
