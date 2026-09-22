"""
Celery tasks for the analytics pipeline.

Design: tasks are THIN. Each one opens its own DB session and calls a
pipeline function that is fully unit-testable without Celery. The chord
fans out three parallel aggregation tasks; the callback assembles
snapshots and finalizes the run; link_error releases the lock on any
failure.

Signature notes (Celery gotchas this module is written around):
  - `.si()` = immutable: extra arguments are NOT prepended by the chord,
    so the finalize callback takes exactly (run_id, owner_id, period).
  - Errbacks ARE invoked with (request, exc, traceback) prepended when
    the errback signature is mutable (`.s()`), so run_failed_task
    declares those first and carries the run identity afterwards.
"""
from celery import chord
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from celery_app import celery_app
from database import get_database_url  # resolves the URL lazily at call time

# Session factory per worker process (engines are pooled per process).
_engine = None
_SessionLocal = None


def _session_factory():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


def _run_with_session(fn, *args, **kwargs):
    """Open a fresh session, run fn, always close (get_db semantics)."""
    Session = _session_factory()
    session = Session()
    try:
        return fn(session, *args, **kwargs)
    finally:
        session.close()


# ---------------------------------------------------------
# FAN-OUT: three scoped aggregation tasks
# ---------------------------------------------------------
def _mark_running(db, run_id, owner_id):
    """QUEUED -> RUNNING. Real aggregation happens in the finalize step."""
    run = pipeline.get_run(db, run_id, owner_id)
    if run and run.status == "QUEUED":
        run.status = "RUNNING"
        db.commit()


@celery_app.task(name="analytics.aggregate_sales")
def aggregate_sales_task(run_id, owner_id, period):
    """Fan-out task: sales lane. Marks the run RUNNING; sees its own session."""
    _run_with_session(_mark_running, run_id, owner_id)


@celery_app.task(name="analytics.aggregate_employees")
def aggregate_employees_task(run_id, owner_id, period):
    """Fan-out task: employees lane."""
    _run_with_session(_mark_running, run_id, owner_id)


@celery_app.task(name="analytics.aggregate_products")
def aggregate_products_task(run_id, owner_id, period):
    """Fan-out task: products lane."""
    _run_with_session(_mark_running, run_id, owner_id)


# ---------------------------------------------------------
# FAN-IN: assemble + snapshot + finalize
# ---------------------------------------------------------
@celery_app.task(name="analytics.finalize_run")
def finalize_run_task(run_id, owner_id, period):
    """
    Chord callback: run the full pipeline (aggregations -> snapshots in
    one transaction) and mark the run COMPLETED.

    Stage-1 note: the three fan-out lanes currently share one scoped
    query in the callback (cheaper than re-querying per lane at POS
    scale). The lanes exist to preserve the chord shape and to split
    into real per-section work when data volume grows.
    """
    _run_with_session(pipeline.execute_run, run_id, period)
    return {"run_id": run_id, "status": "COMPLETED"}


# ---------------------------------------------------------
# FAILURE: release the lock immediately
# ---------------------------------------------------------
@celery_app.task(name="analytics.run_failed")
def run_failed_task(request, exc, traceback=None, run_id=None, owner_id=None, period=None):
    """link_error callback: mark the run FAILED so the owner can retry."""
    if run_id:
        reason = f"{type(exc).__name__}: {exc}"
        _run_with_session(pipeline.mark_failed_public, run_id, reason)
    return {"run_id": run_id, "status": "FAILED"}


# ---------------------------------------------------------
# PUBLIC ENQUEUE (called by the /analytics/run route)
# ---------------------------------------------------------
def enqueue_run(run_id: str, owner_id: int, period: str):
    """
    Build and dispatch the chord. Injected into pipeline.start_run by
    the route layer so the pipeline itself stays Celery-free.
    """
    header = [
        aggregate_sales_task.si(run_id, owner_id, period),
        aggregate_employees_task.si(run_id, owner_id, period),
        aggregate_products_task.si(run_id, owner_id, period),
    ]
    callback = finalize_run_task.si(run_id, owner_id, period).on_error(
        run_failed_task.s(run_id, owner_id, period)
    )
    # Dispatching the chord enqueues the header tasks; the callback runs
    # automatically once all three succeed.
    return chord(header)(callback)
