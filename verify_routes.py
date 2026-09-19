"""
Route verification — runs the real app against a throwaway SQLite DB and
checks every UI + API route for BOTH roles (owner and employee).

Run:  python verify_routes.py
"""
import os

os.environ["TIDB_DATABASE_URL"] = "sqlite:///verify_test.db"

if os.path.exists("verify_test.db"):
    os.remove("verify_test.db")

from fastapi.testclient import TestClient  # noqa: E402

import database  # noqa: E402
import models  # noqa: E402
import services  # noqa: E402
import schemas  # noqa: E402
from main import app  # noqa: E402

database.init_db()
db = database.SessionLocal()

# ---- fresh users (isolated SQLite DB) ----
owner = services.register_user(db, schemas.EmployeeCreate(
    name="Test Owner", phone_number="01700000001", role="owner", password="owner123"))
employee = services.register_user(db, schemas.EmployeeCreate(
    name="Test Employee", phone_number="01700000002", role="employee", password="emp123",
    employer_id=owner.user_id))
product = models.Product(product_name="Test Tea", cost_price=10.0, retail_price=15.0,
                         stock_quantity=100, category="Beverages")
customer = models.Customer(name="Walkin Cust", phone_number="01810000001")
db.add_all([product, customer])
db.commit()
db.refresh(product)
db.refresh(customer)
db.close()

client = TestClient(app)
results = []


def check(label, expected, actual):
    ok = actual == expected
    results.append((ok, label, expected, actual))
    print(f"{'PASS' if ok else 'FAIL':4}  {label:55} expected={expected} actual={actual}")


def login(phone, password):
    r = client.post("/auth/login", json={"phone_number": phone, "password": password})
    assert r.status_code == 200, f"login failed: {r.text}"


def checkout():
    r = client.post("/checkout/", json={
        "customer_id": customer.customer_id,
        "payment_method": "Cash",
        "items": [{"product_id": product.product_id, "quantity": 2}],
    })
    assert r.status_code == 200, f"checkout failed: {r.text}"
    return r.json()


# ================= UNAUTHENTICATED =================
print("\n----- anonymous visitor -----")
check("GET / (anon)", 302, client.get("/", follow_redirects=False).status_code)
for path in ["/owner-dashboard", "/employee-dashboard", "/pos", "/inventory",
             "/customers", "/customers-ui", "/staff", "/sales"]:
    check(f"GET {path} (anon)", 302, client.get(path, follow_redirects=False).status_code)
check("GET /login (anon)", 200, client.get("/login").status_code)
check("GET /register (anon)", 200, client.get("/register").status_code)
check("GET /auth/me (anon)", 401, client.get("/auth/me").status_code)

# ================= OWNER =================
print("\n----- owner -----")
login("01700000001", "owner123")
check("GET / (owner)", 302, client.get("/", follow_redirects=False).status_code)
check("GET /owner-dashboard", 200, client.get("/owner-dashboard").status_code)
check("GET /employee-dashboard (owner)", 302, client.get("/employee-dashboard", follow_redirects=False).status_code)
check("GET /pos", 200, client.get("/pos").status_code)
check("GET /inventory", 200, client.get("/inventory").status_code)
check("GET /customers", 200, client.get("/customers").status_code)
check("GET /customers-ui", 200, client.get("/customers-ui").status_code)
check("GET /staff", 200, client.get("/staff").status_code)
check("GET /sales", 200, client.get("/sales").status_code)
check("GET /auth/me", 200, client.get("/auth/me").status_code)

owner_sale = checkout()
check("POST /checkout/", 200, 200)
check("GET /products/", 200, client.get("/products/").status_code)
check("GET /products/categories", 200, client.get("/products/categories").status_code)
check("POST /products/ (owner)", 200, 200)
check("PATCH /products/{id}/stock", 200, client.patch(
    f"/products/{product.product_id}/stock", json={"quantity_change": 5}).status_code)

# 1x1 transparent PNG for upload tests
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)
check("POST /products/{id}/photo (owner)", 200, client.post(
    f"/products/{product.product_id}/photo",
    files={"file": ("test.png", PNG_BYTES, "image/png")}).status_code)
