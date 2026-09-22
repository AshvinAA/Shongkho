# Analytics Setup (Track A — Stage 1)

How the "Run Analysis" pipeline works, and how to run it locally.
Stage 1 covers the deterministic half: **sales graph, employee race,
top products**. No LLM is involved yet (stage 2 adds insights, stage 3
the assistant).

## Architecture in one paragraph

`POST /api/v1/analytics/run` creates an `analysis_runs` row (the lock)
and executes via a configurable **executor** (selected by
`ANALYTICS_EXECUTOR`):

- **`sync` (default)** — the whole pipeline runs inline in the request:
  aggregations → all four `analytics_snapshots` rows written in ONE
  transaction → run marked `COMPLETED`. The POST response already
  carries the final status; no Redis, Celery, or extra processes
  needed. Ideal for dev and for stores whose aggregations finish in
  well under a second.
- **`celery`** — the production chord: three parallel aggregation
  tasks fan out, a callback fans in to write the four snapshot rows,
  then `COMPLETED`. The error callback marks failures `FAILED`,
  releasing the lock immediately.

The dashboard never aggregates live; it reads the latest completed
snapshot per section (one indexed lookup).

```
ANALYTICS_EXECUTOR=sync:
  POST /analytics/run ─> analysis_runs (lock) ─> aggregate ─> 4 snapshots in one tx
                                                 (all inside the request)

ANALYTICS_EXECUTOR=celery:
POST /analytics/run ──> analysis_runs (QUEUED)  ──> 409 if one is active
        │
        ▼ Celery chord (redis broker)
  [sales] [employees] [products]   (fan-out)
        └────────┬───────────────
                 ▼
     finalize: 4 snapshot rows in one tx  →  COMPLETED
                 │ on error
                 ▼
        run FAILED (lock released)
```

## Repo layout (what stage 1 added)

```
backend/
  analytics/
    timeutils.py      # period windows + bucket math (pure, deterministic)
    aggregators.py    # sales / employees / products computations (pure)
    pipeline.py       # run lifecycle: lock, execute, snapshots, watchdog
    tasks.py          # Celery chord wiring (thin wrappers)
  celery_app.py       # Celery app (broker/backend config)
  routes/analytics.py # POST /run, GET /run/{id}/status, GET /dashboard
  tests/test_analytics.py
frontend/src/
  pages/Analytics.jsx             # owner-only page (RoleGate)
  api/analytics.js
  components/analytics/
    common.jsx                    # SegmentedControl, DeltaChip
    SalesTrend.jsx                # Recharts line chart + best hours/days
    EmployeeRace.jsx              # avatar race (horizontal bars)
    TopProducts.jsx               # ranked table, revenue/profit switch
docs/ANALYTICS_SETUP.md           # this file
```

## Local setup

### 0. Install dependencies

```bash
cd backend
pip install -r requirements.txt      # now includes celery[redis] + redis
```

### 1. Redis

The Celery broker needs a running Redis.

