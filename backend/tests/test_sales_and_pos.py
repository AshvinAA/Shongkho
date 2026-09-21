"""
Sales & POS tests: happy-path checkout, overselling protection,
rollback/atomicity, totals math, receipts, and reports.
"""
import os
import sys

import pytest

# Make backend/ importable (tests live in backend/tests/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def checkout(client, customer_id, items, payment="Cash"):
    """Shorthand POST /checkout with a cart payload."""
    return client.post("/api/v1/checkout/", json={
        "customer_id": customer_id,
        "payment_method": payment,
        "items": items,
    })


def stock_of(client, product_id):
    """Read the current stock of a product from the API."""
    return client.get(f"/api/v1/products/{product_id}").json()["stock_quantity"]


# ---------------------------------------------------------
# HAPPY PATH
# ---------------------------------------------------------

class TestCheckoutHappyPath:
    def test_single_item_checkout(self, client, employee, product, customer):
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 2}])
        assert r.status_code == 200
        body = r.json()
        # Revenue = DB retail price x qty (NOT a client-supplied price).
        assert body["total_revenue"] == pytest.approx(60.0 * 2)
        assert body["total_profit"] == pytest.approx((60.0 - 40.0) * 2)
        assert body["employee_id"] == employee["user_id"]
        assert stock_of(client, product["product_id"]) == 98

    def test_multi_item_cart(self, client, owner_client, employee, product, customer):
        # Add a second product with different economics (owner action).
        second = owner_client.post("/api/v1/products/", json={
            "product_name": "Cheap Gadget", "cost_price": 10,
            "retail_price": 25, "stock_quantity": 50,
        }).json()

        r = checkout(client, customer["customer_id"], [
            {"product_id": product["product_id"], "quantity": 1},   # 60.0
            {"product_id": second["product_id"], "quantity": 3},    # 25.0 x 3
        ])
        assert r.status_code == 200
        body = r.json()
        assert body["total_revenue"] == pytest.approx(60.0 + 75.0)
        assert body["total_profit"] == pytest.approx(20.0 + 45.0)
        assert len(body["items"]) == 2
        assert stock_of(client, product["product_id"]) == 99
        assert stock_of(client, second["product_id"]) == 47

    def test_receipt_snapshots_prices(self, client, employee, product, customer):
        """Receipt prices must not change when the product price changes later."""
        sale = checkout(client, customer["customer_id"],
                        [{"product_id": product["product_id"], "quantity": 1}])
        tid = sale.json()["transaction_id"]

        # Owner changes the retail price after the sale...
        client.put(f"/api/v1/products/{product['product_id']}",
                   json={"retail_price": 999.0})

        receipt = client.get(f"/api/v1/sales/{tid}/receipt").json()
        line = receipt["items"][0]
        assert line["unit_price"] == pytest.approx(60.0)   # old price preserved
        assert receipt["customer_name"] == "Walkin Watson"
        assert receipt["employee_name"] == "Staff Guy"

    def test_sale_recorded_under_session_user(self, client, owner, employee, product, customer):
        """
        Even if the body forges employee_id, the sale must be recorded
        under the logged-in user.
        """
        r = client.post("/api/v1/checkout/", json={
            "customer_id": customer["customer_id"],
            "payment_method": "Cash",
            "employee_id": owner["user_id"],  # forgery attempt
            "items": [{"product_id": product["product_id"], "quantity": 1}],
        })
        assert r.status_code == 200
        assert r.json()["employee_id"] == employee["user_id"]

    def test_all_payment_methods_accepted(self, client, employee, product, customer):
        for method in ["Cash", "Card", "bKash", "Nagad"]:
            r = checkout(client, customer["customer_id"],
                         [{"product_id": product["product_id"], "quantity": 1}],
                         payment=method)
            assert r.status_code == 200
            assert r.json()["payment_method"] == method


# ---------------------------------------------------------
# OVERSELLING / OUT OF STOCK
# ---------------------------------------------------------

