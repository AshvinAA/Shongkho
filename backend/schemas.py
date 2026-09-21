"""
Pydantic schemas: the shape of data entering and leaving the API.

Three kinds of schema live here:
  - *Create  — payloads accepted from clients (validated, price fields
               deliberately EXCLUDED so clients can never set prices)
  - *Update  — partial-update payloads (every field optional)
  - *Response — what we send back (from_attributes lets Pydantic read
               straight from SQLAlchemy model objects)
"""
from typing import List, Optional
from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------
# 1. PRODUCT SCHEMAS
# ---------------------------------------------------------
class ProductBase(BaseModel):
    product_name: str = Field(min_length=1)     # reject empty names
    cost_price: float = Field(ge=0)             # prices cannot be negative
    retail_price: float = Field(ge=0)
    stock_quantity: int = Field(default=0, ge=0)  # stock cannot be negative
    category: Optional[str] = None
    supplier_name: Optional[str] = None
    photo: Optional[str] = None                 # product picture URL (or data URI)

    @field_validator("product_name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        """min_length alone still allows '   ' — reject whitespace-only names."""
        if not v.strip():
            raise ValueError("Product name cannot be blank")
        return v


class ProductCreate(ProductBase):
    """Payload for POST /products (owner-only)."""


class ProductResponse(ProductBase):
    product_id: int
    date: date

    model_config = ConfigDict(from_attributes=True)


class ProductUpdate(BaseModel):
    """Owner-only: partial update of a product."""
    product_name: Optional[str] = Field(None, min_length=1)
    cost_price: Optional[float] = Field(None, ge=0)
    retail_price: Optional[float] = Field(None, ge=0)
    stock_quantity: Optional[int] = Field(None, ge=0)
    category: Optional[str] = None
    supplier_name: Optional[str] = None
    photo: Optional[str] = None


class StockUpdate(BaseModel):
    """
    Owner-only: adjust stock by a delta (can be negative, e.g. -3 after
    breakage). The service layer refuses to let stock go below zero.
    """
    quantity_change: int


# ---------------------------------------------------------
# 2. AUTH SCHEMAS
# ---------------------------------------------------------
class UserLogin(BaseModel):
    phone_number: str
    password: str


class PasswordResetRequest(BaseModel):
    phone_number: str


class PasswordResetConfirm(BaseModel):
    phone_number: str
    new_password: str


class RegisterResponse(BaseModel):
    """Public shape of a freshly registered account (no password!)."""
    user_id: int
    name: str
    phone_number: str
    user_type: str

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# 3. CUSTOMER SCHEMAS
# ---------------------------------------------------------
class CustomerBase(BaseModel):
    name: str = Field(min_length=1)
    phone_number: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        """Reject whitespace-only customer names."""
        if not v.strip():
            raise ValueError("Customer name cannot be blank")
        return v


class CustomerCreate(CustomerBase):
    """Payload for POST /customers (POS quick-add, both roles)."""


class CustomerResponse(CustomerBase):
    customer_id: int

    model_config = ConfigDict(from_attributes=True)


class CustomerUpdate(BaseModel):
    """Partial edit of a customer record."""
    name: Optional[str] = Field(None, min_length=1)


# ---------------------------------------------------------
# 4. EMPLOYEE / USER SCHEMAS
# ---------------------------------------------------------
class UserBase(BaseModel):
    name: str
    phone_number: str
    address: Optional[str] = None
    photo: Optional[str] = None


class EmployeeCreate(BaseModel):
    """
    Registration payload (shared by owner/employee signup).

    The name is historical: it carries `role` ('owner' | 'employee') plus
    the employee-only fields employer_id / position / salary.
    """
    name: str
    phone_number: str
    role: str                     # 'owner' or 'employee'
    password: str                 # raw password from the frontend (hashed server-side)
    employer_id: Optional[int] = None  # employees must reference an existing owner
    position: Optional[str] = None
    salary: Optional[float] = Field(None, ge=0)  # salary cannot be negative


class EmployeeUpdate(BaseModel):
    """Owner-only: update employee info and/or role (owner <-> employee)."""
    name: Optional[str] = None
    phone_number: Optional[str] = None
    position: Optional[str] = None
    salary: Optional[float] = Field(None, ge=0)
    role: Optional[str] = None    # 'owner' or 'employee' — promotes/demotes


class ProfileUpdate(BaseModel):
    """Self-service profile edit (own account, both roles)."""
    name: Optional[str] = Field(None, min_length=1)
    phone_number: Optional[str] = None
    photo: Optional[str] = None   # profile picture URL (or data URI)


class EmployeeResponse(BaseModel):
    """Employee row as the owner sees it in /staff."""
    user_id: int
    name: str
    phone_number: str
    user_type: str
    position: Optional[str] = None
    salary: Optional[float] = None
    employer_id: Optional[int] = None
    photo: Optional[str] = None
    date_appointed: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class MyStoreResponse(BaseModel):
    """Employee dashboard 'My Store' card: where they work and who they work for."""
    store_name: Optional[str] = None
    owner_name: Optional[str] = None
    owner_phone: Optional[str] = None
    owner_photo: Optional[str] = None
    my_position: Optional[str] = None
    my_salary: Optional[float] = None
    date_appointed: Optional[date] = None
    colleagues: int = 0


class EmployeePerformance(BaseModel):
    """One employee's lifetime sales stats (owner's performance view)."""
    employee_id: int
    employee_name: str
    total_sales: int
    total_revenue: float
    total_profit: float


# ---------------------------------------------------------
# 5. SALE & CHECKOUT SCHEMAS
# ---------------------------------------------------------
class SaleItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1)   # must buy at least one

    # NOTE: we deliberately do NOT accept prices here. The frontend never
    # sets prices — the backend reads authoritative prices from the DB.


class SaleItemResponse(BaseModel):
    product_id: int
    quantity: int
    retail_price_at_sale: float
    cost_price_at_sale: float

    model_config = ConfigDict(from_attributes=True)


class SaleCreate(BaseModel):
    """Checkout payload. employee_id is filled from the session server-side."""
    employee_id: Optional[int] = None
    customer_id: int
    payment_method: str = Field(min_length=1)
    items: List[SaleItemCreate] = Field(min_length=1)  # at least one line item


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
    """Owner's daily/weekly/monthly totals."""
    period: str
    start_date: date
    end_date: date
    total_revenue: float
    total_profit: float
    total_transactions: int


