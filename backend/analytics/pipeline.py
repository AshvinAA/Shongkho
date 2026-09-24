"""
Run lifecycle for the analytics pipeline (Track A).

Flow (mirrors the architecture doc):
  POST /analytics/run
    -> owner has a QUEUED/RUNNING row?            -> 409
    -> insert AnalysisRun(QUEUED)                  -> enqueue Celery chord
    -> three aggregations fan out in parallel
    -> executor (sync inline / Celery chord):
         aggregate DTO -> LLM insights (outside any tx, degrades on
         failure) -> write all 4 snapshot rows in ONE transaction
         -> mark run COMPLETED
    -> any failure: link_error marks the run FAILED (releases the lock)

SQLite has no true row locks, so the lock is enforced as "no row in
QUEUED/RUNNING for this owner" — a check-then-insert guarded by a
module-level threading lock in dev, plus the unique-ish semantics of
run ids. Production (TiDB/MySQL) gets the same logic with plain
SELECT ... FOR UPDATE if you later want hard mutual exclusion.
"""
import threading
from datetime import date, datetime, timedelta

import models
from analytics import aggregators, insights, timeutils
from sqlalchemy import func
from sqlalchemy.orm import Session

# Guards the check-then-insert lock sequence within one process
# (uvicorn workers / TestClient). Cross-process safety in production
# comes from the same check inside the enqueue path + run ids.
_run_lock = threading.Lock()

VALID_SECTIONS = ("sales", "employees", "products", "insights")


class RunConflictError(Exception):
    """Raised when the owner already has an active (QUEUED/RUNNING) run."""


class RunValidationError(Exception):
    """Raised for bad input (unknown period, etc.)."""


# ---------------------------------------------------------
# START A RUN
# ---------------------------------------------------------
def start_run(db: Session, owner_id: int, period: str, enqueue=None) -> str:
    """
    Create a QUEUED run (the lock) and enqueue the Celery chord.

    `enqueue` is injected (routes pass the Celery task's .si signature)
    so this module stays importable without Celery — the same seam the
    tests use to swap in a synchronous executor.

    Returns the new run id (uuid string).
    """
    if period not in timeutils.PERIODS:
        raise RunValidationError(f"period must be one of {list(timeutils.PERIODS)}")

    with _run_lock:
        active = db.query(models.AnalysisRun).filter(
            models.AnalysisRun.owner_id == owner_id,
            models.AnalysisRun.status.in_(("QUEUED", "RUNNING")),
        ).first()
        if active:
            raise RunConflictError(
                f"An analysis run is already {active.status} for this store."
            )

        run = models.AnalysisRun(owner_id=owner_id, status="QUEUED")
        db.add(run)
        db.commit()
        db.refresh(run)

    if enqueue is not None:
        try:
            enqueue(run.id, owner_id, period)
        except Exception as exc:  # noqa: BLE001 - broker down: release the lock
            _mark_failed(db, run.id, f"Could not queue analysis: {exc}")
            raise

    return run.id


def get_run(db: Session, run_id: str, owner_id: int):
    """Fetch one run scoped to its owner (404-semantics live in routes)."""
    return db.query(models.AnalysisRun).filter(
        models.AnalysisRun.id == run_id,
        models.AnalysisRun.owner_id == owner_id,
    ).first()


# ---------------------------------------------------------
# EXECUTION (called by Celery tasks — or directly in tests)
# ---------------------------------------------------------
def _store_participants(db: Session, owner_id: int):
    """Everyone whose sales belong to this store: staff + the owner."""
    participants = list(
        db.query(models.Employee).filter(models.Employee.employer_id == owner_id).all()
    )
    owner = db.query(models.Owner).filter(models.Owner.user_id == owner_id).first()
    if owner:
        participants.append(owner)
    return participants


