"""
Celery application for the Shongkho analytics pipeline.

Windows note: the default prefork pool does not work well on Windows.
Start workers with --pool=solo (single-threaded — fine for a dev setup
and small shops; scale-out comes later on Linux prod). See
docs/ANALYTICS_SETUP.md for copy-paste commands.

The chord (fan-out/fan-in):
    aggregate_sales ─┐
    aggregate_employees ─┼─> chord callback: assemble + snapshot + insights
    aggregate_products ─┘

Every task opens its OWN database session (never share session objects
across processes/threads), mirroring database.get_db semantics.
"""
import os

from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
BACKEND_URL = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "shongkho",
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=["analytics.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Reliability knobs for the run pipeline:
    task_acks_late=True,            # re-deliver if a worker dies mid-task
    worker_prefetch_multiplier=1,   # fair fan-out across workers
    # Stage 4 wires this to beat: watchdog reaps runs stuck RUNNING.
    # beat_schedule stays empty until the watchdog task ships.
)

# The DB URL is read lazily inside tasks via get_database_url(); nothing
# here connects to the database at import time (same contract as the
# FastAPI app, so the test suite can point everything at SQLite).
