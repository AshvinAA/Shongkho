"""
Auth & role tests: registration, login, joined-table inheritance
constraints, and permission gates (401 vs 403).
"""
import pytest


# ---------------------------------------------------------
# REGISTRATION FLOWS
# ---------------------------------------------------------

class TestRegistration:
    def test_first_owner_can_register_publicly(self, client):
        """The very first owner bootstraps the store with no auth."""
        r = client.post("/api/v1/auth/register", json={
            "name": "First Owner",
            "phone_number": "01711100001",
            "password": "pass1234",
            "role": "owner",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["user_type"] == "owner"
        assert body["name"] == "First Owner"
        assert "password" not in body  # never leak the hash

    def test_second_owner_requires_logged_in_owner(self, client, owner):
        """After the first owner exists, anonymous owner signup is a 403."""
        r = client.post("/api/v1/auth/register", json={
            "name": "Sneaky Second",
            "phone_number": "01711100002",
            "password": "pass1234",
            "role": "owner",
        })
        assert r.status_code == 403

    def test_owner_can_create_second_owner(self, client, owner_client):
        r = owner_client.post("/api/v1/auth/register/owner", json={
            "name": "Partner Owner",
            "phone_number": "01711100003",
            "password": "pass1234",
            "role": "owner",
        })
        assert r.status_code == 201
        assert r.json()["user_type"] == "owner"

    def test_employee_needs_employer_id(self, client):
        """Employee signup without an owner reference is a 400."""
        r = client.post("/api/v1/auth/register", json={
            "name": "Lost Employee",
            "phone_number": "01711100004",
            "password": "pass1234",
            "role": "employee",
        })
        assert r.status_code == 400
        assert "employer" in r.json()["detail"].lower()

    def test_employee_with_unknown_employer_is_404(self, client):
        r = client.post("/api/v1/auth/register", json={
            "name": "Ghost Employee",
            "phone_number": "01711100005",
            "password": "pass1234",
            "role": "employee",
            "employer_id": 9999,
        })
        assert r.status_code == 404

    def test_employee_registers_under_real_owner(self, client, owner):
        r = client.post("/api/v1/auth/register", json={
            "name": "Good Employee",
            "phone_number": "01711100006",
            "password": "pass1234",
            "role": "employee",
            "employer_id": owner["user_id"],
        })
        assert r.status_code == 201
        assert r.json()["user_type"] == "employee"

    def test_duplicate_phone_rejected(self, client, owner):
        r = client.post("/api/v1/auth/register", json={
            "name": "Copycat",
            "phone_number": "01700000001",  # owner's phone
            "password": "pass1234",
            "role": "employee",
            "employer_id": owner["user_id"],
        })
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"]

    def test_employee_forced_under_calling_owner(self, client, owner, owner_client):
        """Owner-register-employee ignores any employer_id in the body."""
        r = owner_client.post("/api/v1/auth/register/employee", json={
            "name": "Held Employee",
            "phone_number": "01711100007",
            "password": "pass1234",
            "role": "employee",
            "employer_id": 424242,  # bogus on purpose — must be overwritten
        })
        assert r.status_code == 201

        # The roster (owner-only) must show the employee under the caller.
        roster = owner_client.get("/api/v1/employees/").json()
        match = [e for e in roster if e["user_id"] == r.json()["user_id"]]
        assert match and match[0]["employer_id"] == owner["user_id"]

    def test_negative_salary_rejected(self, client, owner_client):
        r = owner_client.post("/api/v1/auth/register/employee", json={
            "name": "Paid Negatively",
            "phone_number": "01711100008",
            "password": "pass1234",
            "role": "employee",
            "salary": -500,
        })
        assert r.status_code == 422  # pydantic ge=0


# ---------------------------------------------------------
# LOGIN / LOGOUT / SESSION
# ---------------------------------------------------------

class TestLoginLogout:
    def test_login_success_returns_role(self, client, owner):
        r = client.post("/api/v1/auth/login", json={
            "phone_number": "01700000001",
            "password": "secret123",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "owner"
        assert body["user_id"] == owner["user_id"]

    def test_login_wrong_password_is_generic_401(self, client, owner):
        r = client.post("/api/v1/auth/login", json={
            "phone_number": "01700000001",
            "password": "wrong!",
        })
        assert r.status_code == 401
        # Same message for wrong phone and wrong password (no enumeration).
        assert "incorrect" in r.json()["detail"].lower()

    def test_login_unknown_phone_same_generic_401(self, client):
        r = client.post("/api/v1/auth/login", json={
            "phone_number": "01999999999",
            "password": "whatever",
        })
        assert r.status_code == 401
        assert "incorrect" in r.json()["detail"].lower()

    def test_logout_clears_session(self, client, owner):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 200
        # The cookie is now useless.
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 401

    def test_me_requires_auth(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_returns_profile(self, client, owner):
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "owner"
        assert body["name"] == "The Owner"


# ---------------------------------------------------------
# JOINED-TABLE INHERITANCE CONSTRAINTS
# ---------------------------------------------------------

class TestInheritanceConstraints:
    def test_owner_not_in_employee_roster(self, client, owner_client, owner, employee):
        """Employee queries must exclude owner rows (polymorphic filter)."""
        roster = owner_client.get("/api/v1/employees/").json()
        ids = [e["user_id"] for e in roster]
        assert employee["user_id"] in ids
        assert owner["user_id"] not in ids

    def test_employee_record_has_owner_fields_absent(self, client, owner_client, owner, employee):
        """Employee rows carry position; owner-specific data is not exposed."""
        roster = owner_client.get("/api/v1/employees/").json()
        emp = next(e for e in roster if e["user_id"] == employee["user_id"])
        assert emp["user_type"] == "employee"
        assert emp["employer_id"] == owner["user_id"]
        assert "store_name" not in emp  # owner-only column not in schema

    def test_owner_profile_not_served_by_employee_roster_search(self, client, owner_client, owner, employee):
        """Search over Employee polymorphic query must not match owners."""
        r = owner_client.get("/api/v1/employees/search/", params={"query": "The Owner"})
        assert r.status_code == 404  # owners are not employees
        r = owner_client.get("/api/v1/employees/search/", params={"query": "Staff"})
        assert r.status_code == 200
        assert any(e["user_id"] == employee["user_id"] for e in r.json())


# ---------------------------------------------------------
# ROLE PERMISSION GATES
# ---------------------------------------------------------

class TestRolePermissions:
    def test_anonymous_gets_401_not_403(self, client):
        """No session at all -> 401 (unauthenticated), not 403."""
        assert client.get("/api/v1/products/").status_code == 401
        assert client.get("/api/v1/employees/").status_code == 401

    def test_employee_cannot_create_product(self, client, employee):
        r = client.post("/api/v1/products/", json={
            "product_name": "Smuggled Item",
            "cost_price": 1,
            "retail_price": 2,
            "stock_quantity": 1,
        })
        assert r.status_code == 403
        assert "owners only" in r.json()["detail"].lower()

    def test_employee_cannot_delete_product(self, client, owner, employee, product):
        r = client.delete(f"/api/v1/products/{product['product_id']}")
        assert r.status_code == 403

    def test_employee_cannot_adjust_stock(self, client, employee, product):
        r = client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": 5})
        assert r.status_code == 403

    def test_employee_cannot_list_employees(self, client, employee):
        assert client.get("/api/v1/employees/").status_code == 403

    def test_employee_cannot_see_performance(self, client, employee):
        assert client.get("/api/v1/employees/performance").status_code == 403

    def test_employee_cannot_see_sales_report(self, client, employee):
        assert client.get("/api/v1/sales/reports/daily").status_code == 403

    def test_employee_cannot_see_customer_directory(self, client, employee):
        assert client.get("/api/v1/customers/").status_code == 403

    def test_employee_can_read_products(self, client, employee):
        assert client.get("/api/v1/products/").status_code == 200

    def test_employee_can_see_own_receipt(self, client, owner, employee, product, customer):
        # Employee checks out...
        sale = client.post("/api/v1/checkout/", json={
            "customer_id": customer["customer_id"],
            "payment_method": "Cash",
            "items": [{"product_id": product["product_id"], "quantity": 1}],
        })
        assert sale.status_code == 200
        tid = sale.json()["transaction_id"]
        # ...and can view their own receipt.
        r = client.get(f"/api/v1/sales/{tid}/receipt")
        assert r.status_code == 200
        assert r.json()["employee_id"] == employee["user_id"]

    def test_owner_can_delete_employee(self, client, owner_client, employee):
        r = owner_client.delete(f"/api/v1/employees/{employee['user_id']}")
        assert r.status_code == 200
        # The deleted employee's session cookie is now inert.
        assert client.get("/api/v1/auth/me").status_code == 401
        # And the roster no longer shows them.
        roster = owner_client.get("/api/v1/employees/").json()
        assert all(e["user_id"] != employee["user_id"] for e in roster)


# ---------------------------------------------------------
# PASSWORD RESET
# ---------------------------------------------------------

class TestPasswordReset:
    def test_reset_flow(self, client, owner):
        r = client.post("/api/v1/auth/forgot-password",
                        json={"phone_number": "01700000001"})
        assert r.status_code == 200
        r = client.post("/api/v1/auth/reset-password", json={
            "phone_number": "01700000001",
            "new_password": "brandnew123",
        })
        assert r.status_code == 200
        # Old password fails, new one works.
        assert client.post("/api/v1/auth/login", json={
            "phone_number": "01700000001", "password": "secret123",
        }).status_code == 401
        assert client.post("/api/v1/auth/login", json={
            "phone_number": "01700000001", "password": "brandnew123",
        }).status_code == 200

    def test_reset_unknown_phone_404(self, client):
        r = client.post("/api/v1/auth/forgot-password",
                        json={"phone_number": "01999999999"})
        assert r.status_code == 404