class ReceiptResponse(BaseModel):
    """Printable receipt for one transaction (items are plain dicts)."""
    transaction_id: int
    date: date
    time: time
    payment_method: str
    total_revenue: float
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    items: List[dict]


class SaleResponse(BaseModel):
    """Full sale record returned right after checkout."""
    transaction_id: int
    date: date
    time: time
    payment_method: str
    total_revenue: float
    total_profit: float
    employee_id: Optional[int] = None
    customer_id: int
    items: List[SaleItemResponse]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# 6. STORE CHAT SCHEMAS
# ---------------------------------------------------------
class ChatMessageCreate(BaseModel):
    """Send a message to the store group chat."""
    body: str = Field(min_length=1, max_length=4000)
    reply_to_id: Optional[int] = None


class ChatSender(BaseModel):
    """The author of a chat message (owner or employee)."""
    user_id: int
    name: str
    user_type: str
    photo: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ChatReplyPreview(BaseModel):
    """Quoted message preview shown above a reply."""
    message_id: int
    sender_name: Optional[str] = None
    body: str
    deleted: bool = False


class ChatMessageResponse(BaseModel):
    """One chat message as rendered in the client."""
    message_id: int
    sender: ChatSender
    body: str
    reply_to_id: Optional[int] = None
    reply_to: Optional[ChatReplyPreview] = None
    deleted: bool = False
    date: date
    time: time

    model_config = ConfigDict(from_attributes=True)
