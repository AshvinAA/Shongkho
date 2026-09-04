from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
from database import get_db

router = APIRouter(prefix="/employees", tags=["Employees"])

@router.post("/", response_model=schemas.EmployeeResponse)
def create_employee(employee: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    # Re-use the existing registration logic!
    return services.register_user(db=db, user_data=employee)

@router.get("/search/", response_model=List[schemas.EmployeeResponse])
def search_employees(query: str, db: Session = Depends(get_db)):
    results = services.search_employees(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No employees found matching that search.")
    return results

@router.get("/", response_model=List[schemas.EmployeeResponse])
def get_employees(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return services.get_employees(db=db, skip=skip, limit=limit)
