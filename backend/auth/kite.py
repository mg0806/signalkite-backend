from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from kiteconnect import KiteConnect
from sqlalchemy.orm import Session

from config import settings
from auth.security import create_access_token, get_current_user
from db import get_db
from models import User
from services.crypto import encrypt_secret
from services.kite_sync import sync_holdings

router = APIRouter(prefix="/auth/kite", tags=["kite-auth"])


def kite_client() -> KiteConnect:
    if not settings.kite_api_key:
        raise HTTPException(status_code=500, detail="KITE_API_KEY is not configured")
    return KiteConnect(api_key=settings.kite_api_key)


@router.get("/login")
def login():
    if not settings.kite_api_key or not settings.kite_api_secret:
        return HTMLResponse(
            """
            <html>
              <body style="font-family: system-ui; padding: 32px; background: #151615; color: #f7f4ea;">
                <h1>SignalKite Kite login is not configured yet</h1>
                <p>Add KITE_API_KEY and KITE_API_SECRET to backend/.env, then restart FastAPI.</p>
                <p>You can still preview the mobile app with the sample portfolio button.</p>
              </body>
            </html>
            """,
            status_code=503,
        )

    client = kite_client()
    return RedirectResponse(client.login_url())


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict[str, bool | int | None]:
    user = db.query(User).order_by(User.id).first()
    return {
        "kite_configured": bool(settings.kite_api_key and settings.kite_api_secret),
        "kite_connected": user is not None,
        "user_id": user.id if user is not None else None,
    }


@router.get("/callback")
def callback(request_token: str, db: Session = Depends(get_db)) -> RedirectResponse:
    client = kite_client()
    session = client.generate_session(request_token, api_secret=settings.kite_api_secret)
    kite_user_id = session.get("user_id")
    access_token = session.get("access_token")
    if not kite_user_id or not access_token:
        raise HTTPException(status_code=401, detail="Kite session did not include a user/token")

    user = db.query(User).filter(User.kite_user_id == kite_user_id).one_or_none()
    if user is None:
        user = User(kite_user_id=kite_user_id, access_token=encrypt_secret(access_token), created_at=datetime.utcnow())
        db.add(user)
    else:
        user.access_token = encrypt_secret(access_token)
        user.token_version += 1
    db.commit()
    db.refresh(user)

    jwt_token = create_access_token(user)
    app_url = f"{settings.frontend_redirect_url}?user_id={user.id}&token={jwt_token}"
    sync_error = ""
    try:
        sync_holdings(db, user)
    except Exception as exc:
        sync_error = f"<p>Login is complete, but holdings sync needs another try: {str(exc)}</p>"

    return HTMLResponse(
        f"""
        <html>
          <head>
            <title>SignalKite connected</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <style>
              body {{
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #151615;
                color: #f7f4ea;
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }}
              main {{
                width: min(520px, calc(100vw - 32px));
              }}
              h1 {{
                margin: 0 0 12px;
                font-size: 32px;
              }}
              p {{
                color: #c8cabd;
                line-height: 1.5;
              }}
              a {{
                display: inline-block;
                margin: 20px 12px 0 0;
                padding: 14px 18px;
                border-radius: 8px;
                background: #73c441;
                color: #10210f;
                font-weight: 800;
                text-decoration: none;
              }}
              a.secondary {{
                background: transparent;
                color: #f7f4ea;
                border: 1px solid #4d5148;
              }}
              code {{
                color: #f7f4ea;
              }}
            </style>
          </head>
          <body>
            <main>
              <h1>Kite connected</h1>
              <p>Your Zerodha session was saved for SignalKite. Open the Expo web app on this computer, or use the mobile link only from Expo Go/a native build.</p>
              {sync_error}
              <a href="http://localhost:8081?token={jwt_token}">Open Expo web</a>
              <a class="secondary" href="{app_url}">Open mobile app</a>
            </main>
          </body>
        </html>
        """
    )


@router.post("/refresh")
def refresh_session(user: User = Depends(get_current_user)) -> dict:
    return {"access_token": create_access_token(user)}


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    user.token_version += 1
    db.commit()
    return {"status": "logged_out"}
