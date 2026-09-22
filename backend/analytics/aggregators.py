"""
Track A aggregators — the deterministic math of the analytics pipeline.

Each aggregator consumes rows already scoped to one owner's store and
computes BOTH the current and previous period in a single pass, so
percentage deltas are exact (not re-derived later from snapshots).

These are pure functions: no DB access, no Celery, no LLM. They take
plain row sequences in and return JSON-ready dicts out. That keeps them
trivially unit-testable and lets Track B tools and the LLM insight
engine reuse the exact same numbers later.

Money is rounded to 2 decimals, percentages to 1. A delta against a
zero baseline is `None` (JSON null) — "no data to compare" is more
honest than a fabricated +100%.
"""
from datetime import datetime

from analytics.timeutils import bucket_key, bucket_series, period_bounds

TOP_N = 10      # products kept per ranking — payload stays small
BEST_N = 3      # "best days / hours" entries shown per metric


def _pct(current: float, previous: float):
    """Percentage change previous -> current, or None without a baseline."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _money(value: float) -> float:
    return round(float(value), 2)


def _when(sale) -> datetime:
    """Combine a Sale row's date + time columns into one datetime."""
    return datetime.combine(sale.date, sale.time)


def _split_windows(sales, period: str, today):
    """
    Partition sale rows into (current_window_rows, previous_window_rows).

    Half-open windows from timeutils.period_bounds; one pass, no double
    iteration over the same query result.
    """
    cur_s, cur_e, prev_s, prev_e = period_bounds(today, period)
    current, previous = [], []
    for sale in sales:
        when = _when(sale)
        if cur_s <= when < cur_e:
            current.append(sale)
        elif prev_s <= when < prev_e:
            previous.append(sale)
    return current, previous


def _window_meta(period: str, today) -> dict:
    """ISO-string window metadata stored with every snapshot."""
    cur_s, cur_e, prev_s, prev_e = period_bounds(today, period)
    return {
        "current_start": cur_s.isoformat(),
        "current_end": cur_e.isoformat(),
        "previous_start": prev_s.isoformat(),
        "previous_end": prev_e.isoformat(),
    }


def _bucketize(sales, period: str):
    """
    Group sales by bucket key -> {key: {revenue, profit, orders}}.

    Orders counts TRANSACTIONS (a 3-line checkout is one order), which
    is the number shop owners actually compare day to day.
    """
    buckets = {}
    for sale in sales:
        key = bucket_key(_when(sale), period)
        cell = buckets.setdefault(key, {"revenue": 0.0, "profit": 0.0, "orders": 0})
        cell["revenue"] += sale.total_revenue or 0.0
        cell["profit"] += sale.total_profit or 0.0
        cell["orders"] += 1
    return buckets


# ---------------------------------------------------------
# 1. SALES
# ---------------------------------------------------------
def aggregate_sales(sales, period: str, today) -> dict:
    """
    Sales section payload: trend series, period totals + deltas, and the
    best hours/days per metric.

    `series` carries BOTH revenue and profit per bucket so the frontend
    metric switch (revenue <-> profit) never needs another fetch.
    """
    current, previous = _split_windows(sales, period, today)
    cur_b, prev_b = _bucketize(current, period), _bucketize(previous, period)

    keys, labels = bucket_series(period, *period_bounds(today, period)[:2])
    unit = "hours" if period == "day" else "days"

    series, by_revenue, by_profit = [], [], []
    for key in keys:
        cur = cur_b.get(key, {"revenue": 0.0, "profit": 0.0, "orders": 0})
        cell = {
            "key": str(key),
            "label": labels[key],
            "revenue": _money(cur["revenue"]),
            "profit": _money(cur["profit"]),
            "orders": cur["orders"],
        }
        series.append(cell)
        if cur["orders"] > 0:  # zero buckets can't be "best" anything
            by_revenue.append(cell)
            by_profit.append(cell)

    by_revenue.sort(key=lambda c: c["revenue"], reverse=True)
    by_profit.sort(key=lambda c: c["profit"], reverse=True)

    totals = lambda rows: {  # noqa: E731 - tiny local helper, read inline
        "revenue": _money(sum(s.total_revenue or 0.0 for s in rows)),
        "profit": _money(sum(s.total_profit or 0.0 for s in rows)),
        "orders": len(rows),
    }
    cur_t, prev_t = totals(current), totals(previous)

    return {
        "period": period,
        "best_unit": unit,
        "current": cur_t,
        "previous": prev_t,
        "change_pct": {
            "revenue": _pct(cur_t["revenue"], prev_t["revenue"]),
            "profit": _pct(cur_t["profit"], prev_t["profit"]),
            "orders": _pct(cur_t["orders"], prev_t["orders"]),
        },
        "series": series,
        "best": {
            "by_revenue": by_revenue[:BEST_N],
            "by_profit": by_profit[:BEST_N],
        },
        "window": _window_meta(period, today),
    }


