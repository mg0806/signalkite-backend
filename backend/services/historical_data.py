from datetime import datetime, timedelta
import time

import httpx
import pandas as pd
import yfinance as yf
from kiteconnect import KiteConnect
from services.ohlcv_cache import read_cached_ohlcv, write_cached_ohlcv


def normalize_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    frame = data.copy().reset_index(drop=False)
    frame.columns = [str(col[0] if isinstance(col, tuple) else col).lower() for col in frame.columns]
    frame = frame.rename(columns={"datetime": "date", "adj close": "adj_close"})
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"])[["date", "open", "high", "low", "close", "volume"]]


def fetch_kite_ohlcv(kite: KiteConnect, instrument_token: int, days: int = 180) -> pd.DataFrame:
    to_date = datetime.utcnow()
    from_date = to_date - timedelta(days=days)
    candles = kite.historical_data(instrument_token, from_date, to_date, "day")
    return normalize_ohlcv(pd.DataFrame(candles))


def fetch_yahoo_ohlcv(tradingsymbol: str, exchange: str = "NSE", days: int = 180) -> pd.DataFrame:
    suffixes = [".NS", ".BO"] if exchange == "NSE" else [".BO", ".NS"]
    candidates = [tradingsymbol] if tradingsymbol.startswith("^") or tradingsymbol.endswith((".NS", ".BO")) else [f"{tradingsymbol}{suffix}" for suffix in suffixes]
    for ticker in candidates:
        frame = fetch_yahoo_chart_ohlcv(ticker, days)
        if len(frame) >= 35:
            return frame

    for ticker in candidates:
        try:
            data = yf.download(ticker, period=f"{days}d", interval="1d", progress=False, auto_adjust=False)
        except Exception:
            continue
        frame = normalize_ohlcv(data)
        if len(frame) >= 35:
            return frame
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


def fetch_yahoo_chart_ohlcv(ticker: str, days: int = 180) -> pd.DataFrame:
    period2 = int(time.time())
    period1 = period2 - (days * 24 * 60 * 60)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    try:
        response = httpx.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
    except Exception:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    quote = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp", [])
    rows = []
    for index, timestamp in enumerate(timestamps):
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp).date(),
                "open": quote.get("open", [None])[index],
                "high": quote.get("high", [None])[index],
                "low": quote.get("low", [None])[index],
                "close": quote.get("close", [None])[index],
                "volume": quote.get("volume", [0])[index],
            }
        )
    return normalize_ohlcv(pd.DataFrame(rows))


def fetch_ohlcv(
    tradingsymbol: str,
    days: int = 180,
    exchange: str = "NSE",
    kite: KiteConnect | None = None,
    instrument_token: int | None = None,
) -> pd.DataFrame:
    cached = read_cached_ohlcv(tradingsymbol, exchange=exchange)
    if len(cached) >= 35:
        return cached.tail(days)

    if kite is not None and instrument_token is not None:
        try:
            frame = fetch_kite_ohlcv(kite, instrument_token, days)
            if len(frame) >= 35:
                write_cached_ohlcv(tradingsymbol, exchange, frame)
                return frame
        except Exception:
            pass

    frame = fetch_yahoo_ohlcv(tradingsymbol, exchange, days)
    if len(frame) >= 35:
        write_cached_ohlcv(tradingsymbol, exchange, frame)
    return frame
