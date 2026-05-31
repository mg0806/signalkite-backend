from datetime import datetime

from sqlalchemy import text

from config import settings
from db import SessionLocal
from services.notifications import configured_channels


def service_metadata() -> dict:
    return {
        "service": "signalkite-api",
        "version": "0.1.0",
        "environment": settings.app_env,
        "time_utc": datetime.utcnow().isoformat(),
    }


def readiness() -> tuple[int, dict]:
    checks: dict[str, dict] = {}

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
    finally:
        db.close()

    checks["kite"] = {
        "status": "ok" if settings.kite_api_key and settings.kite_api_secret else "degraded",
        "configured": bool(settings.kite_api_key and settings.kite_api_secret),
    }
    checks["notifications"] = {
        "status": "ok",
        "channels": configured_channels(),
    }
    checks["scheduler"] = {
        "status": "ok" if settings.scheduler_enabled else "disabled",
        "enabled": settings.scheduler_enabled,
    }

    overall = "ok" if all(check["status"] in {"ok", "disabled"} for check in checks.values()) else "degraded"
    status_code = 200 if checks["database"]["status"] == "ok" else 503
    return status_code, {**service_metadata(), "status": overall, "checks": checks}
