from sqlalchemy.orm import Session
from fastapi import HTTPException
from sqlalchemy import or_, func
from datetime import date, timedelta, datetime
import bcrypt  # type: ignore
import models
import schemas

# ---------------------------------------------------------
# SECURITY & AUTHENTICATION
# ---------------------------------------------------------

def hash_password(password: str) -> str:
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode('utf-8')[:72]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode('utf-8'))

def authenticate_user(db: Session, phone_number: str, password: str):
    # 1. Find the user by phone number
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    
    # If the phone number isn't in the database, return False
    if not user:
        return False
        
    # 2. Verify the password (this uses the verify_password function you wrote in Batch 2)
    if not verify_password(password, user.password):
        return False
        
    # 3. If both match, return the user object back to process_login
    return user

# ---------------------------------------------------------
# USER & AUTH SERVICES
# ---------------------------------------------------------

def register_user(db: Session, user_data: schemas.EmployeeCreate, creator_role: str = None):
    """
    Register a new account.

    Rules:
      - Owner signup: allowed publicly (first owner creates the store),
        but if any owner already exists the caller must be a logged-in owner.
      - Employee signup: MUST provide a valid employer_id of an existing owner.
    """
    # 1. Check if phone number is registered
    existing_user = db.query(models.User).filter(models.User.phone_number == user_data.phone_number).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="This phone number is already registered.")

    role = (user_data.role or 'employee').lower()

    if role == 'owner':
        # Only owners may create additional owner accounts once one exists
        any_owner_exists = db.query(models.Owner).first() is not None
        if any_owner_exists and creator_role != 'owner':
            raise HTTPException(
                status_code=403,
                detail="An owner already exists. Only an owner can register another owner account."
            )
        hashed_pwd = hash_password(user_data.password)
        new_user = models.Owner(
            name=user_data.name,
            phone_number=user_data.phone_number,
            password=hashed_pwd,
            address=getattr(user_data, 'address', None),
            photo=getattr(user_data, 'photo', None),
        )
    else:
        # Employees must register under an existing owner
        employer_id = getattr(user_data, 'employer_id', None)
        if not employer_id:
            raise HTTPException(
                status_code=400,
                detail="Employees must register with an existing owner ID (employer_id)."
            )
        owner = db.query(models.Owner).filter(models.Owner.user_id == employer_id).first()
        if not owner:
            raise HTTPException(
                status_code=404,
                detail=f"Owner ID {employer_id} does not exist. Ask your store owner for their ID."
            )

        hashed_pwd = hash_password(user_data.password)
        new_user = models.Employee(
            name=user_data.name,
            phone_number=user_data.phone_number,
            password=hashed_pwd,
            address=getattr(user_data, 'address', None),
            photo=getattr(user_data, 'photo', None),
            position=getattr(user_data, 'position', None),
            salary=getattr(user_data, 'salary', None),
            employer_id=employer_id
        )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def reset_password_request(db: Session, phone_number: str):
    """Check the account exists for password reset. (No email/SMS in this build.)"""
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with that phone number.")
    return {"detail": f"Account found for {user.name}. You may now set a new password."}


def reset_password_confirm(db: Session, phone_number: str, new_password: str):
    """Set a new password for the account (shared by owner/employee)."""
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with that phone number.")

    user.password = hash_password(new_password)
    db.commit()
    return {"detail": "Password reset successful. You can now log in."}


