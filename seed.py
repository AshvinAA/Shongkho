"""
Seed script — fills the database with demo data so every page has content.

Safe to re-run: each section is skipped if that data already exists.
Run:  python seed.py
"""
import random
from datetime import datetime, timedelta

from database import SessionLocal
import models
import schemas
import services

random.seed(42)  # reproducible demo data

OWNER = {"name": "edwin", "phone_number": "1234567890", "password": "owner123"}

EMPLOYEES = [
    {"name": "adlin", "phone_number": "0987654321", "password": "emp123", "position": "Cashier", "salary": 15000},
]

PRODUCTS = [
    {"product_name": "Samsung Galaxy A15 5G",    "cost_price": 21000.0, "retail_price": 24500.0, "stock_quantity": 12,  "category": "Phones",        "supplier_name": "Samsung Distributors"},
    {"product_name": "Xiaomi Redmi 13C",         "cost_price": 14000.0, "retail_price": 16500.0, "stock_quantity": 18,  "category": "Phones",        "supplier_name": "Xiaomi BD"},
    {"product_name": "iPhone 13 (128GB)",        "cost_price": 78000.0, "retail_price": 86000.0, "stock_quantity": 5,   "category": "Phones",        "supplier_name": "Apple Authorised"},
    {"product_name": "Realme C67",               "cost_price": 17500.0, "retail_price": 19900.0, "stock_quantity": 9,   "category": "Phones",        "supplier_name": "Realme BD"},
    {"product_name": "Anker 20000mAh Power Bank", "cost_price": 2800.0,  "retail_price": 3500.0,  "stock_quantity": 25,  "category": "Accessories",   "supplier_name": "Anker BD"},
    {"product_name": "USB-C Fast Charger 33W",   "cost_price": 750.0,   "retail_price": 1100.0,  "stock_quantity": 40,  "category": "Accessories",   "supplier_name": "Baseus BD"},
    {"product_name": "JBL Tune 520BT Headphones", "cost_price": 4200.0,  "retail_price": 5200.0,  "stock_quantity": 15,  "category": "Audio",         "supplier_name": "JBL BD"},
    {"product_name": "Xiaomi Redmi Buds 4 Lite", "cost_price": 1800.0,  "retail_price": 2400.0,  "stock_quantity": 22,  "category": "Audio",         "supplier_name": "Xiaomi BD"},
    {"product_name": "Grameenphone 100tk Recharge", "cost_price": 96.0, "retail_price": 100.0,   "stock_quantity": 200, "category": "Recharge",      "supplier_name": "GP Load"},
    {"product_name": "Robi 200tk Flexiload",     "cost_price": 194.0,   "retail_price": 200.0,   "stock_quantity": 150, "category": "Recharge",      "supplier_name": "Robi Load"},
    {"product_name": "Airtel 1GB Data Pack",     "cost_price": 95.0,    "retail_price": 109.0,   "stock_quantity": 300, "category": "Recharge",      "supplier_name": "Airtel BD"},
    {"product_name": "Tempered Glass (Universal)", "cost_price": 60.0,  "retail_price": 150.0,   "stock_quantity": 3,   "category": "Accessories",   "supplier_name": "Local Import"},
]

CUSTOMERS = [
    {"name": "Abdul Karim",   "phone_number": "01810000001"},
    {"name": "Nusrat Jahan",  "phone_number": "01810000002"},
    {"name": "Tanvir Hasan",  "phone_number": "01810000003"},
    {"name": "Mitu Akter",    "phone_number": "01810000004"},
    {"name": "Jahangir Alam", "phone_number": "01810000005"},
]

# Store identity shown on the owner profile
STORE_NAME = "zaman telecom"

# payment methods weighted for variety
PAYMENTS = ["Cash", "Cash", "Cash", "Card", "bKash"]


