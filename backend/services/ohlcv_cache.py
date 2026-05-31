from datetime import date, datetime

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db import SessionLocal
from models import OhlcvCache


def read_cached_ohlcv(tradingsymbol: str, exchange: str = "NSE", min_rows: int = 35) -> pd.DataFrame:
    db = SessionLocal()
    try:
        rows = (
            db.query(OhlcvCache)
            .filter(OhlcvCache.tradingsymbol == tradingsymbol.upper(), OhlcvCache.exchange == exchange.upper())
            .order_by(OhlcvCache.date)
            .all()
        )
    finally:
        db.close()

    if len(rows) < min_rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    return pd.DataFrame(
        [
            {
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ]
    )


def _row_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def write_cached_ohlcv(tradingsymbol: str, exchange: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return

    db = SessionLocal()
    try:
        for item in frame.to_dict("records"):
            payload = {
                "tradingsymbol": tradingsymbol.upper(),
                "exchange": exchange.upper(),
                "date": _row_date(item["date"]),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": int(item.get("volume") or 0),
            }
            _upsert_ohlcv(db, payload)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _upsert_ohlcv(db: Session, payload: dict) -> None:
    if db.bind and db.bind.dialect.name == "postgresql":
        statement = pg_insert(OhlcvCache).values(**payload)
        statement = statement.on_conflict_do_update(
            index_elements=["tradingsymbol", "exchange", "date"],
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "volume": statement.excluded.volume,
            },
        )
        db.execute(statement)
        return

    existing = (
        db.query(OhlcvCache)
        .filter(
            OhlcvCache.tradingsymbol == payload["tradingsymbol"],
            OhlcvCache.exchange == payload["exchange"],
            OhlcvCache.date == payload["date"],
        )
        .one_or_none()
    )
    if existing is None:
        db.add(OhlcvCache(**payload))
    else:
        existing.open = payload["open"]
        existing.high = payload["high"]
        existing.low = payload["low"]
        existing.close = payload["close"]
        existing.volume = payload["volume"]
