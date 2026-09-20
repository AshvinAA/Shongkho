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

    # Provide the EXACT explicit join condition
    employees = relationship(
        "Employee", 
        primaryjoin="Owner.user_id == Employee.employer_id", # <--- Forces the exact join
        back_populates="employer"
    )

    __mapper_args__ = {
        'polymorphic_identity': 'owner'
    }


class Employee(User):
    __tablename__ = 'employees'
    
    user_id = Column(Integer, ForeignKey('users.user_id'), primary_key=True)
    position = Column(String(100))
    salary = Column(Float)
    date_appointed = Column(Date, default=date.today)
    
    employer_id = Column(Integer, ForeignKey('owners.user_id'))

    # Match the exact join condition from the Owner side
    employer = relationship(
        "Owner", 
        primaryjoin="Owner.user_id == Employee.employer_id", # <--- Forces the exact join
        back_populates="employees"
    )
    # Sales processed by this employee (Sale.employee is a plain User relationship)
    sales = relationship("Sale", primaryjoin="Employee.user_id == Sale.employee_id", foreign_keys="Sale.employee_id")

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
    # 1. Added unique=True and index=True
    phone_number = Column(String(50), unique=True, index=True, nullable=False)
    
    # 2. Added relationship to fetch full purchase history
    sales = relationship("Sale", back_populates="customer")

class Product(Base):
    __tablename__ = 'products'
    
    product_id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String(255), nullable=False)
    
    cost_price = Column(Float, nullable=False)   
    retail_price = Column(Float, nullable=False) 
    stock_quantity = Column(Integer, default=0, nullable=False) # Add this line
    
    category = Column(String(100))
    supplier_name = Column(String(255))
    photo = Column(String(550))
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
    payment_method = Column(String(50), nullable=False)
    total_revenue = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    
    # Foreign Keys
    # Points at users.user_id so BOTH owners and employees can process sales
    employee_id = Column(Integer, ForeignKey('users.user_id'), nullable=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))

    # ORM Relationships
    employee = relationship("User", foreign_keys=[employee_id], viewonly=True)
    customer = relationship("Customer", back_populates="sales")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")
    


class SaleItem(Base):
    __tablename__ = 'sale_items'
    
    # Composite Primary Key joining Sale and Product
    transaction_id = Column(Integer, ForeignKey('sales.transaction_id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), primary_key=True)
    
    quantity = Column(Integer, nullable=False)
    retail_price_at_sale = Column(Float, nullable=False) # Lock in customer price
    cost_price_at_sale = Column(Float, nullable=False)   # Lock in supplier cost

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")


# ---------------------------------------------------------
# 4. STORE CHAT (WhatsApp-style group for owner + employees)
# ---------------------------------------------------------

class ChatMessage(Base):
    __tablename__ = 'chat_messages'

    message_id = Column(Integer, primary_key=True, index=True)
    # All messages belong to the store's single group chat. Kept as a plain
    # column (not an FK to owners) so chat survives even if an owner account
    # is ever removed.
    owner_id = Column(Integer, index=True)               # store / group identifier
    sender_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    body = Column(Text, nullable=False)
    # Optional message being replied to (WhatsApp-style quote)
    reply_to_id = Column(Integer, ForeignKey('chat_messages.message_id'), nullable=True)
    # Soft delete: message stays for thread integrity but shows as "deleted"
    deleted = Column(Integer, default=0, nullable=False)
    date = Column(Date, default=date.today, nullable=False)
    time = Column(Time, default=lambda: datetime.now().time(), nullable=False)

    sender = relationship("User", foreign_keys=[sender_id], viewonly=True)
    reply_to = relationship("ChatMessage", remote_side=[message_id], viewonly=True)
    

