from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
from database import get_db

router = APIRouter(prefix="/products", tags=["Products"])

@router.post("/", response_model=schemas.ProductResponse)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    return services.create_product(db=db, product=product)

@router.get("/", response_model=List[schemas.ProductResponse])
def get_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return services.get_products(db=db, skip=skip, limit=limit)

@router.get("/search/", response_model=List[schemas.ProductResponse])
def search_products(query: str, db: Session = Depends(get_db)):
    results = services.search_products(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No products found matching that search.")
    return results
