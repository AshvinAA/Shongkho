"""
Employee & profile routes.

Two groups live here:
  - /employees/me/*  : self-service (profile, photo, my store, my stats)
                       available to BOTH roles on their own account.
  - /employees/*     : owner-only staff management (roster, search,
                       performance, role updates, deletion).
"""
import os
import time
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

import deps
import models
import schemas
import services
from database import get_db

router = APIRouter(prefix="/employees", tags=["Employees"])

# Content types accepted for profile pictures, mapped to extensions.
ALLOWED_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


# ---------------------------------------------------------
# SELF-SERVICE PROFILE (own account — owner or employee)
# ---------------------------------------------------------

@router.get("/me/profile", response_model=schemas.EmployeeResponse)
def get_my_profile(current_user=Depends(deps.require_any), db: Session = Depends(get_db)):
    """Profile of the logged-in user (owner or employee)."""
    user = db.query(models.User).filter(models.User.user_id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    return user


@router.put("/me/profile", response_model=schemas.EmployeeResponse)
def update_my_profile(
    updates: schemas.ProfileUpdate,
    request: Request,
    current_user=Depends(deps.require_any),      # BOTH roles — edit your own
    db: Session = Depends(get_db),
):
    """Edit your own profile: name, phone number and/or profile picture."""
    user = services.update_profile(db=db, user_id=current_user["id"], updates=updates)
    # Keep the server session in sync so the UI shows the new name
    # immediately without a re-login.
    if updates.name is not None:
        request.session["name"] = user.name
    return user


@router.post("/me/profile/photo", response_model=schemas.EmployeeResponse)
def upload_my_photo(
    file: UploadFile = File(...),
    current_user=Depends(deps.require_any),      # BOTH roles — edit your own
    db: Session = Depends(get_db),
):
    """Upload a new profile picture for the logged-in user (owner or employee)."""
    ext = ALLOWED_PHOTO_TYPES.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP or GIF images are allowed.")

    contents = file.file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5 MB).")

    user = db.query(models.User).filter(models.User.user_id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")

    # Delete the previous picture (only files we manage).
    if user.photo and user.photo.startswith("/static/profile_pics/"):
        old_path = user.photo.split("?")[0].lstrip("/")
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    upload_dir = os.path.join(deps.BASE_DIR, "static", "profile_pics")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"user_{current_user['id']}{ext}"
    with open(os.path.join(upload_dir, filename), "wb") as out:
        out.write(contents)

    # Cache-busting version so browsers refresh the avatar immediately.
    photo_url = f"/static/profile_pics/{filename}?v={int(time.time())}"
    updates = schemas.ProfileUpdate(photo=photo_url)
    return services.update_profile(db=db, user_id=current_user["id"], updates=updates)


@router.get("/me/store", response_model=schemas.MyStoreResponse)
def get_my_store(current_user=Depends(deps.require_any), db: Session = Depends(get_db)):
    """'My Store' info for the dashboard (employer, salary, colleagues)."""
    return services.get_my_store(db=db, user_id=current_user["id"])


@router.get("/me/performance")
def get_my_performance(current_user=Depends(deps.require_any), db: Session = Depends(get_db)):
    """All-time sales totals for the logged-in user (own numbers only)."""
    return services.get_my_all_time_performance(db=db, employee_id=current_user["id"])


# ---------------------------------------------------------
# OWNER-ONLY STAFF MANAGEMENT
# ---------------------------------------------------------

@router.get("/", response_model=List[schemas.EmployeeResponse])
def get_employees(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: list all employees (owners excluded from the roster)."""
    return services.get_employees(db=db, skip=skip, limit=limit)


@router.get("/search/", response_model=List[schemas.EmployeeResponse])
def search_employees(
    query: str,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: search employees by name, position or phone."""
    results = services.search_employees(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No employees found matching that search.")
    return results


@router.get("/performance", response_model=List[schemas.EmployeePerformance])
def sales_performance(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: lifetime revenue/profit per employee."""
    return services.get_sales_performance(db=db, skip=skip, limit=limit)


@router.put("/{user_id}", response_model=schemas.EmployeeResponse)
def update_employee(
    user_id: int,
    updates: schemas.EmployeeUpdate,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: update an employee's info / position / salary / role."""
    return services.update_employee(db=db, employee_user_id=user_id, updates=updates)


@router.delete("/{user_id}")
def delete_employee(
    user_id: int,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: delete an employee account (sales history is kept)."""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    return services.delete_employee(db=db, employee_user_id=user_id)
