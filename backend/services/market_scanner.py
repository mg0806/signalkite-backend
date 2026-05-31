from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange

from services.historical_data import fetch_ohlcv
from services.signal_engine import compute_signal_from_ohlcv


CATEGORY_UNIVERSE: dict[str, list[str]] = {
    "Banks": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB", "CANBK", "FEDERALBNK"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "MPHASIS", "PERSISTENT", "COFORGE", "OFSS"],
    "Energy": ["RELIANCE", "ONGC", "IOC", "BPCL", "HINDPETRO", "GAIL", "OIL", "PETRONET", "NTPC", "POWERGRID"],
    "Auto": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT", "TVSMOTOR", "HEROMOTOCO", "ASHOKLEY", "MOTHERSON", "BOSCHLTD"],
    "Pharma": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "AUROPHARMA", "ALKEM", "TORNTPHARM", "ZYDUSLIFE", "GLENMARK"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO", "GODREJCP", "COLPAL", "TATACONSUM", "UBL"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "SAIL", "NMDC", "NATIONALUM", "HINDZINC", "COALINDIA"],
    "Cement": ["ULTRACEMCO", "GRASIM", "SHREECEM", "AMBUJACEM", "ACC", "DALBHARAT", "JKCEMENT", "RAMCOCEM", "INDIACEM", "NUVOCO"],
    "Infra": ["LT", "ADANIPORTS", "IRB", "NBCC", "GMRINFRA", "RVNL", "IRCON", "PNCINFRA", "KEC", "KNRCON"],
    "Realty": ["DLF", "LODHA", "GODREJPROP", "OBEROIRLTY", "PHOENIXLTD", "PRESTIGE", "BRIGADE", "SOBHA", "MAHLIFE", "SUNTECK"],
    "Consumer Durables": ["TITAN", "DIXON", "VOLTAS", "BLUESTARCO", "CROMPTON", "HAVELLS", "AMBER", "WHIRLPOOL", "KALYANKJIL", "RAJESHEXPO"],
    "Telecom": ["BHARTIARTL", "IDEA", "INDUSTOWER", "TATACOMM", "TEJASNET", "HFCL", "RAILTEL", "STLTECH"],
    "Defence": ["HAL", "BEL", "BEML", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "DATAPATTNS", "ASTRAMICRO", "PARAS"],
    "Chemicals": ["PIDILITIND", "SRF", "DEEPAKNTR", "AARTIIND", "TATACHEM", "NAVINFLUOR", "ATUL", "FLUOROCHEM", "ALKYLAMINE", "GNFC"],
    "Financial Services": ["BAJFINANCE", "BAJAJFINSV", "JIOFIN", "SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI", "CHOLAFIN", "MUTHOOTFIN", "RECLTD"],
}

_CACHE: dict[tuple[int], tuple[float, list[dict]]] = {}
CACHE_TTL_SECONDS = 15 * 60


@dataclass
class PickCandidate:
    category: str
    tradingsymbol: str
    exchange: str
    last_price: float
    performance_1m: float
    performance_3m: float
    rsi: float | None
    confidence: str
    signal_type: str
    reason: str
    target_low: float
    target_high: float
    downside_level: float
    score: float
    sparkline: list[float]


def _pct_change(frame: pd.DataFrame, sessions: int) -> float:
    if len(frame) <= sessions:
        return 0.0
    current = float(frame["close"].iloc[-1])
    previous = float(frame["close"].iloc[-sessions])
    return ((current - previous) / previous) * 100 if previous else 0.0


def _round_price(value: float) -> float:
    if value >= 1000:
        return round(value)
    if value >= 100:
        return round(value, 1)
    return round(value, 2)


