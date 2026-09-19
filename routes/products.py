from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import schemas
import services
import deps
from database import get_db

router = APIRouter(prefix="/products", tags=["Products"])


@router.post("/", response_model=schemas.ProductResponse)
def create_product(
    product: schemas.ProductCreate,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: add a new product to inventory."""
    return services.create_product(db=db, product=product)


@router.get("/", response_model=List[schemas.ProductResponse])
def get_products(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(deps.require_any),     # both roles
    db: Session = Depends(get_db),
):
    """List products — available to owner and employee (read-only)."""
    return services.get_products(db=db, skip=skip, limit=limit)


@router.get("/search/", response_model=List[schemas.ProductResponse])
def search_products(
    query: str,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    results = services.search_products(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No products found matching that search.")
    return results


@router.get("/{product_id}", response_model=schemas.ProductResponse)
def get_product(
    product_id: int,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Product details — both roles."""
    return services.get_product(db=db, product_id=product_id)


@router.put("/{product_id}", response_model=schemas.ProductResponse)
def update_product(
    product_id: int,
    updates: schemas.ProductUpdate,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: edit product details/prices."""
    return services.update_product(db=db, product_id=product_id, updates=updates)


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: remove a product."""
    return services.delete_product(db=db, product_id=product_id)


@router.patch("/{product_id}/stock", response_model=schemas.ProductResponse)
def update_stock(
    product_id: int,
    payload: schemas.StockUpdate,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: update stock (+/-)."""
    return services.update_stock(db=db, product_id=product_id, quantity_change=payload.quantity_change)