check("Product photo persisted", True, bool(client.get(f"/products/{product.product_id}").json()["photo"]))
check("PUT /products/{id} (owner)", 200, client.put(
    f"/products/{product.product_id}", json={"retail_price": 16.0}).status_code)
check("GET /customers/ (owner)", 200, client.get("/customers/").status_code)
check("GET /customers/phone/{phone}", 200,
      client.get(f"/customers/phone/{customer.phone_number}").status_code)
check("GET /customers/{id}/history", 200,
      client.get(f"/customers/{customer.customer_id}/history").status_code)
check("GET /employees/ (owner)", 200, client.get("/employees/").status_code)
check("GET /employees/performance", 200, client.get("/employees/performance").status_code)
check("GET /sales/", 200, client.get("/sales/").status_code)
check("GET /sales/reports/daily", 200, client.get("/sales/reports/daily").status_code)
check("GET /sales/reports/weekly", 200, client.get("/sales/reports/weekly").status_code)
check("GET /sales/reports/monthly", 200, client.get("/sales/reports/monthly").status_code)
check("GET /sales/{id}/receipt (own)", 200,
      client.get(f"/sales/{owner_sale['transaction_id']}/receipt").status_code)
check("POST /auth/logout", 200, client.post("/auth/logout").status_code)

# ================= EMPLOYEE =================
print("\n----- employee -----")
login("01700000002", "emp123")
check("GET / (employee)", 302, client.get("/", follow_redirects=False).status_code)
check("GET /employee-dashboard", 200, client.get("/employee-dashboard").status_code)
check("GET /owner-dashboard (employee)", 302, client.get("/owner-dashboard", follow_redirects=False).status_code)
check("GET /staff (employee)", 302, client.get("/staff", follow_redirects=False).status_code)
check("GET /pos", 200, client.get("/pos").status_code)
check("GET /inventory", 200, client.get("/inventory").status_code)
check("GET /customers", 200, client.get("/customers").status_code)
check("GET /sales", 200, client.get("/sales").status_code)

emp_sale = checkout()
check("POST /checkout/", 200, 200)
check("GET /products/", 200, client.get("/products/").status_code)
check("POST /products/ (employee)", 403, client.post("/products/", json={
    "product_name": "X", "cost_price": 1, "retail_price": 2}).status_code)
check("DELETE /products/{id} (employee)", 403,
      client.delete(f"/products/{product.product_id}").status_code)
check("PATCH /products/{id}/stock (employee)", 403, client.patch(
    f"/products/{product.product_id}/stock", json={"quantity_change": 5}).status_code)
check("POST /products/{id}/photo (employee)", 403, client.post(
    f"/products/{product.product_id}/photo",
    files={"file": ("test.png", PNG_BYTES, "image/png")}).status_code)
check("GET /customers/ (employee)", 403, client.get("/customers/").status_code)
check("GET /customers/phone/{phone}", 200,
      client.get(f"/customers/phone/{customer.phone_number}").status_code)
check("POST /customers/ (employee quick-add)", 200, client.post("/customers/", json={
    "name": "Quick Add", "phone_number": "01810000009"}).status_code)
check("GET /employees/ (employee)", 403, client.get("/employees/").status_code)
check("GET /employees/performance (employee)", 403, client.get("/employees/performance").status_code)
check("GET /sales/", 200, client.get("/sales/").status_code)
check("GET /sales/reports/daily (employee)", 403, client.get("/sales/reports/daily").status_code)
check("GET /sales/{id}/receipt (own)", 200,
      client.get(f"/sales/{emp_sale['transaction_id']}/receipt").status_code)
check("GET /sales/{id}/receipt (someone else's)", 403,
      client.get(f"/sales/{owner_sale['transaction_id']}/receipt").status_code)

# ================= SUMMARY =================
failed = [r for r in results if not r[0]]
print(f"\n{'=' * 60}")
print(f"TOTAL: {len(results)}  PASS: {len(results) - len(failed)}  FAIL: {len(failed)}")
for ok, label, expected, actual in failed:
    print(f"  FAIL: {label} (expected {expected}, got {actual})")
raise SystemExit(1 if failed else 0)
