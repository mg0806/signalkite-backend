from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

from api.portfolio import router as portfolio_router
from api.market import router as market_router
from api.wealth import router as wealth_router
from auth.kite import router as kite_router
from auth.security import set_current_user_context
from config import settings
from db import init_db
from middleware import RateLimitMiddleware, RequestLoggingMiddleware, metrics_text
from scheduler import start_scheduler
from services.health import readiness, service_metadata

app = FastAPI(title="SignalKite API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(kite_router)
app.include_router(market_router)
app.include_router(portfolio_router, dependencies=[Depends(set_current_user_context)])
app.include_router(wealth_router, dependencies=[Depends(set_current_user_context)])
app.include_router(kite_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1", dependencies=[Depends(set_current_user_context)])
app.include_router(wealth_router, prefix="/api/v1", dependencies=[Depends(set_current_user_context)])


@app.on_event("startup")
def on_startup() -> None:
    if settings.db_auto_create or settings.database_url.startswith("sqlite"):
        init_db()
    if settings.scheduler_enabled:
        app.state.scheduler = start_scheduler()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    status_code, payload = readiness()
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/version")
def version() -> dict:
    return service_metadata()


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    if not settings.metrics_enabled:
        return PlainTextResponse("metrics disabled\n", status_code=404)
    return PlainTextResponse(metrics_text(), media_type="text/plain")
