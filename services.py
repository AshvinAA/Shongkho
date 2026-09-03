from sqlalchemy.orm import Session
from fastapi import HTTPException
from sqlalchemy import or_
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

# ---------------------------------------------------------
# USER & AUTH SERVICES
# ---------------------------------------------------------

def register_user(db: Session, user_data: schemas.UserCreate):
    # 1. Check if phone number is registered
    existing_user = db.query(models.User).filter(models.User.phone_number == user_data.phone_number).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="This phone number is already registered.")

    # 2. Hash raw password
    hashed_pwd = hash_password(user_data.password)
    role = getattr(user_data, 'role', getattr(user_data, 'user_type', 'employee')).lower()

    # 3. Instantiate using model field names (`password` instead of `password_hash`)
    if role == 'owner':
        new_user = models.Owner(
            name=user_data.name,
            phone_number=user_data.phone_number,
            password=hashed_pwd,
            address=getattr(user_data, 'address', None),
            photo=getattr(user_data, 'photo', None),
            store_name=getattr(user_data, 'store_name', None)
        )
    else:
        new_user = models.Employee(
            name=user_data.name,
            phone_number=user_data.phone_number,
            password=hashed_pwd,
            address=getattr(user_data, 'address', None),
            photo=getattr(user_data, 'photo', None),
            position=getattr(user_data, 'position', None),
            salary=getattr(user_data, 'salary', None),
            employer_id=getattr(user_data, 'employer_id', None)
        )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# ---------------------------------------------------------
# PRODUCT SERVICES
# ---------------------------------------------------------

def create_product(db: Session, product: schemas.ProductCreate):
    db_product = models.Product(
        product_name=product.product_name,
        cost_price=product.cost_price,
        retail_price=product.retail_price,
        category=getattr(product, 'category', None),
        supplier_name=getattr(product, 'supplier_name', None)
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def get_products(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Product).offset(skip).limit(limit).all()

def search_products(db: Session, search_term: str):
    return db.query(models.Product).filter(
        or_(
            models.Product.product_name.icontains(search_term),
            models.Product.category.icontains(search_term)
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

# ---------------------------------------------------------
# CHECKOUT / SALE LOGIC
# ---------------------------------------------------------

def create_sale(db: Session, sale_data: schemas.SaleCreate):
    db_sale = models.Sale(
        employee_id=sale_data.employee_id,
        customer_id=sale_data.customer_id,
        payment_method=sale_data.payment_method,
        total_revenue=0.0,
        total_profit=0.0
    )
    
    total_calculated_revenue = 0.0
    total_calculated_profit = 0.0
    
    for item in sale_data.items:
        product = db.query(models.Product).filter(models.Product.product_id == item.product_id).first()
        
        if not product:
            raise HTTPException(status_code=404, detail=f"Product ID {item.product_id} not found")
            
        line_revenue = product.retail_price * item.quantity
        total_calculated_revenue += line_revenue
        
        line_profit = (product.retail_price - product.cost_price) * item.quantity
        total_calculated_profit += line_profit
        
        sale_item = models.SaleItem(
            product_id=product.product_id,
            quantity=item.quantity,
            retail_price_at_sale=product.retail_price,
            cost_price_at_sale=product.cost_price
        )
        
        db_sale.items.append(sale_item)

    db_sale.total_revenue = total_calculated_revenue
    db_sale.total_profit = total_calculated_profit
    
    db.add(db_sale)
    db.commit()
    db.refresh(db_sale)
    
    return db_sale