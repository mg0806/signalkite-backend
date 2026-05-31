import asyncio
import html
import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.portfolio import get_demo_user
from config import settings
from db import get_db
from models import Holding, MarketScanJob, WatchlistItem
from services.instruments import resolve_instrument_token
from services.kite_sync import authenticated_kite
from services.market_data import fx_rate, quote_symbol
from services.market_scan_jobs import create_scan_job, serialize_scan_job
from services.market_scanner import scan_market_top_picks

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quotes")
def quotes(symbols: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    if symbols:
        requested = [(symbol.strip().upper(), "NSE") for symbol in symbols.split(",") if symbol.strip()]
    else:
        holdings = db.query(Holding).filter(Holding.user_id == user.id).all()
        watchlist = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).all()
        requested = [(row.tradingsymbol, row.exchange) for row in [*holdings, *watchlist]]
    return [quote_symbol(symbol, exchange) for symbol, exchange in requested]


@router.get("/top-picks")
def market_top_picks(limit_per_category: int = Query(default=3, ge=1, le=5), db: Session = Depends(get_db)) -> list[dict]:
    picks = scan_market_top_picks(limit_per_category=limit_per_category)
    try:
        user = get_demo_user(db)
        kite = authenticated_kite(user)
    except Exception:
        kite = None

    for pick in picks:
        exchange = pick.get("exchange") or "NSE"
        symbol = pick["tradingsymbol"]
        token = resolve_instrument_token(kite, symbol, exchange) if kite is not None else None
        pick["instrument_token"] = token
        pick["kite_url"] = "https://kite.zerodha.com/dashboard"
        pick["kite_chart_url"] = (
            f"https://kite.zerodha.com/markets/chart/web/ciq/{exchange}/{symbol}/{token}"
            if token is not None
            else "https://kite.zerodha.com/dashboard"
        )
        pick["kite_buy_url"] = f"/market/kite/buy?exchange={exchange}&symbol={symbol}&quantity=1"
    return picks


@router.post("/scan-jobs")
def create_market_scan_job(limit_per_category: int = Query(default=2, ge=1, le=5), db: Session = Depends(get_db)) -> dict:
    return serialize_scan_job(create_scan_job(db, limit_per_category=limit_per_category), include_result=False)


@router.get("/scan-jobs/{job_id}")
def get_market_scan_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.query(MarketScanJob).filter(MarketScanJob.id == job_id).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return serialize_scan_job(job)


@router.get("/kite/buy")
def kite_buy(
    exchange: str = Query(default="NSE"),
    symbol: str = Query(...),
    quantity: int = Query(default=1, ge=1),
) -> HTMLResponse:
    if not settings.kite_api_key:
        return HTMLResponse("<h1>Kite API key is not configured</h1>", status_code=503)

    transaction = {
        "exchange": exchange.upper(),
        "tradingsymbol": symbol.upper(),
        "transaction_type": "BUY",
        "order_type": "MARKET",
        "quantity": quantity,
        "variety": "regular",
        "product": "CNC",
    }
    transactions = html.escape(json.dumps([transaction]), quote=True)
    api_key = html.escape(settings.kite_api_key, quote=True)
    return HTMLResponse(
        f"""
        <html>
          <head>
            <title>Opening Kite order</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
          </head>
          <body style="font-family: system-ui; background: #151615; color: #f7f4ea; padding: 24px;">
            <p>Opening Kite buy order for {html.escape(exchange.upper())}:{html.escape(symbol.upper())}...</p>
            <form id="kite-basket" method="post" action="https://kite.zerodha.com/connect/basket">
              <input type="hidden" name="api_key" value="{api_key}" />
              <input type="hidden" name="data" value="{transactions}" />
            </form>
            <script>document.getElementById("kite-basket").submit();</script>
          </body>
        </html>
        """
    )


@router.websocket("/ws/quotes")
async def quote_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    symbols_param = websocket.query_params.get("symbols", "")
    symbols = [symbol.strip().upper() for symbol in symbols_param.split(",") if symbol.strip()]
    if not symbols:
        await websocket.send_json({"error": "symbols query param is required"})
        await websocket.close()
        return
    try:
        while True:
            await websocket.send_json([quote_symbol(symbol) for symbol in symbols])
            await asyncio.sleep(15)
    except Exception:
        await websocket.close()


@router.get("/fx")
def fx(base: str = "USD", quote: str = "INR") -> dict:
    return fx_rate(base, quote)
