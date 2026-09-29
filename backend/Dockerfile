# Shongkho backend — FastAPI + uvicorn, talking to TiDB Cloud Serverless.
# The database is REMOTE (no DB container here): see docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so rebuilds reuse the layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (seeded avatars/product photos in static/ ship with the image)
COPY . .

RUN mkdir -p static/avatars static/products

EXPOSE 8000

# init_db() runs on startup (main.py lifespan): creates missing tables and
# applies the light column migrations — safe against the shared cloud DB.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