def _candidate(category: str, symbol: str) -> PickCandidate | None:
    frame = fetch_ohlcv(symbol, days=180, exchange="NSE")
    exchange = "NSE"
    if frame.empty or len(frame) < 60:
        frame = fetch_ohlcv(symbol, days=180, exchange="BSE")
        exchange = "BSE"
    if frame.empty or len(frame) < 60:
        return None

    frame = frame.copy()
    close = pd.to_numeric(frame["close"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    frame = frame.assign(close=close, high=high, low=low).dropna(subset=["close", "high", "low"])
    if len(frame) < 60:
        return None

    signal = compute_signal_from_ohlcv(frame)
    last_price = float(frame["close"].iloc[-1])
    performance_1m = _pct_change(frame, 21)
    performance_3m = _pct_change(frame, 63)
    rsi_series = RSIIndicator(close=frame["close"], window=14).rsi()
    rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else None
    macd_hist = MACD(close=frame["close"], window_fast=12, window_slow=26, window_sign=9).macd_diff()
    ema20 = EMAIndicator(close=frame["close"], window=20).ema_indicator()
    ema50 = EMAIndicator(close=frame["close"], window=50).ema_indicator()
    atr = AverageTrueRange(high=frame["high"], low=frame["low"], close=frame["close"], window=14).average_true_range()

    recent = frame.tail(30)
    resistance = float(recent["high"].max())
    support = float(recent["low"].min())
    atr_latest = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else last_price * 0.03
    momentum_target = last_price * (1 + max(min(performance_1m, 18), -8) / 100)
    target_low = max(last_price, min(momentum_target, resistance + atr_latest))
    target_high = max(target_low, resistance + (1.5 * atr_latest))
    downside_level = min(support, last_price - (1.2 * atr_latest))

    score = (performance_3m * 0.5) + (performance_1m * 0.8)
    if signal.signal_type == "BUY":
        score += 8 if signal.confidence == "HIGH" else 4
    if macd_hist.iloc[-1] > macd_hist.iloc[-2]:
        score += 3
    if ema20.iloc[-1] > ema50.iloc[-1]:
        score += 4
    if rsi is not None and rsi > 72:
        score -= 8
    if performance_3m < 0:
        score -= 6
    if signal.signal_type == "SELL":
        score -= 10
    if performance_1m > 0 and performance_3m > 0 and signal.signal_type != "SELL":
        score += 6

    sparkline = [_round_price(float(value)) for value in frame["close"].tail(7)]
    return PickCandidate(
        category=category,
        tradingsymbol=symbol,
        exchange=exchange,
        last_price=_round_price(last_price),
        performance_1m=round(performance_1m, 2),
        performance_3m=round(performance_3m, 2),
        rsi=round(rsi, 1) if rsi is not None else None,
        confidence="HIGH" if score >= 18 else "MEDIUM" if score >= 8 else "LOW",
        signal_type=signal.signal_type,
        reason=signal.reason,
        target_low=_round_price(target_low),
        target_high=_round_price(target_high),
        downside_level=_round_price(downside_level),
        score=round(score, 2),
        sparkline=sparkline,
    )


def scan_market_top_picks(limit_per_category: int = 3) -> list[dict]:
    cache_key = (limit_per_category,)
    cached_at, cached_payload = _CACHE.get(cache_key, (0.0, []))
    if cached_payload and time.time() - cached_at < CACHE_TTL_SECONDS:
        return cached_payload

    by_category: dict[str, list[PickCandidate]] = {category: [] for category in CATEGORY_UNIVERSE}
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(_candidate, category, symbol): category
            for category, symbols in CATEGORY_UNIVERSE.items()
            for symbol in symbols
        }
        for future in as_completed(futures):
            try:
                candidate = future.result()
            except Exception:
                continue
            if candidate is not None:
                by_category[candidate.category].append(candidate)

    picks: list[PickCandidate] = []
    for category, category_picks in by_category.items():
        category_picks.sort(key=lambda item: item.score, reverse=True)
        picks.extend(category_picks[:limit_per_category])

    payload = [
        {
            "category": pick.category,
            "sector": pick.category,
            "tradingsymbol": pick.tradingsymbol,
            "exchange": pick.exchange,
            "last_price": pick.last_price,
            "performance_1m": pick.performance_1m,
            "performance_3m": pick.performance_3m,
            "rsi": pick.rsi,
            "confidence": pick.confidence,
            "signal_type": pick.signal_type,
            "reason": pick.reason,
            "target_low": pick.target_low,
            "target_high": pick.target_high,
            "downside_level": pick.downside_level,
            "score": pick.score,
            "sparkline": pick.sparkline,
            "as_of": datetime.utcnow().isoformat(),
        }
        for pick in picks
    ]
    _CACHE[cache_key] = (time.time(), payload)
    return payload
