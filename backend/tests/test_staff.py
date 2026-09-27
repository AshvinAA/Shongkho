"""
Staff module tests (routes/staff.py + services_staff.py + models_staff.py):

  - warnings: owner-only issue/list, ownership scoping, validation,
    the employee's own view
  - commission: owner-only policy upsert/clear + validation, live
    payout math on the employee dashboard (revenue vs profit basis,
    all-time vs this-month)

No LLM involvement; every call goes through the real API with cookie
sessions (the conftest fixtures register + login via the real
register/login endpoints).
"""
import sys
import os
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
import models_staff  # noqa: E402
from services import hash_password  # noqa: E402


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def _sale(db, employee_id, when, revenue, profit):
    db.add(models.Sale(
        employee_id=employee_id, customer_id=None, payment_method="cash",
        total_revenue=revenue, total_profit=profit,
        date=when.date() if isinstance(when, datetime) else when,
        time=when.time() if isinstance(when, datetime) else None,
    ))
    db.commit()


@pytest.fixture()
def second_employee(db_session, owner):
    """A second employee under the same owner — DB-created, never logs
    in (only their user_id is needed), so `client`'s session is left
    untouched."""
    emp = models.Employee(
        name="Other Staff", phone_number="01700000003", password="x",
        user_type="employee", employer_id=owner["user_id"])
    db_session.add(emp)
    db_session.commit()
    return {"user_id": emp.user_id}


@pytest.fixture()
def rival_owner_client(db_session, employee):
    """A SECOND owner with their own client session — created through
    the ORM (open registration forbids a second owner) and only AFTER
    the API fixtures have registered, or the register endpoint would
    see this row and refuse to create the primary owner."""
    from fastapi.testclient import TestClient
    from main import app

    rival = models.Owner(
        name="Rival Owner", phone_number="01700000008",
        password=hash_password("secret123"), user_type="owner")
    db_session.add(rival)
    db_session.commit()

    second = TestClient(app)
    r = second.post("/api/v1/auth/login", json={
        "phone_number": "01700000008", "password": "secret123"})
    assert r.status_code == 200, r.json()
    return {"user_id": rival.user_id, "role": "owner"}, second


