"""
Period and bucket window math for analytics.

All functions are DETERMINISTIC and side-effect free so that the
aggregators and their tests can rely on identical semantics everywhere.

Period semantics (agreed design):
  day   -> buckets = hours of TODAY;       delta vs YESTERDAY
  week  -> buckets = days of THIS week (Mon-Sun); delta vs LAST week
  month -> buckets = days of THIS month;          delta vs LAST month

A bucket never straddles its period, so bucket totals always sum to the
period total and deltas compare like with like (7 days vs 7 days,
month vs month — never "last 30 days" vs "this month").
"""
from datetime import date, datetime, time, timedelta

PERIODS = ("day", "week", "month")


def period_bounds(today: date, period: str):
    """
    (current_start, current_end, previous_start, previous_end) for a period.

    `end` bounds are EXCLUSIVE (half-open [start, end) windows) so SQL and
    Python filtering is uniform: current window = [current_start, current_end),
    previous window = [previous_start, previous_end).

    day   -> [today 00:00, tomorrow 00:00) vs [yesterday 00:00, today 00:00)
    week  -> [this Mon, next Mon)           vs [last Mon, this Mon)
    month -> [1st of month, 1st of next)    vs [1st of last month, 1st of this)
    """
    if period == "day":
        cur_start = datetime.combine(today, time.min)
        cur_end = cur_start + timedelta(days=1)
        prev_start = cur_start - timedelta(days=1)
        prev_end = cur_start
    elif period == "week":
        # Monday as the first day of the week.
        monday = today - timedelta(days=today.weekday())
        cur_start = datetime.combine(monday, time.min)
        cur_end = cur_start + timedelta(days=7)
        prev_start = cur_start - timedelta(days=7)
        prev_end = cur_start
    elif period == "month":
        cur_start = datetime.combine(today.replace(day=1), time.min)
        nxt_month = (cur_start.month % 12) + 1
        year_bump = cur_start.year + (1 if cur_start.month == 12 else 0)
        cur_end = cur_start.replace(year=year_bump, month=nxt_month)
        # Step back one day from the 1st to land in the previous month,
        # then jump to its 1st (handles year boundaries like Jan -> Dec).
        prev_start = (cur_start - timedelta(days=1)).replace(day=1)
        prev_end = cur_start
    else:
        raise ValueError(f"Unknown period: {period!r} (expected one of {PERIODS})")

    return cur_start, cur_end, prev_start, prev_end


def bucket_key(dt: datetime, period: str):
    """
    Canonical grouping key for a timestamp within a period.

    day   -> hour of day (0-23)
    week  -> date (Monday-anchored, so the key sorts naturally)
    month -> date

    Sale rows store a separate date + time column (see models.Sale), so
    callers combine them into one datetime before calling this.
    """
    if period == "day":
        return dt.hour
    return dt.date()


def bucket_series(period: str, cur_start: datetime, cur_end: datetime):
    """
    Ordered bucket keys covering the CURRENT window, plus display labels.

    Returns (keys, labels) where labels[key] is chart-ready text:
      day   -> "14:00", "15:00", ...
      week  -> "Mon 21", "Tue 22", ...
      month -> "1", "2", ... (day of month)

    Empty buckets stay in the series so the chart shows a continuous
    timeline (a quiet Tuesday reads as 0, not as a gap).
    """
    labels = {}

    if period == "day":
        for h in range(24):
            labels[h] = f"{h:02d}:00"
        return list(range(24)), labels

    d = cur_start.date()
    end_d = cur_end.date()
    while d < end_d:
        labels[d] = d.strftime("%a %d") if period == "week" else str(d.day)
        d += timedelta(days=1)

    return list(labels.keys()), labels
