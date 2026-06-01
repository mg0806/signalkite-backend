from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth.security import current_user_context
from config import settings
from db import get_db
from models import Holding, Signal, User, WatchlistItem
from services.historical_data import fetch_ohlcv
from services.instruments import resolve_instrument_token
from services.kite_sync import authenticated_kite, refresh_holdings_prices
from services.market_scanner import scan_market_top_picks
from services.screener import fetch_screener_snapshot
from services.upstox_stream import sync_upstox_holdings_with_ticks

router = APIRouter(tags=["portfolio"])


def get_demo_user(db: Session) -> User:
    current_user = current_user_context.get()
    if current_user is not None:
        return current_user

    if settings.is_development:
        user = db.query(User).order_by(User.id).first()
        if user is not None:
            return user

    raise HTTPException(status_code=401, detail="Authentication required")


def latest_signal(db: Session, user_id: int, symbol: str) -> Signal | None:
    return (
        db.query(Signal)
        .filter(Signal.user_id == user_id, Signal.tradingsymbol == symbol)
        .order_by(desc(Signal.computed_at))
        .first()
    )


def calculated_target_price(holding: Holding, signal: Signal | None, configured_target: float | None) -> float:
    if configured_target is not None and configured_target > 0:
        return round(configured_target, 2)

    last_price = max(float(holding.last_price or 0), 0)
    average_price = max(float(holding.average_price or 0), 0)
    signal_type = signal.signal_type if signal is not None else "HOLD"

    if signal_type == "BUY":
        target = last_price * 1.05
    elif signal_type == "SELL":
        target = min(last_price, average_price) * 0.98
    else:
        target = max(last_price * 1.03, average_price * 1.02)

    return round(target, 2)


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    refresh_status = "live"
    refresh_error = None
    refresh_stats = {"holdings_count": 0, "quote_count": 0, "missing_quote_count": 0, "quote_errors": []}
    try:
        if user.kite_user_id.startswith("upstox:"):
            refresh_stats = sync_upstox_holdings_with_ticks(db, user)
            if refresh_stats["quote_count"]:
                refresh_status = "upstox_stream"
            else:
                refresh_status = "upstox_stream_starting"
                refresh_error = refresh_stats.get("stream_error")
        else:
            refresh_stats = refresh_holdings_prices(db, user)
            if refresh_stats["holdings_count"] and not refresh_stats["quote_count"]:
                refresh_status = "holdings_snapshot"
                if refresh_stats.get("quote_errors"):
                    refresh_error = "; ".join(refresh_stats["quote_errors"][:2])
            elif refresh_stats["missing_quote_count"]:
                refresh_status = "partial_live"
    except Exception as exc:
        db.rollback()
        refresh_status = "stale"
        refresh_error = str(exc)
    holdings = db.query(Holding).filter(Holding.user_id == user.id).order_by(Holding.tradingsymbol).all()
    watchlist_targets = {
        row.tradingsymbol: row.target_price
        for row in db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.id, WatchlistItem.target_price.isnot(None))
        .all()
    }
    items = []
    total_value = 0.0
    total_pnl = 0.0
    active_signals = 0
    last_updated = None

    for holding in holdings:
        signal = latest_signal(db, user.id, holding.tradingsymbol)
        target_price = calculated_target_price(holding, signal, watchlist_targets.get(holding.tradingsymbol))
        total_value += holding.quantity * holding.last_price
        total_pnl += holding.pnl
        if last_updated is None or holding.synced_at > last_updated:
            last_updated = holding.synced_at
        if signal and signal.signal_type != "HOLD":
            active_signals += 1
        items.append(
            {
                "tradingsymbol": holding.tradingsymbol,
                "exchange": holding.exchange,
                "quantity": holding.quantity,
                "average_price": holding.average_price,
                "last_price": holding.last_price,
                "target_price": target_price,
                "pnl": holding.pnl,
                "synced_at": holding.synced_at,
                "sparkline": [],
                "signal": None
                if signal is None
                else {
                    "type": signal.signal_type,
                    "confidence": signal.confidence,
                    "rsi": signal.rsi,
                    "macd_hist": signal.macd_hist,
                    "bb_position": signal.bb_position,
                    "ema_cross": signal.ema_cross,
                    "reason": signal.reason,
                    "computed_at": signal.computed_at,
                },
            }
        )

    return {
        "summary": {
            "total_value": total_value,
            "today_pnl": total_pnl,
            "overall_gain": total_pnl,
            "xirr": None,
            "active_signals": active_signals,
            "last_updated": last_updated,
            "refresh_status": refresh_status,
            "refresh_error": refresh_error,
            "refresh_stats": refresh_stats,
        },
        "holdings": items,
    }


