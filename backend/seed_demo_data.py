"""
Demo data seeder — populates a realistic store so the Analytics page
(month / week / day views, employee race, top products) has proper data
to chew on.

Creates (idempotent — safe to run twice):
  Owner   : Edwin Zaman          login phone: "edwinzaman"  pw: shongkho123
  Staff   : Rahim, Karim, Sumi, Tanvir (employees of Edwin)
  Products: 12 grocery items with photos
  Sales   : ~4 months of transactions ending TODAY, with:
            - weekday/weekend pattern (weekends busier)
            - lunch (12-14h) + evening (18-21h) peaks
            - per-employee skill/personality so the race is interesting
            - a month-over-month upward trend (revenue grows)
            - one employee with a slump this week (visible in deltas)
            - seasonal product swings (cold drinks up, winter items down)

Run it:
    cd backend
    python seed_demo_data.py          # add --force to WIPE and reseed

All financial facts (revenue/profit) are computed by the same rules as
the real checkout (services.create_sale), so the analytics snapshots
match what production would record.
"""
import argparse
import random
import sys
import os
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models  # noqa: E402
from database import get_engine, get_session_factory, init_db  # noqa: E402
from services import hash_password  # noqa: E402

PASSWORD = "shongkho123"

# ---------------------------------------------------------------
# Deterministic randomness: every reseed produces the same store
# ---------------------------------------------------------------
rng = random.Random(20260923)

# ---------------------------------------------------------------
# Cast: employees with distinct skill -> the race tells a story
# ---------------------------------------------------------------
EMPLOYEES = [
    # (name, phone, position, salary, skill 0..1, base_daily_sales)
    {"name": "Rahim Uddin",  "phone": "01711111101", "position": "Senior Salesperson", "salary": 18000, "skill": 0.95, "base": 12},
    {"name": "Karim Ahmed",  "phone": "01711111102", "position": "Salesperson",        "salary": 14000, "skill": 0.75, "base": 9},
    {"name": "Sumi Akter",   "phone": "01711111103", "position": "Salesperson",        "salary": 13000, "skill": 0.60, "base": 7},
    {"name": "Tanvir Hasan", "phone": "01711111104", "position": "Trainee",            "salary": 9000,  "skill": 0.40, "base": 5},
]

# ---------------------------------------------------------------
# Products: cost/retail spread so margins vary (interesting rankings)
# ---------------------------------------------------------------
PRODUCTS = [
    # (name, cost, retail, category, base_popularity 0..1, seasonal peak month or None)
    {"name": "Mustard Oil 1L",      "cost": 240, "retail": 320, "category": "Cooking",   "pop": 0.9, "peak": None},
    {"name": "Miniket Rice 5kg",    "cost": 380, "retail": 460, "category": "Staples",   "pop": 0.85, "peak": None},
    {"name": "Sugar 1kg",           "cost": 110, "retail": 145, "category": "Staples",   "pop": 0.8, "peak": None},
    {"name": "Atta 2kg",            "cost": 95,  "retail": 130, "category": "Staples",   "pop": 0.7, "peak": None},
    {"name": "Lentils 1kg",         "cost": 130, "retail": 175, "category": "Staples",   "pop": 0.75, "peak": None},
    {"name": "Cold Drink 250ml",    "cost": 18,  "retail": 30,  "category": "Beverages", "pop": 0.95, "peak": 4},   # peaks Apr-Aug
    {"name": "Mango Juice 1L",      "cost": 120, "retail": 170, "category": "Beverages", "pop": 0.6, "peak": 5},   # peaks May-Jul
    {"name": "Tea Leaves 200g",     "cost": 150, "retail": 210, "category": "Beverages", "pop": 0.8, "peak": 12},  # peaks Nov-Feb
    {"name": "Instant Noodles",     "cost": 25,  "retail": 40,  "category": "Snacks",    "pop": 0.9, "peak": None},
    {"name": "Biscuits (family)",   "cost": 55,  "retail": 80,  "category": "Snacks",    "pop": 0.85, "peak": None},
    {"name": "Soap Bar",            "cost": 35,  "retail": 55,  "category": "Care",      "pop": 0.7, "peak": None},
    {"name": "Shampoo Sachet x12",  "cost": 90,  "retail": 130, "category": "Care",      "pop": 0.65, "peak": None},
]

