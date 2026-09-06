# from fastapi import FastAPI,Request
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles 
# from fastapi.templating import Jinja2Templates
# from fastapi import Request
# from fastapi import Depends, HTTPException, status
# # Example security dependency pattern:
# # @app.get("/owner-dashboard")
# # def owner_dash(request: Request, current_user = Depends(get_current_owner)):
# #     return templates.TemplateResponse("owner_dashboard.html", {"request": request, "user": current_user})


# # Import our modular routers
# from routes import auth, products, sales, customers, employees

# app = FastAPI(title="Store POS API", version="2.0")

# #Mounting the static files
# app.mount("/static" , StaticFiles(directory= "static") , name="static")

# #Template directory for Jinja2
# templates = Jinja2Templates(directory="templates")

# # CORS Setup
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # Registering all route files
# app.include_router(auth.router)
# app.include_router(employees.router)
# app.include_router(products.router)
# app.include_router(customers.router)
# app.include_router(sales.router)

# # ---------------------------------------------------------
# # UI ROUTES (Serving HTML Pages)
# # ---------------------------------------------------------
# # ---------------------------------------------------------
# # UI ROUTES (Serving HTML Pages)
# # ---------------------------------------------------------

# @app.get("/", tags=["UI"])
# def serve_home(request: Request):
#     return templates.TemplateResponse(request=request, name="index.html")

# @app.get("/pos", tags=["UI"])
# def serve_pos(request: Request):
#     return templates.TemplateResponse(request=request, name="pos.html")

# @app.get("/inventory", tags=["UI"])
# def serve_products(request: Request):
#     return templates.TemplateResponse(request=request, name="products.html")

# @app.get("/customers-ui", tags=["UI"])
# def serve_customers(request: Request):
#     return templates.TemplateResponse(request=request, name="customers.html")

# @app.get("/staff", tags=["UI"])
# def serve_employees(request: Request):
#     return templates.TemplateResponse(request=request, name="employees.html")

# @app.get("/login", tags=["UI"])
# def serve_login(request: Request):
#     return templates.TemplateResponse(request=request, name="login.html")

# @app.get("/register", tags=["UI"])
# def serve_register(request: Request):
#     return templates.TemplateResponse(request=request, name="register.html")






# @app.get("/owner-dashboard", tags=["UI"])
# def serve_owner_dashboard(request: Request):
#     # Pass owner context to the shared template
#     return templates.TemplateResponse(
#         name="dashboard.html", 
#         context={
#             "request": request, 
#             "user": {"name": "Owner", "role": "owner"}
#         }
#     )

# @app.get("/employee-dashboard", tags=["UI"])
# def serve_employee_dashboard(request: Request):
#     # Pass employee context to the shared template
#     return templates.TemplateResponse(
#         name="dashboard.html", 
#         context={
#             "request": request, 
#             "user": {"name": "Employee", "role": "employee"}
#         }
#     )
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from routes import auth, products, sales, customers, employees

app = FastAPI(title="Store POS API", version="2.0")

# Session middleware — login state 
app.add_middleware(SessionMiddleware, secret_key="CHANGE-THIS-TO-A-LONG-RANDOM-SECRET-STRING")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(products.router)
app.include_router(customers.router)
app.include_router(sales.router)


# ---------------------------------------------------------
# AUTH CHECK FUNCTIONS 
# ---------------------------------------------------------

def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    name = request.session.get("name")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not logged in"
        )

    return {"id": user_id, "role": role, "name": name}


def get_current_owner(current_user = Depends(get_current_user)):
    if current_user["role"] != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owners only"
        )
    return current_user


def get_current_employee(current_user = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------
# UI ROUTES
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

@app.get("/register", tags=["UI"])
def serve_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


# ---------------------------------------------------------
# UI ROUTES — Dashboards
# ---------------------------------------------------------

@app.get("/owner-dashboard", tags=["UI"])
def serve_owner_dashboard(request: Request, current_user = Depends(get_current_owner)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "user": current_user}
    )

@app.get("/employee-dashboard", tags=["UI"])
def serve_employee_dashboard(request: Request, current_user = Depends(get_current_employee)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "user": current_user}
    )