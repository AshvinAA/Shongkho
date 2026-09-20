"""
One-time demo setup for testing the Shongkho React frontend.

Creates:
  - Owner    "edwin" -> phone 1234567890, password owner123, store "zaman telecom"
  - Employee "adlin" -> phone 0987654321, password emp123, under edwin
  - A telecom-flavoured product catalogue + extra customers
  - ~30 days of sales history (mostly adlin, incl. today) so every dashboard,
    report, history and receipt view has data to show.

Safe to re-run: every section checks for existing rows first.
Run:  python setup_demo.py
"""
from datetime import datetime, timedelta
import random

from database import SessionLocal
import models
import services

random.seed(7)  # reproducible demo data

EDWIN = {
    "name": "edwin",
    "phone_number": "1234567890",
    "password": "owner123",
    "store_name": "zaman telecom",
}

ADLIN = {
    "name": "adlin",
    "phone_number": "0987654321",
    "password": "emp123",
    "position": "Sales Executive",
    "salary": 18000.0,
}

# zaman telecom catalogue: phones, accessories, internet gear
PRODUCTS = [
    {"product_name": "Samsung Galaxy A15",        "cost_price": 17500.0, "retail_price": 19999.0, "stock_quantity": 12, "category": "Smartphones",  "supplier_name": "Samsung BD"},
    {"product_name": "Xiaomi Redmi 13C",          "cost_price": 13500.0, "retail_price": 15499.0, "stock_quantity": 15, "category": "Smartphones",  "supplier_name": "Xiaomi BD"},
    {"product_name": "Itel S23+",                 "cost_price": 9800.0,  "retail_price": 11499.0, "stock_quantity": 18, "category": "Smartphones",  "supplier_name": "Itel BD"},
    {"product_name": "Symphony Z60",              "cost_price": 11200.0, "retail_price": 12999.0, "stock_quantity": 10, "category": "Smartphones",  "supplier_name": "Symphony"},
    {"product_name": "Anker 20W Fast Charger",    "cost_price": 950.0,   "retail_price": 1350.0,  "stock_quantity": 40, "category": "Chargers",     "supplier_name": "Anker"},
    {"product_name": "Baseus 65W GaN Charger",    "cost_price": 2100.0,  "retail_price": 2900.0,  "stock_quantity": 20, "category": "Chargers",     "supplier_name": "Baseus"},
    {"product_name": "Samsung 25W Charger",       "cost_price": 1300.0,  "retail_price": 1800.0,  "stock_quantity": 30, "category": "Chargers",     "supplier_name": "Samsung BD"},
    {"product_name": "Type-C Cable 1m (Braided)", "cost_price": 120.0,   "retail_price": 250.0,   "stock_quantity": 90, "category": "Cables",       "supplier_name": "Hoco"},
    {"product_name": "Lightning Cable 1m",        "cost_price": 150.0,   "retail_price": 300.0,   "stock_quantity": 60, "category": "Cables",       "supplier_name": "Hoco"},
    {"product_name": "JBL Tune 125TWS",           "cost_price": 3200.0,  "retail_price": 4200.0,  "stock_quantity": 14, "category": "Audio",        "supplier_name": "JBL BD"},
    {"product_name": "Xiaomi Redmi Buds 4",       "cost_price": 1800.0,  "retail_price": 2500.0,  "stock_quantity": 22, "category": "Audio",        "supplier_name": "Xiaomi BD"},
    {"product_name": "Anker Soundcore Life P2",   "cost_price": 2400.0,  "retail_price": 3300.0,  "stock_quantity": 16, "category": "Audio",        "supplier_name": "Anker"},
    {"product_name": "Power Bank 10000mAh",       "cost_price": 1450.0,  "retail_price": 1990.0,  "stock_quantity": 25, "category": "Power",        "supplier_name": "Anker"},
    {"product_name": "Power Bank 20000mAh",       "cost_price": 2600.0,  "retail_price": 3600.0,  "stock_quantity": 18, "category": "Power",        "supplier_name": "Baseus"},
    {"product_name": "TP-Link TL-WA850RE",        "cost_price": 1650.0,  "retail_price": 2200.0,  "stock_quantity": 12, "category": "Networking",   "supplier_name": "TP-Link BD"},
    {"product_name": "TP-Link Archer C24 Router", "cost_price": 2400.0,  "retail_price": 3200.0,  "stock_quantity": 9,  "category": "Networking",   "supplier_name": "TP-Link BD"},
    {"product_name": "Tempered Glass (Universal)","cost_price": 40.0,    "retail_price": 150.0,   "stock_quantity": 120,"category": "Accessories",  "supplier_name": "Local"},
    {"product_name": "Phone Case (Assorted)",     "cost_price": 70.0,    "retail_price": 220.0,   "stock_quantity": 80, "category": "Accessories",  "supplier_name": "Local"},
    {"product_name": "GP 20GB Data Pack",         "cost_price": 270.0,   "retail_price": 299.0,   "stock_quantity": 100,"category": "Recharge",     "supplier_name": "Grameenphone"},
    {"product_name": "Robi 15GB Data Pack",       "cost_price": 210.0,   "retail_price": 239.0,   "stock_quantity": 100,"category": "Recharge",     "supplier_name": "Robi"},
    {"product_name": "Airtime Top-up 100tk",      "cost_price": 98.0,    "retail_price": 100.0,   "stock_quantity": 200,"category": "Recharge",     "supplier_name": "Flexiload"},
    {"product_name": "MicroSD 64GB SanDisk",      "cost_price": 620.0,   "retail_price": 890.0,   "stock_quantity": 3,  "category": "Accessories",  "supplier_name": "SanDisk"},
    {"product_name": "USB Hub 4-Port",            "cost_price": 480.0,   "retail_price": 700.0,   "stock_quantity": 2,  "category": "Accessories",  "supplier_name": "Ugreen"},
    {"product_name": "Bluetooth Speaker Zealot S16","cost_price": 1900.0,"retail_price": 2700.0,  "stock_quantity": 10, "category": "Audio",        "supplier_name": "Zealot"},
]