def seed():
    db = SessionLocal()
    try:
        # ---------------- Owner ----------------
        owner = db.query(models.Owner).first()
        if not owner:
            owner = services.register_user(db, schemas.EmployeeCreate(**{**OWNER, "role": "owner"}), creator_role=None)
            print(f"[+] Owner created: {owner.name} (ID {owner.user_id}, phone {OWNER['phone_number']}, password owner123)")
            print(f"    Store name: {STORE_NAME}")
        else:
            print(f"[=] Using existing owner: {owner.name} (ID {owner.user_id})")
        # Keep the store name in sync with the demo data
        if owner.store_name != STORE_NAME:
            owner.store_name = STORE_NAME
            db.commit()

        owner_id = owner.user_id

        # ---------------- Employees ----------------
        for emp_data in EMPLOYEES:
            emp = db.query(models.Employee).filter(models.Employee.phone_number == emp_data["phone_number"]).first()
            if not emp:
                payload = schemas.EmployeeCreate(**{**emp_data, "role": "employee", "employer_id": owner_id})
                emp = services.register_user(db, payload, creator_role="owner")
                print(f"[+] Employee created: {emp.name} (ID {emp.user_id}, phone {emp_data['phone_number']}, password emp123)")
            else:
                print(f"[=] Employee already exists: {emp.name} (ID {emp.user_id})")

        employees = db.query(models.Employee).all()

        # ---------------- Products ----------------
        existing_names = {p.product_name for p in db.query(models.Product).all()}
        added = 0
        for p in PRODUCTS:
            if p["product_name"] not in existing_names:
                db.add(models.Product(**p))
                added += 1
        db.commit()
        print(f"[+] {added} new products added to inventory")

        products = db.query(models.Product).all()

        # ---------------- Customers ----------------
        existing_phones = {c.phone_number for c in db.query(models.Customer).all()}
        added = 0
        for c in CUSTOMERS:
            if c["phone_number"] not in existing_phones:
                db.add(models.Customer(**c))
                added += 1
        db.commit()
        print(f"[+] {added} new customers added")

        customers = db.query(models.Customer).all()

        # ---------------- Sales (last 30 days) ----------------
        sale_count = db.query(models.Sale).count()
        if sale_count < 20:
            created = 0
            for days_ago in range(29, -1, -1):
                # 0-3 sales per day (a few extra in the recent week)
                per_day = random.randint(0, 3) + (1 if days_ago < 7 else 0)
                for _ in range(per_day):
                    when = datetime.now() - timedelta(days=days_ago, hours=random.randint(0, 9), minutes=random.randint(0, 59))
                    emp = random.choice(employees)
                    cust = random.choice(customers) if random.random() < 0.8 else None
                    n_items = random.randint(1, 4)
                    chosen = random.sample(products, min(n_items, len(products)))

                    sale = models.Sale(
                        employee_id=emp.user_id,
                        customer_id=cust.customer_id if cust else None,
                        payment_method=random.choice(PAYMENTS),
                        date=when.date(),
                        time=when.time(),
                    )
                    revenue = profit = 0.0
                    for p in chosen:
                        qty = random.randint(1, 3)
                        if p.stock_quantity < qty:
                            continue  # respect available stock
                        p.stock_quantity -= qty
                        revenue += p.retail_price * qty
                        profit += (p.retail_price - p.cost_price) * qty
                        sale.items.append(models.SaleItem(
                            product_id=p.product_id,
                            quantity=qty,
                            retail_price_at_sale=p.retail_price,
                            cost_price_at_sale=p.cost_price,
                        ))
                    if not sale.items:
                        continue  # nothing could be sold (out of stock)
                    sale.total_revenue = round(revenue, 2)
                    sale.total_profit = round(profit, 2)
                    db.add(sale)
                    created += 1
            db.commit()
            print(f"[+] {created} sales spread across the last 30 days (had {sale_count})")
        else:
            print(f"[=] Sales already plentiful ({sale_count}) — skipping")

        # ---------------- Summary ----------------
        print("\n--- Seed summary ---")
        print(f"Owners:    {db.query(models.Owner).count()}")
        print(f"Employees: {db.query(models.Employee).count()}")
        print(f"Products:  {db.query(models.Product).count()}")
        print(f"Customers: {db.query(models.Customer).count()}")
        print(f"Sales:     {db.query(models.Sale).count()}")
        print("\nLogin credentials:")
        print(f"  Owner    -> phone {OWNER['phone_number']}  password {OWNER['password']}  (store: {STORE_NAME})")
        for e in EMPLOYEES:
            print(f"  Employee -> phone {e['phone_number']}  password {e['password']}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
