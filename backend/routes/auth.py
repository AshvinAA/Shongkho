"""
Authentication routes: registration, login/logout, password reset.

Session flow:
  POST /auth/login stores {user_id, role, name} in the cookie session;
  every protected route then re-reads it via deps.get_current_user.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

import deps
import models
import schemas
import services
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=schemas.RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_account(user_data: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    """
    Public registration.

    - Owner signup is allowed only while NO owner exists (the first owner
      bootstraps the store). Later owner accounts must be created by a
      logged-in owner via /auth/register/owner.
    - Employee signup REQUIRES a valid owner ID (employer_id).
    """
    return services.register_user(db=db, user_data=user_data, creator_role=None)


@router.post("/register/employee", response_model=schemas.RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_employee_as_owner(
    user_data: schemas.EmployeeCreate,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """Owner-only: register a new employee under the owner's own account."""
    if (user_data.role or "employee").lower() != "employee":
        raise HTTPException(status_code=400, detail="Use /auth/register/owner to create owner accounts.")
    # Force the employer to be the calling owner — the body cannot place
    # an employee under someone else's store.
    user_data.employer_id = current_user["id"]
    return services.register_user(db=db, user_data=user_data, creator_role="owner")


@router.post("/register/owner", response_model=schemas.RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_owner(
    user_data: schemas.EmployeeCreate,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """Owner-only: create additional owner accounts."""
    if (user_data.role or "").lower() != "owner":
        raise HTTPException(status_code=400, detail="This endpoint is for owner accounts only.")
    return services.register_user(db=db, user_data=user_data, creator_role="owner")


@router.post("/login")
def login(user_credentials: schemas.UserLogin, request: Request, db: Session = Depends(get_db)):
    """
    Shared login for owner and employee.

    Verifies credentials, then writes {user_id, role, name} into the
    cookie session. The response body mirrors the session so the SPA can
    render immediately.
    """
    user = services.process_login(db=db, user_credentials=user_credentials)

    request.session["user_id"] = user["user_id"]
    request.session["role"] = user["role"]
    request.session["name"] = user["name"]

    return user


@router.post("/logout")
def logout(request: Request):
    """Shared logout — clears the server session."""
    request.session.clear()
    return {"detail": "Logged out"}


@router.post("/forgot-password")
def forgot_password(payload: schemas.PasswordResetRequest, db: Session = Depends(get_db)):
    """Step 1 of password reset: verify the account exists."""
    return services.reset_password_request(db=db, phone_number=payload.phone_number)


@router.post("/reset-password")
def reset_password(payload: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    """Step 2 of password reset: set the new password."""
    return services.reset_password_confirm(
        db=db, phone_number=payload.phone_number, new_password=payload.new_password
    )


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    """
    Who am I? The SPA calls this on boot to hydrate auth state and to
    render the role-aware navbar (including the avatar).

    The account is re-verified in the database so a session cookie that
    outlives its account (deletion / role flip) is rejected here too.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    # Look the user up fresh so name/photo changes show immediately, and
    # so deleted accounts can no longer authenticate.
    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session no longer valid")

    return {
        "user_id": user.user_id,
        "role": user.user_type,
        "name": user.name,
        "photo": user.photo,
    }
