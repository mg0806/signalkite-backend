from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import ssl
from threading import Lock, Thread
from uuid import uuid4

import httpx
import websockets
from sqlalchemy.orm import Session

from models import Holding, User
from services.MarketDataFeedV3_pb2 import FeedResponse
from services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

HOLDINGS_URL = "https://api.upstox.com/v2/portfolio/long-term-holdings"
MARKET_FEED_AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

_lock = Lock()
_ticks: dict[int, dict[str, dict]] = {}
_threads: dict[int, Thread] = {}
_status: dict[int, dict] = {}


def _token(user: User) -> str:
    return decrypt_secret(user.access_token)


def fetch_upstox_holdings(access_token: str) -> list[dict]:
    with httpx.Client(timeout=20) as client:
        response = client.get(
            HOLDINGS_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    return data if isinstance(data, list) else []


def _upsert_holding(db: Session, user: User, row: dict, tick: dict | None = None) -> Holding:
    symbol = row.get("tradingsymbol") or row.get("trading_symbol")
    if not symbol:
        raise ValueError("Upstox holding row did not include tradingsymbol")

    quantity = int(row.get("quantity") or 0)
    average_price = float(row.get("average_price") or 0)
    last_price = float((tick or {}).get("ltp") or row.get("last_price") or 0)
    pnl = (last_price - average_price) * quantity if tick else float(row.get("pnl") or 0)

    holding = (
        db.query(Holding)
        .filter(Holding.user_id == user.id, Holding.tradingsymbol == symbol)
        .one_or_none()
    )
    if holding is None:
        holding = Holding(user_id=user.id, tradingsymbol=symbol)
        db.add(holding)

    holding.exchange = row.get("exchange") or "NSE"
    holding.quantity = quantity
    holding.average_price = average_price
    holding.last_price = last_price
    holding.pnl = pnl
    holding.synced_at = datetime.utcnow()
    return holding


def sync_upstox_holdings_with_ticks(db: Session, user: User) -> dict:
    access_token = _token(user)
    rows = fetch_upstox_holdings(access_token)
    instrument_keys = [row.get("instrument_token") for row in rows if row.get("instrument_token")]
    start_upstox_market_stream(user.id, access_token, instrument_keys)

    with _lock:
        user_ticks = dict(_ticks.get(user.id, {}))
        stream_status = dict(_status.get(user.id, {}))

    seen_symbols: set[str] = set()
    tick_count = 0
    for row in rows:
        instrument_key = row.get("instrument_token")
        tick = user_ticks.get(instrument_key) if instrument_key else None
        if tick:
            tick_count += 1
        holding = _upsert_holding(db, user, row, tick)
        seen_symbols.add(holding.tradingsymbol)

    if seen_symbols:
        stale_holdings = (
            db.query(Holding)
            .filter(Holding.user_id == user.id, Holding.tradingsymbol.notin_(seen_symbols))
            .all()
        )
        for holding in stale_holdings:
            db.delete(holding)

    db.commit()
    return {
        "holdings_count": len(rows),
        "quote_count": tick_count,
        "missing_quote_count": max(len(rows) - tick_count, 0),
        "stream_status": stream_status.get("status", "starting"),
        "stream_error": stream_status.get("error"),
        "instrument_count": len(instrument_keys),
    }


def start_upstox_market_stream(user_id: int, access_token: str, instrument_keys: list[str]) -> None:
    if not instrument_keys:
        return
    with _lock:
        existing = _threads.get(user_id)
        if existing and existing.is_alive():
            return
        _status[user_id] = {"status": "starting", "error": None, "instrument_count": len(instrument_keys)}

    thread = Thread(
        target=lambda: asyncio.run(_run_stream(user_id, access_token, instrument_keys)),
        name=f"upstox-market-stream-{user_id}",
        daemon=True,
    )
    with _lock:
        _threads[user_id] = thread
    thread.start()


async def _run_stream(user_id: int, access_token: str, instrument_keys: list[str]) -> None:
    try:
        authorized_url = _authorized_market_feed_url(access_token)
        ssl_context = ssl.create_default_context()
        async with websockets.connect(authorized_url, ssl=ssl_context, ping_interval=20, ping_timeout=20) as websocket:
            subscribe = {
                "guid": str(uuid4()),
                "method": "sub",
                "data": {"mode": "ltpc", "instrumentKeys": instrument_keys},
            }
            await websocket.send(json.dumps(subscribe).encode("utf-8"))
            with _lock:
                _status[user_id] = {"status": "connected", "error": None, "instrument_count": len(instrument_keys)}

            async for message in websocket:
                _handle_feed_message(user_id, message)
    except Exception as exc:
        logger.exception("Upstox market stream failed for user_id=%s", user_id)
        with _lock:
            _status[user_id] = {"status": "error", "error": str(exc), "instrument_count": len(instrument_keys)}


def _authorized_market_feed_url(access_token: str) -> str:
    with httpx.Client(timeout=20) as client:
        response = client.get(
            MARKET_FEED_AUTHORIZE_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
    response.raise_for_status()
    authorized_url = response.json().get("data", {}).get("authorized_redirect_uri")
    if not authorized_url:
        raise RuntimeError("Upstox did not return authorized_redirect_uri")
    return authorized_url


def _handle_feed_message(user_id: int, message: bytes) -> None:
    feed_response = FeedResponse()
    feed_response.ParseFromString(message)

    updates: dict[str, dict] = {}
    for instrument_key, feed in feed_response.feeds.items():
        ltp = None
        ltt = None
        union = feed.WhichOneof("FeedUnion")
        if union == "ltpc":
            ltp = feed.ltpc.ltp
            ltt = feed.ltpc.ltt
        elif union == "fullFeed":
            full_union = feed.fullFeed.WhichOneof("FullFeedUnion")
            if full_union == "marketFF":
                ltp = feed.fullFeed.marketFF.ltpc.ltp
                ltt = feed.fullFeed.marketFF.ltpc.ltt
            elif full_union == "indexFF":
                ltp = feed.fullFeed.indexFF.ltpc.ltp
                ltt = feed.fullFeed.indexFF.ltpc.ltt
        elif union == "firstLevelWithGreeks":
            ltp = feed.firstLevelWithGreeks.ltpc.ltp
            ltt = feed.firstLevelWithGreeks.ltpc.ltt

        if ltp:
            updates[instrument_key] = {"ltp": float(ltp), "ltt": int(ltt or 0), "received_at": datetime.utcnow().isoformat()}

    if updates:
        with _lock:
            _ticks.setdefault(user_id, {}).update(updates)
            status = _status.setdefault(user_id, {})
            status.update({"status": "connected", "last_tick_at": datetime.utcnow().isoformat(), "last_tick_count": len(updates)})


def get_upstox_stream_status(user_id: int) -> dict:
    with _lock:
        return dict(_status.get(user_id, {"status": "not_started"}))
