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


def refresh_holdings_prices(db: Session, user: User) -> list[Holding]:
    kite = authenticated_kite(user)
    rows = kite.holdings()
    refreshed: list[Holding] = []
    seen_symbols: set[str] = set()
    quote_keys = [f"{row.get('exchange', 'NSE')}:{row['tradingsymbol']}" for row in rows]
    quotes = {}
    if quote_keys:
        try:
            quotes = kite.quote(quote_keys)
        except Exception:
            logger.exception("Batch quote refresh failed for user_id=%s", user.id)
            for key in quote_keys:
                try:
                    quotes.update(kite.quote([key]))
                except Exception:
                    logger.exception("Quote refresh failed for user_id=%s instrument=%s", user.id, key)

    for row in rows:
        symbol = row["tradingsymbol"]
        exchange = row.get("exchange", "NSE")
        quote = quotes.get(f"{exchange}:{symbol}", {})
        last_price = float(quote.get("last_price") or row.get("last_price", 0))
        average_price = float(row.get("average_price", 0))
        quantity = int(row.get("quantity", 0))
        seen_symbols.add(symbol)
        holding = (
            db.query(Holding)
            .filter(Holding.user_id == user.id, Holding.tradingsymbol == symbol)
            .one_or_none()
        )
        if holding is None:
            holding = Holding(user_id=user.id, tradingsymbol=symbol)
            db.add(holding)

        holding.exchange = exchange
        holding.quantity = quantity
        holding.average_price = average_price
        holding.last_price = last_price
        holding.pnl = (last_price - average_price) * quantity
        holding.synced_at = datetime.utcnow()
        refreshed.append(holding)

    if seen_symbols:
        stale_holdings = (
            db.query(Holding)
            .filter(Holding.user_id == user.id, Holding.tradingsymbol.notin_(seen_symbols))
            .all()
        )
        for holding in stale_holdings:
            db.delete(holding)

    db.commit()
    for holding in refreshed:
        db.refresh(holding)
    return refreshed


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
