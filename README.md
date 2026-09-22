# Shongkho — POS System

A small-shop point-of-sale system: FastAPI backend + React (Vite) frontend,
fully decoupled. The SPA talks to the API over `/api/v1/*` same-origin
(development proxy) with signed-cookie sessions.

## Structure

```
Shongkho/
├── backend/            # FastAPI application
│   ├── main.py         # App wiring: middleware, static, routers
│   ├── database.py     # Engine/session factory, get_db dependency
│   ├── models.py       # SQLAlchemy models (joined-table inheritance)
│   ├── schemas.py      # Pydantic request/response schemas
│   ├── services.py     # ALL business logic (auth, inventory, sales…)
│   ├── deps.py         # Auth gates: get_current_user / require_owner / require_any
│   ├── routes/         # Thin route handlers, one file per domain
│   ├── static/         # Uploaded images (product_pics/, profile_pics/)
│   ├── tests/          # Pytest suite (isolated SQLite per test)
│   └── requirements.txt
├── frontend/           # React SPA
│   └── src/
│       ├── api/        # Fetch wrappers per domain (client.js is the core)
│       ├── components/ # Reusable UI (RoleGate, Modal, Avatar, …)
│       ├── context/    # AuthContext (session hydration, login/logout)
│       ├── pages/      # POS, Inventory, Dashboard, Staff, Customers, …
│       └── test/       # Vitest + React Testing Library suite
├── docs/
│   └── ANALYTICS_SETUP.md  # Analytics pipeline: architecture + local setup
├── .gitignore
└── README.md
```

## Running

### Backend

```bash
cd backend
# 1. Configure the database URL in .env (TiDB/MySQL or SQLite for dev):
#    TIDB_DATABASE_URL=mysql+pymysql://user:pass@host:4000/db
# 2. Install dependencies:
pip install -r requirements.txt
# 3. Start:
uvicorn main:app --reload
```

The API is now on http://localhost:8000 — docs at /docs.

> **Analytics (Run Analysis pipeline)** needs Redis + a Celery worker on
> top of the steps above. See [docs/ANALYTICS_SETUP.md](docs/ANALYTICS_SETUP.md)
> for the three-process local setup and architecture notes.

> **Launching from the project root also works** — a small launcher `main.py`
> at the repo root re-exports the backend app, so all of these are valid:
>
> ```powershell
> # From F:\Shongkho\Shongkho (no cd needed):
> python -m uvicorn main:app --reload --port 8000
>
> # Or without the shim:
> python -m uvicorn main:app --reload --app-dir backend --port 8000
>
> # Or the classic way:
> cd backend
> python -m uvicorn main:app --reload --port 8000
> ```
>
> If the backend isn't running, the frontend dev server logs
> `http proxy error: ... ECONNREFUSED` for every /api request.
>
> **Database paths are anchored.** A relative SQLite URL in `backend/.env`
> (e.g. `sqlite:///./Shongkho_test.db`) is always resolved against
> `backend/`, regardless of where uvicorn was started — the same .env
> always means the same database file.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The SPA is on http://localhost:5173 and proxies /api + /static to :8000.

## Testing

Backend (109 tests — each runs against an isolated SQLite database):

```bash
cd backend
python -m pytest tests/ -v
```

Frontend (24 tests — Vitest + React Testing Library):

```bash
cd frontend
npm test
```

## Roles

| Ability                          | Owner | Employee |
|----------------------------------|:-----:|:--------:|
| Browse products / customers      | ✅    | ✅       |
| Checkout (POS) / quick-add       | ✅    | ✅       |
| Store chat                       | ✅    | ✅       |
| Product create/update/delete     | ✅    | ❌       |
| Stock adjustments                | ✅    | ❌       |
| Customer directory + spend       | ✅    | ❌       |
| Employee roster / performance    | ✅    | ❌       |
| Sales reports                    | ✅    | ❌       |

## Design notes

- **Prices are server-side.** Checkout payloads carry only product ids and
  quantities; the backend reads authoritative prices from the database.
- **Atomic checkout.** Stock validation, deductions, and the sale record
  commit in a single transaction; any failure rolls everything back.
- **Sessions are re-validated** against the database on every request, so
  deleted accounts are immediately locked out.
- **Role conversions** (owner ↔ employee) swap only the joined-table child
  rows; the shared `users` identity row is never destroyed.
