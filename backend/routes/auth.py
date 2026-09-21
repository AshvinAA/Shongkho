from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import models
import schemas
import services
import deps
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=schemas.RegisterResponse, status_code=status.HTTP_201_CREATED)
def register_account(user_data: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    """
    Public registration.
    - Owner signup allowed only while no owner exists (first owner bootstraps the store).
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
    """Shared login for owner and employee — role comes back in the response."""
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
    """Step 1: verify account exists. Step 2: /auth/reset-password sets the new one."""
    return services.reset_password_request(db=db, phone_number=payload.phone_number)


@router.post("/reset-password")
def reset_password(payload: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    """Shared password reset for owner and employee."""
    return services.reset_password_confirm(
        db=db, phone_number=payload.phone_number, new_password=payload.new_password
    )


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    """Who am I? Used by the frontend to render role-aware UI (incl. navbar avatar)."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    return {
        "user_id": user_id,
        "role": request.session.get("role") or (user.user_type if user else None),
        "name": user.name if user else request.session.get("name"),
        "photo": user.photo if user else None,
    }
