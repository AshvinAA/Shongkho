from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import our modular routers
from routes import auth, products, sales, customers, employees

app = FastAPI(title="Store POS API", version="2.0")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
def read_root():
    return {"message": "Modular Store POS API is running successfully!"}

# Registering all route files
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(products.router)
app.include_router(customers.router)
app.include_router(sales.router)
