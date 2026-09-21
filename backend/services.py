"""
Business logic layer — every database mutation the API performs lives here.

Why a service layer? Route handlers stay thin: they validate input (via
schemas), check permissions (via deps), then delegate here. That keeps
each file readable and makes the rules of the system (who may do what,
what happens on failure) easy to find in one place.

Transaction discipline:
  create_sale is the only multi-step mutation; it commits once at the end
  and rolls back on ANY failure so stock is never deducted without a
  matching sale record.
"""
import bcrypt  # type: ignore
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy import func, or_

import models
import schemas

# ---------------------------------------------------------
# SECURITY & AUTHENTICATION
# ---------------------------------------------------------

# bcrypt only uses the first 72 bytes of a password; extra bytes are
# silently ignored. Truncating up front keeps hashing and checking
# consistent for very long passwords.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (returns a UTF-8 string for the DB)."""
    pwd_bytes = password.encode('utf-8')[:MAX_PASSWORD_BYTES]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time check of a password against its stored bcrypt hash."""
    pwd_bytes = plain_password.encode('utf-8')[:MAX_PASSWORD_BYTES]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode('utf-8'))


def normalize_phone(raw: str) -> str:
    """
    Standardize a phone number before storing or comparing it.

    Strips spaces/dashes and validates 10-15 digits (optionally with a
    leading +). Returns None for anything invalid so callers can raise
    a 400. Example: '+880 171-234 5678' -> '+8801712345678'.
    """
    cleaned = str(raw).replace(" ", "").replace("-", "").strip()
    digits = cleaned.lstrip("+")
    if not digits.isdigit() or not (10 <= len(digits) <= 15):
        return None
    return cleaned


def authenticate_user(db, phone_number: str, password: str):
    """Return the User whose phone+password match, or False."""
    # 1. Find the user by phone number (queries the users table; joined-
    #    table inheritance loads the right subclass automatically).
    user = db.query(models.User).filter(
        models.User.phone_number == phone_number
    ).first()

    # 2. Unknown phone -> fail. (One generic error at login time prevents
    #    account enumeration; registration gives a specific error instead.)
    if not user:
        return False

    # 3. Wrong password -> fail.
    if not verify_password(password, user.password):
        return False

    # 4. Both matched — hand the ORM user back to the caller.
    return user


# ---------------------------------------------------------
# USER & AUTH SERVICES
# ---------------------------------------------------------

def register_user(db, user_data: schemas.EmployeeCreate, creator_role: str = None):
    """
    Register a new account (owner or employee).

    Rules:
      - Owner signup: allowed publicly while NO owner exists (the first
        owner bootstraps the store). After that, only a logged-in owner
        may create more owner accounts.
      - Employee signup: MUST reference an existing owner (employer_id).
    """
    # 1. Phone numbers are unique across ALL users (login key).
    existing_user = db.query(models.User).filter(
        models.User.phone_number == user_data.phone_number
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="This phone number is already registered.")

    role = (user_data.role or 'employee').lower()

    if role == 'owner':
        # Only owners may add more owners once the first one exists.
        any_owner_exists = db.query(models.Owner).first() is not None
        if any_owner_exists and creator_role != 'owner':
            raise HTTPException(
                status_code=403,
                detail="An owner already exists. Only an owner can register another owner account.",
            )
        new_user = models.Owner(
            name=user_data.name,
            phone_number=user_data.phone_number,
            password=hash_password(user_data.password),
            address=getattr(user_data, 'address', None),
            photo=getattr(user_data, 'photo', None),
        )
    else:
        # Employees must hang off an existing owner's account.
        employer_id = getattr(user_data, 'employer_id', None)
        if not employer_id:
            raise HTTPException(
                status_code=400,
                detail="Employees must register with an existing owner ID (employer_id).",
            )
        owner = db.query(models.Owner).filter(
            models.Owner.user_id == employer_id
        ).first()
        if not owner:
            raise HTTPException(
                status_code=404,
                detail=f"Owner ID {employer_id} does not exist. Ask your store owner for their ID.",
            )

        new_user = models.Employee(
            name=user_data.name,
            phone_number=user_data.phone_number,
            password=hash_password(user_data.password),
            address=getattr(user_data, 'address', None),
            photo=getattr(user_data, 'photo', None),
            position=getattr(user_data, 'position', None),
            salary=getattr(user_data, 'salary', None),
            employer_id=employer_id,
        )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def reset_password_request(db, phone_number: str):
    """Step 1 of password reset: verify the account exists."""
    user = db.query(models.User).filter(
        models.User.phone_number == phone_number
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with that phone number.")
    return {"detail": f"Account found for {user.name}. You may now set a new password."}


def reset_password_confirm(db, phone_number: str, new_password: str):
    """Step 2 of password reset: overwrite the stored hash."""
    user = db.query(models.User).filter(
        models.User.phone_number == phone_number
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with that phone number.")

    user.password = hash_password(new_password)
    db.commit()
    return {"detail": "Password reset successful. You can now log in."}


def update_employee(db, employee_user_id: int, updates: schemas.EmployeeUpdate):
    """
    Owner-only: update an employee's info and/or role.

    Role conversion notes:
      - Owner -> Employee conversion happens through services.promote_*
        helpers (update_owner_to_employee) so employer links are set
        correctly; direct conversion here is rejected with a 400.
      - Demoting the LAST owner is impossible via /employees/{id}
        anyway (that endpoint only touches employee accounts), and
        services.delete_employee refuses owner deletion outright.
    """
    user = db.query(models.User).filter(
        models.User.user_id == employee_user_id
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = updates.model_dump(exclude_unset=True)

    # Role change is handled first, separately from plain column edits.
    new_role = data.pop("role", None)
    if new_role and new_role.lower() != user.user_type:
        new_role = new_role.lower()
        if new_role == "owner" and user.user_type == "employee":
            user = promote_employee_to_owner(db, user)
        elif new_role == "employee" and user.user_type == "owner":
            user = demote_owner_to_employee(db, user)
        else:
            raise HTTPException(status_code=400, detail="Role must be 'owner' or 'employee'")

    # Apply plain column updates that are present and non-null.
    for field in ("name", "phone_number", "position", "salary"):
        if field in data and data[field] is not None:
            setattr(user, field, data[field])

    db.commit()
    db.refresh(user)
    return user


def promote_employee_to_owner(db, employee: models.Employee) -> models.Owner:
    """
    Convert an Employee into an Owner WITHOUT touching the shared users row.

    IMPORTANT: with joined-table inheritance, ``db.delete(employee)`` would
    cascade and DELETE the parent users row (killing login, chat history
    and sale references). So we do the conversion as three surgical table
    statements instead of ORM object surgery:
      1. flip the discriminator on the users row,
      2. insert the owners child row (same primary key),
      3. delete the employees child row only.
    """
    if employee.user_type != "employee":
        raise HTTPException(status_code=400, detail="User is already an owner")

    user_id = employee.user_id
    # Drop the stale ORM object so the identity map doesn't collide with
    # the new subclass when we re-query below.
    db.expunge(employee)

    users_t = models.User.__table__
    db.execute(
        users_t.update()
        .where(users_t.c.user_id == user_id)
        .values(user_type="owner")
    )
    db.execute(models.Owner.__table__.insert().values(user_id=user_id))
    db.execute(
        models.Employee.__table__.delete().where(
            models.Employee.__table__.c.user_id == user_id
        )
    )
    db.commit()

    owner = db.query(models.Owner).filter(models.Owner.user_id == user_id).first()
    if not owner:  # defensive — should be impossible
        raise HTTPException(status_code=500, detail="Role conversion failed")
    return owner


def demote_owner_to_employee(db, owner: models.Owner, position=None, salary=None) -> models.Employee:
    """
    Convert an Owner into an Employee under the first remaining owner.
    Refuses to demote the LAST owner — a store always keeps at least one.
    Uses the same raw-table swap as promote_employee_to_owner so the
    users row (and everything referencing it) survives intact.
    """
    if owner.user_type != "owner":
        raise HTTPException(status_code=400, detail="User is already an employee")

    # Count owners excluding this one; block the demotion when it is 0.
    other_owners = db.query(models.Owner).filter(
        models.Owner.user_id != owner.user_id
    ).count()
    if other_owners == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the last owner. Register another owner first.",
        )

    employer = db.query(models.Owner).filter(
        models.Owner.user_id != owner.user_id
    ).first()

    user_id = owner.user_id
    db.expunge(owner)

    users_t = models.User.__table__
    db.execute(
        users_t.update()
        .where(users_t.c.user_id == user_id)
        .values(user_type="employee")
    )
    db.execute(
        models.Employee.__table__.insert().values(
            user_id=user_id,
            position=position,
            salary=salary,
            employer_id=employer.user_id,
        )
    )
    db.execute(
        models.Owner.__table__.delete().where(
            models.Owner.__table__.c.user_id == user_id
        )
    )
    db.commit()

    employee = db.query(models.Employee).filter(models.Employee.user_id == user_id).first()
    if not employee:  # defensive — should be impossible
        raise HTTPException(status_code=500, detail="Role conversion failed")
    return employee


def update_profile(db, user_id: int, updates: schemas.ProfileUpdate):
    """
    Self-service: a logged-in user edits their own profile (name, phone,
    photo). Phone changes are normalized and checked for duplicates
    because the phone number is the login key.
    """
    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")

    data = updates.model_dump(exclude_unset=True)

    # Phone number: normalize and reject junk / duplicates.
    if data.get("phone_number") is not None:
        new_phone = normalize_phone(data["phone_number"])
        if new_phone is None:
            raise HTTPException(
                status_code=400,
                detail="Phone number must be 10-15 digits (e.g. 01712345678).",
            )
        clash = db.query(models.User).filter(
            models.User.phone_number == new_phone,
            models.User.user_id != user_id,
        ).first()
        if clash:
            raise HTTPException(
                status_code=400,
                detail=f"That phone number is already used by {clash.name} (#{clash.user_id}).",
            )
        data["phone_number"] = new_phone

    for field in ("name", "phone_number", "photo"):
        if field in data and data[field] is not None:
            setattr(user, field, data[field])

    db.commit()
    db.refresh(user)
    return user


def delete_employee(db, employee_user_id: int):
    """
    Owner-only: remove an employee account.

    Past sales are detached (employee_id -> NULL) instead of deleted so
    transaction history and reports stay intact.
    """
    user = db.query(models.User).filter(
        models.User.user_id == employee_user_id
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")
    if user.user_type == "owner":
        raise HTTPException(status_code=400, detail="Cannot delete an owner account")

    # Detach past sales so they survive the employee deletion.
    db.query(models.Sale).filter(
        models.Sale.employee_id == employee_user_id
    ).update({models.Sale.employee_id: None})

    name = user.name
    db.delete(user)
    db.commit()
    return {"detail": f"Employee {name} deleted"}


def process_login(db, user_credentials: schemas.UserLogin):
    """
    Validate credentials and return the session payload.

    Returns {user_id, role, name}; the ROUTE stores these in the cookie
    session. Raises 401 with one generic message for both wrong-phone
    and wrong-password (prevents account enumeration).
    """
    user = authenticate_user(
        db, user_credentials.phone_number, user_credentials.password
    )
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect phone number or password",
        )
    return {
        "user_id": user.user_id,
        "role": user.user_type,
        "name": user.name,
    }


# ---------------------------------------------------------
# PRODUCT SERVICES
# ---------------------------------------------------------

def create_product(db, product: schemas.ProductCreate):
    """Insert a new inventory item (owner-only)."""
    db_product = models.Product(
        product_name=product.product_name,
        cost_price=product.cost_price,
        retail_price=product.retail_price,
        stock_quantity=product.stock_quantity,
        category=getattr(product, 'category', None),
        supplier_name=getattr(product, 'supplier_name', None),
        photo=getattr(product, 'photo', None),
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


def get_products(db, skip: int = 0, limit: int = 100):
    """Paged product listing (both roles)."""
    return db.query(models.Product).offset(skip).limit(limit).all()


def get_product(db, product_id: int):
    """Fetch one product or raise 404."""
    product = db.query(models.Product).filter(
        models.Product.product_id == product_id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def search_products(db, search_term: str):
    """Case-insensitive search across name and category."""
    return db.query(models.Product).filter(
        or_(
            models.Product.product_name.icontains(search_term),
            models.Product.category.icontains(search_term),
        )
    ).all()


def update_product(db, product_id: int, updates: schemas.ProductUpdate):
    """Owner-only: apply a partial product edit."""
    product = get_product(db, product_id)
    data = updates.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


def delete_product(db, product_id: int):
    """
    Owner-only: remove a product. Products with recorded sales are
    refused (sale_items reference them); set stock to 0 instead.
    """
    product = get_product(db, product_id)
    if product.sale_items:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a product that has sales recorded. Set stock to 0 instead.",
        )
    name = product.product_name
    db.delete(product)
    db.commit()
    return {"detail": f"Product '{name}' deleted"}


def update_stock(db, product_id: int, quantity_change: int):
    """
    Owner-only: adjust stock up/down by a delta (deliveries, breakage,
    stock counts). Never allows stock to go below zero.
    """
    product = get_product(db, product_id)
    new_quantity = product.stock_quantity + quantity_change
    if new_quantity < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Stock cannot go negative. Current: {product.stock_quantity}, Change: {quantity_change}",
        )
    product.stock_quantity = new_quantity
    db.commit()
    db.refresh(product)
    return product


# ---------------------------------------------------------
# EMPLOYEE SERVICES
# ---------------------------------------------------------

def get_employees(db, skip: int = 0, limit: int = 100):
    """Owner-only roster. Queries models.Employee so owners are excluded."""
    return db.query(models.Employee).offset(skip).limit(limit).all()


def search_employees(db, search_term: str):
    """Owner-only: case-insensitive search by name, position or phone."""
    return db.query(models.Employee).filter(
        or_(
            models.Employee.name.icontains(search_term),
            models.Employee.position.icontains(search_term),
            models.Employee.phone_number.icontains(search_term),
        )
    ).all()


# ---------------------------------------------------------
# CUSTOMER SERVICES
# ---------------------------------------------------------

def create_customer(db, customer: schemas.CustomerCreate):
    """
    Quick-add a customer at the POS (both roles).

    The phone number is the unique lookup key, so duplicates are rejected
    with a message naming the existing customer.
    """
    existing_customer = get_customer_by_phone(db, customer.phone_number)
    if existing_customer:
        raise HTTPException(
            status_code=400,
            detail=f"Phone number {customer.phone_number} is already registered to {existing_customer.name}",
        )

    db_customer = models.Customer(
        name=customer.name,
        phone_number=customer.phone_number,
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


def get_customers(db, skip: int = 0, limit: int = 100):
    """Paged customer listing."""
    return db.query(models.Customer).offset(skip).limit(limit).all()


def get_customer_by_phone(db, phone_number: str):
    """POS lookup by phone — returns None when not found (caller raises 404)."""
    return db.query(models.Customer).filter(
        models.Customer.phone_number == phone_number
    ).first()


def update_customer_name(db, customer_id: int, new_name: str):
    """Edit a customer's display name."""
    customer = db.query(models.Customer).filter(
        models.Customer.customer_id == customer_id
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    customer.name = new_name
    db.commit()
    db.refresh(customer)
    return customer


def get_customer_sales(db, customer_id: int):
    """All transactions for one customer, newest first."""
    return db.query(models.Sale).filter(
        models.Sale.customer_id == customer_id
    ).order_by(models.Sale.transaction_id.desc()).all()


def get_customers_with_spend(db, skip: int = 0, limit: int = 100):
    """Customer directory with lifetime spend (owner view)."""
    customers = get_customers(db, skip=skip, limit=limit)
    result = []
    for c in customers:
        # One aggregate query per customer keeps the code simple; the
        # dataset is small enough that N+1 is acceptable and readable.
        total = db.query(func.coalesce(func.sum(models.Sale.total_revenue), 0.0)).filter(
            models.Sale.customer_id == c.customer_id
        ).scalar()
        result.append({
            "customer_id": c.customer_id,
            "name": c.name,
            "phone_number": c.phone_number,
            "total_spend": float(total),
        })
    return result


# ---------------------------------------------------------
# CHECKOUT / SALE LOGIC
# ---------------------------------------------------------

def create_sale(db, sale_data: schemas.SaleCreate, current_user: dict = None):
    """
    The heart of the POS: turn a cart into a Sale.

    Guarantees:
      1. Employee identity comes from the SESSION, never the body — a
         client cannot record a sale under someone else's name.
      2. Prices come from the DB, never the body — clients cannot set
         their own price.
      3. Stock is validated per line item before anything is written.
      4. Everything commits ATOMICALLY at the end. If ANY step raises,
         the session rolls back: no sale row, no stock deduction, no
         half-written receipt. On SQLite this is a single transaction;
         on TiDB/MySQL InnoDB the same rules apply.
    """
    # 1. Employee identity: session wins over body (security).
    employee_id = sale_data.employee_id
    if current_user is not None:
        employee_id = current_user["id"]
    elif not employee_id:
        raise HTTPException(status_code=401, detail="Login required to check out")

    # 1b. Validate the customer up front. SQLite does not enforce foreign
    # keys by default, so without this check a bogus customer_id would be
    # silently accepted and corrupt reporting downstream.
    customer = db.query(models.Customer).filter(
        models.Customer.customer_id == sale_data.customer_id
    ).first()
    if not customer:
        raise HTTPException(
            status_code=404,
            detail=f"Customer ID {sale_data.customer_id} not found",
        )

    # 2. Start the sale shell. Totals are filled in after all lines pass.
    db_sale = models.Sale(
        employee_id=employee_id,
        customer_id=sale_data.customer_id,
        payment_method=sale_data.payment_method,
        total_revenue=0.0,
        total_profit=0.0,
    )

    total_calculated_revenue = 0.0
    total_calculated_profit = 0.0

    # 3. Validate & compute every line BEFORE writing anything.
    for item in sale_data.items:
        # Authoritative product row (404 if the id is bogus).
        product = db.query(models.Product).filter(
            models.Product.product_id == item.product_id
        ).first()
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product ID {item.product_id} not found",
            )

        # STOCK VALIDATION: refuse to oversell.
        if product.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Not enough stock for '{product.product_name}'. "
                    f"Available: {product.stock_quantity}, Requested: {item.quantity}"
                ),
            )

        # STOCK DEDUCTION (in-memory for now; persisted by the commit).
        product.stock_quantity -= item.quantity

        # FINANCIALS using DB prices (never client-sent prices).
        line_revenue = product.retail_price * item.quantity
        total_calculated_revenue += line_revenue

        line_profit = (product.retail_price - product.cost_price) * item.quantity
        total_calculated_profit += line_profit

        # Bridge row with prices SNAPSHOT at sale time.
        sale_item = models.SaleItem(
            product_id=product.product_id,
            quantity=item.quantity,
            retail_price_at_sale=product.retail_price,
            cost_price_at_sale=product.cost_price,
        )
        db_sale.items.append(sale_item)

    # 4. Finalize totals and persist EVERYTHING in one transaction.
    db_sale.total_revenue = total_calculated_revenue
    db_sale.total_profit = total_calculated_profit

    db.add(db_sale)
    try:
        db.commit()
    except Exception:
        # Anything that fails at flush/commit time (constraint, lost
        # connection) rolls back the sale AND the stock deductions above,
        # leaving inventory exactly as it was before the request.
        db.rollback()
        raise
    db.refresh(db_sale)

    return db_sale


