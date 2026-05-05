from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import oauth
from app.config import settings
from app.db import get_db
from app.models import Role, User
from app.services.audit import audit
from app.templating import _SIDEBAR_WORKFLOWS_CACHE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_same_origin(request: Request) -> bool:
    """Logout-CSRF-Schutz: GET /auth/logout darf nur von Same-Origin-Referrer kommen.

    Hintergrund: ein <img src="https://dashboard.dbshome.de/auth/logout"> auf
    einer Drittseite wuerde sonst den eingeloggten User unbemerkt ausloggen
    (klassischer Logout-CSRF-DoS).

    Policy:
    - Same-Origin-Referer (host matcht) → erlaubt.
    - Cross-Origin-Referer → blockiert.
    - Kein Referer (User tippt URL direkt) → erlaubt; Browser senden bei
      address-bar-Navigation regelmaessig keinen Referer, das ist legitim.

    Reverse-Proxy: hinter Elestio/Nginx ist `request.url.hostname` oft der
    interne Container-Host. Wir matchen primaer gegen `X-Forwarded-Host` (vom
    Proxy gesetzt) und akzeptieren auch `settings.base_url`-Host als Whitelist,
    damit der Production-Logout funktioniert. Fallback ist weiterhin
    `request.url.hostname`.
    """
    referer = request.headers.get("referer")
    if not referer:
        return True
    try:
        ref_host = (urlparse(referer).hostname or "").lower()
    except (ValueError, AttributeError):
        return False
    if not ref_host:
        return False
    candidates: set[str] = set()
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        # X-Forwarded-Host darf eine Komma-separierte Liste sein — den ersten
        # Eintrag nehmen (der naechste Hop nach aussen).
        first = forwarded_host.split(",")[0].strip()
        # Port abschneiden, sofern enthalten (Host:Port).
        if first:
            candidates.add(first.split(":")[0].lower())
    if request.url.hostname:
        candidates.add(request.url.hostname.lower())
    base_url = getattr(settings, "base_url", None)
    if base_url:
        try:
            base_host = (urlparse(base_url).hostname or "").lower()
            if base_host:
                candidates.add(base_host)
        except (ValueError, AttributeError):
            pass
    return ref_host in candidates


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = f"{settings.base_url}/auth/google/callback"
    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        hd=settings.google_hosted_domain,
        prompt="select_account",
    )


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth-Fehler: {exc.error}",
        ) from exc

    userinfo = token.get("userinfo")
    if userinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google lieferte keine Nutzer-Info zurück.",
        )

    if userinfo.get("hd") != settings.google_hosted_domain:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Nur @{settings.google_hosted_domain}-Accounts sind zugelassen.",
        )
    if not userinfo.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="E-Mail-Adresse ist bei Google nicht verifiziert.",
        )

    sub: str = userinfo["sub"]
    email: str = userinfo["email"]
    name: str = userinfo.get("name") or email
    picture: str | None = userinfo.get("picture")
    now = datetime.now(timezone.utc)

    user = db.query(User).filter(User.google_sub == sub).first()
    is_new_user = user is None

    if user is None:
        user = User(
            id=uuid.uuid4(),
            google_sub=sub,
            email=email,
            name=name,
            picture=picture,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.email = email
        user.name = name
        user.picture = picture
        user.last_login_at = now

    # Default-Rolle vergeben (User ohne Rolle bekommt 'user', Bootstrap-Admin 'admin').
    initial_admins = settings.initial_admin_email_set
    if user.role_id is None:
        target_role_key = "admin" if email.lower() in initial_admins else "user"
        role = db.query(Role).filter(Role.key == target_role_key).first()
        if role is not None:
            user.role_id = role.id

    # Ab hier muss der User in der DB sein (inkl. neue Rolle), damit der
    # audit_log-Eintrag seinen FK auf users.id zuverlaessig aufloesen kann.
    # Ohne flush fuehrt is_new_user=True zu einer ForeignKeyViolation im commit,
    # weil der insert auf audit_log vor dem insert auf users ausgefuehrt werden kann.
    db.flush()

    # Disabled-Accounts kommen nicht rein — loggen und Fehler anzeigen.
    if user.disabled_at is not None:
        audit(
            db,
            user,
            "login_denied_disabled",
            entity_type="user",
            entity_id=user.id,
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dein Account wurde deaktiviert. Bitte wende dich an einen Admin.",
        )

    audit(
        db,
        user,
        "login_new_user" if is_new_user else "login",
        entity_type="user",
        entity_id=user.id,
        request=request,
    )

    db.commit()
    db.refresh(user)

    request.session["user_id"] = str(user.id)
    # Token bei jedem Login rotieren — schliesst Session-Fixation gegen CSRF
    # (Pre-Auth-Token wird verworfen, damit ein evtl. von extern injizierter
    # Anonym-Token nach Auth nicht mehr gilt).
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    if not _is_same_origin(request):
        # Cross-Origin-Trigger (z. B. <img src> aus Phishing-Tab) → ignorieren.
        # Kein Audit-Eintrag, kein Logout. User bleibt eingeloggt, redirect zu /.
        logger.warning(
            "logout-csrf-blocked: cross-origin referer=%r",
            request.headers.get("referer"),
        )
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    user_id = request.session.get("user_id")
    if user_id:
        try:
            uid = uuid.UUID(user_id)
            user = db.query(User).filter(User.id == uid).first()
            if user is not None:
                audit(
                    db,
                    user,
                    "logout",
                    entity_type="user",
                    entity_id=user.id,
                    request=request,
                )
                db.commit()
                _SIDEBAR_WORKFLOWS_CACHE.pop(user.id, None)
        except (ValueError, TypeError):
            pass
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
