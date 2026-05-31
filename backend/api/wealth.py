import csv
import io
import re
from datetime import date, datetime
from secrets import token_urlsafe

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.portfolio import get_demo_user, portfolio, signals
from db import get_db
from models import Dividend, Goal, Holding, Portfolio, PortfolioHolding, PriceAlert, ShareLink, Transaction, WatchlistItem
from services.historical_data import fetch_ohlcv
from services.notifications import configured_channels, send_notification
from services.alert_service import evaluate_price_alerts
from services.ollama_ai import ask_ollama, extract_trade_from_text

router = APIRouter(prefix="/wealth", tags=["wealth"])


class PortfolioIn(BaseModel):
    name: str
    base_currency: str = "INR"
    benchmark_symbol: str = "NIFTY 50"


class WatchlistIn(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    target_price: float | None = None
    stop_loss: float | None = None


class PriceAlertIn(BaseModel):
    tradingsymbol: str
    condition: str
    target_price: float
    channels: list[str] = Field(default_factory=lambda: ["browser"])


class TransactionIn(BaseModel):
    tradingsymbol: str
    side: str
    quantity: float
    price: float
    trade_date: datetime
    exchange: str = "NSE"
    charges: float = 0
    source: str = "manual"
    notes: str | None = None


class GoalIn(BaseModel):
    name: str
    target_value: float
    target_date: date | None = None
    inflation_rate: float = 0.06
    expected_return_rate: float = 0.12


class TextImportIn(BaseModel):
    text: str


class AssignmentIn(BaseModel):
    holding_id: int
    allocation_pct: float | None = None


class RetirementPlanIn(BaseModel):
    current_age: int = 30
    retirement_age: int = 60
    monthly_contribution: float = 0
    expected_return_rate: float = 0.12
    inflation_rate: float = 0.06


class NotificationTestIn(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["telegram"])
    message: str = "SignalKite alert test"


def _holding_value(holding: Holding) -> float:
    return holding.quantity * holding.last_price


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    portfolio_payload = portfolio(db)
    holdings = db.query(Holding).filter(Holding.user_id == user.id).all()
    total_value = portfolio_payload["summary"]["total_value"]
    by_exchange: dict[str, float] = {}
    for holding in holdings:
        by_exchange[holding.exchange] = by_exchange.get(holding.exchange, 0) + _holding_value(holding)

    return {
        "summary": portfolio_payload["summary"],
        "allocation": {
            "by_exchange": [
                {"label": exchange, "value": value, "weight": value / total_value if total_value else 0}
                for exchange, value in by_exchange.items()
            ],
            "by_asset_type": [{"label": "Equity/ETF", "value": total_value, "weight": 1 if total_value else 0}],
            "by_currency": [{"label": "INR", "value": total_value, "weight": 1 if total_value else 0}],
        },
        "signals": signals(db),
        "watchlist_count": db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).count(),
        "open_alerts": db.query(PriceAlert).filter(PriceAlert.user_id == user.id, PriceAlert.enabled == True).count(),  # noqa: E712
        "goals": db.query(Goal).filter(Goal.user_id == user.id).count(),
        "notification_channels": configured_channels(),
    }


