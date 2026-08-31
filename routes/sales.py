from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import schemas
import services
from database import get_db

router = APIRouter(prefix="/checkout", tags=["Sales & Checkout"])

@router.post("/", response_model=schemas.SaleResponse)
def process_checkout(sale_data: schemas.SaleCreate, db: Session = Depends(get_db)):
    try:
        new_sale = services.create_sale(db=db, sale_data=sale_data)
        return new_sale
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Checkout failed: {str(e)}")
