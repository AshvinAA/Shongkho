"""
Sales & checkout routes.

The checkout endpoint is the POS core: the session user becomes the
recorded seller (never the request body), and the service layer handles
stock validation and atomic totals.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import deps
import schemas
import services
from database import get_db

# Checkout and sales listing live on separate routers because their
# prefixes differ (/checkout vs /sales) but share one domain.
router = APIRouter(prefix="/checkout", tags=["Sales & Checkout"])
sales_router = APIRouter(prefix="/sales", tags=["Sales & Checkout"])


@router.post("/", response_model=schemas.SaleResponse)
def process_checkout(
    sale_data: schemas.SaleCreate,
    current_user=Depends(deps.require_any),     # both roles can ring up sales
    db: Session = Depends(get_db),
):
    """
    Checkout: validate cart, deduct stock, record the sale — atomically.

    Employee identity comes from the session, prices from the DB.
    """
    try:
        return services.create_sale(db=db, sale_data=sale_data, current_user=current_user)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - surface a clean 400, not a 500
        raise HTTPException(status_code=400, detail=f"Checkout failed: {str(e)}")


@sales_router.get("/", response_model=List[schemas.SaleSummary])
def list_sales(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Owner: every transaction. Employee: only their own transactions."""
    return services.get_sales(db=db, current_user=current_user, skip=skip, limit=limit)


@sales_router.get("/reports/{period}", response_model=schemas.ReportResponse)
def sales_report(
    period: str,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: totals for daily / weekly / monthly periods."""
    return services.get_sales_report(db=db, period=period)


@sales_router.get("/{transaction_id}/receipt", response_model=schemas.ReceiptResponse)
def get_receipt(
    transaction_id: int,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """
    Receipt for one transaction.

    Employees may only view receipts for sales THEY processed; owners
    can view every receipt.
    """
    receipt = services.get_sale_receipt(db=db, transaction_id=transaction_id)
    if current_user["role"] != "owner" and receipt.get("employee_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="You can only view your own receipts")
    return receipt
