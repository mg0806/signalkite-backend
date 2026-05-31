from datetime import datetime
import logging

from kiteconnect import KiteConnect
from sqlalchemy.orm import Session

from config import settings
from models import Holding, User
from services.alert_service import evaluate_price_alerts
from services.crypto import decrypt_secret
from services.instruments import resolve_instrument_token
from services.signal_engine import compute_and_store_signal

logger = logging.getLogger(__name__)


def authenticated_kite(user: User) -> KiteConnect:
    kite = KiteConnect(api_key=settings.kite_api_key)
    kite.set_access_token(decrypt_secret(user.access_token))
    return kite


def sync_holdings(db: Session, user: User) -> list[Holding]:
    kite = authenticated_kite(user)
    rows = kite.holdings()
    synced: list[Holding] = []
    for row in rows:
        symbol = row["tradingsymbol"]
        holding = (
            db.query(Holding)
            .filter(Holding.user_id == user.id, Holding.tradingsymbol == symbol)
            .one_or_none()
        )
        if holding is None:
            holding = Holding(user_id=user.id, tradingsymbol=symbol)
            db.add(holding)

        holding.exchange = row.get("exchange", "NSE")
        holding.quantity = int(row.get("quantity", 0))
        holding.average_price = float(row.get("average_price", 0))
        holding.last_price = float(row.get("last_price", 0))
        holding.pnl = float(row.get("pnl", 0))
        holding.synced_at = datetime.utcnow()
        synced.append(holding)

    db.commit()
    for holding in synced:
        db.refresh(holding)
        token = resolve_instrument_token(kite, holding.tradingsymbol, holding.exchange)
        compute_and_store_signal(
            db,
            user.id,
            holding.tradingsymbol,
            exchange=holding.exchange,
            kite=kite,
            instrument_token=token,
        )
    return synced


def sync_all_users(db: Session) -> None:
    for user in db.query(User).all():
        try:
            sync_holdings(db, user)
            logger.info("Synced holdings for user_id=%s", user.id)
        except Exception as exc:
            logger.exception("Holdings sync failed for user_id=%s: %s", user.id, exc)
            db.rollback()
        alert_results = evaluate_price_alerts(db, user)
        if alert_results:
            logger.info("Evaluated %s price alerts for user_id=%s", len(alert_results), user.id)
