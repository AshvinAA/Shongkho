
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from routes import auth, products, sales, customers, employees

import deps

app = FastAPI(title="Shongkho POS API", version="3.0")

# ---------------------------------------------------------
# MIDDLEWARE
# (SessionMiddleware first, then CORS — so CORSMiddleware is
# the outermost layer and every response gets CORS headers.)
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
# STATIC MEDIA (uploaded images)
# ---------------------------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------
# IMAGE UPLOADS
# ---------------------------------------------------------
@app.post("/api/v1/uploads/profile-photo", tags=["Uploads"])
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user=Depends(deps.get_current_user),
):
    """Save a profile picture and return its public /static URL."""
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WebP or GIF images are allowed.")

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[file.content_type]
    filename = f"{uuid.uuid4().hex}{ext}"

    upload_dir = os.path.join("static", "profile_pics")
    os.makedirs(upload_dir, exist_ok=True)

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be 5 MB or smaller.")

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


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------
@app.get("/api/v1/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "Shongkho POS API"}
