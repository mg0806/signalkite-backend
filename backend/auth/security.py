from datetime import datetime, timedelta
from contextvars import ContextVar

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import User

bearer = HTTPBearer(auto_error=False)
current_user_context: ContextVar[User | None] = ContextVar("current_user_context", default=None)


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "kite_user_id": user.kite_user_id,
        "token_version": user.token_version,
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is not None:
        try:
            payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
            user_id = int(payload["sub"])
        except (JWTError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid auth token") from exc
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        if int(payload.get("token_version", 0)) != user.token_version:
            raise HTTPException(status_code=401, detail="Token has been revoked")
        return user

    if settings.is_development:
        user = db.query(User).order_by(User.id).first()
        if user is not None:
            return user

    raise HTTPException(status_code=401, detail="Authentication required")


def set_current_user_context(user: User = Depends(get_current_user)) -> User:
    current_user_context.set(user)
    return user