def _execute_run(db: Session, run, period: str) -> None:
    """
    Run all three aggregations + snapshot writes for one run row.

    Shared by the Celery tasks and by tests that call the pipeline
    synchronously. Raises on failure; callers mark the run FAILED.
    """
    today = date.today()
    participants = _store_participants(db, run.owner_id)
    participant_ids = [p.user_id for p in participants]

    # One scoped query for the whole window pair (current + previous).
    # Pull rows once and aggregate in Python — DB-agnostic (SQLite tests
    # fine) and fast at POS scale.
    window_start = timeutils.period_bounds(today, period)[2]  # previous_start
    sales = (
        db.query(models.Sale)
        .filter(
            models.Sale.date >= window_start.date(),
            models.Sale.employee_id.in_(participant_ids),
        )
        .options()  # explicit: no eager loads needed beyond items below
        .all()
    )

    product_ids = {
        item.product_id
        for sale in sales for item in sale.items
    }
    product_names = {}
    if product_ids:
        rows = db.query(models.Product.product_id, models.Product.product_name).filter(
            models.Product.product_id.in_(product_ids)
        ).all()
        product_names = dict(rows)

    # ---- deterministic aggregations (pure functions) ----
    sales_payload = aggregators.aggregate_sales(sales, period, today)
    employees_payload = aggregators.aggregate_employees(
        sales, participants, period, today
    )
    products_payload = aggregators.aggregate_products(sales, product_names, period, today)

    # ---- Part A: LLM insight engine (docs/LLM_INTEGRATION.md §2) ----
    # History fetch happens BEFORE the network call and the snapshot tx:
    # completed sales-section snapshots for this owner + period_type,
    # newest first. Calendar mapping (dedupe, gap-as-null, rollup) lives
    # in insights.build_context.
    history = [
        row.data for row in db.query(models.AnalyticsSnapshot.data)
        .join(models.AnalysisRun, models.AnalysisRun.id == models.AnalyticsSnapshot.run_id)
        .filter(
            models.AnalyticsSnapshot.owner_id == run.owner_id,
            models.AnalyticsSnapshot.section == "sales",
            models.AnalyticsSnapshot.period_type == period,
            models.AnalysisRun.status == "COMPLETED",
        )
        .order_by(models.AnalyticsSnapshot.id.desc())
        .limit(insights.HISTORY_K * 4)  # headroom for same-window duplicates
        .all()
    ]
    bundle = insights.build_context(
        sales_payload, history,
        employees_payload=employees_payload,
        products_payload=products_payload,
    )
    # The LLM call happens HERE — after aggregations, BEFORE the snapshot
    # transaction. No DB transaction ever spans the network call; any
    # failure degrades to a flagged fallback and the run still completes.
    insights_payload = insights.build_insights(bundle, period)

    # ---- snapshot writes: all sections in ONE transaction ----
    # All four payloads are fully computed above; the single tx publishes
    # them atomically. (Stage-1 placeholder removed: the LLM now supplies
    # real insights, or a degraded marker when it could not run.)
    now = datetime.utcnow()
    rows = [
        models.AnalyticsSnapshot(
            run_id=run.id, owner_id=run.owner_id,
            section="sales", period_type=period,
            data=sales_payload, generated_at=now,
        ),
        models.AnalyticsSnapshot(
            run_id=run.id, owner_id=run.owner_id,
            section="employees", period_type=period,
            data=employees_payload, generated_at=now,
        ),
        models.AnalyticsSnapshot(
            run_id=run.id, owner_id=run.owner_id,
            section="products", period_type=period,
            data=products_payload, generated_at=now,
        ),
        models.AnalyticsSnapshot(
            run_id=run.id, owner_id=run.owner_id,
            section="insights", period_type=period,
            data=insights_payload, generated_at=now,
        ),
    ]
    db.add_all(rows)
    db.commit()  # all four visible or none — never mixed stale/fresh

    run.status = "COMPLETED"
    run.completed_at = datetime.utcnow()
    db.commit()


