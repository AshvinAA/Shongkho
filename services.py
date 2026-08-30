from sqlalchemy.orm import Session
from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy import or_
import models
import schemas

# ---------------------------------------------------------
# SECURITY & AUTHENTICATION
# ---------------------------------------------------------
# Set up password hashing using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# ---------------------------------------------------------
# EMPLOYEE SERVICES
# ---------------------------------------------------------
def create_employee(db: Session, employee: schemas.EmployeeCreate):
    # Hash the password before saving it to the database
    hashed_pwd = get_password_hash(employee.password)
    
    db_employee = models.Employee(
        name=employee.name,
        phone_number=employee.phone_number,
        address=employee.address,
        password=hashed_pwd,
        position=employee.position,
        salary=employee.salary,
        employer_id=employee.employer_id
    )
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee


    
def search_employees(db: Session, search_term: str):
    # This will find employees where the search term matches part of their name OR phone number
    return db.query(models.Employee).filter(
        or_(
            models.Employee.name.contains(search_term),
            models.Employee.phone_number.contains(search_term)
        )
    ).all()

# ---------------------------------------------------------
# PRODUCT SERVICES
# ---------------------------------------------------------
def create_product(db: Session, product: schemas.ProductCreate):
    # Manually mapping each field instead of using model_dump()
    db_product = models.Product(
        product_name=product.product_name,
        current_price=product.current_price,
        category=product.category,
        supplier_name=product.supplier_name
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def get_products(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Product).offset(skip).limit(limit).all()


def search_products(db: Session, search_term: str):
    # This will find products where the search term matches part of their name OR category
    return db.query(models.Product).filter(
        or_(
            models.Product.product_name.contains(search_term),
            models.Product.category.contains(search_term)
        )
    ).all()


# ---------------------------------------------------------
# CUSTOMER SERVICES
# ---------------------------------------------------------
def create_customer(db: Session, customer: schemas.CustomerCreate):
    # Manually mapping each field instead of using model_dump()
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

# ---------------------------------------------------------
# CHECKOUT / SALE LOGIC (The most important part)
# ---------------------------------------------------------
def create_sale(db: Session, sale_data: schemas.SaleCreate):
    # 1. Create the empty Sale record first
    db_sale = models.Sale(
        employee_id=sale_data.employee_id,
        customer_id=sale_data.customer_id,
        payment_method=sale_data.payment_method,
        total_revenue=0.0  # We will calculate this securely right now
    )
    
    # 2. Process each item in the cart
    total_calculated_revenue = 0.0
    
    for item in sale_data.items:
        # Fetch the product from the database to get its SECURE current price
        product = db.query(models.Product).filter(models.Product.product_id == item.product_id).first()
        
        if not product:
            raise HTTPException(status_code=404, detail=f"Product ID {item.product_id} not found")
            
        # Calculate revenue for this specific item
        line_total = product.current_price * item.quantity
        total_calculated_revenue += line_total
        
        # Create the SaleItem bridge record
        sale_item = models.SaleItem(
            product_id=product.product_id,
            quantity=item.quantity,
            unit_price_at_sale=product.current_price # Locks in the price for historical records
        )
        
        # Attach the item to the main sale record
        db_sale.items.append(sale_item)

    # 3. Update the total revenue
    db_sale.total_revenue = total_calculated_revenue
    
    # 4. Save everything to the database in one single transaction
    db.add(db_sale)
    db.commit()
    db.refresh(db_sale)
    
    return db_sale