from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import os
import time
import services
import schemas
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


ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


@router.post("/{product_id}/photo", response_model=schemas.ProductResponse)
def upload_product_photo(
    product_id: int,
    file: UploadFile = File(...),
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: upload a picture for a product and set it as its photo."""
    ext = ALLOWED_IMAGE_TYPES.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP or GIF images are allowed.")

    contents = file.file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 2 MB).")

    upload_dir = os.path.join("static", "product_pics")
    os.makedirs(upload_dir, exist_ok=True)

    product = services.get_product(db=db, product_id=product_id)

    # Remove the previous picture (only files we manage)
    if product.photo and product.photo.startswith("/static/product_pics/"):
        old_path = product.photo.lstrip("/")
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    filename = f"product_{product_id}{ext}"
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as out:
        out.write(contents)

    product.photo = f"/static/product_pics/{filename}?v={int(time.time())}"
    db.commit()
    db.refresh(product)
    return product


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
