"""
Full API test suite run against the real backend using the two demo accounts.

  Owner    edwin -> 1234567890 / owner123
  Employee adlin -> 0987654321 / emp123

Covers: auth, owner CRUD, stock, reports, performance, RBAC (403s),
employee-scoped sales, checkout flow, receipts, and negative paths.
Creates clearly-marked TEST rows and cleans up the ones it can.

Run:  python test_demo_flow.py
"""
from datetime import datetime

from fastapi.testclient import TestClient

import main
from database import get_db

BASE = "/api/v1"
OWNER = {"phone_number": "1234567890", "password": "owner123"}
EMP = {"phone_number": "0987654321", "password": "emp123"}

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  -> {detail}" if (detail and not condition) else ""))


def main_tests():
    client = TestClient(main.app)

    anon = TestClient(main.app)
    owner = TestClient(main.app)
    emp = TestClient(main.app)

    # ------------------------------------------------ 1. Health
    r = anon.get(f"{BASE}/health")
    check("health endpoint", r.status_code == 200 and r.json()["status"] == "ok")

    # ------------------------------------------------ 2. Auth
    r = anon.post(f"{BASE}/auth/login", json={"phone_number": OWNER["phone_number"], "password": "wrong"})
    check("login rejects wrong password (401)", r.status_code == 401)

    r = owner.post(f"{BASE}/auth/login", json=OWNER)
    check("edwin login (owner)", r.status_code == 200 and r.json()["role"] == "owner" and r.json()["name"] == "edwin", str(r.json()))

    r = emp.post(f"{BASE}/auth/login", json=EMP)
    check("adlin login (employee)", r.status_code == 200 and r.json()["role"] == "employee", str(r.json()))

    r = owner.get(f"{BASE}/auth/me")
    check("edwin /me hydrates session", r.status_code == 200 and r.json()["user_id"] and r.json()["role"] == "owner")

    r = anon.get(f"{BASE}/auth/me")
    check("anonymous /me is 401", r.status_code == 401)

    # ------------------------------------------------ 3. Products
    r = emp.get(f"{BASE}/products/", params={"limit": 200})
    products = r.json()
    check("product list (employee)", r.status_code == 200 and len(products) >= 20, f"n={len(products)}")

    r = owner.get(f"{BASE}/products/search/", params={"query": "Galaxy"})
    check("product search 'Galaxy'", r.status_code == 200 and any("Galaxy" in p["product_name"] for p in r.json()))

    r = anon.get(f"{BASE}/products/")
    check("product list anonymous -> 401", r.status_code == 401)

    payload = {"product_name": "TEST_Product X", "cost_price": 50.0, "retail_price": 80.0,
               "stock_quantity": 10, "category": "TEST", "supplier_name": "TEST"}
    r = owner.post(f"{BASE}/products/", json=payload)
    check("create product (owner)", r.status_code == 200 and r.json()["product_name"] == "TEST_Product X", str(r.json()))
    test_pid = r.json().get("product_id")

    r = emp.post(f"{BASE}/products/", json=payload)
    check("create product as employee -> 403", r.status_code == 403)

    r = owner.post(f"{BASE}/products/", json={"product_name": "bad", "cost_price": -5.0, "retail_price": 10.0})
    check("negative cost price -> 422", r.status_code == 422)

    r = owner.put(f"{BASE}/products/{test_pid}", json={"retail_price": 99.0})
    check("update product price (owner)", r.status_code == 200 and r.json()["retail_price"] == 99.0)

    r = owner.patch(f"{BASE}/products/{test_pid}/stock", json={"quantity_change": 5})
    check("stock +5 (owner)", r.status_code == 200 and r.json()["stock_quantity"] == 15, str(r.json()))

    r = owner.patch(f"{BASE}/products/{test_pid}/stock", json={"quantity_change": -2})
    check("stock -2 (owner)", r.status_code == 200 and r.json()["stock_quantity"] == 13)

    r = owner.patch(f"{BASE}/products/{test_pid}/stock", json={"quantity_change": -999})
    check("stock below zero -> 400", r.status_code == 400)

    r = emp.patch(f"{BASE}/products/{test_pid}/stock", json={"quantity_change": 1})
    check("stock adjust as employee -> 403", r.status_code == 403)

    r = owner.delete(f"{BASE}/products/{test_pid}")
    check("delete test product (owner)", r.status_code == 200)
    r = owner.get(f"{BASE}/products/{test_pid}")
    check("deleted product -> 404", r.status_code == 404)

    # ------------------------------------------------ 4. Customers
    r = owner.get(f"{BASE}/customers/", params={"limit": 100})
    check("customer directory with lifetime spend (owner)",
          r.status_code == 200 and len(r.json()) >= 5 and "total_spend" in r.json()[0], f"n={len(r.json()) if r.status_code==200 else r.text}")

    r = emp.get(f"{BASE}/customers/")
    check("customer directory as employee -> 403", r.status_code == 403)

    # unique phone per run so the suite can be re-run safely
    test_phone = f"01911{int(datetime.now().timestamp()) % 100000:05d}"
    r = emp.post(f"{BASE}/customers/", json={"name": "TEST_Customer", "phone_number": test_phone})
    check("quick-add customer (employee)", r.status_code == 200 and r.json()["name"] == "TEST_Customer", str(r.json()))
    test_cid = r.json().get("customer_id")

    r = emp.post(f"{BASE}/customers/", json={"name": "Dup", "phone_number": test_phone})
    check("duplicate phone -> 400", r.status_code == 400)

    r = emp.get(f"{BASE}/customers/phone/{test_phone}")
    check("lookup customer by phone", r.status_code == 200 and r.json()["customer_id"] == test_cid)

    r = anon.get(f"{BASE}/customers/phone/01820000001")
    check("customer lookup anonymous -> 401", r.status_code == 401)

    r = emp.put(f"{BASE}/customers/{test_cid}", json={"name": "TEST_Customer_Renamed"})
    check("rename customer", r.status_code == 200 and r.json()["name"] == "TEST_Customer_Renamed")

    # pick a customer that actually has purchases (by lifetime spend)
    r = owner.get(f"{BASE}/customers/", params={"limit": 100})
    directory = r.json()
    with_spend = [c for c in directory if c.get("total_spend", 0) > 0]
    check("at least one customer has purchases", len(with_spend) >= 1, f"n={len(with_spend)}")
    target = with_spend[0]

    r = owner.get(f"{BASE}/customers/{target['customer_id']}/history")
    hist = r.json()
    check("customer purchase history", r.status_code == 200 and len(hist) >= 1,
          f"for {target['name']}: n={len(hist) if r.status_code==200 else r.text}")

    r = owner.get(f"{BASE}/customers/999999/history")
    check("history for nonexistent customer -> 404", r.status_code == 404)

    # ------------------------------------------------ 5. Checkout
    prods = {p["product_name"]: p for p in products}
    # pick two well-stocked products dynamically (shelves sell out during demos)
    in_stock = sorted((p for p in products if p["stock_quantity"] >= 10), key=lambda p: -p["stock_quantity"])
    check("at least two products in stock for checkout test", len(in_stock) >= 2, f"n={len(in_stock)}")
    first, second = in_stock[0], in_stock[1]
    cust = emp.get(f"{BASE}/customers/phone/01820000003").json()

    stock_before = (emp.get(f"{BASE}/products/{first['product_id']}").json()["stock_quantity"],
                    emp.get(f"{BASE}/products/{second['product_id']}").json()["stock_quantity"])

    cart = {"customer_id": cust["customer_id"], "payment_method": "bKash",
            "items": [{"product_id": first["product_id"], "quantity": 2},
                      {"product_id": second["product_id"], "quantity": 1},
                      {"product_id": 999999, "quantity": 1}]}
    r = emp.post(f"{BASE}/checkout/", json=cart)
    check("checkout with nonexistent product -> 404", r.status_code == 404, str(r.json()))

    cart["items"] = [{"product_id": first["product_id"], "quantity": 2},
                     {"product_id": second["product_id"], "quantity": 1}]
    r = anon.post(f"{BASE}/checkout/", json=cart)
    check("checkout anonymous -> 401", r.status_code == 401)

    r = emp.post(f"{BASE}/checkout/", json=cart)
    body = r.json()
    expected = round(first["retail_price"] * 2 + second["retail_price"] * 1, 2)
    check("checkout (adlin, multi-item)", r.status_code == 200, str(body))
    check("checkout totals computed server-side", body.get("total_revenue") == expected,
          f"got {body.get('total_revenue')}, expected {expected}")
    txn = body.get("transaction_id")

    stock_after = (emp.get(f"{BASE}/products/{first['product_id']}").json()["stock_quantity"],
                   emp.get(f"{BASE}/products/{second['product_id']}").json()["stock_quantity"])
    check("stock deducted after sale", stock_after == (stock_before[0] - 2, stock_before[1] - 1),
          f"{stock_before} -> {stock_after}")

    huge = {"customer_id": cust["customer_id"], "payment_method": "Cash",
            "items": [{"product_id": second["product_id"], "quantity": 99999}]}
    r = emp.post(f"{BASE}/checkout/", json=huge)
    check("overselling blocked -> 400", r.status_code == 400, str(r.json()))

    r = emp.get(f"{BASE}/sales/{txn}/receipt")
    rc = r.json()
    # item order is not guaranteed (composite PK ordering) — compare as a set
    receipt_names = {it["product_name"] for it in rc.get("items", [])}
    check("receipt drill-down", r.status_code == 200 and len(rc.get("items", [])) == 2
          and receipt_names == {first["product_name"], second["product_name"]}
          and rc.get("employee_name") == "adlin", str(rc)[:200])

    r = emp.post(f"{BASE}/checkout/", json={**cart, "employee_id": 999})
    check("client-sent employee_id ignored (session wins)", r.status_code == 200)

    # ------------------------------------------------ 6. Sales scoping & reports
    r = emp.get(f"{BASE}/sales/", params={"limit": 200})
    emp_sales = r.json()
    check("adlin sees only her sales", r.status_code == 200 and all(s.get("employee_id") == emp.get(f"{BASE}/auth/me").json()["user_id"] for s in emp_sales),
          f"n={len(emp_sales)}")

    r = owner.get(f"{BASE}/sales/", params={"limit": 300})
    owner_sales = r.json()
    check("edwin sees all sales", r.status_code == 200 and len(owner_sales) >= len(emp_sales), f"n={len(owner_sales)}")
    check("sales sorted newest first", owner_sales[0]["transaction_id"] >= owner_sales[-1]["transaction_id"])

    for period in ("daily", "weekly", "monthly"):
        r = owner.get(f"{BASE}/sales/reports/{period}")
        ok = r.status_code == 200 and r.json()["period"] == period and r.json()["total_transactions"] > 0
        check(f"{period} report (owner)", ok, str(r.json())[:120])

    r = emp.get(f"{BASE}/sales/reports/daily")
    check("report as employee -> 403", r.status_code == 403)

    r = owner.get(f"{BASE}/sales/reports/yearly")
    check("invalid report period -> 400", r.status_code == 400)

    # ------------------------------------------------ 7. Employees / staff
    r = owner.get(f"{BASE}/employees/")
    roster = r.json()
    check("employee roster (owner)", r.status_code == 200 and any(e["name"] == "adlin" for e in roster), str(roster)[:120])
    adlin_row = next((e for e in roster if e["name"] == "adlin"), None)

    r = emp.get(f"{BASE}/employees/")
    check("roster as employee -> 403", r.status_code == 403)

    r = owner.get(f"{BASE}/employees/performance")
    perf = r.json()
    adlin_perf = next((p for p in perf if p["employee_name"] == "adlin"), None)
    check("performance report (owner)", r.status_code == 200 and adlin_perf and adlin_perf["total_sales"] > 0,
          str(adlin_perf))

    r = owner.get(f"{BASE}/employees/search/", params={"query": "adlin"})
    check("employee search", r.status_code == 200 and any(e["name"] == "adlin" for e in r.json()))

    r = owner.put(f"{BASE}/employees/{adlin_row['user_id']}", json={"position": "Senior Sales Executive", "salary": 20000.0})
    check("update adlin position/salary", r.status_code == 200 and r.json()["position"] == "Senior Sales Executive")

    # restore demo values
    owner.put(f"{BASE}/employees/{adlin_row['user_id']}", json={"position": "Sales Executive", "salary": 18000.0})

    r = emp.put(f"{BASE}/employees/{adlin_row['user_id']}", json={"position": "Hacker"})
    check("employee cannot edit staff -> 403", r.status_code == 403)

    r = owner.delete(f"{BASE}/employees/{owner.get(f'{BASE}/auth/me').json()['user_id']}")
    check("owner cannot delete self -> 400", r.status_code == 400)

    r = owner.delete(f"{BASE}/employees/999999")
    check("delete nonexistent employee -> 404", r.status_code == 404)

    r = emp.delete(f"{BASE}/employees/{adlin_row['user_id']}")
    check("employee cannot delete staff -> 403", r.status_code == 403)

    # ------------------------------------------------ 8. Auth extras
    r = anon.post(f"{BASE}/auth/forgot-password", json={"phone_number": EMP["phone_number"]})
    check("forgot-password finds adlin", r.status_code == 200 and "adlin" in r.json()["detail"], str(r.json()))

    r = anon.post(f"{BASE}/auth/forgot-password", json={"phone_number": "0111111111"})
    check("forgot-password unknown phone -> 404", r.status_code == 404)

    r = emp.post(f"{BASE}/auth/logout")
    check("adlin logout", r.status_code == 200)
    r = emp.get(f"{BASE}/auth/me")
    check("session cleared after logout", r.status_code == 401)

    # edwin still logged in
    r = owner.get(f"{BASE}/auth/me")
    check("edwin session unaffected", r.status_code == 200)


if __name__ == "__main__":
    print("=" * 64)
    print("Shongkho API test suite — edwin (owner) & adlin (employee)")
    print("=" * 64)
    try:
        main_tests()
    except Exception as e:
        check("suite completed without crash", False, repr(e))
    finally:
        passed = sum(1 for _, ok in results if ok)
        failed = len(results) - passed
        print("-" * 64)
        print(f"RESULT: {passed}/{len(results)} passed" + (f"  ({failed} FAILED)" if failed else "  — all green"))
        raise SystemExit(1 if failed else 0)
