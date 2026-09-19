from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
import deps
from database import get_db

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("/", response_model=schemas.CustomerResponse)
def create_customer(
    customer: schemas.CustomerCreate,
    current_user=Depends(deps.require_any),     # both roles (POS quick-add)
    db: Session = Depends(get_db),
):
    """Quick-add customer at the POS terminal (both roles)."""
    return services.create_customer(db=db, customer=customer)


@router.get("/", response_model=List[schemas.CustomerSpendResponse])
def get_customers(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_owner),   # OWNER ONLY (directory w/ lifetime spend)
    db: Session = Depends(get_db),
):
    """Owner-only: full customer directory with lifetime spend."""
    return services.get_customers_with_spend(db=db, skip=skip, limit=limit)


@router.get("/phone/{phone_number}", response_model=schemas.CustomerResponse)
def get_customer_by_phone(
    phone_number: str,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """POS lookup by phone (both roles)."""
    customer = services.get_customer_by_phone(db=db, phone_number=phone_number)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/{customer_id}", response_model=schemas.CustomerResponse)
def update_customer(
    customer_id: int,
    update_data: schemas.CustomerUpdate,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    return services.update_customer_name(db=db, customer_id=customer_id, new_name=update_data.name)


@router.get("/{customer_id}/history", response_model=List[schemas.SaleSummary])
def get_customer_history(
    customer_id: int,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Purchase history (both roles)."""
    sales = services.get_customer_sales(db=db, customer_id=customer_id)
    if not sales:
        raise HTTPException(status_code=404, detail="No purchase history found for this customer.")
    return sales
