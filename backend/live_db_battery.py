"""
Live database battery — end-to-end checks against the REAL configured
database (TiDB Cloud when backend/.env points there).

Unlike tests/ (which is hermetic on throwaway SQLite), this script boots
the actual app on the actual database and exercises it through the real
API stack: schema, auth, RBAC, products, checkout math, group chat,
staff warnings/commission, customers, and seeded photos.

Every row this script creates is cleaned up again; seeded demo data is
left pristine.

Run:  cd backend && python live_db_battery.py
Exit: 0 when every check passes, 1 otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import certifi  # noqa: E402
import pymysql  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import database  # noqa: E402
from main import app  # noqa: E402

PASSWORD = "shongkho123"
OWNER = "01711111100"  # Edwin Zaman
EMPLOYEE = "01711111101"  # Rahim Uddin

EXPECTED_TABLES = {
    "analysis_runs", "analytics_snapshots", "assistant_messages",
    "chat_messages", "commission_settings", "customers", "employees",
    "owners", "products", "sale_items", "sales", "staff_warnings", "users",
}

results = []


def retry_1205(fn, attempts=3):
    """TiDB lock-wait timeouts can happen if something else writes concurrently."""
    import time
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if "1205" in str(exc) and i < attempts - 1:
                time.sleep(3)
                continue
            raise


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def tidb_conn():
    return pymysql.connect(
        host=os.environ["TIDB_HOST"], port=int(os.environ["TIDB_PORT"]),
        user=os.environ["TIDB_USER"], password=os.environ["TIDB_PASSWORD"],
        database="shongkho", ssl={"ca": certifi.where(), "verify_identity": True},
        autocommit=True,
    )


print("Booting the app against the configured database…")
with TestClient(app) as client:
    # ------------------------------------------------ 1. schema
    print("\n[1] Schema")
    insp = inspect(database.get_engine())
    tables = set(insp.get_table_names())
    check("all 13 tables exist", EXPECTED_TABLES <= tables,
          f"missing: {sorted(EXPECTED_TABLES - tables)}" if EXPECTED_TABLES - tables else "")

    # ------------------------------------------------ 2. auth + RBAC
    print("\n[2] Auth & RBAC")
    r = client.post("/api/v1/auth/login", json={"phone_number": OWNER, "password": PASSWORD})
    check("owner login", r.status_code == 200 and r.json().get("role") == "owner", r.text[:80])
    r = client.post("/api/v1/auth/login", json={"phone_number": EMPLOYEE, "password": "wrong-pass"})
    check("wrong password rejected", r.status_code in (401, 403), f"status {r.status_code}")
    r = client.post("/api/v1/auth/login", json={"phone_number": EMPLOYEE, "password": PASSWORD})
    check("employee login", r.status_code == 200 and r.json().get("role") == "employee", r.text[:80])

    r = client.get("/api/v1/employees/performance?limit=3")
    check("RBAC: employee blocked from owner endpoint", r.status_code == 403, f"status {r.status_code}")

    # owner session (separate client so the employee cookie is preserved)
    owner_client = TestClient(app)
    r = owner_client.post("/api/v1/auth/login", json={"phone_number": OWNER, "password": PASSWORD})
    r = owner_client.get("/api/v1/employees/performance?limit=5")
    check("RBAC: owner allowed + performance data", r.status_code == 200 and len(r.json()) >= 5,
          f"{len(r.json())} rows")

    # ------------------------------------------------ 3. products (CRUD + stock)
    print("\n[3] Products")
    r = owner_client.get("/api/v1/products/?limit=100")
    products = r.json()
    check("product list", r.status_code == 200 and len(products) >= 20, f"{len(products)} products")

    r = owner_client.post("/api/v1/products/", json={
        "product_name": "ZZZ Battery Test Item", "cost_price": 10, "retail_price": 15,
        "stock_quantity": 100, "category": "Test",
    })
    check("owner creates product", r.status_code in (200, 201), r.text[:80])
    test_pid = r.json()["product_id"]
    r = owner_client.put(f"/api/v1/products/{test_pid}", json={"stock_quantity": 100})
    check("owner updates product", r.status_code == 200, f"status {r.status_code}")

    # ------------------------------------------------ 4. checkout math
    print("\n[4] Checkout")
    conn = tidb_conn()
    cur = conn.cursor()
    cur.execute("SELECT customer_id FROM customers ORDER BY customer_id LIMIT 1")
    cust_id = cur.fetchone()[0]
    conn.close()
    r = client.post("/api/v1/checkout/", json={
        "customer_id": cust_id, "payment_method": "cash",
        "items": [{"product_id": test_pid, "quantity": 2}],
    })
    check("employee checkout succeeds", r.status_code == 200, r.text[:90])
    tid = r.json()["transaction_id"]
    check("revenue math exact (2 x 15)", r.json()["total_revenue"] == 30.0,
          f"got {r.json()['total_revenue']}")
    check("profit math exact (2 x 5)", r.json()["total_profit"] == 10.0,
          f"got {r.json()['total_profit']}")
    r = owner_client.get(f"/api/v1/products/{test_pid}")
    check("stock decremented 100 -> 98", r.json()["stock_quantity"] == 98,
          f"got {r.json()['stock_quantity']}")

    # ------------------------------------------------ 5. group chat
    print("\n[5] Group chat")
    r = client.post("/api/v1/chat/messages", json={"body": "Battery test message from Rahim."})
    check("employee posts chat message", r.status_code == 201, f"status {r.status_code}")
    emp_msg_id = r.json()["message_id"]
    r = owner_client.post("/api/v1/chat/messages",
                          json={"body": "Reply from the owner.", "reply_to_id": emp_msg_id})
    check("owner replies (threaded)", r.status_code == 201 and r.json().get("reply_to_id") == emp_msg_id,
          f"reply_to={r.json().get('reply_to_id')}")
    owner_msg_id = r.json()["message_id"]
    r = client.get("/api/v1/chat/messages?limit=200")
    bodies = [m["body"] for m in r.json()]
    check("employee sees owner reply in history",
          any("Reply from the owner." in b for b in bodies), f"{len(bodies)} messages visible")
    r = client.delete(f"/api/v1/chat/messages/{owner_msg_id}")
    check("cannot delete someone else's message", r.status_code in (403, 404), f"status {r.status_code}")
    r = owner_client.delete(f"/api/v1/chat/messages/{owner_msg_id}")
    check("owner deletes own message", r.status_code == 200, f"status {r.status_code}")

    # ------------------------------------------------ 6. staff warnings + commission
    print("\n[6] Staff module")
    conn = tidb_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE phone_number=%s", (EMPLOYEE,))
    rahim_id = cur.fetchone()[0]
    conn.close()
    r = owner_client.put(f"/api/v1/staff/employees/{rahim_id}/commission",
                         json={"basis": "revenue", "rate": 5})
    check("owner sets 5% revenue commission", r.status_code == 200, r.text[:80])
    r = owner_client.get(f"/api/v1/staff/employees/{rahim_id}/commission")
    check("commission round-trips", r.json().get("rate") == 5 and r.json().get("basis") == "revenue",
          str(r.json())[:80])
    r = retry_1205(lambda: owner_client.post(
        f"/api/v1/staff/employees/{rahim_id}/warnings",
        json={"reason": "Battery test warning — ignore."}))
    check("owner issues warning", r.status_code in (200, 201), r.text[:80])
    warn_id = r.json().get("id") or r.json().get("warning_id")
    r = client.get("/api/v1/staff/me/warnings")
    check("employee sees own warning", r.status_code == 200 and len(r.json()) >= 1,
          f"{len(r.json())} warning(s)")
    r = owner_client.put(f"/api/v1/staff/employees/{rahim_id}/commission",
                         json={"basis": "revenue", "rate": None})
    check("commission cleared", r.status_code == 200, f"status {r.status_code}")

    # ------------------------------------------------ 7. customers
    print("\n[7] Customers")
    r = owner_client.get("/api/v1/customers/")
    check("owner lists customers", r.status_code == 200 and len(r.json()) >= 10,
          f"{len(r.json())} customers")
    r = owner_client.post("/api/v1/customers/", json={
        "name": "ZZZ Battery Test Customer", "phone_number": "01999997777"})
    check("owner creates customer", r.status_code in (200, 201), r.text[:80])
    test_cust_id = r.json()["customer_id"]

    # ------------------------------------------------ 8. seeded photos
    print("\n[8] Seeded portraits")
    conn = tidb_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE photo IS NOT NULL AND photo LIKE '/static/avatars/%'")
    photo_users = cur.fetchone()[0]
    conn.close()
    check("all 8 users carry portrait URLs", photo_users == 8, f"{photo_users}/8")
    r = client.get("/static/avatars/rahim.jpg")
    check("portrait served over /static", r.status_code == 200 and len(r.content) > 1000,
          f"{len(r.content)} bytes")

    # ------------------------------------------------ 9. sales history
    print("\n[9] Sales history")
    r = owner_client.get("/api/v1/sales/?limit=5")
    check("sales history endpoint", r.status_code == 200 and len(r.json()) == 5,
          f"{len(r.json())} rows on page 1")

    # ------------------------------------------------ cleanup (hard-delete test rows)
    print("\nCleanup")
    conn = tidb_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sale_items WHERE transaction_id=%s", (tid,))
    cur.execute("DELETE FROM sales WHERE transaction_id=%s", (tid,))
    cur.execute("DELETE FROM products WHERE product_id=%s", (test_pid,))
    cur.execute("DELETE FROM customers WHERE customer_id=%s", (test_cust_id,))
    if warn_id:
        cur.execute("DELETE FROM staff_warnings WHERE id=%s", (warn_id,))
    # chat deletes are soft by design — hard-remove the two battery rows
    # by id, CHILD (reply) first: reply_to_id carries an FK to its parent.
    for mid in (owner_msg_id, emp_msg_id):
        cur.execute("DELETE FROM chat_messages WHERE message_id=%s", (mid,))
    conn.commit()
    conn.close()
    print("  test rows removed (sale, product, customer, warning, chat)")

# ------------------------------------------------ summary
failed = [name for name, ok, _ in results if not ok]
print(f"\n{'=' * 50}\nLIVE DB BATTERY: {len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED:", *failed, sep="\n  - ")
sys.exit(1 if failed else 0)
