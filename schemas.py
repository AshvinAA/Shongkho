from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import date, time

# ---------------------------------------------------------
# 1. PRODUCT SCHEMAS
# ---------------------------------------------------------
class ProductBase(BaseModel):
    product_name: str
    current_price: float
    category: Optional[str] = None
    supplier_name: Optional[str] = None

class ProductCreate(ProductBase):
    pass  # Used when creating a new product from the frontend

class ProductResponse(ProductBase):
    product_id: int
    date: date
    
    # Allows Pydantic to read data directly from SQLAlchemy models
    model_config = ConfigDict(from_attributes=True)

# ---------------------------------------------------------
# 2. CUSTOMER SCHEMAS
# ---------------------------------------------------------
class CustomerBase(BaseModel):
    name: str
    phone_number: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerResponse(CustomerBase):
    customer_id: int
    model_config = ConfigDict(from_attributes=True)

# ---------------------------------------------------------
# 3. EMPLOYEE / USER SCHEMAS
# ---------------------------------------------------------
class UserBase(BaseModel):
    name: str
    phone_number: str
    address: Optional[str] = None
    photo: Optional[str] = None

class EmployeeCreate(UserBase):
    password: str
    position: str
    salary: float
    employer_id: int

class EmployeeResponse(UserBase):
    user_id: int
    position: str
    salary: float
    date_appointed: date
    employer_id: int
    
    model_config = ConfigDict(from_attributes=True)

# ---------------------------------------------------------
# 4. SALE & CHECKOUT SCHEMAS
# ---------------------------------------------------------
class SaleItemCreate(BaseModel):
    product_id: int
    quantity: int
    # We do NOT ask the frontend for the price to prevent hacking.
    # We will fetch the secure price from the DB in our business logic!

class SaleItemResponse(BaseModel):
    product_id: int
    quantity: int
    unit_price_at_sale: float
    model_config = ConfigDict(from_attributes=True)

class SaleCreate(BaseModel):
    employee_id: int
    customer_id: int
    payment_method: str
    items: List[SaleItemCreate]  # A list of the items being purchased

class SaleResponse(BaseModel):
    transaction_id: int
    date: date
    time: time
    payment_method: str
    total_revenue: float
    employee_id: int
    customer_id: int
    items: List[SaleItemResponse]
    
    model_config = ConfigDict(from_attributes=True)

