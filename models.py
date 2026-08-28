from datetime import date, datetime
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, Time, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# ---------------------------------------------------------
# 1. USER HIERARCHY (Joined Table Inheritance)
# ---------------------------------------------------------
class User(Base):
    __tablename__ = 'users'
    
    user_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone_number = Column(String(50))
    address = Column(Text)
    password = Column(String(255), nullable=False)
    photo = Column(String(550))
    
    # Discriminator column to distinguish between Owner and Employee
    user_type = Column(String(50)) 

    __mapper_args__ = {
        'polymorphic_on': user_type,
        'polymorphic_identity': 'user'
    }


class Owner(User):
    __tablename__ = 'owners'
    
    user_id = Column(Integer, ForeignKey('users.user_id'), primary_key=True)
    store_name = Column(String(255))

    # Relationship to track all employees hired by this owner
    employees = relationship("Employee", back_populates="employer")

    __mapper_args__ = {
        'polymorphic_identity': 'owner'
    }


class Employee(User):
    __tablename__ = 'employees'
    
    user_id = Column(Integer, ForeignKey('users.user_id'), primary_key=True)
    position = Column(String(100))
    salary = Column(Float)
    date_appointed = Column(Date, default=date.today)
    
    # Foreign Key pointing to Owner's user_id
    employer_id = Column(Integer, ForeignKey('owners.user_id'))

    employer = relationship("Owner", back_populates="employees")
    sales = relationship("Sale", back_populates="employee")

    __mapper_args__ = {
        'polymorphic_identity': 'employee'
    }

# ---------------------------------------------------------
# 2. CORE ENTITIES (Customer & Product)
# ---------------------------------------------------------
class Customer(Base):
    __tablename__ = 'customers'
    
    customer_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone_number = Column(String(50))

    sales = relationship("Sale", back_populates="customer")


class Product(Base):
    __tablename__ = 'products'
    
    product_id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String(255), nullable=False)
    current_price = Column(Float, nullable=False)
    category = Column(String(100))
    supplier_name = Column(String(255))
    date = Column(Date, default=date.today)

    sale_items = relationship("SaleItem", back_populates="product")

# ---------------------------------------------------------
# 3. TRANSACTION ENTITIES (Sale & SaleItem Bridge)
# ---------------------------------------------------------
class Sale(Base):
    __tablename__ = 'sales'
    
    transaction_id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, default=date.today)
    time = Column(Time, default=lambda: datetime.now().time())
    payment_method = Column(String(50))
    total_revenue = Column(Float, default=0.0)
    
    # Foreign Keys
    employee_id = Column(Integer, ForeignKey('employees.user_id'))
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))

    # ORM Relationships
    employee = relationship("Employee", back_populates="sales")
    customer = relationship("Customer", back_populates="sales")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = 'sale_items'
    
    # Composite Primary Key joining Sale and Product
    transaction_id = Column(Integer, ForeignKey('sales.transaction_id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), primary_key=True)
    
    quantity = Column(Integer, nullable=False)
    unit_price_at_sale = Column(Float, nullable=False)  # Preserves historical sale price

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")