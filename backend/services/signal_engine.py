from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from kiteconnect import KiteConnect
from sqlalchemy.orm import Session
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands

from models import Signal
from services.historical_data import fetch_ohlcv


@dataclass
class SignalResult:
    signal_type: str
    confidence: str
    rsi: float | None
    macd_hist: float | None
    bb_position: str
    ema_cross: str
    reason: str


def _latest_cross(previous_fast: float, previous_slow: float, fast: float, slow: float) -> str:
    if previous_fast <= previous_slow and fast > slow:
        return "bullish"
    if previous_fast >= previous_slow and fast < slow:
        return "bearish"
    return "flat"


def compute_signal_from_ohlcv(ohlcv: pd.DataFrame) -> SignalResult:
    if ohlcv.empty or len(ohlcv) < 35:
        return SignalResult("HOLD", "LOW", None, None, "unknown", "flat", "Not enough candle history")

    frame = ohlcv.copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    close = frame["close"]

    frame["rsi"] = RSIIndicator(close=close, window=14).rsi()
    macd_indicator = MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    bbands = BollingerBands(close=close, window=20, window_dev=2)
    frame["ema9"] = EMAIndicator(close=close, window=9).ema_indicator()
    frame["ema21"] = EMAIndicator(close=close, window=21).ema_indicator()

    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    rsi = float(latest["rsi"]) if pd.notna(latest["rsi"]) else None
    price = float(latest["close"])
    lower = float(bbands.bollinger_lband().iloc[-1])
    upper = float(bbands.bollinger_hband().iloc[-1])
    macd_diff = macd_indicator.macd_diff()
    macd_hist = float(macd_diff.iloc[-1])
    previous_macd_hist = float(macd_diff.iloc[-2])
    ema_cross = _latest_cross(previous["ema9"], previous["ema21"], latest["ema9"], latest["ema21"])

    buy_reasons: list[str] = []
    sell_reasons: list[str] = []

    if rsi is not None and rsi < 35:
        buy_reasons.append("RSI oversold")
    if rsi is not None and rsi > 65:
        sell_reasons.append("RSI overbought")

    if previous_macd_hist <= 0 < macd_hist:
        buy_reasons.append("MACD bullish crossover")
    if previous_macd_hist >= 0 > macd_hist:
        sell_reasons.append("MACD bearish crossover")

    bb_position = "middle"
    if price <= lower:
        bb_position = "lower"
        buy_reasons.append("price at lower Bollinger Band")
    elif price >= upper:
        bb_position = "upper"
        sell_reasons.append("price at upper Bollinger Band")

    if ema_cross == "bullish":
        buy_reasons.append("EMA9 crossed above EMA21")
    elif ema_cross == "bearish":
        sell_reasons.append("EMA9 crossed below EMA21")

    if len(buy_reasons) > len(sell_reasons) and buy_reasons:
        signal_type = "BUY"
        reasons = buy_reasons
    elif len(sell_reasons) > len(buy_reasons) and sell_reasons:
        signal_type = "SELL"
        reasons = sell_reasons
    else:
        signal_type = "HOLD"
        reasons = ["mixed or neutral indicator readings"]

    confidence = "HIGH" if signal_type != "HOLD" and len(reasons) >= 2 else "LOW"
    return SignalResult(signal_type, confidence, rsi, macd_hist, bb_position, ema_cross, ", ".join(reasons))


def compute_and_store_signal(
    db: Session,
    user_id: int,
    tradingsymbol: str,
    exchange: str = "NSE",
    kite: KiteConnect | None = None,
    instrument_token: int | None = None,
) -> Signal:
    result = compute_signal_from_ohlcv(
        fetch_ohlcv(tradingsymbol, exchange=exchange, kite=kite, instrument_token=instrument_token)
    )
    signal = Signal(
        user_id=user_id,
        tradingsymbol=tradingsymbol,
        signal_type=result.signal_type,
        confidence=result.confidence,
        rsi=result.rsi,
        macd_hist=result.macd_hist,
        bb_position=result.bb_position,
        ema_cross=result.ema_cross,
        reason=result.reason,
        computed_at=datetime.utcnow(),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal
