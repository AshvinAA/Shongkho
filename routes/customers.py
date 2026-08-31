from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
from database import get_db

router = APIRouter(prefix="/customers", tags=["Customers"])

@router.post("/", response_model=schemas.CustomerResponse)
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    return services.create_customer(db=db, customer=customer)

@router.get("/", response_model=List[schemas.CustomerResponse])
def get_customers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return services.get_customers(db=db, skip=skip, limit=limit)


@router.get("/phone/{phone_number}", response_model=schemas.CustomerResponse)
def get_customer_by_phone(phone_number: str, db: Session = Depends(get_db)):
    customer = services.get_customer_by_phone(db=db, phone_number=phone_number)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

@router.put("/{customer_id}", response_model=schemas.CustomerResponse)
def update_customer(customer_id: int, update_data: schemas.CustomerUpdate, db: Session = Depends(get_db)):
    return services.update_customer_name(db=db, customer_id=customer_id, new_name=update_data.name)

@router.get("/{customer_id}/history", response_model=List[schemas.SaleResponse])
def get_customer_history(customer_id: int, db: Session = Depends(get_db)):
    sales = services.get_customer_sales(db=db, customer_id=customer_id)
    if not sales:
        raise HTTPException(status_code=404, detail="No purchase history found for this customer.")
    return sales
