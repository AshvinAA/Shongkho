"""
Analytics routes (Track A) — owner-only.

  POST /analytics/run               -> start a run (409 while one is active)
  GET  /analytics/run/{id}/status   -> poll run lifecycle
  GET  /analytics/dashboard         -> latest completed snapshots per section

Snapshots freeze per-run results, so dashboard reads are single indexed
lookups — never live aggregation. All endpoints are gated by
require_owner, matching the existing /sales/reports gate.
"""
import functools
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import deps
import models
import schemas
from analytics import pipeline
from database import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Per-process cache of the chosen executor (Celery vs sync fallback).
_enqueue_cache = None


def _sync_enqueue(db: Session, run_id: str, owner_id: int, period: str):
    """
    In-request executor used when Celery/Redis is unavailable.

    Deliberately runs on the REQUEST's own DB session: that session is
    bound to the database this tenant/store actually uses (tests swap
    it for SQLite; deployments may shard). A module-level session
    factory would silently target a different database.
    """
    pipeline.execute_run(db, run_id=run_id, period=period)


def get_enqueue(db: Session = Depends(get_db)):
    """
    Executor injected into pipeline.start_run.

    Selected by ANALYTICS_EXECUTOR:

      "sync" (default)
          Pipeline executes inline in the POST request, on the request's
          session. Same pipeline, same tables, same snapshots — results
          are ready when the response returns (the frontend poller sees
          COMPLETED on its first tick). No Redis/Celery needed.

      "celery"
          The production chord (fan-out/fan-in via Redis). Requires
          celery + redis packages AND a running worker; if celery is
          missing we log and fall back to sync rather than 500-ing.

    Explicit configuration beats runtime probing: a broker probe could
    "pass" with no worker attached, leaving runs queued forever. The
    sync branch binds the request session via partial — no per-process
    cache, the mode lookup is trivial. Tests override this dependency
    wholesale.
    """
    mode = os.getenv("ANALYTICS_EXECUTOR", "sync").strip().lower()

    if mode == "celery":
        try:
            from analytics import tasks
            return tasks.enqueue_run
        except ImportError as exc:
            print(f"[analytics] ANALYTICS_EXECUTOR=celery but celery is "
                  f"unavailable ({exc}); using synchronous execution")

    return functools.partial(_sync_enqueue, db)


def _period(period: str) -> str:
    """Validate the period query param once, in one place."""
    if period not in ("day", "week", "month"):
        raise HTTPException(status_code=400, detail="period must be day, week or month")
    return period


# ---------------------------------------------------------
# POST /analytics/run — trigger the pipeline
# ---------------------------------------------------------
@router.post("/run", status_code=202)
def start_analysis(
    payload: schemas.RunStartRequest,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
    enqueue=Depends(get_enqueue),
):
    """
    Kick off a full analytics run for the owner's store.

    Returns 202 immediately with the run id — the frontend then polls
    /run/{id}/status. Rejects with 409 while another run is QUEUED or
    RUNNING for this store (the lock).
    """
    try:
        run_id = pipeline.start_run(
            db,
            owner_id=current_user["id"],
            period=payload.period,
            enqueue=enqueue,
        )
    except pipeline.RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except pipeline.RunValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - clean error, not a traceback
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {exc}",
        )

    # With the sync executor the run finishes inside start_run, so the
    # response reflects the true state; with Celery it is still QUEUED.
    # db.expire_all() forces a fresh SELECT: the sync executor writes via
    # a different session, and the identity map would otherwise replay
    # the stale in-memory QUEUED status it cached earlier in the request.
    db.expire_all()
    run = pipeline.get_run(db, run_id, current_user["id"])
    status = run.status if run else "QUEUED"
    return {"run_id": run_id, "status": status, "period": payload.period}


# ---------------------------------------------------------
# GET /analytics/run/{run_id}/status — poll lifecycle
# ---------------------------------------------------------
@router.get("/run/{run_id}/status", response_model=schemas.RunStatusResponse)
def run_status(
    run_id: str,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    run = pipeline.get_run(db, run_id, current_user["id"])
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return schemas.RunStatusResponse(
        run_id=run.id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failure_reason=run.failure_reason,
    )


# ---------------------------------------------------------
# GET /analytics/dashboard — latest snapshots
# ---------------------------------------------------------
@router.get("/dashboard", response_model=schemas.AnalyticsDashboardResponse)
def dashboard(
    period: str = Query(default="week"),
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """
    Latest COMPLETED snapshot per section for one period type.

    The frontend switches day/week/month by refetching this endpoint —
    snapshots are frozen per run, so a switch is one indexed lookup.
    """
    period = _period(period)
    sections = pipeline.latest_snapshots(db, current_user["id"], period)

    generated_at = None
    if sections:
        newest = (
            db.query(models.AnalyticsSnapshot)
            .filter(
                models.AnalyticsSnapshot.owner_id == current_user["id"],
                models.AnalyticsSnapshot.period_type == period,
            )
            .order_by(models.AnalyticsSnapshot.id.desc())
            .first()
        )
        if newest:
            generated_at = newest.generated_at

    return schemas.AnalyticsDashboardResponse(
        period=period, generated_at=generated_at, sections=sections
    )
