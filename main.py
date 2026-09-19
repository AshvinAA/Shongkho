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
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from routes import auth, products, sales, customers, employees
import deps

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
app.include_router(sales.sales_router)


# ---------------------------------------------------------
# AUTH CHECK FUNCTIONS (implemented in deps.py)
# ---------------------------------------------------------

get_current_user = deps.get_current_user
get_current_owner = deps.require_owner
get_current_employee = deps.require_any
get_optional_user = deps.get_optional_user


# ---------------------------------------------------------
# UI ROUTES
# ---------------------------------------------------------

@app.get("/", tags=["UI"])
def serve_home(request: Request, user=Depends(get_optional_user)):
    # Send users straight to the right dashboard
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user["role"] == "owner":
        return RedirectResponse(url="/owner-dashboard", status_code=302)
    return RedirectResponse(url="/employee-dashboard", status_code=302)

@app.get("/pos", tags=["UI"])
def serve_pos(request: Request, user=Depends(get_optional_user)):
    # POS terminal — both roles can ring up sales
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="pos.html", context={"request": request, "user": user}
    )

@app.get("/inventory", tags=["UI"])
def serve_products(request: Request, user=Depends(get_optional_user)):
    # Inventory — both roles can view; owner gets edit buttons (in template)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="products.html", context={"request": request, "user": user}
    )

@app.get("/customers", tags=["UI"])
@app.get("/customers-ui", tags=["UI"])
def serve_customers(request: Request, user=Depends(get_optional_user)):
    # Customers — both roles can look up customers & purchase history
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="customers.html", context={"request": request, "user": user}
    )

@app.get("/staff", tags=["UI"])
def serve_employees(request: Request, user=Depends(get_optional_user)):
    # OWNER ONLY — employees are redirected to their dashboard
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user["role"] != "owner":
        return RedirectResponse(url="/employee-dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request, name="employees.html", context={"request": request, "user": user}
    )

@app.get("/login", tags=["UI"])
def serve_login(request: Request, user=Depends(get_optional_user)):
    # Already logged in? Go straight to the right dashboard.
    if user:
        if user["role"] == "owner":
            return RedirectResponse(url="/owner-dashboard", status_code=302)
        return RedirectResponse(url="/employee-dashboard", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/register", tags=["UI"])
def serve_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@app.get("/sales", tags=["UI"])
def serve_sales(request: Request, user=Depends(get_optional_user)):
    # Sales history: owner sees all, employee sees only their own (filtered by API)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="sales.html", context={"request": request, "user": user}
    )


# ---------------------------------------------------------
# UI ROUTES — Dashboards
# ---------------------------------------------------------

@app.get("/owner-dashboard", tags=["UI"])
def serve_owner_dashboard(request: Request, user=Depends(get_optional_user)):
    # Owners only — employees land on their own dashboard
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user["role"] != "owner":
        return RedirectResponse(url="/employee-dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "user": user}
    )

@app.get("/employee-dashboard", tags=["UI"])
def serve_employee_dashboard(request: Request, user=Depends(get_optional_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user["role"] == "owner":
        return RedirectResponse(url="/owner-dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "user": user}
    )