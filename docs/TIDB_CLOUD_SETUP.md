# TiDB Cloud Serverless — setup & operations

Shongkho's backend runs on **TiDB Cloud Serverless** (MySQL-compatible),
region `ap-southeast-1` (Singapore).

## What changed in code

| File | Change |
|---|---|
| `backend/database.py` | `mysql+pymysql://` URLs now get **mandatory TLS** (cert-verification via `certifi`) and `charset=utf8mb4` through `connect_args`. TiDB Cloud refuses plain connections; SQLite behavior is untouched. |
| `backend/tests/conftest.py` | Pins `SQLALCHEMY_DATABASE_URL` to a throwaway SQLite file **before importing the app**, so the test suite never touches the cloud cluster. |

## Connection

`backend/.env` (gitignored — never commit or print):

```
TIDB_DATABASE_URL=mysql+pymysql://<user>:<password>@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/shongkho
TIDB_HOST=gateway01.ap-southeast-1.prod.aws.tidbcloud.com
TIDB_PORT=4000
TIDB_USER=<user>
TIDB_PASSWORD=<password>
```

- Port is **4000** (TiDB Cloud Serverless), not 3306.
- TLS is enforced in code — no CA file needs to be shipped; `certifi`'s bundle
  verifies the server certificate.
- `utf8mb4` end-to-end: Bangla text and emoji round-trip safely.
- The app database is **`shongkho`** (created with `CREATE DATABASE IF NOT
  EXISTS`). The cluster's `sys` database stays TiDB-internal.

## Schema & data

- All 13 tables (`products`, `sales`, `sale_items`, `customers`, `employees`,
  `owners`, `users`, `staff_warnings`, `commission_settings`,
  `assistant_messages`, `chat_messages`, `analysis_runs`,
  `analytics_snapshots`) are created by `init_db()` via `create_all` on
  startup — no manual DDL needed.

## Operations

- **Run the app**: unchanged — `python -m uvicorn main:app` from `backend/`.
  Startup runs `init_db()` (idempotent `create_all` + light migrations).
- **Re-seed demo data**: `python seed_demo_data.py --force` from `backend/`
  now seeds TiDB directly (it uses `get_engine()`).
- **Run tests**: unchanged — `python -m pytest tests/`. Hermetic, SQLite-only.

## Security notes

- The cluster root password lives only in the gitignored `backend/.env`.
  Rotate it in the TiDB Cloud console if it was ever shared.
- Prefer a least-privilege SQL user for the app over the cluster root
  login.
- Serverless free-tier connection limits are modest; the engine's
  `pool_pre_ping` + `pool_recycle=3600` handle idle-connection drops.
