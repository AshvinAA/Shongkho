"""
Staff services: warnings + commission.

Owner-side management reads/writes for the Staff page's per-employee
tabs, plus the employee-dashboard commission view.

Design notes:
  - Warnings are audit-only: no edit/delete endpoint on purpose (a
    formal warning is a record, not a draft). The employee SEES the
    count and the reasons — transparency is the point.
  - Commission is a policy, not a ledger: the payout is always computed
    live from the employee's own sales totals, so a policy change
    applies immediately and there is nothing to backfill.
  - Every lookup verifies the target is an Employee row (the users
    table also holds owners) AND, for owner actions, that the target
    works for the acting owner (employer_id) — an owner cannot manage
    another owner's staff.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func

import models
import models_staff
import schemas


# ---------------------------------------------------------
# Shared target validation
# ---------------------------------------------------------
def _get_staff_employee(db, employee_user_id: int,
                        owner_id: int | None = None) -> models.Employee:
    """
    The Employee row for `employee_user_id`, verified to be a real
    employee. With `owner_id`, also verify they work for THAT owner.
    """
    emp = db.query(models.Employee).filter(
        models.Employee.user_id == employee_user_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if owner_id is not None and emp.employer_id != owner_id:
        raise HTTPException(status_code=403, detail="This employee does not work for you")
    return emp


def _staff_ids_for_owner(db, owner_id: int):
    """User ids of all employees employed by `owner_id`."""
    return [row[0] for row in db.query(models.Employee.user_id).filter(
        models.Employee.employer_id == owner_id).all()]


# ---------------------------------------------------------
# Warnings
# ---------------------------------------------------------
def issue_warning(db, *, employee_user_id: int, owner_id: int,
                  payload: schemas.StaffWarningCreate):
    """Owner-only: record a formal warning against one of their staff."""
    _get_staff_employee(db, employee_user_id, owner_id=owner_id)
    warning = models_staff.StaffWarning(
        employee_id=employee_user_id,
        issued_by=owner_id,
        reason=payload.reason.strip(),
    )
    db.add(warning)
    db.commit()
    db.refresh(warning)
    return _warning_out(db, warning)


def list_warnings(db, employee_user_id: int,
                  owner_id: int | None = None):
    """Newest-first warnings for one employee (owner Staff tab, or the
    employee's own view — ownership verified when `owner_id` given)."""
    _get_staff_employee(db, employee_user_id, owner_id=owner_id)
    rows = db.query(models_staff.StaffWarning).filter(
        models_staff.StaffWarning.employee_id == employee_user_id,
    ).order_by(models_staff.StaffWarning.created_at.desc()).all()
    return [_warning_out(db, w) for w in rows]


def count_warnings(db, employee_user_id: int) -> int:
    return db.query(models_staff.StaffWarning).filter(
        models_staff.StaffWarning.employee_id == employee_user_id,
    ).count()


def _warning_out(db, warning: models_staff.StaffWarning) -> dict:
    """Serialized warning with the issuing owner's display name."""
    issuer = db.query(models.Owner).filter(
        models.Owner.user_id == warning.issued_by).first()
    return {
        "id": warning.id,
        "employee_id": warning.employee_id,
        "issued_by": warning.issued_by,
        "issued_by_name": issuer.name if issuer else None,
        "reason": warning.reason,
        "created_at": warning.created_at,
    }


# ---------------------------------------------------------
# Commission policy (owner side)
# ---------------------------------------------------------
def get_commission_setting(db, employee_user_id: int):
    """The employee's policy row, or None when never set."""
    return db.query(models_staff.CommissionSetting).filter(
        models_staff.CommissionSetting.employee_id == employee_user_id,
    ).first()


def set_commission_setting(db, *, employee_user_id: int, owner_id: int,
                           payload: schemas.CommissionSettingUpdate):
    """
    Owner-only: upsert the commission policy. rate=None clears it.

    Employees of employee-owners (user_type='employee' but employing
    others) are NOT blocked from having a policy — commission is
    computed from their own sales rows, whatever their role is.
    """
    _get_staff_employee(db, employee_user_id, owner_id=owner_id)
    row = get_commission_setting(db, employee_user_id)
    if payload.rate is None:
        if row:
            db.delete(row)
            db.commit()
        return None
    if row is None:
        row = models_staff.CommissionSetting(employee_id=employee_user_id)
        db.add(row)
    row.basis = payload.basis
    row.rate = payload.rate
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------
# Commission payout (employee dashboard)
# ---------------------------------------------------------
def my_commission_view(db, employee_user_id: int) -> dict:
    """
    The employee-dashboard card: the policy plus the payout computed
    from their OWN sales, all-time and calendar-this-month.

    Commission = rate% of the policy's basis, where the basis amount is
    the employee's own generated revenue (what customers paid) or
    profit (revenue minus cost of goods). Never includes other staff's
    sales; owners see their own only via their own sales rows.
    """
    setting = get_commission_setting(db, employee_user_id)
    totals = db.query(
        func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
        func.coalesce(func.sum(models.Sale.total_profit), 0.0),
    ).filter(models.Sale.employee_id == employee_user_id).one()

    month_start = date.today().replace(day=1)
    month_totals = db.query(
        func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
        func.coalesce(func.sum(models.Sale.total_profit), 0.0),
    ).filter(
        models.Sale.employee_id == employee_user_id,
        models.Sale.date >= month_start,
    ).one()

    active = bool(setting and setting.rate)
    rate = float(setting.rate) if active else 0.0
    all_rev, all_prof = float(totals[0]), float(totals[1])
    mon_rev, mon_prof = float(month_totals[0]), float(month_totals[1])

    def payout(rev: float, prof: float) -> float:
        base = prof if (setting and setting.basis == "profit") else rev
        return round(base * rate / 100.0, 2)

    return {
        "active": active,
        "basis": setting.basis if setting else None,
        "rate": float(setting.rate) if setting else None,
        "all_time_revenue": round(all_rev, 2),
        "all_time_profit": round(all_prof, 2),
        "all_time_commission": payout(all_rev, all_prof),
        "month_revenue": round(mon_rev, 2),
        "month_profit": round(mon_prof, 2),
        "month_commission": round(payout(mon_rev, mon_prof), 2),
    }