# ---------------------------------------------------------
# SALES LISTING, RECEIPTS & REPORTS
# ---------------------------------------------------------

def get_sales(db, current_user: dict, skip: int = 0, limit: int = 100):
    """Owner sees every transaction; employees only see their own."""
    query = db.query(models.Sale)
    if current_user["role"] != "owner":
        query = query.filter(models.Sale.employee_id == current_user["id"])
    return (
        query.order_by(models.Sale.transaction_id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_sale_receipt(db, transaction_id: int):
    """Full receipt data for one transaction (permission checked by the route)."""
    sale = db.query(models.Sale).filter(
        models.Sale.transaction_id == transaction_id
    ).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Transaction not found")

    items = []
    for item in sale.items:
        product = db.query(models.Product).filter(
            models.Product.product_id == item.product_id
        ).first()
        items.append({
            "product_id": item.product_id,
            "product_name": product.product_name if product else f"Product #{item.product_id}",
            "quantity": item.quantity,
            "unit_price": item.retail_price_at_sale,
            "line_total": item.retail_price_at_sale * item.quantity,
        })

    return {
        "transaction_id": sale.transaction_id,
        "employee_id": sale.employee_id,
        "date": sale.date,
        "time": sale.time,
        "payment_method": sale.payment_method,
        "total_revenue": sale.total_revenue,
        "employee_name": sale.employee.name if sale.employee else "(deleted employee)",
        "customer_name": sale.customer.name if sale.customer else "Walk-in",
        "customer_phone": sale.customer.phone_number if sale.customer else None,
        "items": items,
    }


def get_sales_report(db, period: str):
    """Owner-only: revenue/profit/transaction totals for a period."""
    today = date.today()
    periods = {
        "daily": today,
        "weekly": today - timedelta(days=7),
        "monthly": today - timedelta(days=30),
    }
    if period not in periods:
        raise HTTPException(status_code=400, detail="Period must be 'daily', 'weekly' or 'monthly'")

    start_date = periods[period]
    rows = db.query(
        func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
        func.coalesce(func.sum(models.Sale.total_profit), 0.0),
        func.count(models.Sale.transaction_id),
    ).filter(models.Sale.date >= start_date).one()

    return {
        "period": period,
        "start_date": start_date,
        "end_date": today,
        "total_revenue": float(rows[0]),
        "total_profit": float(rows[1]),
        "total_transactions": rows[2],
    }


def get_sales_performance(db, skip: int = 0, limit: int = 100):
    """Owner-only: lifetime revenue/profit per employee."""
    employees = db.query(models.Employee).offset(skip).limit(limit).all()
    result = []
    for emp in employees:
        totals = db.query(
            func.count(models.Sale.transaction_id),
            func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
            func.coalesce(func.sum(models.Sale.total_profit), 0.0),
        ).filter(models.Sale.employee_id == emp.user_id).one()
        result.append({
            "employee_id": emp.user_id,
            "employee_name": emp.name,
            "total_sales": totals[0],
            "total_revenue": float(totals[1]),
            "total_profit": float(totals[2]),
        })
    return result


def get_my_all_time_performance(db, employee_id: int):
    """All-time sales stats for one employee (their own dashboard)."""
    totals = db.query(
        func.count(models.Sale.transaction_id),
        func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
        func.coalesce(func.sum(models.Sale.total_profit), 0.0),
    ).filter(models.Sale.employee_id == employee_id).one()
    return {
        "total_sales": totals[0],
        "total_revenue": float(totals[1]),
        "total_profit": float(totals[2]),
    }


def get_my_store(db, user_id: int):
    """
    'My Store' card for the employee dashboard: employer identity,
    their own position/salary, and how many colleagues they have.
    """
    emp = db.query(models.Employee).filter(
        models.Employee.user_id == user_id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee account not found")

    owner = emp.employer
    colleague_count = 0
    if owner:
        colleague_count = (
            db.query(models.Employee)
            .filter(
                models.Employee.employer_id == owner.user_id,
                models.Employee.user_id != user_id,
            )
            .count()
        )

    return {
        "store_name": owner.store_name if owner else None,
        "owner_name": owner.name if owner else None,
        "owner_phone": owner.phone_number if owner else None,
        "owner_photo": owner.photo if owner else None,
        "my_position": emp.position,
        "my_salary": emp.salary,
        "date_appointed": emp.date_appointed,
        "colleagues": colleague_count,
    }


# ---------------------------------------------------------
# STORE CHAT SERVICES
# ---------------------------------------------------------

def _resolve_store_group(db, user_id: int, role: str):
    """
    Find the store (owner account) this user chats under.

    - Owners chat under their OWN store (owner_id = their own user_id).
    - Employees chat under their employer's store.
    Raises 404 when the account or its store cannot be found.
    """
    if role == "owner":
        owner = db.query(models.Owner).filter(
            models.Owner.user_id == user_id
        ).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner account not found")
        return owner

    emp = db.query(models.Employee).filter(
        models.Employee.user_id == user_id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee account not found")
    if not emp.employer_id:
        raise HTTPException(status_code=404, detail="You are not linked to a store yet")
    owner = emp.employer
    if not owner:
        raise HTTPException(status_code=404, detail="Your store owner account no longer exists")
    return owner


def _sender_payload(user: models.User) -> dict:
    """Serialize a chat participant (works for owners AND employees)."""
    return {
        "user_id": user.user_id,
        "name": user.name,
        "user_type": user.user_type,
        "photo": user.photo,
    }


def _message_payload(msg, sender, reply_msg=None, reply_sender=None) -> dict:
    """Build the JSON for one chat message, including its quoted reply."""
    payload = {
        "message_id": msg.message_id,
        "sender": _sender_payload(sender),
        "body": "" if msg.deleted else msg.body,
        "reply_to_id": msg.reply_to_id,
        "reply_to": None,
        "deleted": bool(msg.deleted),
        "date": msg.date,
        "time": msg.time,
    }
    if msg.reply_to_id:
        if reply_msg is not None:
            payload["reply_to"] = {
                "message_id": reply_msg.message_id,
                "sender_name": reply_sender.name if reply_sender else "Unknown",
                "body": "" if reply_msg.deleted else reply_msg.body,
                "deleted": bool(reply_msg.deleted),
            }
        else:
            # The quoted message is gone — show a placeholder instead of
            # crashing the client.
            payload["reply_to"] = {
                "message_id": msg.reply_to_id,
                "sender_name": "Unknown",
                "body": "Message unavailable",
                "deleted": True,
            }
    return payload


def get_chat_messages(db, user_id: int, role: str, after_id: int = 0, limit: int = 200):
    """
    Group chat history for the caller's store, oldest first.

    `after_id` enables cheap incremental polling: only fetch messages
    newer than the last one the client already rendered.
    """
    owner = _resolve_store_group(db, user_id, role)

    query = db.query(models.ChatMessage).filter(
        models.ChatMessage.owner_id == owner.user_id
    )
    if after_id:
        query = query.filter(models.ChatMessage.message_id > after_id)
    rows = query.order_by(models.ChatMessage.message_id.desc()).limit(limit).all()
    rows.reverse()  # oldest -> newest for rendering

    # Collect senders + reply targets in bulk to avoid N+1 queries.
    sender_ids = {m.sender_id for m in rows}
    reply_ids = {m.reply_to_id for m in rows if m.reply_to_id}

    senders = {}
    if sender_ids:
        for u in db.query(models.User).filter(models.User.user_id.in_(sender_ids)).all():
            senders[u.user_id] = u

    replies = {}
    if reply_ids:
        for r in db.query(models.ChatMessage).filter(
            models.ChatMessage.message_id.in_(reply_ids)
        ).all():
            replies[r.message_id] = r

    result = []
    for m in rows:
        sender = senders.get(m.sender_id)
        if sender is None:
            continue  # sender account removed and message orphaned — skip defensively
        reply_msg = replies.get(m.reply_to_id) if m.reply_to_id else None
        reply_sender = None
        if reply_msg is not None:
            reply_sender = senders.get(reply_msg.sender_id)
        result.append(_message_payload(m, sender, reply_msg, reply_sender))
    return result


def send_chat_message(db, user_id: int, role: str, payload: schemas.ChatMessageCreate):
    """Post a message to the caller's store group chat (optionally as a reply)."""
    owner = _resolve_store_group(db, user_id, role)

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # If replying, the quoted message must live in the SAME chat —
    # otherwise a user could quote across stores.
    reply_msg = None
    if payload.reply_to_id:
        reply_msg = (
            db.query(models.ChatMessage)
            .filter(
                models.ChatMessage.message_id == payload.reply_to_id,
                models.ChatMessage.owner_id == owner.user_id,
            )
            .first()
        )
        if not reply_msg:
            raise HTTPException(
                status_code=404,
                detail="The message you replied to no longer exists",
            )

    msg = models.ChatMessage(
        owner_id=owner.user_id,
        sender_id=user_id,
        body=body,
        reply_to_id=payload.reply_to_id if reply_msg else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    reply_sender = None
    if reply_msg is not None:
        reply_sender = db.query(models.User).filter(
            models.User.user_id == reply_msg.sender_id
        ).first()
    sender = db.query(models.User).filter(models.User.user_id == user_id).first()
    return _message_payload(msg, sender, reply_msg, reply_sender)


def delete_chat_message(db, user_id: int, message_id: int):
    """
    Soft-delete a message — allowed only for its sender (owner or
    employee). The row stays so reply previews keep working.
    """
    msg = db.query(models.ChatMessage).filter(
        models.ChatMessage.message_id == message_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    msg.deleted = 1
    msg.body = ""
    db.commit()
    return {"detail": "Message deleted", "message_id": message_id}