class TestOverSelling:
    def test_cannot_sell_more_than_stock(self, client, employee, product, customer):
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 101}])
        assert r.status_code == 400
        assert "not enough stock" in r.json()["detail"].lower()
        # Stock must be completely untouched after the failed attempt.
        assert stock_of(client, product["product_id"]) == product["stock_quantity"]

    def test_failed_line_does_not_partial_charge_other_lines(
        self, client, owner_client, employee, product, customer
    ):
        """
        Cart = [1x in-stock, 999x out-of-stock]. The whole transaction
        must fail — no deduction on the first line either.
        """
        other = owner_client.post("/api/v1/products/", json={
            "product_name": "Scarce Item", "cost_price": 1,
            "retail_price": 2, "stock_quantity": 5,
        }).json()

        r = checkout(client, customer["customer_id"], [
            {"product_id": product["product_id"], "quantity": 1},
            {"product_id": other["product_id"], "quantity": 999},
        ])
        assert r.status_code == 400
        assert stock_of(client, product["product_id"]) == product["stock_quantity"]
        assert stock_of(client, other["product_id"]) == 5

    def test_exact_stock_quantity_is_allowed(self, client, employee, product, customer):
        """Selling out completely is legitimate."""
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"],
                       "quantity": product["stock_quantity"]}])
        assert r.status_code == 200
        assert stock_of(client, product["product_id"]) == 0

    def test_zero_quantity_rejected(self, client, employee, product, customer):
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 0}])
        assert r.status_code == 422  # ge=1

    def test_negative_quantity_rejected(self, client, employee, product, customer):
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": -2}])
        assert r.status_code == 422

    def test_unknown_product_404(self, client, employee, customer):
        r = checkout(client, customer["customer_id"],
                     [{"product_id": 99999, "quantity": 1}])
        assert r.status_code == 404

    def test_empty_cart_rejected(self, client, employee, customer):
        r = checkout(client, customer["customer_id"], items=[])
        assert r.status_code == 422  # min_length=1

    def test_unknown_customer_404(self, client, employee, product):
        """A checkout for a non-existent customer must be rejected."""
        r = checkout(client, 99999,
                     [{"product_id": product["product_id"], "quantity": 1}])
        assert r.status_code == 404
        assert "customer" in r.json()["detail"].lower()

    def test_cannot_checkout_after_sellout(self, client, employee, product, customer):
        """Sell out, then attempt one more — must fail cleanly."""
        checkout(client, customer["customer_id"],
                 [{"product_id": product["product_id"],
                   "quantity": product["stock_quantity"]}])
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 1}])
        assert r.status_code == 400
        assert stock_of(client, product["product_id"]) == 0


# ---------------------------------------------------------
# ROLLBACK / ATOMICITY
# ---------------------------------------------------------

class TestAtomicity:
    def test_db_error_rolls_back_stock(self, client, employee, product, customer, monkeypatch):
        """
        Simulate a crash DURING commit (disk failure / constraint):
        stock deducted in memory must be rolled back — inventory intact.
        """
        import services

        original_commit = type(client).__mro__  # placeholder, real patch below

        def broken_commit():
            raise RuntimeError("simulated disk failure during commit")

        # Patch Session.commit used inside services.create_sale.
        from sqlalchemy.orm import Session
        monkeypatch.setattr(Session, "commit", broken_commit)

        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 3}])
        assert r.status_code == 400
        assert "checkout failed" in r.json()["detail"].lower()

        # Fresh session (override recreated per request) sees original stock.
        assert stock_of(client, product["product_id"]) == product["stock_quantity"]

    def test_error_mid_cart_leaves_no_sale_row(self, client, employee, product, customer, monkeypatch):
        """A SaleItem failure mid-cart must leave zero partial rows."""
        from sqlalchemy.orm import Session

        real_commit = Session.commit
        calls = {"n": 0}

        def flaky_commit(self):
            calls["n"] += 1
            if calls["n"] >= 1:
                raise RuntimeError("boom")
            return real_commit(self)

        monkeypatch.setattr(Session, "commit", flaky_commit)
        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 1}])
        assert r.status_code == 400

        # No sale should exist anywhere.
        sales = client.get("/api/v1/sales/").json()
        assert sales == []
        assert stock_of(client, product["product_id"]) == product["stock_quantity"]

    def test_saleitem_append_failure_keeps_stock(self, client, employee, product, customer, monkeypatch):
        """
        Mock an error while building the sale's items — the deduction
        must not persist.
        """
        import services

        real = models_saleitem = None
        from models import SaleItem

        def broken_saleitem(*args, **kwargs):
            raise RuntimeError("cannot build sale item")

        monkeypatch.setattr(SaleItem, "__init__", broken_saleitem, raising=True)

        r = checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 2}])
        assert r.status_code == 400
        assert stock_of(client, product["product_id"]) == product["stock_quantity"]


