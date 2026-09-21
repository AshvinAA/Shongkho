"""
Product (inventory) routes.

Permissions at a glance:
  - POST /, PUT /{id}, DELETE /{id}, PATCH /{id}/stock, POST /{id}/photo  -> owner only
  - GET /, GET /{id}, GET /search, GET /categories                        -> both roles
"""
import os
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from typing import List

import deps
import models
import schemas
import services
from database import get_db

router = APIRouter(prefix="/products", tags=["Products"])

# Content types we accept for product pictures, mapped to file extensions.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


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
    """Search products by name or category (both roles)."""
    results = services.search_products(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No products found matching that search.")
    return results


@router.get("/categories", response_model=List[str])
def get_categories(
    current_user=Depends(deps.require_any),     # both roles
    db: Session = Depends(get_db),
):
    """Distinct category names already used by products (for autocomplete)."""
    rows = (
        db.query(models.Product.category)
        .filter(models.Product.category.isnot(None))
        .distinct()
        .all()
    )
    # Deduplicate + sort; ignore blank/whitespace-only categories.
    categories = sorted({(row[0] or "").strip() for row in rows if row[0] and row[0].strip()})
    return categories


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
    """Owner-only: remove a product (refused if it has sales)."""
    return services.delete_product(db=db, product_id=product_id)


@router.patch("/{product_id}/stock", response_model=schemas.ProductResponse)
def update_stock(
    product_id: int,
    payload: schemas.StockUpdate,
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """Owner-only: adjust stock by a delta (+/-), never below zero."""
    return services.update_stock(db=db, product_id=product_id, quantity_change=payload.quantity_change)


@router.post("/{product_id}/photo", response_model=schemas.ProductResponse)
def upload_product_photo(
    product_id: int,
    file: UploadFile = File(...),
    current_user=Depends(deps.require_owner),   # OWNER ONLY
    db: Session = Depends(get_db),
):
    """
    Owner-only: upload (or replace) the product picture.

    The file is stored under backend/static/product_pics/ and the DB row
    keeps a cache-busting URL (/static/product_pics/product_{id}.jpg?v=...).
    """
    ext = ALLOWED_IMAGE_TYPES.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP or GIF images are allowed.")

    contents = file.file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5 MB).")

    product = services.get_product(db=db, product_id=product_id)

    # Delete the previous picture (only files we manage) to save disk.
    if product.photo and product.photo.startswith("/static/product_pics/"):
        old_path = product.photo.split("?")[0].lstrip("/")
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    upload_dir = os.path.join(deps.BASE_DIR, "static", "product_pics")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"product_{product_id}{ext}"
    with open(os.path.join(upload_dir, filename), "wb") as out:
        out.write(contents)

    # Cache-busting version so browsers refresh the image after an edit.
    photo_url = f"/static/product_pics/{filename}?v={int(time.time())}"
    updates = schemas.ProductUpdate(photo=photo_url)
    return services.update_product(db=db, product_id=product_id, updates=updates)
