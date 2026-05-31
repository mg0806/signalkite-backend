from collections import defaultdict, deque
from time import monotonic, time
import json
import logging
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

logger = logging.getLogger("signalkite.requests")

REQUEST_COUNT: dict[tuple[str, str, int], int] = defaultdict(int)
REQUEST_LATENCY_SUM: dict[tuple[str, str], float] = defaultdict(float)
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        started = monotonic()
        response = await call_next(request)
        elapsed_ms = round((monotonic() - started) * 1000, 2)
        response.headers["x-request-id"] = request_id
        REQUEST_COUNT[(request.method, request.url.path, response.status_code)] += 1
        REQUEST_LATENCY_SUM[(request.method, request.url.path)] += elapsed_ms
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "elapsed_ms": elapsed_ms,
                    "client": request.client.host if request.client else None,
                }
            )
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health", "/ready", "/version", "/metrics"}:
            return await call_next(request)

        identifier = request.headers.get("authorization") or (request.client.host if request.client else "unknown")
        now = time()
        bucket = _RATE_BUCKETS[identifier]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_minute:
            return Response("Rate limit exceeded", status_code=429)
        bucket.append(now)
        return await call_next(request)


def metrics_text() -> str:
    lines = [
        "# HELP signalkite_http_requests_total Total HTTP requests",
        "# TYPE signalkite_http_requests_total counter",
    ]
    for (method, path, status), count in REQUEST_COUNT.items():
        lines.append(f'signalkite_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
    lines.extend(
        [
            "# HELP signalkite_http_request_latency_ms_sum Total request latency in milliseconds",
            "# TYPE signalkite_http_request_latency_ms_sum counter",
        ]
    )
    for (method, path), total in REQUEST_LATENCY_SUM.items():
        lines.append(f'signalkite_http_request_latency_ms_sum{{method="{method}",path="{path}"}} {total}')
    return "\n".join(lines) + "\n"
