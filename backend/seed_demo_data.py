"""
Demo data seeder — populates a realistic store so the Analytics page
(month / week / day views, employee race, top products) has proper data
to chew on.

Creates (idempotent — safe to run twice; --force wipes and reseeds):
  Owner   : Edwin Zaman          login phone: "01711111100"  pw: shongkho123
  Staff   : 7 employees of Edwin — Rahim, Karim, Sumi, Tanvir,
            Nusrat, Jahangir, Mim (skill spread -> a real race with
            a clear leader, a mid-pack and trainees; Sumi slumps this
            week; Mim is AWAY the last 3 days)
  Products: 24 grocery items — clear best-sellers, seasonal swings
            (cold/energy drinks up in summer, chocolate in winter),
            slow movers, and Ghee 500g as DEAD STOCK (no sales in the
            last 14 days, 500 units on the shelf)
  Sales   : ~8 months of transactions ending TODAY, with:
            - weekday/weekend pattern (weekends busier)
            - lunch (12-14h) + evening (18-21h) peaks
            - a month-over-month upward trend (revenue grows)
            - TODAY is boosted ~30% so chatbot testing on "today"
              questions always has real data to answer with

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
import time as _time
import urllib.request
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models  # noqa: E402
from database import get_engine, get_session_factory, init_db, BASE_DIR  # noqa: E402
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
    {"name": "Nusrat Jahan", "phone": "01711111105", "position": "Senior Salesperson", "salary": 17000, "skill": 0.85, "base": 11},
    {"name": "Jahangir Alam", "phone": "01711111106", "position": "Salesperson",       "salary": 12000, "skill": 0.55, "base": 6},
    {"name": "Mim Rahman",   "phone": "01711111107", "position": "Trainee",            "salary": 8500,  "skill": 0.35, "base": 4},
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
    # --- second shelf: more spread for top-product rankings ---
    {"name": "Soybean Oil 5L",      "cost": 720, "retail": 890, "category": "Cooking",   "pop": 0.88, "peak": None},
    {"name": "Milk Powder 500g",    "cost": 260, "retail": 330, "category": "Staples",   "pop": 0.78, "peak": None},
    {"name": "Ghee 500g",           "cost": 480, "retail": 620, "category": "Cooking",   "pop": 0.15, "peak": None,
     "quiet_days": 14},   # DEAD STOCK: nothing sells in the last 14 days
    {"name": "Rolled Oats 400g",    "cost": 130, "retail": 175, "category": "Staples",   "pop": 0.50, "peak": None},
    {"name": "Turmeric Powder 200g","cost": 45,  "retail": 70,  "category": "Cooking",   "pop": 0.66, "peak": None},
    {"name": "Chili Powder 200g",   "cost": 60,  "retail": 90,  "category": "Cooking",   "pop": 0.70, "peak": None},
    {"name": "Coriander Seeds 100g","cost": 35,  "retail": 55,  "category": "Cooking",   "pop": 0.30, "peak": None},
    {"name": "Puffed Rice 500g",    "cost": 40,  "retail": 60,  "category": "Snacks",    "pop": 0.60, "peak": None},
    {"name": "Chanachur 350g",      "cost": 55,  "retail": 85,  "category": "Snacks",    "pop": 0.72, "peak": None},
    {"name": "Chocolate Bar",       "cost": 30,  "retail": 50,  "category": "Snacks",    "pop": 0.68, "peak": 12},  # peaks Dec-Feb
    {"name": "Energy Drink 250ml",  "cost": 55,  "retail": 85,  "category": "Beverages", "pop": 0.75, "peak": 4},   # peaks Apr-Aug
    {"name": "Mineral Water 1L",    "cost": 12,  "retail": 20,  "category": "Beverages", "pop": 0.90, "peak": None},
]

# -----------------------------------------------------------------
# Portrait photos: fetched once into backend/static/avatars/ and
# referenced by /static URL, so the demo works offline afterwards.
# Falls back to the SVG-initial avatars when there is no internet.
# -----------------------------------------------------------------
PORTRAITS = {
    # slug: (source URL, fallback initial, fallback color index)
    "edwin":    ("https://randomuser.me/api/portraits/men/32.jpg", "E", 0),
    "rahim":    ("https://randomuser.me/api/portraits/men/75.jpg", "R", 1),
    "karim":    ("https://randomuser.me/api/portraits/men/41.jpg", "K", 2),
    "sumi":     ("https://randomuser.me/api/portraits/women/65.jpg", "S", 3),
    "tanvir":   ("https://randomuser.me/api/portraits/men/22.jpg", "T", 4),
    "nusrat":   ("https://randomuser.me/api/portraits/women/44.jpg", "N", 0),
    "jahangir": ("https://randomuser.me/api/portraits/men/68.jpg", "J", 1),
    "mim":      ("https://randomuser.me/api/portraits/women/68.jpg", "M", 2),
}

AVATAR_DIR = os.path.join(BASE_DIR, "static", "avatars")
PRODUCT_IMG_DIR = os.path.join(BASE_DIR, "static", "products")

# Per-product photo source: a Wikimedia Commons search term. The best
# JPEG/PNG hit is downloaded once into backend/static/products/ and the
# product.photo points at the /static URL. Falls back to a generated
# category-colored tile when offline or when nothing sensible is found.
PRODUCT_PHOTOS = {
    "Mustard Oil 1L":       "mustard oil bottle",
    "Miniket Rice 5kg":     "white rice",
    "Sugar 1kg":            "sugar",
    "Atta 2kg":             "wheat flour",
    "Lentils 1kg":          "lentils",
    "Cold Drink 250ml":     "soda bottle",
    "Mango Juice 1L":       "mango juice",
    "Tea Leaves 200g":      "tea leaves",
    "Instant Noodles":      "instant noodles",
    "Biscuits (family)":    "biscuits",
    "Soap Bar":             "soap bar",
    "Shampoo Sachet x12":   "shampoo bottle",
    "Soybean Oil 5L":       "soybean oil",
    "Milk Powder 500g":     "milk powder",
    "Ghee 500g":            "ghee",
    "Rolled Oats 400g":     "rolled oats",
    "Turmeric Powder 200g": "turmeric powder",
    "Chili Powder 200g":    "chili powder",
    "Coriander Seeds 100g": "coriander seeds",
    "Puffed Rice 500g":     "puffed rice",
    "Chanachur 350g":       "snack mix",
    "Chocolate Bar":        "chocolate bar",
    "Energy Drink 250ml":   "energy drink",
    "Mineral Water 1L":     "mineral water bottle",
}

# Category-colored fallback tiles (used when a download fails offline)
CATEGORY_COLORS = {
    "Cooking":   "#c2410c",
    "Staples":   "#a16207",
    "Beverages": "#0e7490",
    "Snacks":    "#9d174d",
    "Care":      "#4d7c0f",
}


def _slugify(name: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    return "-".join(part for part in out.split("-") if part)


def _valid_image(path: str) -> bool:
    """Heuristic: real JPEG/PNG bytes, big enough to be a photo."""
    try:
        if os.path.getsize(path) < 2000:
            return False
        with open(path, "rb") as f:
            head = f.read(8)
        return head[:2] == b"\xff\xd8" or head[:4] == b"\x89PNG"
    except OSError:
        return False


def _fallback_tile(name: str, category: str) -> str:
    """Category-colored SVG tile with the product initial (offline path)."""
    color = CATEGORY_COLORS.get(category or "", "#1f7263")
    initial = name.strip()[0].upper()
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='480' height='480'>"
        f"<rect width='480' height='480' fill='{color}'/>"
        f"<text x='240' y='305' font-family='Arial' font-size='220' "
        f"fill='white' text-anchor='middle' font-weight='bold'>{initial}</text>"
        f"</svg>"
    )
    return "data:image/svg+xml;utf8," + svg.replace("<", "%3C").replace(">", "%3E").replace("#", "%23").replace(" ", "%20")


def _commons_image_url(term: str, width: int = 480):
    """Best JPEG/PNG thumbnail URL from a Wikimedia Commons search."""
    import json
    import urllib.parse

    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": "6", "gsrsearch": term, "gsrlimit": "4",
        "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": str(width),
    })
    url = f"https://commons.wikimedia.org/w/api.php?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "ShongkhoDemoSeeder/1.0 (demo data)"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    for page in (data.get("query") or {}).get("pages", {}).values():
        for info in page.get("imageinfo", []):
            if info.get("mime") in ("image/jpeg", "image/png"):
                return info.get("thumburl") or info.get("url")
    return None


def _refresh_product_photos(db) -> None:
    """
    Give every product a photo: search Wikimedia Commons once, cache the
    download in static/products/, and point products.photo at the /static
    URL. Falls back to a generated category-colored tile when the network
    is unavailable or the search finds nothing usable.
    """
    os.makedirs(PRODUCT_IMG_DIR, exist_ok=True)
    updated = real = 0
    for row in db.query(models.Product).all():
        if row.photo and str(row.photo).startswith("/static/products/"):
            continue  # already has a seeded photo
        term = PRODUCT_PHOTOS.get(row.product_name)
        slug = _slugify(row.product_name)
        dest = os.path.join(PRODUCT_IMG_DIR, f"{slug}.jpg")
        # a cached file that isn't a real image (error page etc.) gets retried
        if os.path.exists(dest) and not _valid_image(dest):
            os.remove(dest)
        if term and not os.path.exists(dest):
            try:
                src = _commons_image_url(term)
                _time.sleep(1.0)  # be polite to the Commons API (rate limits)
                if src:
                    req = urllib.request.Request(
                        src, headers={"User-Agent": "ShongkhoDemoSeeder/1.0 (demo data)"},
                    )
                    with urllib.request.urlopen(req, timeout=25) as resp, open(dest, "wb") as out:
                        out.write(resp.read())
                    _time.sleep(1.0)
            except Exception as exc:  # noqa: BLE001 — offline must not crash seeding
                print(f"  photo unavailable for {row.product_name} ({exc.__class__.__name__})")
        if os.path.exists(dest) and _valid_image(dest):
            row.photo = f"/static/products/{slug}.jpg"
            real += 1
        else:
            row.photo = _fallback_tile(row.product_name, row.category)
        updated += 1
    db.commit()
    print(f"Product photos: {updated} assigned ({real} real downloads, {updated - real} fallback tiles)")


def _ensure_portraits() -> dict:
    """Download portraits once; return {slug: /static URL or None}."""
    os.makedirs(AVATAR_DIR, exist_ok=True)
    urls = {}
    for slug, (source, _initial, _idx) in PORTRAITS.items():
        dest = os.path.join(AVATAR_DIR, f"{slug}.jpg")
        if not os.path.exists(dest):
            try:
                req = urllib.request.Request(
                    source, headers={"User-Agent": "Mozilla/5.0 (Shongkho demo seeder)"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp, open(dest, "wb") as out:
                    out.write(resp.read())
                print(f"  portrait downloaded: {slug}.jpg")
            except Exception as exc:  # offline / blocked -> fall back
                print(f"  portrait unavailable for {slug} ({exc.__class__.__name__}) — using initials avatar")
                dest = None
        urls[slug] = f"/static/avatars/{slug}.jpg" if dest else None
    return urls


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

    owner_row = db.query(models.User).filter(models.User.phone_number == "01711111100").first()

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
                      models.AnalysisRun, models.ChatMessage,
                      models.AssistantMessage):  # stale chat history too
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
    # -----------------------------------------------------------
    # People (+ portrait photos where the download succeeded)
    # -----------------------------------------------------------
    photos = _ensure_portraits()

    def photo_or_initial(slug, name, idx):
        return photos.get(slug) or svg_avatar(name, idx)

    edwin, _ = _ensure_user(
        db, name="Edwin Zaman", phone="01711111100", role="owner",
        password=PASSWORD, photo=photo_or_initial("edwin", "Edwin", 0),
    )
    staff = []
    for i, spec in enumerate(EMPLOYEES):
        slug = spec["name"].split()[0].lower()
        emp, _ = _ensure_user(
            db, name=spec["name"], phone=spec["phone"], role="employee",
            password=PASSWORD, position=spec["position"], salary=spec["salary"],
            employer_id=edwin.user_id,
            photo=photo_or_initial(slug, spec["name"], i + 1),
        )
        staff.append((emp, spec))
    print(f"Owner: Edwin Zaman (login: 01711111100 / {PASSWORD})")
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

    # Product photos: real keyword-matched downloads with offline fallback
    _refresh_product_photos(db)

    # -----------------------------------------------------------
    # Customers: a regular pool + walk-ins
    # -----------------------------------------------------------
    customers = []
    for i in range(12):
        # 11 chars exactly and distinct from the walk-in (01800000000):
        # the old f"018{i:09d}"[:11] collapsed ALL of these onto one phone.
        phone = f"0182{i:07d}"
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
    # Sales: ~8 months ending today
    # -----------------------------------------------------------
    today = date.today()
    start = today - timedelta(days=239)          # ~8 months of history
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
        # TODAY gets a ~30% boost: chatbot questions about "today" must
        # always have real data to answer with, whatever the hour.
        day_scale = (1.35 if weekend else 1.0) * month_ratio \
            * (1.3 if d == today else 1.0)

        for emp, spec in staff:
            # Everyone works most days; trainee misses more days.
            attendance = 0.95 if spec["skill"] > 0.5 else 0.8
            if rng.random() > attendance:
                continue
            # Mim is AWAY the last 3 days (an attendance gap the
            # employee race and the chatbot can point at).
            if spec["name"].startswith("Mim") and (today - d).days < 3:
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
                    # Dead stock: nothing sells in the last N days —
                    # the chatbot should flag it as a slow mover.
                    if pspec.get("quiet_days") \
                            and (today - d).days < pspec["quiet_days"]:
                        continue
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

    # -----------------------------------------------------------
    # Group chat: a realistic team conversation (backdated)
    # -----------------------------------------------------------
    already_chatted = db.query(models.ChatMessage).filter(
        models.ChatMessage.owner_id == edwin.user_id
    ).count()
    if force or already_chatted == 0:
        print("Seeding group chat…")
        by_name = {emp.name: emp for emp, _ in staff}
        rahim = by_name["Rahim Uddin"]
        karim = by_name["Karim Ahmed"]
        sumi = by_name["Sumi Akter"]
        tanvir = by_name["Tanvir Hasan"]
        nusrat = by_name["Nusrat Jahan"]
        jahangir = by_name["Jahangir Alam"]
        mim = by_name["Mim Rahman"]

        def _msg(sender, body, days_ago, hour, minute=0, reply_to=None):
            msg = models.ChatMessage(
                owner_id=edwin.user_id,
                sender_id=sender.user_id,
                body=body,
                reply_to_id=reply_to.message_id if reply_to else None,
                date=today - timedelta(days=days_ago),
                time=time(hour, minute),
            )
            db.add(msg)
            db.flush()  # assigns message_id so replies can reference it
            return msg

        m1 = _msg(edwin, "Good morning everyone. Weekly target is live — let's push the Cold Drinks combo this week.", 6, 9, 12)
        m2 = _msg(rahim, "Received. Shelf 3 restocked with the combo display, boss.", 6, 9, 41)
        _msg(karim, "On it. Doing the same for the evening rush.", 6, 10, 5, reply_to=m2)
        m4 = _msg(nusrat, "Two bulk orders of Soybean Oil 5L today — added to the customer register.", 5, 12, 22)
        _msg(edwin, "Great — that's the highest-margin item, keep it moving.", 5, 12, 40, reply_to=m4)
        m6 = _msg(sumi, "Card machine is acting up again at my counter.", 4, 16, 5)
        _msg(edwin, "Restarted it from the office tablet. Tell me if it repeats.", 4, 16, 20, reply_to=m6)
        _msg(tanvir, "Noted the new barcode for Mineral Water 1L — scanning fine now.", 3, 11, 15)
        m9 = _msg(mim, "I'll be away for 3 days starting tomorrow, sir. Family matter.", 3, 19, 30)
        _msg(edwin, "Take care, Mim. We'll manage the till.", 3, 19, 44, reply_to=m9)
        m11 = _msg(jahangir, "Going to be 30 min late tomorrow, bus issue.", 2, 20, 45)
        _msg(edwin, "Okay — Karim covers the opening hour.", 2, 21, 2, reply_to=m11)
        m13 = _msg(rahim, "Price of Sugar 1kg went up at the distributor. Should we adjust retail?", 1, 10, 5)
        _msg(edwin, "Hold at 145 for now. I'm comparing suppliers this weekend.", 1, 10, 30, reply_to=m13)
        _msg(sumi, "Big chocolate order from the school canteen this afternoon!", 1, 15, 40)
        _msg(edwin, "Excellent — that's the seasonal push working. See you all tomorrow.", 0, 21, 30)
        db.commit()
        print(f"  {len(by_name) + 1} participants, 15 messages seeded")

    # -----------------------------------------------------------
    # Protik assistant history for the owner (grounded Part-B turns)
    # -----------------------------------------------------------
    already_assistant = db.query(models.AssistantMessage).filter(
        models.AssistantMessage.owner_id == edwin.user_id
    ).count()
    if force or already_assistant == 0:
        print("Seeding Protik assistant history…")
        turns = [
            ("user", "How did we do today?", None),
            ("assistant",
             "Today is tracking strong: ৳18,420 revenue across 46 transactions, up 31% vs the last four Fridays. "
             "Cold Drink 250ml and Miniket Rice 5kg lead the basket mix, and the evening peak (6-9pm) contributed "
             "44% of today's revenue.",
             [{"tool": "get_revenue", "args": {"period": "day"}}]),
            ("user", "Who is selling the most this week?", None),
            ("assistant",
             "Rahim Uddin leads the week with ৳31,200 revenue across 78 transactions, ahead of Nusrat Jahan "
             "(৳26,850). Sumi Akter is well below her usual pace — her revenue is down roughly 60% against her "
             "four-week average.",
             [{"tool": "get_employee_ranking", "args": {"period": "week", "metric": "revenue"}}]),
            ("user", "Is Ghee 500g selling at all?", None),
            ("assistant",
             "No sales of Ghee 500g in the last 14 days while 500 units sit on the shelf — your clearest "
             "dead-stock item. Consider bundling it with Mustard Oil 1L or giving it a front-shelf spot this week.",
             [{"tool": "get_dead_stock", "args": {"days": 14}}]),
        ]
        now = datetime.utcnow()
        for i, (role, message, tool_calls) in enumerate(turns):
            db.add(models.AssistantMessage(
                owner_id=edwin.user_id,
                role=role,
                message=message,
                tool_calls=tool_calls,
                created_at=now - timedelta(days=1, minutes=(len(turns) - i) * 7),
            ))
        db.commit()
        print("  6 assistant turns (3 questions, 3 grounded answers)")

    print(f"Sales created: {made} across {days} days "
          f"({start.isoformat()} -> {today.isoformat()})")
    print("Done. Log in as 01711111100 / shongkho123 and open Analytics.")
    print("Chatbot test questions this data answers well:")
    print("  - Who is selling the most today? / this week?")
    print("  - Which product should we push more this week?")
    print("  - How is Sumi doing lately? (visible slump)")
    print("  - Is Ghee 500g selling at all? (dead stock, no sales in 14d)")
    print("  - How did we do today? / this week? / this month?")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo data for Shongkho analytics")
    parser.add_argument("--force", action="store_true", help="wipe existing data and reseed")
    args = parser.parse_args()
    seed(force=args.force)
