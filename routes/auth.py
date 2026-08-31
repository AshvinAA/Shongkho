
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import schemas
import services
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=schemas.EmployeeResponse)
def register_user(employee: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    return services.create_employee(db=db, employee=employee)

@router.post("/login")
def login():
    return {"message": "Login endpoint placeholder"}
