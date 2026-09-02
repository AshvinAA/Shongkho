from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from fastapi.templating import Jinja2Templates

# Import our modular routers
from routes import auth, products, sales, customers, employees

app = FastAPI(title="Store POS API", version="2.0")

#Mounting the static files
app.mount("/static" , StaticFiles(directory= "static") , name="static")

#Template directory for Jinja2
templates = Jinja2Templates(directory="templates")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registering all route files
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(products.router)
app.include_router(customers.router)
app.include_router(sales.router)

# ---------------------------------------------------------
# UI ROUTES (Serving HTML Pages)
# ---------------------------------------------------------
# ---------------------------------------------------------
# UI ROUTES (Serving HTML Pages)
# ---------------------------------------------------------

@app.get("/", tags=["UI"])
def serve_home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/pos", tags=["UI"])
def serve_pos(request: Request):
    return templates.TemplateResponse(request=request, name="pos.html")

@app.get("/inventory", tags=["UI"])
def serve_products(request: Request):
    return templates.TemplateResponse(request=request, name="products.html")

@app.get("/customers-ui", tags=["UI"])
def serve_customers(request: Request):
    return templates.TemplateResponse(request=request, name="customers.html")

@app.get("/staff", tags=["UI"])
def serve_employees(request: Request):
    return templates.TemplateResponse(request=request, name="employees.html")

@app.get("/login", tags=["UI"])
def serve_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")



