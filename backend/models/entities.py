from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kite_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access_token: Mapped[str] = mapped_column(String(512))
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fcm_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    holdings: Mapped[list["Holding"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    portfolios: Mapped[list["Portfolio"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(96))
    base_currency: Mapped[str] = mapped_column(String(8), default="INR")
    benchmark_symbol: Mapped[str] = mapped_column(String(32), default="NIFTY 50")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="portfolios")


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "tradingsymbol", name="uq_user_holding_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    quantity: Mapped[int] = mapped_column(Integer)
    average_price: Mapped[float] = mapped_column(Float)
    last_price: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="holdings")


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "holding_id", name="uq_portfolio_holding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    holding_id: Mapped[int] = mapped_column(ForeignKey("holdings.id"), index=True)
    allocation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    signal_type: Mapped[str] = mapped_column(String(8), index=True)
    confidence: Mapped[str] = mapped_column(String(8), index=True)
    rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_position: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ema_cross: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(256))
    signal_type: Mapped[str] = mapped_column(String(8))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "tradingsymbol", name="uq_user_watch_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id"), nullable=True, index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float, default=0)
    trade_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Dividend(Base):
    __tablename__ = "dividends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    ex_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="forecast")


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(32), index=True)
    condition: Mapped[str] = mapped_column(String(16))
    target_price: Mapped[float] = mapped_column(Float)
    channels: Mapped[str] = mapped_column(String(128), default="browser")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(96))
    target_value: Mapped[float] = mapped_column(Float)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    inflation_rate: Mapped[float] = mapped_column(Float, default=0.06)
    expected_return_rate: Mapped[float] = mapped_column(Float, default=0.12)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(32), default="read_only")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OhlcvCache(Base):
    __tablename__ = "ohlcv_cache"
    __table_args__ = (UniqueConstraint("tradingsymbol", "exchange", "date", name="uq_ohlcv_symbol_exchange_date"),)

    tradingsymbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), primary_key=True, default="NSE")
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)


class MarketScanJob(Base):
    __tablename__ = "market_scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    limit_per_category: Mapped[int] = mapped_column(Integer, default=2)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
