
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
    # 1. Authenticate the user (uses the service function from earlier)
    user = services.authenticate_user(db, user_credentials.phone_number, user_credentials.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect phone number or password"
        )
        
    # 2. Create the JWT Token
    access_token = services.create_access_token(
        data={"sub": str(user.user_id), "role": user.user_type}
    )
    
    # 3. Return the token and some basic user info for the UI
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "role": user.user_type,
        "name": user.name
    }