# SVG avatars: tiny data-URIs with distinct bg colors + initials,
# seeded into users.photo so EVERY page (navbar, race, staff) shows them.
AVATAR_COLORS = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed"]


def svg_avatar(name: str, idx: int) -> str:
    initial = name.strip()[0].upper()
    color = AVATAR_COLORS[idx % len(AVATAR_COLORS)]
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='96' height='96'>"
        f"<rect width='96' height='96' rx='48' fill='{color}'/>"
        f"<text x='48' y='62' font-family='Arial' font-size='40' "
        f"fill='white' text-anchor='middle' font-weight='bold'>{initial}</text>"
        f"</svg>"
    )
    return "data:image/svg+xml;utf8," + svg.replace("<", "%3C").replace(">", "%3E").replace("#", "%23").replace(" ", "%20")


def _ensure_user(db, *, name, phone, role, password, position=None,
                 salary=None, employer_id=None, photo=None):
    """Create-or-return a user by phone number (login key)."""
    existing = db.query(models.User).filter(models.User.phone_number == phone).first()
    if existing:
        return existing, False
    # Joined-table inheritance: create the SUBCLASS directly — SQLAlchemy
    # splits it into users + owners/employees rows itself.
    if role == "owner":
        user = models.Owner(
            name=name, phone_number=phone, password=hash_password(password),
            user_type="owner", photo=photo, store_name="Shongkho Demo Store",
        )
    else:
        user = models.Employee(
            name=name, phone_number=phone, password=hash_password(password),
            user_type="employee", photo=photo, position=position,
            salary=salary, employer_id=employer_id,
            date_appointed=date.today() - timedelta(days=200),
        )
    db.add(user)
    db.flush()
    return user, True