# ---------------------------------------------------------
# SALES LISTING, PERMISSIONS & REPORTS
# ---------------------------------------------------------

class TestSalesListingAndReports:
    def test_employee_sees_only_own_sales(self, client, owner_client, employee, product, customer):
        """The employee's listing must contain only sales they processed."""
        checkout(client, customer["customer_id"],
                 [{"product_id": product["product_id"], "quantity": 1}])
        sales = client.get("/api/v1/sales/").json()
        assert len(sales) == 1
        assert sales[0]["employee_id"] == employee["user_id"]

    def test_owner_sees_all_sales(self, client, owner_client, employee, product, customer):
        """The owner's listing includes sales processed by anyone."""
        checkout(client, customer["customer_id"],
                 [{"product_id": product["product_id"], "quantity": 2}])
        sales = owner_client.get("/api/v1/sales/").json()
        assert len(sales) == 1
        assert sales[0]["employee_id"] == employee["user_id"]

    def test_employee_cannot_view_others_receipt(
        self, client, owner, employee, product, customer
    ):
        # Sale processed by `employee`...
        sale = checkout(client, customer["customer_id"],
                        [{"product_id": product["product_id"], "quantity": 1}])
        tid = sale.json()["transaction_id"]

        # ...a SECOND employee of the same store tries to view it.
        owner_client = TestClient(app)
        owner_client.post("/api/v1/auth/login", json={
            "phone_number": "01700000001", "password": "secret123"})
        owner_client.post("/api/v1/auth/register/employee", json={
            "name": "Second Staff", "phone_number": "01700000003",
            "password": "secret123", "role": "employee"})
        other = TestClient(app)
        other.post("/api/v1/auth/login", json={
            "phone_number": "01700000003", "password": "secret123"})

        r = other.get(f"/api/v1/sales/{tid}/receipt")
        assert r.status_code == 403

    def test_receipt_404_unknown(self, client, employee):
        assert client.get("/api/v1/sales/99999/receipt").status_code == 404

    def test_daily_report_owner_only(self, client, owner_client, employee, product, customer):
        checkout(client, customer["customer_id"],
                 [{"product_id": product["product_id"], "quantity": 2}])
        r = owner_client.get("/api/v1/sales/reports/daily")
        assert r.status_code == 200
        body = r.json()
        assert body["total_transactions"] == 1
        assert body["total_revenue"] == pytest.approx(120.0)

    def test_report_invalid_period_400(self, client, owner_client):
        assert owner_client.get("/api/v1/sales/reports/century").status_code == 400


# ---------------------------------------------------------
# EMPLOYEE PERFORMANCE METRICS
# ---------------------------------------------------------

class TestPerformanceMetrics:
    def test_sales_increment_employee_metrics(self, client, owner_client, employee, product, customer):
        """Each recorded sale must bump the employee's counters exactly."""
        for _ in range(3):
            checkout(client, customer["customer_id"],
                     [{"product_id": product["product_id"], "quantity": 1}])

        perf = owner_client.get("/api/v1/employees/performance").json()
        row = next(p for p in perf if p["employee_id"] == employee["user_id"])
        assert row["total_sales"] == 3
        assert row["total_revenue"] == pytest.approx(180.0)
        assert row["total_profit"] == pytest.approx(60.0)

    def test_my_performance_endpoint(self, client, employee, product, customer):
        checkout(client, customer["customer_id"],
                 [{"product_id": product["product_id"], "quantity": 2}])
        r = client.get("/api/v1/employees/me/performance")
        assert r.status_code == 200
        body = r.json()
        assert body["total_sales"] == 1
        assert body["total_revenue"] == pytest.approx(120.0)