# ---------------------------------------------------------
# 2. EMPLOYEES
# ---------------------------------------------------------
def aggregate_race_series(sales, period: str, today) -> dict:
    """
    Cumulative revenue/profit per employee across the period's buckets
    — the data behind the "race over time" line chart (avatars drift
    apart as the period progresses).

    Keys are STRING employee ids: JSON object keys are always strings,
    and the snapshot round-trips through storage. Buckets include the
    empty ones so the lines advance tick-by-tick like a real race.
    """
    current, _ = _split_windows(sales, period, today)

    rev_by = {}   # employee_id -> {bucket_key: revenue}
    prof_by = {}  # employee_id -> {bucket_key: profit}
    for sale in current:
        if sale.employee_id is None:
            continue
        key = bucket_key(_when(sale), period)
        rev_by.setdefault(sale.employee_id, {})
        prof_by.setdefault(sale.employee_id, {})
        rev_by[sale.employee_id][key] = rev_by[sale.employee_id].get(key, 0.0) + (sale.total_revenue or 0.0)
        prof_by[sale.employee_id][key] = prof_by[sale.employee_id].get(key, 0.0) + (sale.total_profit or 0.0)

    keys, labels = bucket_series(period, *period_bounds(today, period)[:2])

    def cumulative(by_key):
        out = {}
        for employee_id, cells in by_key.items():
            series, running = [], 0.0
            for key in keys:
                running += cells.get(key, 0.0)
                series.append(_money(running))
            out[str(employee_id)] = series
        return out

    return {
        "keys": [str(k) for k in keys],
        "labels": [labels[k] for k in keys],
        "revenue": cumulative(rev_by),
        "profit": cumulative(prof_by),
    }
def aggregate_employees(sales, participants, period: str, today) -> dict:
    """
    Employee race payload, current vs previous period per participant.

    `participants` are User rows (the store's employees; the pipeline
    may include the owner account, flagged via is_owner) supplying
    user_id / name / photo. A participant who sold in EITHER window
    gets a lane — someone who sold last week but nothing this week
    shows as a zero lane with a declining delta, which is exactly the
    signal the race should surface. Fully inactive participants are
    omitted as noise.

    Both metrics are computed so the frontend can race on revenue or
    profit without refetching.
    """
    info = {p.user_id: {"name": p.name, "photo": p.photo,
                        "is_owner": p.user_type == "owner"}
            for p in participants}

    current, previous = _split_windows(sales, period, today)

    def tally(rows):
        out = {}
        for sale in rows:
            if sale.employee_id is None:
                continue  # detached sale (former staff) — not a race lane
            cell = out.setdefault(
                sale.employee_id, {"orders": 0, "revenue": 0.0, "profit": 0.0}
            )
            cell["orders"] += 1
            cell["revenue"] += sale.total_revenue or 0.0
            cell["profit"] += sale.total_profit or 0.0
        return out

    cur_t, prev_t = tally(current), tally(previous)

    lanes = []
    for employee_id in info:
        cur = cur_t.get(employee_id, {"orders": 0, "revenue": 0.0, "profit": 0.0})
        prev = prev_t.get(employee_id, {"orders": 0, "revenue": 0.0, "profit": 0.0})
        if cur["orders"] == 0 and prev["orders"] == 0:
            continue  # no sales in either window — not a lane worth showing
        meta = info[employee_id]
        lanes.append({
            "employee_id": employee_id,
            "name": meta["name"],
            "photo": meta["photo"],
            "is_owner": meta["is_owner"],
            "orders": cur["orders"],
            "revenue": _money(cur["revenue"]),
            "profit": _money(cur["profit"]),
            "change_pct": {
                "revenue": _pct(cur["revenue"], prev["revenue"]),
                "profit": _pct(cur["profit"], prev["profit"]),
                "orders": _pct(cur["orders"], prev["orders"]),
            },
        })

    lanes.sort(key=lambda l: l["revenue"], reverse=True)

    return {
        "period": period,
        "employees": lanes,
        "race_series": aggregate_race_series(sales, period, today),
        "window": _window_meta(period, today),
    }