@router.get("/portfolio/summary")
def portfolio_summary(db: Session = Depends(get_db)) -> dict:
    return portfolio(db)["summary"]


@router.get("/portfolio/{symbol}/analysis")
def stock_analysis(symbol: str, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    symbol = symbol.upper()
    holding = db.query(Holding).filter(Holding.user_id == user.id, Holding.tradingsymbol == symbol).one_or_none()
    history = (
        db.query(Signal)
        .filter(Signal.user_id == user.id, Signal.tradingsymbol == symbol)
        .order_by(desc(Signal.computed_at))
        .limit(10)
        .all()
    )
    if not history:
        raise HTTPException(status_code=404, detail="No signal history for symbol")
    latest = history[0]
    exchange = holding.exchange if holding is not None else "NSE"
    kite = authenticated_kite(user)
    token = resolve_instrument_token(kite, symbol, exchange)
    ohlcv = fetch_ohlcv(symbol, exchange=exchange, kite=kite, instrument_token=token)
    candles = [
        {
            "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"] or 0),
        }
        for row in ohlcv.tail(30).to_dict("records")
    ]
    if ohlcv.empty:
        levels = {"support": None, "resistance": None, "bollinger_upper": None, "bollinger_lower": None}
    else:
        recent = ohlcv.tail(20)
        close = recent["close"]
        mid = close.rolling(20).mean().iloc[-1] if len(recent) >= 20 else close.mean()
        std = close.rolling(20).std().iloc[-1] if len(recent) >= 20 else close.std()
        levels = {
            "support": float(recent["low"].min()),
            "resistance": float(recent["high"].max()),
            "bollinger_upper": float(mid + (2 * std)) if std == std else None,
            "bollinger_lower": float(mid - (2 * std)) if std == std else None,
        }

    return {
        "tradingsymbol": symbol,
        "candles": candles,
        "latest_signal": {
            "type": latest.signal_type,
            "confidence": latest.confidence,
            "reason": latest.reason,
            "rsi": latest.rsi,
            "macd_hist": latest.macd_hist,
            "bb_position": latest.bb_position,
            "ema_cross": latest.ema_cross,
        },
        "levels": levels,
        "fundamentals": fetch_screener_snapshot(symbol),
        "signal_history": [
            {
                "type": row.signal_type,
                "confidence": row.confidence,
                "reason": row.reason,
                "computed_at": row.computed_at,
            }
            for row in history
            if row.reason != "Not enough candle history"
        ],
    }


@router.get("/signals")
def signals(db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    since = datetime.utcnow() - timedelta(days=2)
    rows = (
        db.query(Signal)
        .filter(Signal.user_id == user.id, Signal.computed_at >= since)
        .order_by(desc(Signal.computed_at))
        .all()
    )
    latest_by_symbol: dict[str, Signal] = {}
    for row in rows:
        if row.tradingsymbol not in latest_by_symbol:
            latest_by_symbol[row.tradingsymbol] = row

    return [
        {
            "tradingsymbol": row.tradingsymbol,
            "type": row.signal_type,
            "confidence": row.confidence,
            "rsi": row.rsi,
            "reason": row.reason,
            "computed_at": row.computed_at,
        }
        for row in latest_by_symbol.values()
    ]


@router.get("/signals/history")
def signal_history(db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    since = datetime.utcnow() - timedelta(days=30)
    return [
        {
            "tradingsymbol": row.tradingsymbol,
            "type": row.signal_type,
            "confidence": row.confidence,
            "reason": row.reason,
            "computed_at": row.computed_at,
        }
        for row in db.query(Signal)
        .filter(Signal.user_id == user.id, Signal.computed_at >= since)
        .order_by(desc(Signal.computed_at))
        .all()
    ]


@router.get("/top-picks")
def top_picks(db: Session = Depends(get_db)) -> list[dict]:
    return scan_market_top_picks()
