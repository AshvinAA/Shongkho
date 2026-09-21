"""
Development launcher — start the API from the PROJECT ROOT with:

    python -m uvicorn main:app --reload --port 8000

Why this file exists
--------------------
The real application lives in backend/main.py (decoupled layout), but
uvicorn resolves the "main:app" import string against the directory it
is started from. Without this shim, launching from the root fails with
`Could not import module "main"` and the frontend proxy then logs
ECONNREFUSED for every /api request.

How it works
------------
1. Put backend/ on sys.path so the app's internal imports
   (database, deps, models, routes, ...) resolve.
2. Load backend/main.py under a DIFFERENT module name ("backend_main").
   Importing it as "main" would find THIS file (uvicorn asked for the
   module "main") and recurse into itself.
3. Re-export its FastAPI `app` object for uvicorn.

Reload caveat
-------------
--reload watches the directory uvicorn starts in (here: the root), so
edits under backend/ will NOT auto-restart the server unless you add:

    --reload-dir backend

Alternatively, run uvicorn from inside backend/ (see README).
"""
import importlib.util
import os
import sys

# 1. Make the backend package directory importable (database, routes, ...).
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# 2. Execute backend/main.py under an alias to avoid self-recursion.
_spec = importlib.util.spec_from_file_location(
    "backend_main", os.path.join(BACKEND_DIR, "main.py")
)
_backend_main = importlib.util.module_from_spec(_spec)
sys.modules["backend_main"] = _backend_main
_spec.loader.exec_module(_backend_main)

# 3. Expose the ASGI app that uvicorn looks for in "main:app".
app = _backend_main.app