@router.get("/performance")
def performance(benchmark: str = "NIFTY 50", db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    holdings = db.query(Holding).filter(Holding.user_id == user.id).all()
    series: dict[str, float] = {}
    for holding in holdings:
        frame = fetch_ohlcv(holding.tradingsymbol, exchange=holding.exchange, days=180)
        for row in frame.tail(90).to_dict("records"):
            key = row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"])
            series[key] = series.get(key, 0) + (float(row["close"]) * holding.quantity)
    benchmark_symbol = "^NSEI" if benchmark.upper() in {"NIFTY", "NIFTY 50"} else benchmark
    benchmark_frame = fetch_ohlcv(benchmark_symbol, days=180)
    return {
        "benchmark": benchmark,
        "portfolio": [{"date": key, "value": value} for key, value in sorted(series.items())],
        "benchmark_series": [
            {
                "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
                "value": float(row["close"]),
            }
            for row in benchmark_frame.tail(90).to_dict("records")
        ],
    }


@router.get("/portfolios")
def list_portfolios(db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    rows = db.query(Portfolio).filter(Portfolio.user_id == user.id).order_by(Portfolio.id).all()
    if not rows:
        row = Portfolio(user_id=user.id, name="Zerodha Portfolio", base_currency="INR", benchmark_symbol="NIFTY 50", is_default=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        rows = [row]
    return [
        {
            "id": row.id,
            "name": row.name,
            "base_currency": row.base_currency,
            "benchmark_symbol": row.benchmark_symbol,
            "is_default": row.is_default,
        }
        for row in rows
    ]


@router.post("/portfolios")
def create_portfolio(payload: PortfolioIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    row = Portfolio(user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name}


@router.get("/portfolios/{portfolio_id}/holdings")
def portfolio_holdings(portfolio_id: int, db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    portfolio_row = db.query(Portfolio).filter(Portfolio.id == portfolio_id, Portfolio.user_id == user.id).one_or_none()
    if portfolio_row is None:
        return []
    assignments = db.query(PortfolioHolding).filter(PortfolioHolding.portfolio_id == portfolio_id).all()
    if not assignments and portfolio_row.is_default:
        holdings = db.query(Holding).filter(Holding.user_id == user.id).order_by(Holding.tradingsymbol).all()
        return [{"holding_id": row.id, "tradingsymbol": row.tradingsymbol, "value": row.quantity * row.last_price, "allocation_pct": None} for row in holdings]
    holding_by_id = {row.id: row for row in db.query(Holding).filter(Holding.user_id == user.id).all()}
    return [
        {
            "holding_id": assignment.holding_id,
            "tradingsymbol": holding_by_id[assignment.holding_id].tradingsymbol,
            "value": holding_by_id[assignment.holding_id].quantity * holding_by_id[assignment.holding_id].last_price,
            "allocation_pct": assignment.allocation_pct,
        }
        for assignment in assignments
        if assignment.holding_id in holding_by_id
    ]


@router.post("/portfolios/{portfolio_id}/holdings")
def assign_holding(portfolio_id: int, payload: AssignmentIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    holding = db.query(Holding).filter(Holding.id == payload.holding_id, Holding.user_id == user.id).one_or_none()
    portfolio_row = db.query(Portfolio).filter(Portfolio.id == portfolio_id, Portfolio.user_id == user.id).one_or_none()
    if holding is None or portfolio_row is None:
        return {"status": "not_found"}
    row = db.query(PortfolioHolding).filter(PortfolioHolding.portfolio_id == portfolio_id, PortfolioHolding.holding_id == payload.holding_id).one_or_none()
    if row is None:
        row = PortfolioHolding(portfolio_id=portfolio_id, holding_id=payload.holding_id, allocation_pct=payload.allocation_pct)
        db.add(row)
    else:
        row.allocation_pct = payload.allocation_pct
    db.commit()
    return {"status": "assigned", "portfolio_id": portfolio_id, "holding_id": payload.holding_id}


@router.get("/watchlist")
def list_watchlist(db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    rows = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).order_by(WatchlistItem.created_at.desc()).all()
    return [
        {
            "id": row.id,
            "tradingsymbol": row.tradingsymbol,
            "exchange": row.exchange,
            "target_price": row.target_price,
            "stop_loss": row.stop_loss,
        }
        for row in rows
    ]


@router.post("/watchlist")
def add_watchlist_item(payload: WatchlistIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    row = WatchlistItem(user_id=user.id, tradingsymbol=payload.tradingsymbol.upper(), exchange=payload.exchange, target_price=payload.target_price, stop_loss=payload.stop_loss)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "tradingsymbol": row.tradingsymbol}


@router.get("/dividends")
def dividends(db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    rows = db.query(Dividend).filter(Dividend.user_id == user.id).order_by(Dividend.pay_date.desc()).all()
    total = sum(row.amount for row in rows)
    return {
        "total_income": total,
        "forecast_income": sum(row.amount for row in rows if row.status == "forecast"),
        "calendar": [
            {
                "tradingsymbol": row.tradingsymbol,
                "amount": row.amount,
                "currency": row.currency,
                "ex_date": row.ex_date,
                "pay_date": row.pay_date,
                "status": row.status,
            }
            for row in rows
        ],
    }


@router.get("/alerts")
def list_price_alerts(db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    rows = db.query(PriceAlert).filter(PriceAlert.user_id == user.id).order_by(PriceAlert.created_at.desc()).all()
    return [
        {
            "id": row.id,
            "tradingsymbol": row.tradingsymbol,
            "condition": row.condition,
            "target_price": row.target_price,
            "channels": row.channels.split(","),
            "enabled": row.enabled,
            "triggered_at": row.triggered_at,
        }
        for row in rows
    ]


@router.post("/alerts")
def create_price_alert(payload: PriceAlertIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    row = PriceAlert(
        user_id=user.id,
        tradingsymbol=payload.tradingsymbol.upper(),
        condition=payload.condition,
        target_price=payload.target_price,
        channels=",".join(payload.channels),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "tradingsymbol": row.tradingsymbol}


@router.post("/alerts/evaluate")
def evaluate_alerts(db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    return {"results": evaluate_price_alerts(db, user)}


@router.post("/transactions")
def add_transaction(payload: TransactionIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    row = Transaction(user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "tradingsymbol": row.tradingsymbol}


@router.get("/reports/capital-gains")
def capital_gains_report(tax_year: str | None = None, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    rows = db.query(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.trade_date).all()
    buys: dict[str, list[dict]] = {}
    realized = []
    for row in rows:
        if row.side.upper() == "BUY":
            buys.setdefault(row.tradingsymbol, []).append({"quantity": row.quantity, "price": row.price, "trade_date": row.trade_date})
        elif row.side.upper() == "SELL":
            remaining = row.quantity
            cost = 0.0
            lots = buys.get(row.tradingsymbol, [])
            while remaining > 0 and lots:
                lot = lots[0]
                matched = min(remaining, lot["quantity"])
                cost += matched * lot["price"]
                holding_days = (row.trade_date.date() - lot["trade_date"].date()).days if lot.get("trade_date") and row.trade_date else None
                lot["quantity"] -= matched
                remaining -= matched
                if lot["quantity"] <= 0:
                    lots.pop(0)
            proceeds = row.quantity * row.price
            tax_bucket = "unknown"
            if holding_days is not None:
                tax_bucket = "LTCG" if holding_days and holding_days > 365 else "STCG"
            realized.append(
                {
                    "tradingsymbol": row.tradingsymbol,
                    "proceeds": proceeds,
                    "cost": cost,
                    "gain": proceeds - cost,
                    "trade_date": row.trade_date,
                    "tax_bucket": tax_bucket,
                    "india_tax_note": "Equity STCG/LTCG classification is FIFO-based; verify holding period and exemptions before filing.",
                }
            )
    total_gain = sum(item["gain"] for item in realized)
    return {
        "tax_year": tax_year,
        "jurisdiction": "India",
        "method": "FIFO",
        "realized": realized,
        "total_gain": total_gain,
        "disclaimer": "Draft estimate only. Confirm with a CA before filing.",
    }


@router.get("/goals")
def list_goals(db: Session = Depends(get_db)) -> list[dict]:
    user = get_demo_user(db)
    current_value = portfolio(db)["summary"]["total_value"]
    rows = db.query(Goal).filter(Goal.user_id == user.id).order_by(Goal.created_at.desc()).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "target_value": row.target_value,
            "target_date": row.target_date,
            "current_value": current_value,
            "progress": min(current_value / row.target_value, 1) if row.target_value else 0,
            "expected_return_rate": row.expected_return_rate,
        }
        for row in rows
    ]


@router.post("/goals")
def create_goal(payload: GoalIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    row = Goal(user_id=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name}


@router.post("/share-links")
def create_share_link(db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    row = ShareLink(user_id=user.id, token=token_urlsafe(32), scope="read_only")
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"token": row.token, "url": f"/share/{row.token}"}


@router.post("/imports/ai")
def ai_trade_import(payload: TextImportIn) -> dict:
    ollama_trade = extract_trade_from_text(payload.text)
    if ollama_trade:
        return {"status": "parsed", "provider": "ollama", "input_type": "text", "extracted": ollama_trade}

    text = payload.text.upper()
    side_match = re.search(r"\b(BUY|BOUGHT|SELL|SOLD)\b", text)
    qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:QTY|SHARES|UNITS)?", text)
    price_match = re.search(r"(?:AT|@|PRICE)\s*(?:RS\.?|INR|₹)?\s*(\d+(?:\.\d+)?)", text)
    ignored_tokens = {"BUY", "BOUGHT", "SELL", "SOLD", "AT", "PRICE", "QTY", "SHARES", "UNITS", "INR", "RS"}
    symbol = None
    for token in re.findall(r"\b[A-Z]{2,15}\b", text):
        if token not in ignored_tokens:
            symbol = token
            break
    side = None
    if side_match:
        side = "BUY" if side_match.group(1) in {"BUY", "BOUGHT"} else "SELL"
    extracted = {
        "tradingsymbol": symbol,
        "side": side,
        "quantity": float(qty_match.group(1)) if qty_match else None,
        "price": float(price_match.group(1)) if price_match else None,
        "trade_date": datetime.utcnow().isoformat(),
        "confidence": "LOW",
    }
    return {"status": "parsed", "provider": "heuristic", "input_type": "text", "extracted": extracted}


@router.post("/imports/csv")
def csv_import(payload: TextImportIn, db: Session = Depends(get_db)) -> dict:
    user = get_demo_user(db)
    reader = csv.DictReader(io.StringIO(payload.text))
    created = 0
    errors = []
    for index, row in enumerate(reader, start=2):
        try:
            normalized = {key.lower().strip().replace(" ", "_"): value for key, value in row.items() if key}
            symbol = normalized.get("tradingsymbol") or normalized.get("symbol") or normalized.get("instrument") or normalized.get("instrument_name")
            side = normalized.get("side") or normalized.get("transaction_type") or normalized.get("trade_type")
            quantity = normalized.get("quantity") or normalized.get("qty")
            price = normalized.get("price") or normalized.get("trade_price") or normalized.get("average_price")
            trade_date = normalized.get("trade_date") or normalized.get("date") or normalized.get("order_execution_time")
            trade = Transaction(
                user_id=user.id,
                tradingsymbol=str(symbol).upper(),
                side=str(side).upper(),
                quantity=float(quantity),
                price=float(price),
                trade_date=datetime.fromisoformat(str(trade_date).replace(" ", "T")[:19]),
                exchange=normalized.get("exchange") or "NSE",
                charges=float(normalized.get("charges") or normalized.get("brokerage") or 0),
                source="zerodha_csv",
                notes=normalized.get("notes"),
            )
            db.add(trade)
            created += 1
        except Exception as exc:
            errors.append({"line": index, "error": str(exc)})
    db.commit()
    return {"status": "imported", "created": created, "errors": errors}


@router.post("/planning/retirement")
def retirement_projection(payload: RetirementPlanIn, db: Session = Depends(get_db)) -> dict:
    current_value = portfolio(db)["summary"]["total_value"]
    years = max(payload.retirement_age - payload.current_age, 0)
    annual_contribution = payload.monthly_contribution * 12
    projected = current_value
    path = []
    for year in range(1, years + 1):
        projected = (projected + annual_contribution) * (1 + payload.expected_return_rate)
        real_value = projected / ((1 + payload.inflation_rate) ** year)
        path.append({"year": year, "nominal": projected, "inflation_adjusted": real_value})
    return {"current_value": current_value, "years": years, "projected_value": projected, "path": path}


@router.post("/ai/ask")
def ask_portfolio(payload: TextImportIn, db: Session = Depends(get_db)) -> dict:
    question = payload.text.lower()
    data = portfolio(db)
    current_signals = signals(db)
    ai_context = {
        "summary": data["summary"],
        "signals": current_signals,
        "question": payload.text,
    }
    ollama_answer = ask_ollama(
        f"Answer this Indian portfolio question using the JSON context. Context: {ai_context}",
        system="You are SignalKite's Indian portfolio assistant. Be concise and avoid guaranteeing returns.",
    )
    if ollama_answer:
        return {"answer": ollama_answer, "provider": "ollama", "data": ai_context}
    if "risk" in question or "sell" in question:
        answer = [row for row in current_signals if row["type"] == "SELL"]
        return {"answer": "Current risk flags are SELL signals and overbought positions.", "data": answer}
    if "buy" in question or "opportunity" in question:
        answer = [row for row in current_signals if row["type"] == "BUY"]
        return {"answer": "Current opportunities are BUY signals from the technical engine.", "data": answer}
    if "allocation" in question or "diversification" in question:
        return {"answer": "Allocation is available by exchange, asset type, and currency in the dashboard endpoint.", "data": dashboard(db)["allocation"]}
    return {"answer": f"Portfolio value is {data['summary']['total_value']:.2f} INR with {data['summary']['active_signals']} active signals.", "data": data["summary"]}


@router.get("/notifications/channels")
def notification_channels() -> dict:
    return configured_channels()


@router.post("/notifications/test")
def test_notifications(payload: NotificationTestIn) -> dict:
    return {
        "configured": configured_channels(),
        "results": send_notification(payload.channels, "SignalKite", payload.message),
    }
