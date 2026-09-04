
from fastapi import APIRouter, Depends, HTTPException , status
from sqlalchemy.orm import Session
import schemas
import services
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=schemas.EmployeeResponse, status_code=status.HTTP_201_CREATED)
def register_account(user_data: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    # This matches the services.register_user function from Batch 2 perfectly!
    return services.register_user(db=db, user_data=user_data)

@router.post("/login")
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    # Just pass the credentials straight to the service function!
    # The service will handle the password check and return the raw user data.
    return services.process_login(db=db, user_credentials=user_credentials)