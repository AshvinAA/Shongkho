"""
Shongkho Analytics — Track A (batch analysis pipeline).

Modules:
  timeutils   — period/bucket window math (deterministic, shared)
  aggregators — pure computations: sales / employees / products
  pipeline    — run lifecycle: lock, execute, snapshot writes
  tasks       — Celery wrappers (imported lazily; requires celery+redis)

This package deliberately avoids importing `tasks` at package import
time so the API and test suite run without Celery installed — the
tasks module (and therefore celery) is only loaded when the real
enqueue path is taken (see routes.analytics.get_enqueue).
"""
