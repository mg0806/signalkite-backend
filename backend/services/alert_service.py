from datetime import datetime
import logging

import httpx
from sqlalchemy.orm import Session

from config import settings
from models import Alert, PriceAlert, Signal, User
from services.market_data import quote_symbol
from services.notifications import send_notification

logger = logging.getLogger(__name__)


def send_high_confidence_alert(db: Session, user: User, signal: Signal) -> Alert | None:
    if signal.confidence != "HIGH" or not user.fcm_token:
        return None

    message = f"{signal.tradingsymbol} - {signal.signal_type} signal ({signal.reason})"
    alert = Alert(user_id=user.id, tradingsymbol=signal.tradingsymbol, message=message, signal_type=signal.signal_type)
    db.add(alert)
    db.commit()
    db.refresh(alert)

    if settings.fcm_server_key:
        httpx.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={"Authorization": f"key={settings.fcm_server_key}"},
            json={"to": user.fcm_token, "notification": {"title": "SignalKite", "body": message}},
            timeout=10,
        )
    return alert


def _condition_met(condition: str, price: float, target: float) -> bool:
    normalized = condition.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"above", "gte", "greater_than", "greater_than_or_equal", "crosses_above", ">=", ">"}:
        return price >= target
    if normalized in {"below", "lte", "less_than", "less_than_or_equal", "crosses_below", "<=", "<"}:
        return price <= target
    return False


def evaluate_price_alerts(db: Session, user: User | None = None) -> list[dict]:
    query = db.query(PriceAlert).filter(PriceAlert.enabled == True, PriceAlert.triggered_at.is_(None))  # noqa: E712
    if user is not None:
        query = query.filter(PriceAlert.user_id == user.id)

    results: list[dict] = []
    for alert in query.all():
        logger.info("Evaluating price alert id=%s symbol=%s condition=%s target=%s", alert.id, alert.tradingsymbol, alert.condition, alert.target_price)
        try:
            quote = quote_symbol(alert.tradingsymbol)
        except Exception as exc:
            logger.exception("Quote lookup failed for alert id=%s symbol=%s", alert.id, alert.tradingsymbol)
            results.append({"id": alert.id, "tradingsymbol": alert.tradingsymbol, "status": "quote_failed", "error": str(exc)})
            continue

        price = quote.get("price")
        if price is None:
            logger.warning("Price unavailable for alert id=%s symbol=%s", alert.id, alert.tradingsymbol)
            results.append({"id": alert.id, "tradingsymbol": alert.tradingsymbol, "status": "price_unavailable"})
            continue

        current_price = float(price)
        if not _condition_met(alert.condition, current_price, alert.target_price):
            results.append(
                {
                    "id": alert.id,
                    "tradingsymbol": alert.tradingsymbol,
                    "status": "waiting",
                    "price": current_price,
                    "target_price": alert.target_price,
                }
            )
            continue

        title = f"SignalKite price alert: {alert.tradingsymbol}"
        message = (
            f"{alert.tradingsymbol} is now {current_price:.2f}, "
            f"triggering {alert.condition} {alert.target_price:.2f}."
        )
        channels = [channel.strip() for channel in alert.channels.split(",") if channel.strip()]
        notification_results = send_notification(channels, title, message)
        failed_channels = [result for result in notification_results if result.get("status") == "failed"]
        if failed_channels:
            logger.warning("Alert id=%s triggered with failed notification channels: %s", alert.id, failed_channels)
        else:
            logger.info("Alert id=%s triggered for %s at %.2f", alert.id, alert.tradingsymbol, current_price)

        db.add(
            Alert(
                user_id=alert.user_id,
                tradingsymbol=alert.tradingsymbol,
                message=message,
                signal_type="PRICE",
            )
        )
        alert.triggered_at = datetime.utcnow()
        alert.enabled = False
        db.commit()
        results.append(
            {
                "id": alert.id,
                "tradingsymbol": alert.tradingsymbol,
                "status": "triggered",
                "price": current_price,
                "target_price": alert.target_price,
                "condition": alert.condition,
                "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
                "notifications": notification_results,
            }
        )
    return results
