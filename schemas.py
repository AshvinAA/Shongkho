from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import date, time

# ---------------------------------------------------------
# 1. PRODUCT SCHEMAS
# ---------------------------------------------------------

class ProductBase(BaseModel):
    product_name: str
    cost_price: float     
    retail_price: float   
    stock_quantity: int = 0  # Add this line
    category: Optional[str] = None
    supplier_name: Optional[str] = None


class ProductCreate(ProductBase):
    pass  # Used when creating a new product from the frontend

class ProductResponse(ProductBase):
    product_id: int
    date: date
    
    # Allows Pydantic to read data directly from SQLAlchemy models
    model_config = ConfigDict(from_attributes=True)


class ProductUpdate(BaseModel):
    """Owner-only: partial update of a product."""
    product_name: Optional[str] = None
    cost_price: Optional[float] = None
    retail_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    category: Optional[str] = None
    supplier_name: Optional[str] = None


class StockUpdate(BaseModel):
    """Owner-only: adjust stock by a delta (can be negative)."""
    quantity_change: int
    


class UserLogin(BaseModel):
    phone_number: str
    password: str


class PasswordResetRequest(BaseModel):
    phone_number: str


class PasswordResetConfirm(BaseModel):
    phone_number: str
    new_password: str


class RegisterResponse(BaseModel):
    user_id: int
    name: str
    phone_number: str
    user_type: str
    model_config = ConfigDict(from_attributes=True)

# ---------------------------------------------------------
# CUSTOMER SCHEMAS
# ---------------------------------------------------------
class CustomerBase(BaseModel):
    name: str
    phone_number: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerResponse(CustomerBase):
    customer_id: int
    model_config = ConfigDict(from_attributes=True)
    
class CustomerUpdate(BaseModel):
    name: str

# ---------------------------------------------------------
# 3. EMPLOYEE / USER SCHEMAS
# ---------------------------------------------------------
class UserBase(BaseModel):
    name: str
    phone_number: str
    address: Optional[str] = None
    photo: Optional[str] = None


class EmployeeCreate(BaseModel):
    name: str
    phone_number: str
    role: str       # They will select "owner" or "employee"
    password: str   # The raw password from the frontend
    employer_id: Optional[int] = None   # Employees must register under an existing owner
    position: Optional[str] = None
    salary: Optional[float] = None


class EmployeeUpdate(BaseModel):
    """Owner-only: update employee info / role."""
    name: Optional[str] = None
    phone_number: Optional[str] = None
    position: Optional[str] = None
    salary: Optional[float] = None
    role: Optional[str] = None   # promote/demote between owner and employee


class EmployeeResponse(BaseModel):
    user_id: int
    name: str
    phone_number: str
    user_type: str
    position: Optional[str] = None
    salary: Optional[float] = None
    employer_id: Optional[int] = None

    class Config:
        from_attributes = True


class EmployeePerformance(BaseModel):
    employee_id: int
    employee_name: str
    total_sales: int
    total_revenue: float
    total_profit: float

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
    retail_price_at_sale: float
    cost_price_at_sale: float
    model_config = ConfigDict(from_attributes=True)



class SaleCreate(BaseModel):
    employee_id: Optional[int] = None   # Filled from the session when missing
    customer_id: int
    payment_method: str
    items: List[SaleItemCreate]  # A list of the items being purchased


class SaleSummary(BaseModel):
    """Sale without items — used for list views."""
    transaction_id: int
    date: date
    time: time
    payment_method: str
    total_revenue: float
    total_profit: float
    employee_id: Optional[int] = None
    customer_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class CustomerSpendResponse(CustomerResponse):
    """Customer with lifetime spend (owner directory view)."""
    total_spend: float = 0.0


class ReportResponse(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_revenue: float
    total_profit: float
    total_transactions: int


class ReceiptResponse(BaseModel):
    transaction_id: int
    date: date
    time: time
    payment_method: str
    total_revenue: float
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    customer_name: Optional[str] = None
    items: List[dict]

class SaleResponse(BaseModel):
    transaction_id: int
    date: date
    time: time
    payment_method: str
    total_revenue: float
    total_profit: float
    employee_id: int
    customer_id: int
    items: List[SaleItemResponse]
    
    model_config = ConfigDict(from_attributes=True)




