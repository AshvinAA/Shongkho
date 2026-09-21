"""
Store group chat routes (owner + employees of one store).

All three endpoints require any logged-in user; the service layer scopes
every operation to the caller's store and enforces "only delete your own
messages".
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import deps
import schemas
import services
from database import get_db

router = APIRouter(prefix="/chat", tags=["Store Chat"])


@router.get("/messages", response_model=List[schemas.ChatMessageResponse])
def list_chat_messages(
    after_id: int = 0,
    limit: int = 200,
    current_user=Depends(deps.require_any),   # owner and employee, one group per store
    db: Session = Depends(get_db),
):
    """
    Store group chat history (oldest -> newest).

    Pass `after_id` to fetch only newer messages — the client polls with
    the last message id it rendered, keeping the payload tiny.
    """
    try:
        return services.get_chat_messages(
            db=db,
            user_id=current_user["id"],
            role=current_user["role"],
            after_id=after_id,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - convert unexpected errors to a clean 500
        raise HTTPException(status_code=500, detail=f"Could not load chat: {e}")


@router.post("/messages", response_model=schemas.ChatMessageResponse, status_code=201)
def post_chat_message(
    payload: schemas.ChatMessageCreate,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Send a message to the store group chat (set reply_to_id to quote)."""
    try:
        return services.send_chat_message(
            db=db,
            user_id=current_user["id"],
            role=current_user["role"],
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not send message: {e}")


@router.delete("/messages/{message_id}")
def remove_chat_message(
    message_id: int,
    current_user=Depends(deps.require_any),
    db: Session = Depends(get_db),
):
    """Delete your own message (shows as 'message deleted' to everyone)."""
    result = services.delete_chat_message(
        db=db, user_id=current_user["id"], message_id=message_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Message not found")
    return result