CUSTOMERS = [
    {"name": "Rakib Hasan",      "phone_number": "01820000001"},
    {"name": "Sumaiya Akter",    "phone_number": "01820000002"},
    {"name": "Jahid Hossain",    "phone_number": "01820000003"},
    {"name": "Mim Chowdhury",    "phone_number": "01820000004"},
    {"name": "Tanvir Ahmed",     "phone_number": "01820000005"},
    {"name": "Nabila Karim",     "phone_number": "01820000006"},
    {"name": "Shakil Khan",      "phone_number": "01820000007"},
    {"name": "Farhana Rahman",   "phone_number": "01820000008"},
]

PAYMENTS = ["Cash", "Cash", "Cash", "bKash", "Nagad", "Card"]


def upsert_owner(db):
    owner = db.query(models.User).filter(models.User.phone_number == EDWIN["phone_number"]).first()
    if owner:
        print(f"[=] Owner already exists: {owner.name} (ID {owner.user_id})")
        if owner.user_type == "owner" and not owner.store_name:
            owner.store_name = EDWIN["store_name"]
            db.commit()
    else:
        owner = models.Owner(
            name=EDWIN["name"],
            phone_number=EDWIN["phone_number"],
            password=services.hash_password(EDWIN["password"]),
            user_type="owner",
            store_name=EDWIN["store_name"],
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        print(f"[+] Owner created: {owner.name} (ID {owner.user_id})")
    return owner


def upsert_employee(db, owner):
    emp = db.query(models.User).filter(models.User.phone_number == ADLIN["phone_number"]).first()
    if emp:
        print(f"[=] Employee already exists: {emp.name} (ID {emp.user_id})")
        if emp.user_type == "employee" and emp.employer_id != owner.user_id:
            emp.employer_id = owner.user_id
            db.commit()
    else:
        emp = models.Employee(
            name=ADLIN["name"],
            phone_number=ADLIN["phone_number"],
            password=services.hash_password(ADLIN["password"]),
            user_type="employee",
            position=ADLIN["position"],
            salary=ADLIN["salary"],
            employer_id=owner.user_id,
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)
        print(f"[+] Employee created: {emp.name} (ID {emp.user_id}, employer {owner.user_id})")
    return emp


def upsert_products(db):
    existing = {p.product_name: p for p in db.query(models.Product).all()}
    added = 0
    restocked = 0
    for p in PRODUCTS:
        if p["product_name"] not in existing:
            db.add(models.Product(**p))
            added += 1
        else:
            row = existing[p["product_name"]]
            # demo shelves sell out — restock catalogue items that ran low
            if row.stock_quantity <= 5 and p["stock_quantity"] > row.stock_quantity:
                row.stock_quantity = p["stock_quantity"]
                restocked += 1
    db.commit()
    print(f"[+] {added} new products added, {restocked} restocked ({len(PRODUCTS) - added} already present)")


def upsert_customers(db):
    existing = {c.phone_number for c in db.query(models.Customer).all()}
    added = 0
    for c in CUSTOMERS:
        if c["phone_number"] not in existing:
            db.add(models.Customer(**c))
            added += 1
    db.commit()
    print(f"[+] {added} new customers added ({len(CUSTOMERS) - added} already present)")


def make_sale(db, when, employee, products, customers, customer_idx=None):
    """Build one sale with 1-4 items, respecting available stock.

    customer_idx: round-robin index so every demo customer gets history;
    None means walk-in.
    """
    if customer_idx is not None and customers:
        cid = customers[customer_idx % len(customers)].customer_id
    elif random.random() < 0.85:
        cid = random.choice(customers).customer_id
    else:
        cid = None
    sale = models.Sale(
        employee_id=employee.user_id,
        customer_id=cid,
        payment_method=random.choice(PAYMENTS),
        date=when.date(),
        time=when.time(),
    )
    revenue = profit = 0.0
    chosen = random.sample(products, min(random.randint(1, 4), len(products)))
    for p in chosen:
        qty = random.randint(1, 2) if p.retail_price > 3000 else random.randint(1, 5)
        if p.stock_quantity < qty:
            continue
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
        return None
    sale.total_revenue = round(revenue, 2)
    sale.total_profit = round(profit, 2)
    db.add(sale)
    return sale


def seed_sales(db, owner, employee):
    """~30 days of sales; 70% by adlin so her dashboard/exports look real."""
    existing = db.query(models.Sale).filter(models.Sale.employee_id == employee.user_id).count()
    if existing >= 30:
        print(f"[=] Sales already plentiful ({existing} for adlin) — skipping")
        return

    products = db.query(models.Product).all()
    customers = db.query(models.Customer).all()
    staff = [employee, owner]
    created = 0
    now = datetime.now()

    for days_ago in range(29, -1, -1):
        per_day = random.randint(1, 3) + (2 if days_ago < 7 else 0)  # busier recent week
        for _ in range(per_day):
            when = now - timedelta(days=days_ago, hours=random.randint(0, 10), minutes=random.randint(0, 59))
            # 70% adlin, 30% edwin
            seller = employee if random.random() < 0.7 else owner
            if seller not in staff:
                seller = employee
            # round-robin customers so every demo customer has purchase history
            sale = make_sale(db, when, seller, products, customers, customer_idx=created)
            if sale:
                created += 1
    db.commit()
    print(f"[+] {created} sales spread across the last 30 days (adlin ~70%, edwin ~30%)")


def topup_history(db, owner, employee):
    """Give any demo customer without purchases 1-2 sales (idempotent)."""
    customers = db.query(models.Customer).all()
    products = db.query(models.Product).all()
    if not customers or not products:
        return
    buying = [c for c in customers if len(c.sales) == 0]
    if not buying:
        print("[=] Every customer already has purchase history")
        return
    created = 0
    now = datetime.now()
    for c in buying:
        for _ in range(random.randint(1, 2)):
            when = now - timedelta(days=random.randint(0, 25), hours=random.randint(0, 10))
            seller = employee if random.random() < 0.7 else owner
            sale = make_sale(db, when, seller, products, [c], customer_idx=0)
            if sale:
                created += 1
    db.commit()
    print(f"[+] {created} top-up sales so every customer has history")


def main():
    db = SessionLocal()
    try:
        owner = upsert_owner(db)
        emp = upsert_employee(db, owner)
        upsert_products(db)
        upsert_customers(db)
        seed_sales(db, owner, emp)
        topup_history(db, owner, emp)

        print("\n--- Demo summary ---")
        print(f"Owners:    {db.query(models.Owner).count()}")
        print(f"Employees: {db.query(models.Employee).count()}")
        print(f"Products:  {db.query(models.Product).count()}")
        print(f"Customers: {db.query(models.Customer).count()}")
        print(f"Sales:     {db.query(models.Sale).count()}")
        print("\nLogin accounts:")
        print(f"  Owner    -> phone {EDWIN['phone_number']}  password {EDWIN['password']}  (store: {EDWIN['store_name']})")
        print(f"  Employee -> phone {ADLIN['phone_number']}  password {ADLIN['password']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
