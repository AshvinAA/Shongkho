# UI Audit — Shongkho Frontend (Phase 0)

Date: 2026-09-28 · Baseline commit: `e8c5d32` · Scope: `frontend/src/` only (backend, API contracts, `{message, tool_calls, meta}` envelope: untouched).

## 1. Styling approach

- **React 18 + Vite 5 + react-router 6 + Recharts**. Vitest + Testing Library (41 tests).
- **No Tailwind, no CSS modules, no component library.** One global stylesheet: `src/styles.css` (~2,100 lines) of plain CSS organized by feature-area comment banners appended over time.
- **Token layer exists but is thin** (`:root` custom properties): colors (incl. the teal/green identity from the earlier pass), spacing `--space-1…8`, type `--text-xs…3xl`, radius, two shadows, focus ring. Charts consume tokens via `components/analytics/chartPalette.js`.
- **Design debt:**
  - **99 hex literals** still in `styles.css` (legacy one-off rules predating the token sweep).
  - **Inline `style={{…}}` in 9 files** (17 occurrences): Customers, Dashboard, Inventory, Profile, Register, Staff, EmployeeRace, ErrorBoundary, PhotoUpload.
  - Duplicate near-identical rule blocks (`.stat-box` vs `.stat-card`, two navbar-avatar blocks, two empty-state patterns).
  - **No lint script** in `package.json` — the "lint must pass" gate has nothing to run; build + vitest are the enforced gates. (Adding ESLint is out of scope for a visual pass.)
- 3 hex codes in JSX are all CSS-var *fallbacks* (`var(--chart-axis, #5c6f68)`) — acceptable, not raw styling.

## 2. Component layout

```
src/
  main.jsx                 router (all routes + RoleGate wrappers)
  App.jsx                  shell: <Navbar/> + <main><Outlet/></main> + footer
  styles.css               single global stylesheet
  context/AuthContext.jsx  auth state (untouched by redesign)
  utils/format.js          fmtMoney/fmtDate/fmtNumber
  components/
    Navbar.jsx Modal.jsx Avatar.jsx RoleGate.jsx ProtectedRoute.jsx
    ErrorBoundary.jsx PhotoUpload.jsx CategoryInput.jsx
    analytics/  SalesTrend, EmployeeRace, TopProducts, common.jsx (SegmentedControl, DeltaChip), chartPalette.js
    assistant/  AssistantPanel.jsx (text-only chat)
  pages/  Login, Register, Dashboard, POS, Inventory, Sales, Customers, Staff, Chat, Profile, Analytics, Protik
```

No shared UI-primitives layer exists — Button/Input/Card/etc. are raw CSS classes, so every screen hand-rolls structure.

## 3. Screen / route inventory

| Route | Page | Role | State |
|---|---|---|---|
| `/login`, `/register` | Login, Register | public | migrated, inline styles ×2 in Register |
| `/` | Dashboard | both | migrated, inline styles ×3 |
| `/pos` | POS | both | migrated; functional but not register-optimized |
| `/inventory` | Inventory | owner | migrated, inline styles ×1 |
| `/sales` | Sales | both | migrated, table styling |
| `/customers` | Customers | both | migrated, inline styles ×3 |
| `/analytics` | Analytics | owner | 3 sections (SalesTrend, EmployeeRace, TopProducts) after strip-down |
| `/protik` | Protik | owner | Part A analysis hero + language switch + AssistantPanel |
| `/chat` | Chat | both | WhatsApp-style staff store chat (unrelated to Protik) |
| `/profile` | Profile | both | migrated, inline styles ×1 |
| `/staff` | Staff | owner | per-employee tabs (warnings/commission), inline styles ×3 |
| `*` | NotFound | — | inline styles |

**Legacy/vanilla screens: none.** All pages are React; "legacy" here means *styling debt* (inline styles, pre-token CSS), listed above.

## 4. Chat envelope (hard constraint)

Assistant responses are **text-only**: `{message, tool_calls, meta}` — there are no `ui_blocks` anywhere in the codebase. The redesign must not change this shape. `AssistantPanel` renders prose + suggestion chips only.

## 5. Locked decisions (user-approved this session)

1. **Brand: keep the deep teal/green identity** (the brief's indigo-600 is overridden by the user's earlier explicit choice). Semantic data colors stay: revenue = teal, profit = green, orders = amber, deltas = green/red **with ▲/▼ arrows** (never color alone).
2. **Analytics stays 3 sections** (sales by day, employee race, top products). The LLM insights block and Protik chat live on **/protik** — Phase 5 applies the BI treatment there (hero + insight sections + generated-at), not by re-adding insights to Analytics.
3. Guardrails: no backend/API/auth/data-layer changes; tests updated only where markup changes require it.

## 6. Phase plan (commit after each)

| Phase | Scope | Key deliverables |
|---|---|---|
| 1 | Foundation | Token restructure (slate neutrals + teal ramp, dark-ready), `src/components/ui/` primitives (Button, Input, Select, SegmentedControl, Card, Badge, DeltaChip, StatCard, DataTable, Drawer/Modal, Tabs, Skeleton, EmptyState, ErrorState, Toast, Avatar), `lucide-react` icons; every primitive: hover/focus-visible/disabled/loading |
| 2 | App shell | Fixed left sidebar (icon+label, collapsible, role-based items) + top bar (store name, user menu, role badge) + max-width content; replaces Navbar for every screen |
| 3 | POS | Two-pane register: autofocus search + category chips + large tiles ⇄ fixed cart (steppers, remove, tabular totals), payment selector, 56px Charge, ≥48px targets, keyboard shortcuts, success/next-sale state, tablet-first |
| 4 | Analytics | Header w/ run states + last-analyzed, KPI strip (StatCard+DeltaChip+sparkline), restyled chart w/ segmented controls, employee race (ranked bars, avatars, deltas), top products DataTable (rank, inline bars, margin, toggles), best-days visual, skeleton/empty/error states |
| 5 | Assistant + Protik | Advisor panel (identity constant, prose styling, chips, working state, daily-limit indicator, error styling) on /protik; Protik hero gets the BI treatment (summary/observations/watch + generated-at) |
| 6 | Inventory + Staff | Dense DataTable + filters + low-stock badges + row actions + Drawer edit forms; staff table w/ role badges + drawer forms |
| 7 | Polish + verify | Loading/empty/error everywhere, focus-visible, aria, responsive; grep-proof zero hardcoded hex/px outside token files; converted-vs-leftover list; build+vitest green |

## 7. Baseline verification

- `npx vitest run` → **41 passed** · `npm run build` → green.
