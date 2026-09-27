"""
Models: staff warnings + per-employee commission settings.

Both are owner-side management entities that live next to the staff
features they serve:

  - StaffWarning   — a formal warning an owner issues to one employee
                     (reason text + timestamp). Shown in that employee's
                     Staff tab and surfaced to the employee themselves.
  - CommissionSetting — per-employee commission policy the owner sets:
                     a percentage of either REVENUE or PROFIT generated
                     by that employee. One row per employee (unique).
                     The computed payout shows up on the employee's
                     dashboard.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from models import Base


class StaffWarning(Base):
    """A formal warning the owner issued to one employee."""
    __tablename__ = 'staff_warnings'

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey('users.user_id'), index=True,
                         nullable=False)
    issued_by = Column(Integer, ForeignKey('owners.user_id'), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CommissionSetting(Base):
    """
    Per-employee commission policy: `rate` percent of the chosen `basis`.

    basis: 'revenue' | 'profit' — the owner picks which generated amount
    the percentage applies to. One row per employee; deleting the policy
    (rate=None) disables commission for that employee.
    """
    __tablename__ = 'commission_settings'

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey('users.user_id'), index=True,
                         nullable=False, unique=True)
    basis = Column(String(20), nullable=False, default='revenue')
    rate = Column(Float, nullable=True)   # percent, e.g. 5.0; None = disabled
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)
