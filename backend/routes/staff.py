"""
Staff routes: per-employee warnings + commission.

Two groups, mirroring routes/employees.py's split:

  - /staff/employees/{id}/... : OWNER-ONLY management of their own
    staff (issue/list warnings, set/get the commission policy). Every
    action verifies the target works for the acting owner.
  - /staff/me/...             : the logged-in employee's own view —
    their warning history and their commission card (policy + live
    payout from their own sales).

Commission math lives in services_staff.my_commission_view: rate% of
the owner-chosen basis (revenue or profit), computed live from the
employee's own Sale rows — a policy change applies immediately and
there is no ledger to backfill.
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import deps
import models
import schemas
import services_staff
from database import get_db

router = APIRouter(prefix="/staff", tags=["Staff"])


# ---------------------------------------------------------
# OWNER-ONLY: manage one employee
# ---------------------------------------------------------
@router.post("/employees/{user_id}/warnings",
             response_model=schemas.StaffWarningResponse, status_code=201)
def issue_warning(
    user_id: int,
    payload: schemas.StaffWarningCreate,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """Issue a formal warning to one of your employees."""
    return services_staff.issue_warning(
        db, employee_user_id=user_id, owner_id=current_user["id"],
        payload=payload)


@router.get("/employees/{user_id}/warnings",
            response_model=List[schemas.StaffWarningResponse])
def list_employee_warnings(
    user_id: int,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """Warning history for one of your employees (newest first)."""
    return services_staff.list_warnings(db, user_id,
                                        owner_id=current_user["id"])


@router.get("/employees/{user_id}/commission",
            response_model=schemas.CommissionSettingResponse)
def get_employee_commission(
    user_id: int,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """The commission policy you set for one of your employees."""
    services_staff._get_staff_employee(db, user_id,
                                       owner_id=current_user["id"])
    row = services_staff.get_commission_setting(db, user_id)
    if row is None:
        return schemas.CommissionSettingResponse(
            employee_id=user_id, basis="revenue", rate=None)
    return row


@router.put("/employees/{user_id}/commission",
            response_model=schemas.CommissionSettingResponse)
def set_employee_commission(
    user_id: int,
    payload: schemas.CommissionSettingUpdate,
    current_user=Depends(deps.require_owner),
    db: Session = Depends(get_db),
):
    """
    Set (or clear, rate=null) the commission policy: `rate` percent of
    the chosen basis. Takes effect immediately — payouts are computed
    from live sales totals, never stored.
    """
    row = services_staff.set_commission_setting(
        db, employee_user_id=user_id, owner_id=current_user["id"],
        payload=payload)
    if row is None:
        return schemas.CommissionSettingResponse(
            employee_id=user_id, basis=payload.basis, rate=None)
    return row


# ---------------------------------------------------------
# SELF-VIEW: the employee's own staff page
# ---------------------------------------------------------
@router.get("/me/warnings", response_model=List[schemas.StaffWarningResponse])
def my_warnings(
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Your own warning history (owners have none — empty list)."""
    if current_user["role"] == "owner":
        return []
    return services_staff.list_warnings(db, current_user["id"])


@router.get("/me/commission", response_model=schemas.MyCommissionResponse)
def my_commission(
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Your commission card: policy + live payout from your own sales."""
    return services_staff.my_commission_view(db, current_user["id"])