def update_employee(db: Session, employee_user_id: int, updates: schemas.EmployeeUpdate):
    """Owner-only: update employee info and/or role."""
    user = db.query(models.User).filter(models.User.user_id == employee_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = updates.model_dump(exclude_unset=True)

    new_role = data.pop("role", None)
    if new_role:
        new_role = new_role.lower()
        if new_role == user.user_type:
            pass  # no-op
        elif new_role == "owner":
            # Promote employee -> owner
            if user.user_type != "employee":
                raise HTTPException(status_code=400, detail="User is already an owner")
            db.delete(user)
            db.flush()
            new_owner = models.Owner(
                user_id=user.user_id,
                name=user.name,
                phone_number=user.phone_number,
                password=user.password,
                address=user.address,
                photo=user.photo,
            )
            db.add(new_owner)
        elif new_role == "employee":
            if user.user_type != "owner":
                raise HTTPException(status_code=400, detail="User is already an employee")
            db.delete(user)
            db.flush()
            new_emp = models.Employee(
                user_id=user.user_id,
                name=user.name,
                phone_number=user.phone_number,
                password=user.password,
                address=user.address,
                photo=user.photo,
                position=data.pop("position", None),
                salary=data.pop("salary", None),
            )
            db.add(new_emp)
        else:
            raise HTTPException(status_code=400, detail="Role must be 'owner' or 'employee'")

    # Apply plain column updates
    for field in ("name", "phone_number", "position", "salary"):
        if field in data and data[field] is not None:
            setattr(user, field, data[field])

    db.commit()
    db.refresh(user)
    return user


def update_profile(db: Session, user_id: int, updates: schemas.ProfileUpdate):
    """Self-service: a logged-in user edits their own profile (name, phone, photo)."""
    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")

    data = updates.model_dump(exclude_unset=True)

    # Phone number: normalize and reject junk / duplicates (login depends on it)
    if data.get("phone_number") is not None:
        new_phone = str(data["phone_number"]).replace(" ", "").replace("-", "").strip()
        digits = new_phone.replace("+", "")
        if not digits.isdigit() or not (10 <= len(digits) <= 15):
            raise HTTPException(
                status_code=400,
                detail="Phone number must be 10-15 digits (e.g. 01712345678)."
            )
        clash = db.query(models.User).filter(
            models.User.phone_number == new_phone,
            models.User.user_id != user_id
        ).first()
        if clash:
            raise HTTPException(
                status_code=400,
                detail=f"That phone number is already used by {clash.name} (#{clash.user_id})."
            )
        data["phone_number"] = new_phone

    for field in ("name", "phone_number", "photo"):
        if field in data and data[field] is not None:
            setattr(user, field, data[field])

    db.commit()
    db.refresh(user)
    return user


def delete_employee(db: Session, employee_user_id: int):
    """Owner-only: remove an employee account."""
    user = db.query(models.User).filter(models.User.user_id == employee_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Employee not found")
    if user.user_type == "owner":
        raise HTTPException(status_code=400, detail="Cannot delete an owner account")

    # Detach past sales so they survive the employee deletion
    db.query(models.Sale).filter(models.Sale.employee_id == employee_user_id).update(
        {models.Sale.employee_id: None}
    )
    db.delete(user)
    db.commit()
    return {"detail": f"Employee {user.name} deleted"}

def process_login(db: Session, user_credentials: schemas.UserLogin):
    # 1. Check DB and password hash
    user = authenticate_user(db, user_credentials.phone_number, user_credentials.password)
    
    # 2. Raise HTTP error if credentials fail
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect phone number or password"
        )
        
    # 3. Return the raw user data directly
    return {
        "user_id": user.user_id,
        "role": user.user_type,
        "name": user.name
    }
# ---------------------------------------------------------
# PRODUCT SERVICES
# ---------------------------------------------------------

def create_product(db: Session, product: schemas.ProductCreate):
    db_product = models.Product(
        product_name=product.product_name,
        cost_price=product.cost_price,
        retail_price=product.retail_price,
        stock_quantity=product.stock_quantity,
        category=getattr(product, 'category', None),
        supplier_name=getattr(product, 'supplier_name', None),
        photo=getattr(product, 'photo', None)
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def get_products(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Product).offset(skip).limit(limit).all()

def get_product(db: Session, product_id: int):
    product = db.query(models.Product).filter(models.Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

def search_products(db: Session, search_term: str):
    return db.query(models.Product).filter(
        or_(
            models.Product.product_name.icontains(search_term),
            models.Product.category.icontains(search_term)
        )
    ).all()

def update_product(db: Session, product_id: int, updates: schemas.ProductUpdate):
    """Owner-only: edit product details."""
    product = get_product(db, product_id)
    data = updates.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product

def delete_product(db: Session, product_id: int):
    """Owner-only: remove a product from inventory."""
    product = get_product(db, product_id)
    if product.sale_items:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a product that has sales recorded. Set stock to 0 instead."
        )
    db.delete(product)
    db.commit()
    return {"detail": f"Product '{product.product_name}' deleted"}

def update_stock(db: Session, product_id: int, quantity_change: int):
    """Owner-only: adjust stock up/down by a delta."""
    product = get_product(db, product_id)
    new_quantity = product.stock_quantity + quantity_change
    if new_quantity < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Stock cannot go negative. Current: {product.stock_quantity}, Change: {quantity_change}"
        )
    product.stock_quantity = new_quantity
    db.commit()
    db.refresh(product)
    return product
    

# ---------------------------------------------------------
# EMPLOYEE SERVICES
# ---------------------------------------------------------

def get_employees(db: Session, skip: int = 0, limit: int = 100):
    # Notice we query models.Employee specifically, filtering out Owners
    return db.query(models.Employee).offset(skip).limit(limit).all()

def search_employees(db: Session, search_term: str):
    return db.query(models.Employee).filter(
        or_(
            models.Employee.name.icontains(search_term),
            models.Employee.position.icontains(search_term),
            models.Employee.phone_number.icontains(search_term)
        )
    ).all()

# ---------------------------------------------------------
# CUSTOMER SERVICES
# ---------------------------------------------------------

def create_customer(db: Session, customer: schemas.CustomerCreate):
    existing_customer = get_customer_by_phone(db, customer.phone_number)
    if existing_customer:
        raise HTTPException(
            status_code=400, 
            detail=f"Phone number {customer.phone_number} is already registered to {existing_customer.name}"
        )

    db_customer = models.Customer(
        name=customer.name,
        phone_number=customer.phone_number
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer

def get_customers(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Customer).offset(skip).limit(limit).all()

def get_customer_by_phone(db: Session, phone_number: str):
    return db.query(models.Customer).filter(models.Customer.phone_number == phone_number).first()

def update_customer_name(db: Session, customer_id: int, new_name: str):
    customer = db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    customer.name = new_name
    db.commit()
    db.refresh(customer)
    return customer

def get_customer_sales(db: Session, customer_id: int):
    return db.query(models.Sale).filter(models.Sale.customer_id == customer_id).all()

def get_customers_with_spend(db: Session, skip: int = 0, limit: int = 100):
    """Customer directory with lifetime spend (owner view)."""
    customers = get_customers(db, skip=skip, limit=limit)
    result = []
    for c in customers:
        total = db.query(func.coalesce(func.sum(models.Sale.total_revenue), 0.0)).filter(
            models.Sale.customer_id == c.customer_id
        ).scalar()
        result.append({
            "customer_id": c.customer_id,
            "name": c.name,
            "phone_number": c.phone_number,
            "total_spend": float(total)
        })
    return result

# ---------------------------------------------------------
# CHECKOUT / SALE LOGIC
# ---------------------------------------------------------

def create_sale(db: Session, sale_data: schemas.SaleCreate, current_user: dict = None):
    # 1. Employee identity comes from the session, not the request body (security)
    employee_id = sale_data.employee_id
    if current_user is not None:
        employee_id = current_user["id"]
    elif not employee_id:
        raise HTTPException(status_code=401, detail="Login required to check out")

    # 2. Initialize the Sale record
    db_sale = models.Sale(
        employee_id=employee_id,
        customer_id=sale_data.customer_id,
        payment_method=sale_data.payment_method,
        total_revenue=0.0,
        total_profit=0.0
    )
    
    total_calculated_revenue = 0.0
    total_calculated_profit = 0.0
    
    # 2. Process each item in the cart
    for item in sale_data.items:
        # Fetch the authoritative product data from the database
        product = db.query(models.Product).filter(models.Product.product_id == item.product_id).first()
        
        if not product:
            raise HTTPException(status_code=404, detail=f"Product ID {item.product_id} not found")
            
        # 3. STOCK VALIDATION: Prevent selling more than what is available
        if product.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=400, 
                detail=f"Not enough stock for '{product.product_name}'. Available: {product.stock_quantity}, Requested: {item.quantity}"
            )
            
        # 4. STOCK DEDUCTION: Subtract the purchased amount from inventory
        product.stock_quantity -= item.quantity
            
        # 5. Financial Calculations (Securely using DB prices)
        line_revenue = product.retail_price * item.quantity
        total_calculated_revenue += line_revenue
        
        line_profit = (product.retail_price - product.cost_price) * item.quantity
        total_calculated_profit += line_profit
        
        # 6. Create the bridging SaleItem record
        sale_item = models.SaleItem(
            product_id=product.product_id,
            quantity=item.quantity,
            retail_price_at_sale=product.retail_price,
            cost_price_at_sale=product.cost_price
        )
        
        db_sale.items.append(sale_item)

    # 7. Finalize totals
    db_sale.total_revenue = total_calculated_revenue
    db_sale.total_profit = total_calculated_profit
    
    # 9. Save everything to TiDB
    db.add(db_sale)
    db.commit()
    db.refresh(db_sale)
    
    return db_sale


# ---------------------------------------------------------
# SALES LISTING, RECEIPTS & REPORTS
# ---------------------------------------------------------

def get_sales(db: Session, current_user: dict, skip: int = 0, limit: int = 100):
    """Owner sees every transaction; employees only see their own."""
    query = db.query(models.Sale)
    if current_user["role"] != "owner":
        query = query.filter(models.Sale.employee_id == current_user["id"])
    return query.order_by(models.Sale.transaction_id.desc()).offset(skip).limit(limit).all()


def get_sale_receipt(db: Session, transaction_id: int):
    """Full receipt data for one transaction."""
    sale = db.query(models.Sale).filter(models.Sale.transaction_id == transaction_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Transaction not found")

    items = []
    for item in sale.items:
        product = db.query(models.Product).filter(models.Product.product_id == item.product_id).first()
        items.append({
            "product_id": item.product_id,
            "product_name": product.product_name if product else f"Product #{item.product_id}",
            "quantity": item.quantity,
            "unit_price": item.retail_price_at_sale,
            "line_total": item.retail_price_at_sale * item.quantity
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
        "items": items
    }


def get_sales_report(db: Session, period: str):
    """Owner-only: totals for daily / weekly / monthly periods."""
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
        func.count(models.Sale.transaction_id)
    ).filter(models.Sale.date >= start_date).one()

    return {
        "period": period,
        "start_date": start_date,
        "end_date": today,
        "total_revenue": float(rows[0]),
        "total_profit": float(rows[1]),
        "total_transactions": rows[2]
    }


def get_sales_performance(db: Session, skip: int = 0, limit: int = 100):
    """Owner-only: revenue/profit per employee across all time."""
    employees = db.query(models.Employee).offset(skip).limit(limit).all()
    result = []
    for emp in employees:
        totals = db.query(
            func.count(models.Sale.transaction_id),
            func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
            func.coalesce(func.sum(models.Sale.total_profit), 0.0)
        ).filter(models.Sale.employee_id == emp.user_id).one()
        result.append({
            "employee_id": emp.user_id,
            "employee_name": emp.name,
            "total_sales": totals[0],
            "total_revenue": float(totals[1]),
            "total_profit": float(totals[2])
        })
    return result


def get_my_all_time_performance(db: Session, employee_id: int):
    """All-time sales stats for one employee (used on their dashboard)."""
    totals = db.query(
        func.count(models.Sale.transaction_id),
        func.coalesce(func.sum(models.Sale.total_revenue), 0.0),
        func.coalesce(func.sum(models.Sale.total_profit), 0.0)
    ).filter(models.Sale.employee_id == employee_id).one()
    return {
        "total_sales": totals[0],
        "total_revenue": float(totals[1]),
        "total_profit": float(totals[2])
    }


def get_my_store(db: Session, user_id: int):
    """'My Store' card data for the employee dashboard: employer, salary, colleagues."""
    emp = db.query(models.Employee).filter(models.Employee.user_id == user_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee account not found")

    owner = emp.employer
    colleague_count = 0
    if owner:
        colleague_count = (
            db.query(models.Employee)
            .filter(models.Employee.employer_id == owner.user_id, models.Employee.user_id != user_id)
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

def _resolve_store_group(db: Session, user_id: int, role: str):
    """Find the store (owner account) this user chats under.

    - Owners chat under their OWN store (owner_id = their own user_id).
    - Employees chat under their employer's store.
    Raises 404 when the account or its store cannot be found.
    """
    if role == "owner":
        owner = db.query(models.Owner).filter(models.Owner.user_id == user_id).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner account not found")
        return owner

    emp = db.query(models.Employee).filter(models.Employee.user_id == user_id).first()
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


def _message_payload(msg: models.ChatMessage, sender: models.User, reply_msg=None, reply_sender=None) -> dict:
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
            # The quoted message is gone or not yet loaded
            payload["reply_to"] = {
                "message_id": msg.reply_to_id,
                "sender_name": "Unknown",
                "body": "Message unavailable",
                "deleted": True,
            }
    return payload


def get_chat_messages(db: Session, user_id: int, role: str, after_id: int = 0, limit: int = 200):
    """Group chat history for the caller's store, oldest first.

    `after_id` enables cheap incremental polling: only fetch messages newer
    than the last one the client has already rendered.
    """
    owner = _resolve_store_group(db, user_id, role)

    query = db.query(models.ChatMessage).filter(models.ChatMessage.owner_id == owner.user_id)
    if after_id:
        query = query.filter(models.ChatMessage.message_id > after_id)
    rows = query.order_by(models.ChatMessage.message_id.desc()).limit(limit).all()
    rows.reverse()  # oldest -> newest for rendering

    # Collect sender + reply targets in bulk to avoid N+1 queries
    sender_ids = {m.sender_id for m in rows}
    reply_ids = {m.reply_to_id for m in rows if m.reply_to_id}

    senders = {}
    if sender_ids:
        for u in db.query(models.User).filter(models.User.user_id.in_(sender_ids)).all():
            senders[u.user_id] = u

    replies = {}
    if reply_ids:
        for r in db.query(models.ChatMessage).filter(models.ChatMessage.message_id.in_(reply_ids)).all():
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
            if reply_sender is None:
                ru = db.query(models.User).filter(models.User.user_id == reply_msg.sender_id).first()
                reply_sender = ru
        result.append(_message_payload(m, sender, reply_msg, reply_sender))
    return result


def send_chat_message(db: Session, user_id: int, role: str, payload: schemas.ChatMessageCreate):
    """Post a message to the caller's store group chat (optionally as a reply)."""
    owner = _resolve_store_group(db, user_id, role)

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    reply_msg = None
    if payload.reply_to_id:
        reply_msg = (
            db.query(models.ChatMessage)
            .filter(
                models.ChatMessage.message_id == payload.reply_to_id,
                models.ChatMessage.owner_id == owner.user_id,  # must be in the SAME chat
            )
            .first()
        )
        if not reply_msg:
            raise HTTPException(status_code=404, detail="The message you replied to no longer exists")

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
        reply_sender = db.query(models.User).filter(models.User.user_id == reply_msg.sender_id).first()
    return _message_payload(msg, db.query(models.User).filter(models.User.user_id == user_id).first(), reply_msg, reply_sender)


def delete_chat_message(db: Session, user_id: int, message_id: int):
    """Soft-delete a message — allowed only for its sender (owner or employee)."""
    msg = db.query(models.ChatMessage).filter(models.ChatMessage.message_id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    msg.deleted = 1
    msg.body = ""
    db.commit()
    return {"detail": "Message deleted", "message_id": message_id}