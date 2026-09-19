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

OWNER = {"name": "Rahim Store Owner", "phone_number": "01700000001", "password": "owner123"}

EMPLOYEES = [
    {"name": "Karim Uddin", "phone_number": "01700000002", "password": "emp123", "position": "Cashier", "salary": 15000},
    {"name": "Sadia Islam", "phone_number": "01700000003", "password": "emp123", "position": "Sales Associate", "salary": 13000},
]

PRODUCTS = [
    {"product_name": "Pran Chola Dal 1kg",      "cost_price": 95.0,  "retail_price": 120.0, "stock_quantity": 60,  "category": "Grocery",     "supplier_name": "Pran-RFL"},
    {"product_name": "Miniket Rice 5kg",        "cost_price": 340.0, "retail_price": 410.0, "stock_quantity": 35,  "category": "Grocery",     "supplier_name": "City Group"},
    {"product_name": "Teer Soybean Oil 1L",     "cost_price": 150.0, "retail_price": 175.0, "stock_quantity": 48,  "category": "Grocery",     "supplier_name": "City Group"},
    {"product_name": "Fresh Sugar 1kg",         "cost_price": 105.0, "retail_price": 130.0, "stock_quantity": 40,  "category": "Grocery",     "supplier_name": "Fresh Foods"},
    {"product_name": "Coca-Cola 1.25L",         "cost_price": 75.0,  "retail_price": 90.0,  "stock_quantity": 72,  "category": "Beverages",   "supplier_name": "CBC Distributors"},
    {"product_name": "Pran Mango Juice 1L",     "cost_price": 95.0,  "retail_price": 115.0, "stock_quantity": 30,  "category": "Beverages",   "supplier_name": "Pran-RFL"},
    {"product_name": "Fu Wang Noodles 4-pack",  "cost_price": 55.0,  "retail_price": 70.0,  "stock_quantity": 80,  "category": "Snacks",      "supplier_name": "Fu-Wang"},
    {"product_name": "Mr. Twist Chips",         "cost_price": 12.0,  "retail_price": 20.0,  "stock_quantity": 120, "category": "Snacks",      "supplier_name": "Pran-RFL"},
    {"product_name": "Lux Soap 100g",           "cost_price": 45.0,  "retail_price": 60.0,  "stock_quantity": 65,  "category": "Care",        "supplier_name": "Unilever"},
    {"product_name": "Closeup Toothpaste 100g", "cost_price": 110.0, "retail_price": 140.0, "stock_quantity": 45,  "category": "Care",        "supplier_name": "Unilever"},
    {"product_name": "Harpic Toilet Cleaner",   "cost_price": 130.0, "retail_price": 160.0, "stock_quantity": 4,   "category": "Household",   "supplier_name": "Reckitt"},
    {"product_name": "Fresh Milk Powder 500g",  "cost_price": 320.0, "retail_price": 375.0, "stock_quantity": 3,   "category": "Grocery",     "supplier_name": "Fresh Foods"},
]

CUSTOMERS = [
    {"name": "Abdul Karim",   "phone_number": "01810000001"},
    {"name": "Nusrat Jahan",  "phone_number": "01810000002"},
    {"name": "Tanvir Hasan",  "phone_number": "01810000003"},
    {"name": "Mitu Akter",    "phone_number": "01810000004"},
    {"name": "Jahangir Alam", "phone_number": "01810000005"},
]

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
        else:
            print(f"[=] Using existing owner: {owner.name} (ID {owner.user_id})")
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
        print(f"  Owner    -> phone 01700000001  password owner123")
        print(f"  Employee -> phone 01700000002  password emp123")
        print(f"  Employee -> phone 01700000003  password emp123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
