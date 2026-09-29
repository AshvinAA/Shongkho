<!-- ======================================================================
     BANNER — place your banner image at docs/assets/banner.png and
     uncomment the block below. The two-linked-rings mark already exists
     as a React component (frontend/src/components/Logo.jsx); export it
     to PNG/SVG at ~1200x300 for a clean banner.

<p align="center">
  <img src="docs/assets/banner.png" alt="Shongkho — POS for small Bangladeshi shops" width="720" />
</p>
====================================================================== -->

# Shongkho (সংখ্যা)

> **Numbers for the shop you run in your head.**
> A point-of-sale system with an AI advisor, built for small Bangladeshi retail stores.

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-Build-646CFF?logo=vite&logoColor=white)
![MySQL](https://img.shields.io/badge/TiDB%20Cloud-MySQL%20compatible-4479A1?logo=mysql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-300%20backend%20%C2%B7%2046%20frontend%20passing-2EA043)
![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## The problem it solves

Ask a small shop owner in Dhaka how business is going and they'll tell you — from memory.
Which item sells fastest on Fridays, which employee actually moves stock, what's
gathering dust on the shelf: it's all in their head, or in a worn notebook. When
nothing is written down, nothing can be improved.

**Shongkho** (Bengali for "numbers") writes it down, automatically, at the point of
sale. It's a full POS for the counter — fast checkout with cash/bKash/card, live
inventory with product photos, a customer directory — plus per-employee logins so
every sale carries a name. Owners get a real analytics dashboard (revenue, profit,
orders, employee race, top products) instead of a shoebox of receipts.

And then there's **Protik**, the part we're proudest of: an AI advisor that answers
questions in plain English or Bangla — *"How did we do today?"*, *"Is Ghee 500g
selling at all?"* — using **only your store's actual data**. It calls the same
functions the dashboard uses, checks its own numbers before replying, and would
rather say "I can't verify that" than invent a figure. There's also a WhatsApp-style
**store group chat** for owner and staff, attached to the till instead of lost in
personal DMs.

## Screenshots & demo

<!-- ============================================================
     HOW TO FILL THIS SECTION
     Run the app (see Getting started), seed the demo store, then
     capture the shots below into docs/screenshots/ and delete the
     placeholder text. Keep filenames as listed — they're referenced
     by the markdown below. A 30–60s GIF of the POS checkout or a
     Protik conversation is worth more than any screenshot.
     ============================================================ -->

> **TODO (screenshots):** capture these and drop them in `docs/screenshots/`:

| # | Where | What to capture | Filename |
|---|-------|-----------------|----------|
| 1 | Login → Dashboard (owner) | KPI cards + today's trend after seeding demo data | `docs/screenshots/dashboard.png` |
| 2 | POS | Two-pane checkout with a few items in the cart | `docs/screenshots/pos.png` |
| 3 | Analytics | Sales trend + employee race + top products in one scroll | `docs/screenshots/analytics.png` |
| 4 | Protik | A grounded Q&A, e.g. *"How did we do today?"* with tool chips | `docs/screenshots/protik.png` |
| 5 | Store Chat | The group chat with the mixed Bangla team conversation | `docs/screenshots/chat.png` |
| 6 | Inventory | Product grid with photos and stock levels | `docs/screenshots/inventory.png` |

<!-- Paste screenshot 1+2 side by side once captured:

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="Owner dashboard" width="48%" />
  &nbsp;
  <img src="docs/screenshots/pos.png" alt="Point of sale" width="48%" />
</p>

Paste screenshot 3 (Analytics) full width:

<p align="center">
  <img src="docs/screenshots/analytics.png" alt="Analytics dashboard" width="90%" />
</p>
-->

<!-- GIF of a Protik conversation (highly recommended — this is the demo that sells it):

https://github.com/user-attachments/assets/<your-gif-id>
-->

<!-- Video walkthrough (YouTube/Loom embed once uploaded):

[![Shongkho demo video](docs/screenshots/video-thumb.png)](https://www.youtube.com/watch?v=YOUR_VIDEO_ID)
-->

## Tech stack

| Layer | What | Why |
|-------|------|-----|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, PyMySQL | Typed API, `/api/v1/*`, signed-cookie sessions |
| Database | TiDB Cloud (MySQL) — SQLite works locally | Serverless MySQL, TLS via certifi |
| Analytics | Celery + Redis (optional), pandas-free aggregators | `sync` executor runs in-request; Celery chord scales out |
| AI | Gemini REST (via stdlib `urllib`), Ollama supported | Grounded tool-calling advisor with number verification |
| Frontend | React 18, Vite, React Router, Recharts, lucide-react | SPA, custom design-token system, no CSS framework |
| Testing | pytest (300), Vitest + React Testing Library (46) | Hermetic — tests never touch your real DB |
| Deploy | Docker Compose, nginx, Vercel-ready | See [docs/DOCKER.md](docs/DOCKER.md) |

## Getting started

**Prerequisites:** Python 3.12+, Node 20+, Git. (Docker optional. Windows/macOS/Linux all fine.)

```bash
# 1. Clone
git clone https://github.com/AshvinAA/Shongkho.git
cd Shongkho

# 2. Backend — create env, install, configure
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then edit .env:
#   TIDB_DATABASE_URL=sqlite:///./Shongkho_dev.db     ← easiest local start
#   (or point it at a TiDB/MySQL URL for the full experience)
#   SESSION_SECRET_KEY=some-long-random-string

# 3. Seed the demo store (owner, 7 staff, 24 products, ~11k sales, chat, Protik history)
python seed_demo_data.py

# 4. Run the API
python -m uvicorn main:app --reload  # → http://localhost:8000  (docs at /docs)
```

```bash
# 5. Frontend — second terminal
cd frontend
npm install
npm run dev                          # → http://localhost:5173
```

Log in with the demo accounts:

| Role | Phone | Password |
|------|-------|----------|
| Owner (Edwin Zaman) | `01711111100` | `shongkho123` |
| Employees (Rahim, Karim, Sumi, …) | `01711111101` – `01711111107` | `shongkho123` |

> **AI advisor:** set `LLM_PROVIDER=gemini` + `GEMINI_API_KEY=…` in `.env` for the real
> thing, or `LLM_PROVIDER=ollama` to run a local model for free. Without a key, Shongkho
> still works — Protik falls back to deterministic, number-checked summaries.
> **Analytics at scale:** `ANALYTICS_EXECUTOR=sync` (default) needs nothing extra; set it
> to `celery` with Redis for the distributed pipeline (see [docs/ANALYTICS_SETUP.md](docs/ANALYTICS_SETUP.md)).

## Usage examples

Everything the UI does is a plain REST call under `/api/v1`. A taste:

```bash
# Log in (session cookie)
curl -c cookies.txt -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "01711111100", "password": "shongkho123"}'

# Ring up a sale: 2x product #1, cash (prices come from the DB, never the client)
curl -b cookies.txt -X POST localhost:8000/api/v1/checkout/ \
  -H "Content-Type: application/json" \
  -d '{"payment_method": "cash", "items": [{"product_id": 1, "quantity": 2}]}'

# Run the weekly analysis, then read the snapshot dashboard
curl -b cookies.txt -X POST localhost:8000/api/v1/analytics/run \
  -H "Content-Type: application/json" -d '{"period": "week"}'
curl -b cookies.txt "localhost:8000/api/v1/analytics/dashboard?period=week"

# Ask Protik something — the answer is grounded in the store's real numbers
curl -b cookies.txt -X POST localhost:8000/api/v1/analytics/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Who is selling the most this week?"}'
```

Interactive API docs live at `http://localhost:8000/docs` while the server runs.

## Testing

Both suites are hermetic — the backend pins a throwaway SQLite database before the app
imports, so tests never touch your configured database.

```bash
cd backend && python -m pytest tests/ -q     # 300 tests
cd frontend && npm test                      # 46 tests
```

## Roles

| Ability                          | Owner | Employee |
|----------------------------------|:-----:|:--------:|
| Browse products / customers      | ✅    | ✅       |
| Checkout (POS) / quick-add       | ✅    | ✅       |
| Store group chat                 | ✅    | ✅       |
| Protik AI advisor & analytics    | ✅    | ❌       |
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
- **Protik doesn't hallucinate numbers.** Narration that fails the
  number-check is discarded and re-synthesized deterministically from the
  tool output — the answer always matches the database.
- **Role conversions** (owner ↔ employee) swap only the joined-table child
  rows; the shared `users` identity row is never destroyed.

## Documentation

- [Analytics setup](docs/ANALYTICS_SETUP.md) — sync vs Celery executor, Redis on Windows
- [LLM integration](docs/LLM_INTEGRATION.md) — Protik's grounding, verification & language modes
- [TiDB Cloud setup](docs/TIDB_CLOUD_SETUP.md) — migration & TLS configuration
- [Docker](docs/DOCKER.md) — containerized stack (backend + nginx frontend)
- [UI audit](docs/UI_AUDIT.md) — the design-token system behind the interface

## Contributing

This started as a project to solve a real problem, and it grows because people poke
holes in it. If Shongkho would help your shop — or you can see something missing —
that's exactly the feedback wanted:

- 🐛 Found a bug? Open an issue with steps to reproduce.
- 💡 Idea (big or small)? Issues and discussions are open.
- 🔧 Code? PRs are welcome — run both test suites before submitting, and keep PRs focused.

## License

Released under the [MIT License](LICENSE) — free to use, modify, and build on,
with attribution. <!-- TODO: add the LICENSE file itself (one-liner: the standard
MIT text, Copyright (c) 2026 <your name>) — the README link above points to it. -->
