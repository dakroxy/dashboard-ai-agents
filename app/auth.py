from __future__ import annotations

import uuid

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    client_kwargs={"scope": "openid email profile"},
)


def _load_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None
    return db.query(User).filter(User.id == uid).first()


def get_optional_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    return _load_user(request, db)


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = _load_user(request, db)
    if user is None:
        # Session abgelaufen oder User weg -> Redirect auf Login
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/google/login"},
        )
    if user.disabled_at is not None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dein Account wurde deaktiviert. Bitte wende dich an einen Admin.",
        )
    return user
