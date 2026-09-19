from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
import deps
from database import get_db

router = APIRouter(prefix="/employees", tags=["Employees"])


@router.get("/", response_model=List[schemas.EmployeeResponse])
def get_employees(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: list all employees."""
    return services.get_employees(db=db, skip=skip, limit=limit)


@router.get("/search/", response_model=List[schemas.EmployeeResponse])
def search_employees(
    query: str,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    results = services.search_employees(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No employees found matching that search.")
    return results


@router.get("/performance", response_model=List[schemas.EmployeePerformance])
def sales_performance(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: revenue/profit per employee."""
    return services.get_sales_performance(db=db, skip=skip, limit=limit)


@router.put("/{user_id}", response_model=schemas.EmployeeResponse)
def update_employee(
    user_id: int,
    updates: schemas.EmployeeUpdate,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: update employee info / role."""
    return services.update_employee(db=db, employee_user_id=user_id, updates=updates)


@router.delete("/{user_id}")
def delete_employee(
    user_id: int,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: delete an employee account."""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    return services.delete_employee(db=db, employee_user_id=user_id)
