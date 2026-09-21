"""
Shongkho POS API — application entry point.

Wiring overview:
  1. Middleware: CORS (outermost, so every response gets CORS headers)
     and the signed-cookie session used for authentication.
  2. Static files: uploaded pictures served from backend/static.
  3. Routers: everything the SPA uses lives under /api/v1/*.
  4. Health check: GET /api/v1/health for uptime probes.

Run with:
  uvicorn main:app --reload                      (from the backend/ directory)
  uvicorn main:app --reload --app-dir backend    (from the project root)
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import database
import deps
from routes import auth, chat, customers, employees, products, sales

STATIC_DIR = os.path.join(deps.BASE_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: make sure new tables and columns (chat_messages,
    products.photo, ...) exist before serving traffic. A migration
    failure is logged but does not block boot.
    """
    try:
        database.init_db()
    except Exception as exc:  # noqa: BLE001 - don't block boot on migration issues
        print(f"[startup] migration check failed: {exc}")
    yield


app = FastAPI(title="Shongkho POS API", version="3.0", lifespan=lifespan)

# ---------------------------------------------------------
# MIDDLEWARE
# SessionMiddleware is added first, then CORS — middleware runs in
# reverse order of registration, so CORS ends up as the outermost layer
# and every response (including errors) carries CORS headers.
# ---------------------------------------------------------
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "CHANGE-THIS-TO-A-LONG-RANDOM-SECRET-STRING"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# STATIC MEDIA (uploaded images, resolved from backend/ regardless of cwd)
# ---------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------
# PROFILE PHOTO UPLOAD
# ---------------------------------------------------------
@app.post("/api/v1/uploads/profile-photo", tags=["Uploads"])
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user=Depends(deps.get_current_user),
):
    """
    Save a profile picture and return its public /static URL.

    Used by the Profile page before saving; the URL is then attached to
    the account via PUT /employees/me/profile.
    """
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WebP or GIF images are allowed.")

    ext = allowed[file.content_type]
    filename = f"{os.urandom(8).hex()}{ext}"  # random name — never trust client filenames

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be 5 MB or smaller.")

    upload_dir = os.path.join(STATIC_DIR, "profile_pics")
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), "wb") as out:
        out.write(contents)

    return {"photo_url": f"/static/profile_pics/{filename}"}


# ---------------------------------------------------------
# API ROUTERS (/api/v1/*)
# ---------------------------------------------------------
API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(products.router, prefix=API_PREFIX)
app.include_router(customers.router, prefix=API_PREFIX)
app.include_router(employees.router, prefix=API_PREFIX)
app.include_router(sales.router, prefix=API_PREFIX)
app.include_router(sales.sales_router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------
@app.get("/api/v1/health", tags=["Health"])
def health_check():
    """Uptime probe — no auth required."""
    return {"status": "ok", "service": "Shongkho POS API"}