- **Windows:** easiest options are [Memurai](https://www.memurai.com/)
  (native Windows service, dev-friendly) or Redis inside WSL
  (`sudo apt install redis-server && redis-server`).
- **macOS/Linux:** `redis-server` (or `docker run -p 6379:6379 redis:7`).

Defaults in `backend/.env` point at `redis://localhost:6379/1` (broker)
and `/2` (result backend) — adjust via `CELERY_BROKER_URL` /
`CELERY_RESULT_BACKEND`.

### 2. Backend environment

```bash
cp backend/.env.example backend/.env
# set TIDB_DATABASE_URL (TiDB/MySQL in prod, or sqlite:///./Shongkho_dev.db for dev)
```

`GEMINI_API_KEY` can stay empty — stage 1 never calls an LLM.

### 3. Run the stack

**Default (sync executor — no Redis/Celery needed):**

```bash
# 1) API
cd backend
uvicorn main:app --reload --port 8000

# 2) Frontend
cd ../frontend
npm run dev
```

**Celery mode** (`ANALYTICS_EXECUTOR=celery` in backend/.env): the same
steps, plus a running Redis and a worker process:

```bash
# Celery worker  (Windows: --pool=solo is REQUIRED for the default prefork pool)
celery -A celery_app.celery_app worker --loglevel=info --pool=solo
```

> **Windows note:** `--pool=solo` runs tasks in the worker process
> itself — perfectly fine for a dev machine and small stores. On Linux
> prod, drop the flag to get the normal prefork pool.

With the sync default, "Run analysis" works out of the box — results
are ready the moment the button's request returns. Switch to
`ANALYTICS_EXECUTOR=celery` only when you actually run the worker
(switching with no worker would leave runs QUEUED until the watchdog
reaps them).

### 4. Use it

1. Log in as an **owner** (employees get 403 — same gate as reports).
2. Open **Analytics** in the navbar.
3. Pick day/week/month, hit **▶ Run analysis**.
4. The button polls run status (QUEUED → RUNNING → COMPLETED) and
   refetches the dashboard when done.

`ANALYTICS_EXECUTOR` (backend/.env or environment): `sync` (default) or
`celery`. See "Run the stack" above.

### Period semantics (agreed design)

| period | graph buckets      | delta baseline      |
|--------|--------------------|---------------------|
| day    | hours of today     | vs yesterday        |
| week   | days of this week (Mon–Sun) | vs last week |
| month  | days of this month | vs last month       |

Deltas with a zero baseline render as "— no comparison" rather than a
fabricated +∞.

## API reference

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/v1/analytics/run` | POST | owner | body `{"period": "day\|week\|month"}` → `202 {run_id, status}` (status already `COMPLETED` with the sync executor); `409` while a run is active |
| `/api/v1/analytics/run/{id}/status` | GET | owner | `{status, failure_reason, ...}` — poll this |
| `/api/v1/analytics/dashboard?period=week` | GET | owner | latest completed snapshot per section |

## Demo data (edwinzaman store)

A seeder populates a realistic store so every period view has real
shape (weekday/weekend patterns, lunch+evening peaks, per-employee
skill differences, month-over-month growth, seasonal products):

```bash
cd backend
python seed_demo_data.py          # idempotent: skips if data exists
python seed_demo_data.py --force  # WIPE everything and reseed
```

What you get:

| Account | Login | Password |
|---|---|---|
| Edwin Zaman (owner) | `edwinzaman` | `shongkho123` |
| Rahim Uddin, Karim Ahmed, Sumi Akter, Tanvir Hasan (employees) | `01711111101`…`04` | `shongkho123` |

Plus 12 products, 13 customers, and ~3,600 sales across ~4 months
ending today. Employees get SVG initial-avatars seeded into
`users.photo`, so the race chart, staff page, and navbar all show
them. Storyline baked in: Rahim leads, Sumi has a visible slump this
week, cold drinks trend up in hot months.

After seeding, open Analytics as Edwin and hit **▶ Run analysis** for
each period you want to view.

## Tests

```bash
cd backend && python -m pytest tests/test_analytics.py -q      # 24 tests
cd frontend && npx vitest run src/test/Analytics.test.jsx      # 6 tests
```

The backend suite runs **without Redis or Celery installed**: the
route's executor dependency (`get_enqueue`) is overridden with a
synchronous executor in tests — the same seam production swaps for the
Celery chord.

## Roadmap

- **Stage 2 — Insight engine:** `analytics/insights.py` calls Gemini in
  JSON mode with the aggregated DTO; validates returned `claims` against
  the DTO; falls back to a safe string on mismatch. Writes the real
  `insights` snapshot (the placeholder row is already in place).
- **Stage 3 — Business assistant:** `analytics/tools.py` (closed tool
  registry, owner scope injected from the session) + `/analytics/chat`
  + `assistant_messages` table + daily cap.
- **Stage 4 — Scale infra:** Celery beat watchdog
  (`pipeline.mark_stale_runs_failed` — already implemented, just wire
  the schedule), snapshot pruning, optional SSE instead of polling.
