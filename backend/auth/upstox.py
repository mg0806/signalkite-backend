from datetime import datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth.security import create_access_token, get_current_user
from config import settings
from db import get_db
from models import User
from services.crypto import decrypt_secret, encrypt_secret
from services.upstox_stream import get_upstox_stream_status

router = APIRouter(prefix="/auth/upstox", tags=["upstox-auth"])

AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
HOLDINGS_URL = "https://api.upstox.com/v2/portfolio/long-term-holdings"


def upstox_configured() -> bool:
    return bool(settings.upstox_api_key and settings.upstox_api_secret and settings.upstox_redirect_url)


@router.get("/status")
def status() -> dict[str, bool]:
    return {"upstox_configured": upstox_configured()}


@router.get("/login")
def login():
    if not upstox_configured():
        return HTMLResponse(
            """
            <html>
              <body style="font-family: system-ui; padding: 32px;">
                <h1>Upstox login is not configured</h1>
                <p>Add UPSTOX_API_KEY, UPSTOX_API_SECRET, and UPSTOX_REDIRECT_URL.</p>
              </body>
            </html>
            """,
            status_code=503,
        )

    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.upstox_api_key,
            "redirect_uri": settings.upstox_redirect_url,
        }
    )
    return RedirectResponse(f"{AUTHORIZE_URL}?{query}")


@router.get("/callback")
def callback(code: str, db: Session = Depends(get_db)) -> HTMLResponse:
    if not upstox_configured():
        raise HTTPException(status_code=500, detail="Upstox is not configured")

    with httpx.Client(timeout=20) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.upstox_api_key,
                "client_secret": settings.upstox_api_secret,
                "redirect_uri": settings.upstox_redirect_url,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    access_token = payload.get("access_token")
    user_id = payload.get("user_id") or payload.get("client_id") or "unknown"
    if not access_token:
        raise HTTPException(status_code=401, detail="Upstox token response did not include access_token")

    broker_user_id = f"upstox:{user_id}"
    user = db.query(User).filter(User.kite_user_id == broker_user_id).one_or_none()
    if user is None:
        user = User(kite_user_id=broker_user_id, access_token=encrypt_secret(access_token), created_at=datetime.utcnow())
        db.add(user)
    else:
        user.access_token = encrypt_secret(access_token)
        user.token_version += 1
    db.commit()
    db.refresh(user)

    jwt_token = create_access_token(user)
    app_url = f"{settings.frontend_redirect_url}?user_id={user.id}&token={jwt_token}"
    return HTMLResponse(
        f"""
        <html>
          <body style="font-family: system-ui; padding: 32px; background: #151615; color: #f7f4ea;">
            <h1>Upstox connected</h1>
            <p>Your Upstox token was saved for SignalKite.</p>
            <p>Use the token below only for local testing.</p>
            <p><code>{jwt_token}</code></p>
            <p><a href="http://localhost:8081?token={jwt_token}">Open Expo web</a></p>
            <p><a href="{app_url}">Open mobile app</a></p>
          </body>
        </html>
        """
    )


@router.get("/holdings")
def holdings(user: User = Depends(get_current_user)) -> dict:
    if not user.kite_user_id.startswith("upstox:"):
        raise HTTPException(status_code=400, detail="Current token is not an Upstox session")

    token = decrypt_secret(user.access_token)
    with httpx.Client(timeout=20) as client:
        response = client.get(HOLDINGS_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@router.get("/stream/status")
def stream_status(user: User = Depends(get_current_user)) -> dict:
    if not user.kite_user_id.startswith("upstox:"):
        raise HTTPException(status_code=400, detail="Current token is not an Upstox session")
    return get_upstox_stream_status(user.id)
