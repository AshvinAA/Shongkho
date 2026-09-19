"""
Shared auth dependencies — the single source of truth for role-based access.

Roles:
  - owner    : full access to everything
  - employee : read-only + checkout + customer lookup
"""
from fastapi import Depends, HTTPException, status, Request

# ---------------------------------------------------------
# CORE AUTH (session based)
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


def get_optional_user(request: Request):
    """Like get_current_user but returns None instead of raising.

    Used by HTML page routes so anonymous visitors can be redirected
    to /login instead of getting a 500 error."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return {
        "id": user_id,
        "role": request.session.get("role"),
        "name": request.session.get("name"),
    }


def require_owner(current_user=Depends(get_current_user)):
    """Owner-only access. Raises 403 for employees."""
    if current_user["role"] != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owners only"
        )
    return current_user


def require_any(current_user=Depends(get_current_user)):
    """Any logged-in user (owner or employee)."""
    if current_user["role"] not in ("owner", "employee"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown role"
        )
    return current_user


# Backward-compatible aliases used by main.py UI routes
get_current_owner = require_owner
get_current_employee = require_any
