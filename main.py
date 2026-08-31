from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

# Import our local files
import schemas
import services
from database import get_db

# Initialize the FastAPI app
app = FastAPI(title="Store POS API", version="1.0")

# ---------------------------------------------------------
# CORS CONFIGURATION
# ---------------------------------------------------------
# This is crucial for connecting your frontend UI to this backend.
# It allows your HTML/JS, Bootstrap, or React frontend running on a different 
# port (like localhost:3000) to safely make fetch() requests to this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace "*" with your actual frontend URL
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],
)

# ---------------------------------------------------------
# ROOT ENDPOINT
# ---------------------------------------------------------
@app.get("/")
def read_root():
    return {"Welcome to the POS System API. The server is running successfully!"}

# ---------------------------------------------------------
# EMPLOYEE ROUTES
# ---------------------------------------------------------
@app.post("/employees/", response_model=schemas.EmployeeResponse)
def create_employee(employee: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    return services.create_employee(db=db, employee=employee)

@app.get("/employees/search/", response_model=List[schemas.EmployeeResponse])
def search_employees(query: str, db: Session = Depends(get_db)):
    results = services.search_employees(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No employees found matching that search.")
    return results

# ---------------------------------------------------------
# PRODUCT ROUTES
# ---------------------------------------------------------
@app.post("/products/", response_model=schemas.ProductResponse)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    return services.create_product(db=db, product=product)

@app.get("/products/", response_model=List[schemas.ProductResponse])
def get_products(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return services.get_products(db=db, skip=skip, limit=limit)

@app.get("/products/search/", response_model=List[schemas.ProductResponse])
def search_products(query: str, db: Session = Depends(get_db)):
    results = services.search_products(db=db, search_term=query)
    if not results:
        raise HTTPException(status_code=404, detail="No products found matching that search.")
    return results

# ---------------------------------------------------------
# CUSTOMER ROUTES
# ---------------------------------------------------------
@app.post("/customers/", response_model=schemas.CustomerResponse)
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    return services.create_customer(db=db, customer=customer)

@app.get("/customers/", response_model=List[schemas.CustomerResponse])
def get_customers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return services.get_customers(db=db, skip=skip, limit=limit)

@app.get("/customers/phone/{phone_number}", response_model=schemas.CustomerResponse)
def get_customer_by_phone(phone_number: str, db: Session = Depends(get_db)):
    customer = services.get_customer_by_phone(db=db, phone_number=phone_number)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

# 2. Update customer name (Fired if cashier clicks "Update to New Name")
@app.put("/customers/{customer_id}", response_model=schemas.CustomerResponse)
def update_customer(customer_id: int, update_data: schemas.CustomerUpdate, db: Session = Depends(get_db)):
    return services.update_customer_name(db=db, customer_id=customer_id, new_name=update_data.name)

# 3. Get Customer Purchase History (To show previous receipts on their profile)
@app.get("/customers/{customer_id}/history", response_model=List[schemas.SaleResponse])
def get_customer_history(customer_id: int, db: Session = Depends(get_db)):
    sales = services.get_customer_sales(db=db, customer_id=customer_id)
    if not sales:
        raise HTTPException(status_code=404, detail="No purchase history found for this customer.")
    return sales

# ---------------------------------------------------------
# CHECKOUT / SALE ROUTE
# ---------------------------------------------------------
@app.post("/checkout/", response_model=schemas.SaleResponse)
def process_checkout(sale_data: schemas.SaleCreate, db: Session = Depends(get_db)):
    try:
        # Hand the validated JSON over to our business logic
        new_sale = services.create_sale(db=db, sale_data=sale_data)
        return new_sale
    except HTTPException as e:
        # Pass through any specific errors (like Product Not Found)
        raise e
    except Exception as e:
        # Catch any other database errors
        raise HTTPException(status_code=400, detail=f"Checkout failed: {str(e)}")

