"""
Shared dependencies — the single source of truth for authentication and
role-based access, plus the runtime path constant for uploaded files.

Roles and their access level:
  - owner    : full access to everything (inventory, staff, reports, chat)
  - employee : read-only data + checkout + customer lookup + chat

Auth model:
  We use server-side sessions (Starlette SessionMiddleware), not JWTs.
  After /auth/login the session cookie carries `user_id`, `role` and
  `name`. Every request re-reads those keys via get_current_user.
"""
import os

from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

import models

# Make backend/ importable for `from database import get_db` below.
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db  # noqa: E402

# Absolute path of the backend/ folder on disk.
#
# Uploads (profile pictures, product pictures) and the /static mount are
# resolved relative to THIS path instead of the current working directory,
# so the server behaves identically whether uvicorn is started from
# backend/ or from the repository root.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    """
    Read the logged-in user from the session cookie AND verify the
    account still exists in the database.

    The DB check matters: sessions are signed cookies, so a session
    survives on the client after the account is deleted (or a role is
    flipped). Re-validating on every request makes deleted accounts
    immediately inert. Costs one primary-key lookup per request.

    Raises 401 when nobody is logged in (or the account vanished).
    Returns a plain dict ({id, role, name}) rather than an ORM object so
    permission checks stay cheap and predictable.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not logged in",
        )

    user = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user:
        # Account deleted while the cookie was still in the jar.
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session no longer valid",
        )

    # The DATABASE is the source of truth for the role — not the cookie —
    # so a role change (owner <-> employee) applies on the next request.
    return {
        "id": user.user_id,
        "role": user.user_type,
        "name": user.name,
    }


def require_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Owner-only gate. Use on every route that mutates money- or
    staff-related data (inventory CRUD, employee CRUD, reports).
    Employees receive a strict 403.
    """
    if current_user["role"] != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owners only",
        )
    return current_user


def require_any(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Any authenticated user with a known role (owner or employee).
    Used for shared endpoints: product listings, checkout, chat, etc.
    """
    if current_user["role"] not in ("owner", "employee"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown role",
        )
    return current_user
