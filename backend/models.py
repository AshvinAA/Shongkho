"""
SQLAlchemy models for the Shongkho POS system.

Model map (who stores what):

  users/owners/employees  — joined-table inheritance. `users` holds the
  shared identity columns (name, phone, password, photo); `owners` and
  `employees` hold role-specific columns and join back to `users` on
  user_id. The `user_type` discriminator column tells SQLAlchemy which
  subclass to build when loading rows.

  customers               — walk-in / regular buyers (unique phone number)
  products                — inventory (prices, stock, category, photo)
  sales / sale_items      — transactions and their line items (bridge table)
  chat_messages           — the store's WhatsApp-style group chat
  analysis_runs           — analytics "Run Analysis" lifecycle + lock
  analytics_snapshots     — frozen, versioned analytics results per run
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, Date, Time, Text,
    DateTime, JSON, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------
# 1. USER HIERARCHY (Joined Table Inheritance)
# ---------------------------------------------------------
class User(Base):
    """
    Base identity for every human in the system.

    Note: the password column stores a bcrypt HASH, never the raw
    password (see services.hash_password).
    """
    __tablename__ = 'users'

    user_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone_number = Column(String(50))
    address = Column(Text)
    password = Column(String(255), nullable=False)
    photo = Column(String(550))

    # Discriminator: 'owner' | 'employee' — decides which subclass a row
    # is loaded as, and acts as the single role flag used by deps.py.
    user_type = Column(String(50))

    __mapper_args__ = {
        'polymorphic_on': user_type,
        'polymorphic_identity': 'user',
    }


class Owner(User):
    """Store owner: extra column store_name; owns employees and the chat."""
    __tablename__ = 'owners'

    user_id = Column(Integer, ForeignKey('users.user_id'), primary_key=True)
    store_name = Column(String(255))

    # Explicit join condition: employees point at me via their
    # employer_id column (not via user_id, which is what SQLAlchemy
    # would otherwise guess from the inheritance setup).
    employees = relationship(
        "Employee",
        primaryjoin="Owner.user_id == Employee.employer_id",
        back_populates="employer",
    )

    __mapper_args__ = {
        'polymorphic_identity': 'owner',
    }


class Employee(User):
    """Staff member: position/salary, and a link to the owner they work for."""
    __tablename__ = 'employees'

    user_id = Column(Integer, ForeignKey('users.user_id'), primary_key=True)
    position = Column(String(100))
    salary = Column(Float)
    date_appointed = Column(Date, default=date.today)

    employer_id = Column(Integer, ForeignKey('owners.user_id'))

    employer = relationship(
        "Owner",
        primaryjoin="Owner.user_id == Employee.employer_id",
        back_populates="employees",
    )
    # Sales processed by this employee (Sale.employee points at ANY User).
    sales = relationship(
        "Sale",
        primaryjoin="Employee.user_id == Sale.employee_id",
        foreign_keys="Sale.employee_id",
    )

    __mapper_args__ = {
        'polymorphic_identity': 'employee',
    }


# ---------------------------------------------------------
# 2. CORE ENTITIES (Customer & Product)
# ---------------------------------------------------------
class Customer(Base):
    """A buyer. Phone number is unique — it is the lookup key at the POS."""
    __tablename__ = 'customers'

    customer_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    phone_number = Column(String(50), unique=True, index=True, nullable=False)

    sales = relationship("Sale", back_populates="customer")


class Product(Base):
    """Inventory item. Retail price drives receipts; cost price drives profit."""
    __tablename__ = 'products'

    product_id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String(255), nullable=False)

    cost_price = Column(Float, nullable=False)
    retail_price = Column(Float, nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)

    category = Column(String(100))
    supplier_name = Column(String(255))
    photo = Column(String(550))
    date = Column(Date, default=date.today)

    sale_items = relationship("SaleItem", back_populates="product")


# ---------------------------------------------------------
# 3. TRANSACTION ENTITIES (Sale & SaleItem bridge)
# ---------------------------------------------------------
class Sale(Base):
    """
    One checkout transaction.

    employee_id references users (not employees) so that sales remain
    attached even after role changes; it is nullable because past
    employees can be deleted while their sales survive (services.
    delete_employee detaches them first).
    """
    __tablename__ = 'sales'

    transaction_id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, default=date.today)
    time = Column(Time, default=lambda: datetime.now().time())
    payment_method = Column(String(50), nullable=False)
    total_revenue = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)

    # Foreign keys
    employee_id = Column(Integer, ForeignKey('users.user_id'), nullable=True)
    customer_id = Column(Integer, ForeignKey('customers.customer_id'))

    # ORM relationships
    employee = relationship("User", foreign_keys=[employee_id], viewonly=True)
    customer = relationship("Customer", back_populates="sales")
    items = relationship(
        "SaleItem", back_populates="sale", cascade="all, delete-orphan"
    )


class SaleItem(Base):
    """
    Bridge row: how many of which product were in one sale.

    Both prices are SNAPSHOTTED at sale time so later price edits never
    rewrite history on receipts or reports.
    """
    __tablename__ = 'sale_items'

    # Composite primary key joining Sale and Product
    transaction_id = Column(Integer, ForeignKey('sales.transaction_id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.product_id'), primary_key=True)

    quantity = Column(Integer, nullable=False)
    retail_price_at_sale = Column(Float, nullable=False)  # locked-in customer price
    cost_price_at_sale = Column(Float, nullable=False)    # locked-in supplier cost

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")


# ---------------------------------------------------------
# 4. STORE CHAT (WhatsApp-style group for owner + employees)
# ---------------------------------------------------------
class ChatMessage(Base):
    """
    One message in the store's group chat.

    owner_id identifies WHICH store's chat a message belongs to (the
    owner's user_id). It is deliberately a plain column, not a foreign
    key, so the chat history survives even if the owner account is ever
    removed.
    """
    __tablename__ = 'chat_messages'

    message_id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, index=True)  # store / group identifier
    sender_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    body = Column(Text, nullable=False)
    # Optional message being replied to (WhatsApp-style quote)
    reply_to_id = Column(Integer, ForeignKey('chat_messages.message_id'), nullable=True)
    # Soft delete: row stays for thread integrity but renders as "deleted"
    deleted = Column(Integer, default=0, nullable=False)
    date = Column(Date, default=date.today, nullable=False)
    time = Column(Time, default=lambda: datetime.now().time(), nullable=False)

    sender = relationship("User", foreign_keys=[sender_id], viewonly=True)
    reply_to = relationship("ChatMessage", remote_side=[message_id], viewonly=True)


# ---------------------------------------------------------
# 5. ANALYTICS (Track A: batch analysis pipeline)
# ---------------------------------------------------------

def _uuid() -> str:
    """Fresh UUID string for analysis run ids."""
    return str(uuid.uuid4())


class AnalysisRun(Base):
    """
    One "Run Analysis" click — lifecycle record AND concurrency lock.

    Lifecycle: QUEUED -> RUNNING -> COMPLETED | FAILED.

    Locking rule: POST /analytics/run is rejected with 409 while any row
    for this owner is QUEUED or RUNNING, so two runs can never race.
    failure_reason is filled on FAILED (including watchdog timeouts).
    """
    __tablename__ = 'analysis_runs'

    id = Column(String(36), primary_key=True, default=_uuid)
    owner_id = Column(Integer, ForeignKey('owners.user_id'), index=True, nullable=False)

    status = Column(String(20), nullable=False, default='QUEUED')
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)


class AnalyticsSnapshot(Base):
    """
    Frozen, versioned analytics output — one row per run/section/period.

    Insert-per-run (never update-in-place):
      - The "+X% vs last period" delta can also be computed across runs.
      - History accumulates for free (trend across many runs).
      - UNIQUE(run_id, section, period_type) prevents double writes.

    The dashboard read path is always "latest completed row per
    section/period for this owner" — a single indexed lookup, never a
    live aggregation. `data` holds the section's JSON payload (already
    pruned to what the charts need).
    """
    __tablename__ = 'analytics_snapshots'

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(36), ForeignKey('analysis_runs.id'), nullable=False)
    owner_id = Column(Integer, ForeignKey('owners.user_id'), index=True, nullable=False)

    # 'sales' | 'employees' | 'products' | 'insights'
    section = Column(String(20), nullable=False)
    # 'day' | 'week' | 'month'
    period_type = Column(String(10), nullable=False)

    data = Column(JSON, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('run_id', 'section', 'period_type',
                         name='uq_snapshot_run_section_period'),
    )