def execute_run(db: Session, run_id: str, period: str) -> None:
    """
    Execute a run end-to-end, marking it FAILED on any error.

    The period travels with the enqueue payload (run.id, owner_id,
    period) — the chord tasks pass it straight through here.

    Re-entry rules (make retries safe):
      - QUEUED   -> flipped to RUNNING and executed.
      - RUNNING  -> re-executed (worker retry / sync fallback re-entry).
      - FAILED   -> re-executed (a retry after failure must be able to
                    rewrite the snapshots; stale FAILED rows from a
                    partial attempt are cleared first).
      - COMPLETED-> no-op (a completed run is immutable).
    """
    run = db.query(models.AnalysisRun).filter(
        models.AnalysisRun.id == run_id
    ).first()
    if not run or run.status == "COMPLETED":
        return

    if run.status != "RUNNING":
        # Drop any partial snapshots from a previously failed attempt so
        # the UNIQUE(run_id, section, period_type) constraint cannot be
        # violated by the retry.
        db.query(models.AnalyticsSnapshot).filter(
            models.AnalyticsSnapshot.run_id == run.id
        ).delete()
        run.status = "RUNNING"
        run.failure_reason = None
        db.commit()

    try:
        _execute_run(db, run, period)
    except Exception as exc:  # noqa: BLE001 - any failure releases the lock
        db.rollback()
        _mark_failed(db, run.id, str(exc) or exc.__class__.__name__)
        raise


# ---------------------------------------------------------
# FAILURE / RECOVERY
# ---------------------------------------------------------
def _mark_failed(db: Session, run_id: str, reason: str) -> None:
    """Mark a run FAILED (releases the owner's lock for the next retry)."""
    run = db.query(models.AnalysisRun).filter(
        models.AnalysisRun.id == run_id
    ).first()
    if not run or run.status in ("COMPLETED", "FAILED"):
        return
    run.status = "FAILED"
    run.completed_at = datetime.utcnow()
    run.failure_reason = reason[:2000]
    db.commit()


def mark_failed_public(db: Session, run_id: str, reason: str) -> None:
    """Public wrapper used by Celery link_error callbacks."""
    _mark_failed(db, run_id, reason)


def mark_stale_runs_failed(db: Session, timeout_minutes: int = 10) -> int:
    """
    Watchdog: fail runs stuck in RUNNING/QUEUED past the timeout.

    Returns how many runs were reaped. Wired to a Celery beat schedule
    in stage 4; safe to call manually any time.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    stale = db.query(models.AnalysisRun).filter(
        models.AnalysisRun.status.in_(("QUEUED", "RUNNING")),
        models.AnalysisRun.started_at < cutoff,
    ).all()
    for run in stale:
        run.status = "FAILED"
        run.completed_at = datetime.utcnow()
        run.failure_reason = f"TIMEOUT after {timeout_minutes} min"
    if stale:
        db.commit()
    return len(stale)


# ---------------------------------------------------------
# DASHBOARD READ PATH
# ---------------------------------------------------------
def latest_snapshots(db: Session, owner_id: int, period: str) -> dict:
    """
    Latest COMPLETED snapshot per section for this owner + period.

    The dashboard's only read: indexed lookup, never live aggregation.
    Sections with no completed run yet are simply absent from the dict.
    """
    # max(id) per section = the newest run's row for that section: rows
    # are inserted per run in one transaction, so ids are monotonic with
    # runs. Joining back on id avoids any generated_at tie ambiguity.
    latest_sq = (
        db.query(
            models.AnalyticsSnapshot.section,
            func.max(models.AnalyticsSnapshot.id).label("max_id"),
        )
        .join(models.AnalysisRun,
              models.AnalysisRun.id == models.AnalyticsSnapshot.run_id)
        .filter(
            models.AnalyticsSnapshot.owner_id == owner_id,
            models.AnalyticsSnapshot.period_type == period,
            models.AnalysisRun.status == "COMPLETED",
        )
        .group_by(models.AnalyticsSnapshot.section)
        .subquery()
    )

    rows = db.query(models.AnalyticsSnapshot).join(
        latest_sq,
        models.AnalyticsSnapshot.id == latest_sq.c.max_id,
    ).all()

    return {row.section: row.data for row in rows}