def seed(force: bool = False) -> None:
    init_db()
    engine = get_engine()
    Session = get_session_factory()
    db = Session()

    owner_row = db.query(models.User).filter(models.User.phone_number == "edwinzaman").first()

    if owner_row and not force:
        sales_count = db.query(models.Sale).filter(
            models.Sale.employee_id.in_(
                [u.user_id for u in db.query(models.User).filter(models.User.user_type == "employee")]
            )
        ).count()
        if sales_count > 0:
            print("Demo data already present — nothing to do (use --force to wipe & reseed).")
            db.close()
            return
        # Owner exists but no sales: continue and backfill sales only.
        print("Owner exists but no sales — backfilling sales...")

    if force:
        print("Wiping existing demo data (--force)...")
        # children first
        for model in (models.SaleItem, models.Sale, models.AnalyticsSnapshot,
                      models.AnalysisRun, models.ChatMessage):
            db.query(model).delete()
        db.query(models.Product).delete()
        db.query(models.Customer).delete()
        db.query(models.Employee).delete()
        db.query(models.Owner).delete()
        db.query(models.User).delete()
        db.commit()

    # -----------------------------------------------------------
    # People
    # -----------------------------------------------------------
    edwin, _ = _ensure_user(
        db, name="Edwin Zaman", phone="edwinzaman", role="owner",
        password=PASSWORD, photo=svg_avatar("Edwin", 0),
    )
    staff = []
    for i, spec in enumerate(EMPLOYEES):
        emp, _ = _ensure_user(
            db, name=spec["name"], phone=spec["phone"], role="employee",
            password=PASSWORD, position=spec["position"], salary=spec["salary"],
            employer_id=edwin.user_id, photo=svg_avatar(spec["name"], i + 1),
        )
        staff.append((emp, spec))
    print(f"Owner: Edwin Zaman (login: edwinzaman / {PASSWORD})")
    for emp, _ in staff:
        print(f"  Employee: {emp.name} ({emp.phone_number})")

    # -----------------------------------------------------------
    # Products
    # -----------------------------------------------------------
    products = []
    for spec in PRODUCTS:
        row = db.query(models.Product).filter(models.Product.product_name == spec["name"]).first()
        if not row:
            row = models.Product(
                product_name=spec["name"], cost_price=spec["cost"],
                retail_price=spec["retail"], stock_quantity=500,
                category=spec["category"], supplier_name="Demo Supplier",
                date=date.today() - timedelta(days=200),
            )
            db.add(row)
            db.flush()
        products.append((row, spec))
    print(f"Products: {len(products)}")

    # -----------------------------------------------------------
    # Customers: a regular pool + walk-ins
    # -----------------------------------------------------------
    customers = []
    for i in range(12):
        phone = f"018{i:09d}"[:11]
        row = db.query(models.Customer).filter(models.Customer.phone_number == phone).first()
        if not row:
            row = models.Customer(
                name=f"Customer {i + 1}", phone_number=phone,
            )
            db.add(row)
            db.flush()
        customers.append(row)
    walkin = db.query(models.Customer).filter(models.Customer.phone_number == "01800000000").first()
    if not walkin:
        walkin = models.Customer(name="Walk-in", phone_number="01800000000")
        db.add(walkin)
        db.flush()
    customers.append(walkin)

    # -----------------------------------------------------------
    # Sales: ~4 months ending today
    # -----------------------------------------------------------
    today = date.today()
    start = today - timedelta(days=118)          # ~4 months of history
    days = (today - start).days
    month_ratio = 1.0                            # month-over-month growth factor

    made = 0
    for day_offset in range(days + 1):           # inclusive: seed TODAY too
        d = start + timedelta(days=day_offset)
        progress = day_offset / max(days - 1, 1)  # 0..1 across the window
        dow = d.weekday()
        weekend = dow >= 5

        # Month-over-month growth: from ~0.75x to ~1.25x across the window.
        month_ratio = 0.75 + 0.5 * progress
        day_scale = (1.35 if weekend else 1.0) * month_ratio

        for emp, spec in staff:
            # Everyone works most days; trainee misses more days.
            attendance = 0.95 if spec["skill"] > 0.5 else 0.8
            if rng.random() > attendance:
                continue

            # Sumi's slump: this week she sells far below her baseline.
            in_slump_week = (
                spec["name"].startswith("Sumi")
                and (today - d).days <= 7
            )

            n_sales = spec["base"] * day_scale * rng.uniform(0.7, 1.3)
            if in_slump_week:
                n_sales *= 0.35  # visible collapse in this week's race
            count = max(1, int(round(n_sales)))

            for _ in range(count):
                # Peaks at lunch (12-14) and evening (18-21).
                hour = rng.choices(
                    [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
                    weights=[2, 3, 5, 8, 8, 4, 3, 4, 6, 9, 8, 6, 3],
                )[0]
                when = datetime.combine(d, time(hour, rng.randint(0, 59)))

                # 1-3 distinct products per ticket.
                picked = rng.sample(products, k=min(len(products), rng.randint(1, 3)))
                revenue = profit = 0.0
                items = []
                for prow, pspec in picked:
                    qty = 1
                    if pspec["pop"] > 0.8 and rng.random() < 0.5:
                        qty = rng.randint(2, 5)  # staples sell in multiples
                    # Seasonal swing: hot months favor cold drinks etc.
                    seasonal = 1.0
                    if pspec["peak"] is not None:
                        off = (d.month - pspec["peak"]) % 12
                        seasonal = 1.6 if off <= 2 else (0.6 if off >= 8 else 1.0)
                    if rng.random() > pspec["pop"] * seasonal:
                        continue
                    revenue += prow.retail_price * qty
                    profit += (prow.retail_price - prow.cost_price) * qty
                    items.append((prow.product_id, qty,
                                  prow.retail_price, prow.cost_price))
                if not items:
                    continue

                sale = models.Sale(
                    employee_id=emp.user_id,
                    customer_id=rng.choice(customers).customer_id,
                    payment_method=rng.choice(["cash", "cash", "cash", "bkash", "card"]),
                    total_revenue=revenue,
                    total_profit=profit,
                    date=d,
                    time=when.time(),
                )
                for pid, qty, rp, cp in items:
                    sale.items.append(models.SaleItem(
                        product_id=pid, quantity=qty,
                        retail_price_at_sale=rp, cost_price_at_sale=cp,
                    ))
                db.add(sale)
                made += 1

        # Commit per day keeps the transaction small.
        if day_offset % 15 == 14:
            db.commit()
    db.commit()
    print(f"Sales created: {made} across {days} days "
          f"({start.isoformat()} -> {today.isoformat()})")
    print("Done. Log in as edwinzaman / shongkho123 and open Analytics.")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo data for Shongkho analytics")
    parser.add_argument("--force", action="store_true", help="wipe existing data and reseed")
    args = parser.parse_args()
    seed(force=args.force)