# ---------------------------------------------------------
# 3. PRODUCTS
# ---------------------------------------------------------
def aggregate_products(sales, product_names, period: str, today) -> dict:
    """
    Top/bottom products for the ranked table.

    `product_names` maps product_id -> name (resolved by the pipeline in
    one query); deleted products fall back to "Product #<id>" so old
    receipts never break the table.

    Two rankings (revenue and profit) ship in one payload so the
    frontend metric switch re-ranks locally. Items are pruned to TOP_N
    per ranking before they ever reach the snapshot — and later the LLM.
    """
    current, previous = _split_windows(sales, period, today)

    def tally(rows):
        out = {}
        for sale in rows:
            when_key = None  # noqa: F841 - per-item grouping needs no bucket
            for item in sale.items:
                cell = out.setdefault(item.product_id, {
                    "units": 0, "revenue": 0.0, "profit": 0.0,
                })
                qty = item.quantity or 0
                cell["units"] += qty
                cell["revenue"] += (item.retail_price_at_sale or 0.0) * qty
                cell["profit"] += (
                    (item.retail_price_at_sale or 0.0)
                    - (item.cost_price_at_sale or 0.0)
                ) * qty
        return out

    def rank(tallied, key):
        ranked = []
        for product_id, cell in tallied.items():
            margin = None
            if cell["revenue"] > 0:
                margin = round(cell["profit"] / cell["revenue"] * 100, 1)
            ranked.append({
                "product_id": product_id,
                "name": product_names.get(product_id, f"Product #{product_id}"),
                "units": cell["units"],
                "revenue": _money(cell["revenue"]),
                "profit": _money(cell["profit"]),
                "margin_pct": margin,
            })
        ranked.sort(key=lambda row: row[key], reverse=True)
        return ranked

    cur_products = rank(tally(current), "revenue")
    prev_products = rank(tally(previous), "revenue")  # baseline for unit deltas

    prev_by_id = {row["product_id"]: row for row in prev_products}

    def with_trend(rows):
        out = []
        for row in rows:
            row = dict(row)  # never mutate the shared ranking list
            prev = prev_by_id.get(row["product_id"])
            row["units_change_pct"] = (
                _pct(row["units"], prev["units"]) if prev else None
            )
            out.append(row)
        return out

    by_revenue = sorted(cur_products, key=lambda r: r["revenue"], reverse=True)
    by_profit = sorted(cur_products, key=lambda r: r["profit"], reverse=True)

    return {
        "period": period,
        "top_by_revenue": with_trend(by_revenue[:TOP_N]),
        "top_by_profit": with_trend(by_profit[:TOP_N]),
        "bottom_by_revenue": with_trend(
            sorted(by_revenue, key=lambda r: r["revenue"])[:TOP_N]
        ),
        "window": _window_meta(period, today),
    }
