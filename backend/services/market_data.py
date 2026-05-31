from datetime import datetime

import httpx

from services.historical_data import fetch_yahoo_chart_ohlcv


def quote_symbol(symbol: str, exchange: str = "NSE") -> dict:
    suffixes = [".NS", ".BO"] if exchange == "NSE" else [".BO", ".NS"]
    candidates = [symbol] if symbol.endswith((".NS", ".BO")) else [f"{symbol}{suffix}" for suffix in suffixes]
    for ticker in candidates:
        frame = fetch_yahoo_chart_ohlcv(ticker, days=7)
        if not frame.empty:
            latest = frame.tail(1).iloc[0]
            previous = frame.tail(2).iloc[0] if len(frame) > 1 else latest
            price = float(latest["close"])
            prev_close = float(previous["close"])
            return {
                "tradingsymbol": symbol,
                "ticker": ticker,
                "price": price,
                "previous_close": prev_close,
                "change": price - prev_close,
                "change_pct": ((price - prev_close) / prev_close) * 100 if prev_close else 0,
                "as_of": datetime.utcnow().isoformat(),
            }
    return {"tradingsymbol": symbol, "price": None, "change": None, "change_pct": None, "as_of": datetime.utcnow().isoformat()}


def fx_rate(base: str, quote: str) -> dict:
    if base.upper() == quote.upper():
        return {"base": base.upper(), "quote": quote.upper(), "rate": 1.0}
    pair = f"{base.upper()}{quote.upper()}=X"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}"
    try:
        response = httpx.get(url, params={"range": "5d", "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        close = result["indicators"]["quote"][0]["close"]
        rate = next(value for value in reversed(close) if value is not None)
    except Exception:
        rate = None
    return {"base": base.upper(), "quote": quote.upper(), "rate": rate}
