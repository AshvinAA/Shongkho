from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
import deps
from database import get_db

router = APIRouter(prefix="/checkout", tags=["Sales & Checkout"])


@router.post("/", response_model=schemas.SaleResponse)
def process_checkout(
    sale_data: schemas.SaleCreate,
    current_user=Depends(deps.require_any),     # both roles can ring up sales
    db: Session = Depends(get_db),
):
    """Checkout — employee identity is taken from the session, never the body."""
    try:
        new_sale = services.create_sale(db=db, sale_data=sale_data, current_user=current_user)
        return new_sale
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Checkout failed: {str(e)}")


# ---------------------------------------------------------
# Sales history & receipts (shared router for listing)
# ---------------------------------------------------------
sales_router = APIRouter(prefix="/sales", tags=["Sales & Checkout"])


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
    """Receipt for one transaction. Employees can only view their own."""
    receipt = services.get_sale_receipt(db=db, transaction_id=transaction_id)
    if current_user["role"] != "owner" and receipt.get("employee_id") != current_user["id"]:
        # employee looking at someone else's receipt
        raise HTTPException(status_code=403, detail="You can only view your own receipts")
    return receipt
