"""
Part B tool registry (docs/LLM_INTEGRATION.md §3.3).

A CLOSED registry of three tools the conversational assistant may call.
Contract highlights:

  - store_id is ALWAYS injected server-side (scope injection) — it is
    never an LLM-supplidable argument, in any tool. Every query is
    scoped to the owner's participant ids (employees + the owner).
  - Tools return PRE-AGGREGATED payloads — never raw rows — shaped like
    the dashboard sections the frontend already renders (reusing
    SalesTrend / EmployeeRace / TopProducts).
  - Bad arguments raise ValueError; the agent loop turns that error
    text into the tool observation so the model gets ONE counted
    corrective retry (doc §3.3 self-correction).
  - No LLM output is ever trusted here: dates are strictly parsed,
    metric/limit enums are explicit, unexpected errors are converted to
    model-safe ValueError text (no tracebacks into the chat).
"""
from datetime import date, datetime, timedelta

from analytics import aggregators, timeutils

# Hard ceiling on ranked product rows returned to the UI (mirrors the
# dashboard's TOP_N so the table component's expectations hold).
PRODUCT_LIMIT_CAP = 10

DATE_FORMAT = "%Y-%m-%d"


# ---------------------------------------------------------
# Argument validation (model-facing error text)
# ---------------------------------------------------------
def _parse_date(value, name: str) -> date:
    """Strict ISO date parsing — the ValueError text goes to the model."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a 'YYYY-MM-DD' string")
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        raise ValueError(
            f"{name} is not a valid date: got {value!r}, expected 'YYYY-MM-DD'"
        ) from None


def _store_sales(db, owner_id: int, start_dt: datetime, end_dt: datetime):
    """
    The owner's store sales inside [start_dt, end_dt), one query.

    Scoped to participant ids (employees + the owner) exactly like
    Track A's pipeline — an empty participant list matches nothing,
    which is the safe default, never "everyone".
    """
    import models
    participant_ids = [p.user_id for p in _participants(db, owner_id)]
    rows = (
        db.query(models.Sale)
        .filter(
            models.Sale.date >= start_dt.date(),
            models.Sale.date < end_dt.date(),
            models.Sale.employee_id.in_(participant_ids),
        )
        .all()
    )
    return [s for s in rows
            if start_dt <= aggregators._when(s) < end_dt]  # noqa: SLF001


def _find_participant(participants, name: str):
    """Case-insensitive contains-match; ValueError when nobody matches."""
    needle = (name or "").strip().lower()
    if needle:
        for p in participants:
            if needle in (p.name or "").lower():
                return p
    raise ValueError(
        f"no employee matching {name!r} — ask the user or try another name"
    )


# ---------------------------------------------------------
# Tool 1: sales metrics over an arbitrary range
# ---------------------------------------------------------
def get_sales_metrics(db, owner_id: int, start, end) -> dict:
    """
    Revenue/profit/orders bucketed across [start, end], scoped to the
    owner's store. Buckets follow timeutils.range_buckets resolution
    (daily/weekly/monthly, 60-bucket ceiling).
    """
    s = _parse_date(start, "start")
    e = _parse_date(end, "end")
    start_dt, end_dt, keys, labels = timeutils.range_buckets(s, e)

    sales = _store_sales(db, owner_id, start_dt, end_dt)

    rev_by, prof_by, ord_by = {}, {}, {}
    for sale in sales:
        when = aggregators._when(sale)  # noqa: SLF001
        key = _bucket_key(when, keys)
        rev_by[key] = rev_by.get(key, 0.0) + (sale.total_revenue or 0.0)
        prof_by[key] = prof_by.get(key, 0.0) + (sale.total_profit or 0.0)
        ord_by[key] = ord_by.get(key, 0) + 1

    series = [{
        "key": str(k),
        "label": labels[k],
        "revenue": round(rev_by.get(k, 0.0), 2),
        "profit": round(prof_by.get(k, 0.0), 2),
        "orders": ord_by.get(k, 0),
    } for k in keys]

    return {
        "section": "sales_metrics",
        "range": {"start": s.isoformat(), "end": e.isoformat()},
        "totals": {
            "revenue": round(sum(rev_by.values()), 2),
            "profit": round(sum(prof_by.values()), 2),
            "orders": len(sales),
        },
        "series": series,
        "best": {
            "by_revenue": sorted(
                series, key=lambda c: c["revenue"], reverse=True)[:3],
        },
    }


# ---------------------------------------------------------
# Tool 2: employee performance over an arbitrary range
# ---------------------------------------------------------
def get_employee_performance(db, owner_id: int, start, end,
                             employee_name: str = None) -> dict:
    """
    Per-employee revenue/profit/orders across [start, end] — the
    EmployeeRace lane shape. Optional `employee_name` narrows to one
    person (case-insensitive contains-match; unknown names raise
    ValueError so the model can correct itself). No change_pct here:
    an arbitrary range has no like-for-like baseline.
    """
    s = _parse_date(start, "start")
    e = _parse_date(end, "end")
    start_dt, end_dt, _keys, _labels = timeutils.range_buckets(s, e)

    participants = _participants(db, owner_id)
    wanted = None
    if employee_name:
        wanted = _find_participant(participants, employee_name)

    scope = [wanted] if wanted else participants
    sales = _store_sales(db, owner_id, start_dt, end_dt)
    if wanted:
        sales = [x for x in sales if x.employee_id == wanted.user_id]

    tally = {}
    for sale in sales:
        if sale.employee_id is None:
            continue
        cell = tally.setdefault(sale.employee_id,
                                {"orders": 0, "revenue": 0.0, "profit": 0.0})
        cell["orders"] += 1
        cell["revenue"] += sale.total_revenue or 0.0
        cell["profit"] += sale.total_profit or 0.0

    lanes = []
    for p in scope:
        cell = tally.get(p.user_id)
        if not cell:
            continue  # no sales in range — not a lane worth showing
        lanes.append({
            "employee_id": p.user_id,
            "name": p.name,
            "photo": p.photo,
            "is_owner": p.user_type == "owner",
            "orders": cell["orders"],
            "revenue": round(cell["revenue"], 2),
            "profit": round(cell["profit"], 2),
        })
    lanes.sort(key=lambda lane: lane["revenue"], reverse=True)

    return {
        "section": "employee_performance",
        "range": {"start": s.isoformat(), "end": e.isoformat()},
        "employees": lanes,
    }


# ---------------------------------------------------------
# Tool 3: top products over an arbitrary range
# ---------------------------------------------------------
def get_top_products(db, owner_id: int, start, end,
                     metric: str = "revenue", limit=5) -> dict:
    """
    Ranked products across [start, end] by `metric` (revenue|profit|
    units), top `limit` rows (<= 10). Rows match the TopProducts table:
    name/units/revenue/profit/margin_pct.
    """
    s = _parse_date(start, "start")
    e = _parse_date(end, "end")
    if metric not in ("revenue", "profit", "units"):
        raise ValueError(
            f"metric must be one of 'revenue', 'profit', 'units' — got {metric!r}"
        )
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError(f"limit must be an integer — got {limit!r}") from None
    if not 1 <= limit <= PRODUCT_LIMIT_CAP:
        raise ValueError(f"limit must be between 1 and {PRODUCT_LIMIT_CAP}")

    start_dt, end_dt, _keys, _labels = timeutils.range_buckets(s, e)
    sales = _store_sales(db, owner_id, start_dt, end_dt)

    import models
    product_ids = {item.product_id for sale in sales for item in sale.items}
    product_names = {}
    if product_ids:
        rows = db.query(models.Product.product_id,
                        models.Product.product_name).filter(
            models.Product.product_id.in_(product_ids)).all()
        product_names = dict(rows)

    tally = {}
    for sale in sales:
        for item in sale.items:
            cell = tally.setdefault(item.product_id,
                                    {"units": 0, "revenue": 0.0, "profit": 0.0})
            qty = item.quantity or 0
            cell["units"] += qty
            cell["revenue"] += (item.retail_price_at_sale or 0.0) * qty
            cell["profit"] += (
                (item.retail_price_at_sale or 0.0) - (item.cost_price_at_sale or 0.0)
            ) * qty

    ranked = []
    for pid, cell in tally.items():
        margin = None
        if cell["revenue"] > 0:
            margin = round(cell["profit"] / cell["revenue"] * 100, 1)
        ranked.append({
            "product_id": pid,
            "name": product_names.get(pid, f"Product #{pid}"),
            "units": cell["units"],
            "revenue": round(cell["revenue"], 2),
            "profit": round(cell["profit"], 2),
            "margin_pct": margin,
        })
    ranked.sort(key=lambda row: row[metric], reverse=True)

    return {
        "section": "top_products",
        "range": {"start": s.isoformat(), "end": e.isoformat()},
        "metric": metric,
        "products": ranked[:limit],
    }


# ---------------------------------------------------------
# Registry (closed — doc §3.3)
# ---------------------------------------------------------
REGISTRY = {
    "get_sales_metrics": {
        "fn": get_sales_metrics,
        "description": (
            "Revenue/profit/orders for the store over a date range, "
            "bucketed into days/weeks/months. Use for trend questions."
        ),
        "args": ["start", "end"],
    },
    "get_employee_performance": {
        "fn": get_employee_performance,
        "description": (
            "Per-employee sales (revenue, profit, orders) over a range. "
            "Optional employee_name narrows to one person."
        ),
        "args": ["start", "end", "employee_name?"],
    },
    "get_top_products": {
        "fn": get_top_products,
        "description": (
            "Top products by revenue, profit or units over a range, "
            "ranked and limited."
        ),
        "args": ["start", "end", "metric?", "limit?"],
    },
}


def execute(db, owner_id: int, name: str, args: dict):
    """
    Run one tool by registry name with server-injected scope.

    Returns the tool payload dict. Raises ValueError on bad args (the
    agent loop returns the message to the model as the observation).
    Any unexpected error is also converted to ValueError with a
    model-safe message — tools never leak tracebacks into the chat.
    """
    entry = REGISTRY.get(name)
    if entry is None:
        raise ValueError(
            f"unknown tool {name!r} — available: {sorted(REGISTRY)}"
        )
    args = dict(args or {})
    args.pop("store_id", None)  # scope is injected, never supplied
    try:
        return entry["fn"](db, owner_id, **args)
    except ValueError:
        raise
    except TypeError as exc:
        raise ValueError(f"bad arguments for {name}: {exc}") from None
    except Exception as exc:  # noqa: BLE001 - model-safe error text only
        raise ValueError(f"tool {name} failed: {type(exc).__name__}") from exc


# ---------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------
def _participants(db, owner_id):
    """Store participants: employees + the owner (same rule as Track A)."""
    import models
    participants = list(
        db.query(models.Employee).filter(
            models.Employee.employer_id == owner_id).all()
    )
    owner = db.query(models.Owner).filter(
        models.Owner.user_id == owner_id).first()
    if owner:
        participants.append(owner)
    return participants


def _bucket_key(when: datetime, keys):
    """
    Map a timestamp to the bucket plan's key. `keys` are homogeneous:

      monthly  -> keys are (year, month) tuples
      weekly   -> keys are dates spaced 7 days apart (Mondays)
      daily    -> keys are dates spaced 1 day apart
    """
    first = keys[0]
    if isinstance(first, tuple):  # monthly
        return (when.year, when.month)
    d = when.date()
    if (len(keys) > 1 and (keys[1] - keys[0]).days == 7):
        return d - timedelta(days=d.weekday())  # weekly: Monday anchor
    return d  # daily
