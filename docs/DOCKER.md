# Docker — running all of Shongkho in containers

Two containers, one command:

```
┌────────────────────────────── Docker ──────────────────────────────┐
│  frontend (nginx:80)  ──/api, /static──▶  backend (uvicorn:8000)   │
│  published on host :8080                        │ TLS + utf8mb4    │
└─────────────────────────────────────────────────┼──────────────────┘
                                                  ▼
                                    TiDB Cloud Serverless (remote)
```

- **No database container** — the store runs on TiDB Cloud Serverless
  (`backend/.env` → `TIDB_DATABASE_URL`). One source of truth for every
  environment; the app's engine already handles TLS (certifi) + utf8mb4.
- **Only one port is published**: `8080` → nginx. nginx serves the built
  SPA and proxies `/api/*` and `/static/*` to the backend, so the session
  cookie stays first-party (no CORS anywhere).

## Quick start

```bash
# 1. Configure (one time). Never commit backend/.env.
cp backend/.env.example backend/.env
#    → fill in TIDB_DATABASE_URL (mysql+pymysql://…@gateway01…:4000/shongkho)
#    → fill in GEMINI_API_KEY (or set LLM_PROVIDER=ollama + OLLAMA_URL)
#    → set a long random SESSION_SECRET_KEY

# 2. Build + run
docker compose up --build -d

# 3. Open
#    App:       http://localhost:8080
#    API docs:  http://localhost:8080/api/v1/docs
#    Health:    http://localhost:8080/api/v1/health

# 4. Optional: seed the demo store (idempotent; skip if TiDB already has data)
docker compose exec backend python seed_demo_data.py --force
```

Log in with the demo accounts (docs/ANALYTICS_SETUP.md):
owner `01711111100` / `shongkho123`, employees `01711111101`–`07`.

## What's in the image

| Piece | Base | Notes |
|---|---|---|
| `backend/Dockerfile` | `python:3.12-slim` | installs requirements, runs `uvicorn main:app`. `init_db()` runs on startup — creates missing tables + light migrations against the shared cloud DB. Static avatars/product photos ship with the image. |
| `frontend/Dockerfile` | node build → `nginx:1.27-alpine` | `npm ci && npm run build`, hashed-asset caching, SPA fallback routing. |

`.dockerignore` files keep secrets (`.env`), tests, and local `*.db`
files out of the build context — the image never contains credentials.

## Operations

```bash
docker compose ps                       # state + healthchecks
docker compose logs -f backend          # tail the API
docker compose up --build -d            # rebuild after code changes
docker compose down                     # stop (data lives in TiDB Cloud)
```

- The backend healthcheck (`/api/v1/health`) gates the frontend startup
  (`depends_on: service_healthy`), so nginx never proxies to a cold API.
- Analytics executor: the default `ANALYTICS_EXECUTOR=sync` needs no
  extra services. If you switch to `celery`, add a `redis` service and a
  worker container (see docs/ANALYTICS_SETUP.md §executor).

## Security checklist

- `SESSION_SECRET_KEY`: set a real random value in `backend/.env`
  (compose only injects a placeholder default when it's missing).
- Credentials live only in the gitignored `backend/.env` — never in the
  images or compose file.
- TiDB password rotation: update `TIDB_DATABASE_URL` in `backend/.env`,
  then `docker compose up -d --force-recreate backend`.
