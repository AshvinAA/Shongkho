# Shongkho POS — Frontend (React + Vite)

The decoupled SPA for the Shongkho POS system. Talks to the FastAPI backend
entirely through the JSON API under `/api/v1/*` (proxied in development —
no direct backend URL appears in app code).

## Stack

- **Vite 5** — dev server + build
- **React 18** — function components and hooks only
- **React Router v6** (`createBrowserRouter`)
- **Plain CSS** (`src/styles.css`) — no UI framework

## Getting started

```bash
# from the frontend/ directory
npm install
npm run dev      # http://localhost:5173 (proxies /api and /static to :8000)
```

The backend must be running on port 8000:

```bash
# from the backend directory (Shongkho/)
uvicorn main:app --reload --port 8000
```

Demo logins after running `python seed.py`:

| Role     | Phone       | Password |
| -------- | ----------- | -------- |
| Owner    | 01700000001 | owner123 |
| Employee | 01700000002 | emp123   |

## Project structure

```
src/
├── api/            # one module per backend domain, all using client.js
│   ├── client.js   # fetch wrapper: credentials:'include', FastAPI error parsing
│   ├── auth.js
│   ├── products.js
│   ├── customers.js
│   ├── employees.js
│   └── sales.js
├── components/     # reusable building blocks
│   ├── ProtectedRoute.jsx   # auth guard + redirect to /login
│   ├── RoleGate.jsx         # role-based rendering (owner vs employee)
│   ├── Navbar.jsx
│   ├── Modal.jsx
│   ├── PhotoUpload.jsx      # uploads via /api/v1/uploads/profile-photo
│   ├── CategoryInput.jsx    # datalist autocomplete for categories
│   └── ErrorBoundary.jsx
├── context/
│   └── AuthContext.jsx      # session hydration via /auth/me, login/logout
├── pages/          # one file per screen
│   ├── Login.jsx  Register.jsx
│   ├── Dashboard.jsx  POS.jsx  Inventory.jsx
│   ├── Sales.jsx  Customers.jsx  Staff.jsx
├── utils/format.js # money/date/time formatting (৳)
├── main.jsx        # router + providers
├── App.jsx         # authenticated layout shell (Navbar + Outlet)
└── styles.css
```

## Routing & auth model

- Routes are declared in `main.jsx` with `createBrowserRouter`.
- `/login` and `/register` are public; everything else sits under a
  `ProtectedRoute` layout that waits for the session check, then redirects
  anonymous users to `/login` (original location preserved in state).
- There are **no tokens in localStorage** — auth is the FastAPI session
  cookie, sent automatically on every request (`credentials: 'include'`,
  same-origin in dev via the Vite proxy).
- Owner-only screens (Staff) are wrapped in `RoleGate`; role-aware UI
  inside shared pages uses `RoleGate` or `useAuth().user.role`.

## Backend contract notes

- Login/register return `{ user_id, name, role }`; `user_type` values are
  `owner` and `employee`.
- Checkout payload: `{ customer_id, payment_method, items: [{ product_id, quantity }] }`
  — the server derives the employee from the session and recalculates all
  prices, so the client never sends totals.
- Products use `product_id`, `product_name`, `cost_price`, `retail_price`,
  `stock_quantity`, `category`, `supplier_name`.
- Reports: `GET /sales/reports/{daily|weekly|monthly}` (owner only).