# ---------------------------------------------------------
# Warnings
# ---------------------------------------------------------
class TestWarnings:
    def test_issue_and_list(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.post(f"/api/v1/staff/employees/{eid}/warnings",
                              json={"reason": "Late for the morning shift"})
        assert r.status_code == 201, r.json()
        body = r.json()
        assert body["reason"] == "Late for the morning shift"
        assert body["employee_id"] == eid
        assert body["issued_by"] == 1   # the owner is the first user
        assert body["issued_by_name"] == "The Owner"
        assert body["created_at"]

        r = owner_client.get(f"/api/v1/staff/employees/{eid}/warnings")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["reason"] == "Late for the morning shift"

    def test_owner_sees_their_name_not_id_artifact(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.post(f"/api/v1/staff/employees/{eid}/warnings",
                              json={"reason": "register mixup"})
        assert r.json()["issued_by_name"] == "The Owner"

    def test_employee_cannot_issue_warnings(self, client, employee, owner):
        # `employee` puts the EMPLOYEE session in client's jar.
        r = client.post(
            f"/api/v1/staff/employees/{owner['user_id']}/warnings",
            json={"reason": "nope"})
        assert r.status_code == 403

    def test_owner_cannot_warn_other_owners_staff(
            self, rival_owner_client, employee):
        _, rival_client = rival_owner_client
        eid = employee["user_id"]
        r = rival_client.post(f"/api/v1/staff/employees/{eid}/warnings",
                              json={"reason": "not mine"})
        assert r.status_code == 403

    def test_warning_on_unknown_employee_404(self, owner_client):
        r = owner_client.post("/api/v1/staff/employees/99999/warnings",
                              json={"reason": "ghost"})
        assert r.status_code == 404

    def test_empty_reason_rejected(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.post(f"/api/v1/staff/employees/{eid}/warnings",
                              json={"reason": ""})
        assert r.status_code == 422

    def test_employee_sees_own_warnings(self, client, owner_client, employee):
        eid = employee["user_id"]
        owner_client.post(f"/api/v1/staff/employees/{eid}/warnings",
                          json={"reason": "Register was short"})
        owner_client.post(f"/api/v1/staff/employees/{eid}/warnings",
                          json={"reason": "Missed stock count"})
        r = client.get("/api/v1/staff/me/warnings")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2
        assert {w["reason"] for w in rows} == {
            "Register was short", "Missed stock count"}

    def test_owner_has_no_warnings(self, owner_client):
        r = owner_client.get("/api/v1/staff/me/warnings")
        assert r.status_code == 200
        assert r.json() == []

    def test_newest_first_ordering(self, db_session, owner_client, employee):
        eid = employee["user_id"]
        db_session.add(models_staff.StaffWarning(
            employee_id=eid, issued_by=1,
            reason="older", created_at=datetime.utcnow() - timedelta(days=2)))
        db_session.add(models_staff.StaffWarning(
            employee_id=eid, issued_by=1,
            reason="newer", created_at=datetime.utcnow()))
        db_session.commit()
        rows = owner_client.get(f"/api/v1/staff/employees/{eid}/warnings").json()
        assert [w["reason"] for w in rows] == ["newer", "older"]


# ---------------------------------------------------------
# Commission policy (owner side)
# ---------------------------------------------------------
class TestCommissionPolicy:
    def test_set_and_get(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                             json={"basis": "revenue", "rate": 5})
        assert r.status_code == 200, r.json()
        assert r.json()["rate"] == 5.0
        assert r.json()["basis"] == "revenue"

        r = owner_client.get(f"/api/v1/staff/employees/{eid}/commission")
        assert r.status_code == 200
        assert r.json()["rate"] == 5.0

    def test_unset_policy_reads_as_null_rate(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.get(f"/api/v1/staff/employees/{eid}/commission")
        assert r.status_code == 200
        body = r.json()
        assert body["rate"] is None
        assert body["employee_id"] == eid

    def test_update_changes_basis_and_rate(self, owner_client, employee):
        eid = employee["user_id"]
        url = f"/api/v1/staff/employees/{eid}/commission"
        owner_client.put(url, json={"basis": "revenue", "rate": 5})
        r = owner_client.put(url, json={"basis": "profit", "rate": 12.5})
        assert r.json()["basis"] == "profit"
        assert r.json()["rate"] == 12.5

    def test_clear_with_null_rate(self, owner_client, employee):
        eid = employee["user_id"]
        url = f"/api/v1/staff/employees/{eid}/commission"
        owner_client.put(url, json={"basis": "revenue", "rate": 5})
        r = owner_client.put(url, json={"basis": "revenue", "rate": None})
        assert r.status_code == 200
        assert r.json()["rate"] is None
        # The row is gone, not zeroed.
        assert owner_client.get(url).json()["rate"] is None

    def test_invalid_basis_rejected(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                             json={"basis": "salary", "rate": 5})
        assert r.status_code == 422

    def test_zero_rate_rejected(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                             json={"basis": "revenue", "rate": 0})
        assert r.status_code == 422

    def test_rate_over_100_rejected(self, owner_client, employee):
        eid = employee["user_id"]
        r = owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                             json={"basis": "revenue", "rate": 150})
        assert r.status_code == 422

    def test_employee_cannot_set_policy(self, client, employee, owner):
        r = client.put(
            f"/api/v1/staff/employees/{owner['user_id']}/commission",
            json={"basis": "revenue", "rate": 5})
        assert r.status_code == 403

    def test_owner_cannot_set_rivals_staff(self, rival_owner_client,
                                           employee):
        _, rival_client = rival_owner_client
        eid = employee["user_id"]
        r = rival_client.put(f"/api/v1/staff/employees/{eid}/commission",
                             json={"basis": "revenue", "rate": 5})
        assert r.status_code == 403


# ---------------------------------------------------------
# Commission payout (employee dashboard, live math)
# ---------------------------------------------------------
class TestMyCommission:
    def test_no_policy_reports_inactive(self, client, employee):
        r = client.get("/api/v1/staff/me/commission")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] is False
        assert body["rate"] is None
        assert body["all_time_commission"] == 0.0

    def test_revenue_basis_all_time_and_month(self, db_session, client,
                                              owner_client, employee):
        eid = employee["user_id"]
        owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                         json={"basis": "revenue", "rate": 10})
        today = datetime.now()
        _sale(db_session, eid, today.replace(hour=10), 1000.0, 300.0)
        _sale(db_session, eid, today - timedelta(days=3), 500.0, 150.0)

        r = client.get("/api/v1/staff/me/commission")
        body = r.json()
        assert body["active"] is True
        assert body["basis"] == "revenue"
        assert body["rate"] == 10.0
        assert body["all_time_revenue"] == 1500.0
        assert body["all_time_commission"] == 150.0   # 10% of revenue
        assert body["month_commission"] == 150.0      # both sales this month

    def test_profit_basis_uses_profit_not_revenue(self, db_session, client,
                                                  owner_client, employee):
        eid = employee["user_id"]
        owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                         json={"basis": "profit", "rate": 20})
        _sale(db_session, eid, datetime.now(), 1000.0, 300.0)

        body = client.get("/api/v1/staff/me/commission").json()
        assert body["basis"] == "profit"
        assert body["all_time_revenue"] == 1000.0
        assert body["all_time_profit"] == 300.0
        assert body["all_time_commission"] == 60.0    # 20% of PROFIT

    def test_basis_switch_recomputes_immediately(self, db_session, client,
                                                 owner_client, employee):
        eid = employee["user_id"]
        _sale(db_session, eid, datetime.now(), 1000.0, 200.0)
        url = f"/api/v1/staff/employees/{eid}/commission"
        owner_client.put(url, json={"basis": "revenue", "rate": 10})
        assert client.get("/api/v1/staff/me/commission").json()[
            "all_time_commission"] == 100.0
        owner_client.put(url, json={"basis": "profit", "rate": 10})
        assert client.get("/api/v1/staff/me/commission").json()[
            "all_time_commission"] == 20.0

    def test_month_window_only_counts_this_month(self, db_session, client,
                                                 owner_client, employee):
        eid = employee["user_id"]
        owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                         json={"basis": "revenue", "rate": 10})
        now = datetime.now()
        first_of_month = now.replace(day=1, hour=9)
        _sale(db_session, eid, first_of_month, 100.0, 30.0)
        prev_month_last = (first_of_month - timedelta(days=1))
        _sale(db_session, eid, prev_month_last, 900.0, 270.0)

        body = client.get("/api/v1/staff/me/commission").json()
        assert body["all_time_revenue"] == 1000.0
        assert body["month_revenue"] == 100.0
        assert body["month_commission"] == 10.0
        assert body["all_time_commission"] == 100.0

    def test_only_own_sales_count(self, db_session, client, owner_client,
                                  employee, second_employee):
        eid = employee["user_id"]
        owner_client.put(f"/api/v1/staff/employees/{eid}/commission",
                         json={"basis": "revenue", "rate": 10})
        _sale(db_session, eid, datetime.now(), 1000.0, 300.0)
        _sale(db_session, second_employee["user_id"], datetime.now(),
              9999.0, 999.0)

        body = client.get("/api/v1/staff/me/commission").json()
        assert body["all_time_revenue"] == 1000.0
        assert body["all_time_commission"] == 100.0

    def test_policy_kept_on_reseed_like_flow(self, owner_client, employee):
        """Setting a policy twice does not duplicate rows (unique)."""
        eid = employee["user_id"]
        url = f"/api/v1/staff/employees/{eid}/commission"
        owner_client.put(url, json={"basis": "revenue", "rate": 5})
        owner_client.put(url, json={"basis": "profit", "rate": 7})
        rows = owner_client.get(url).json()
        assert rows["rate"] == 7.0
