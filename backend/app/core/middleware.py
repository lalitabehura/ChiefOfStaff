"""HTTP hardening: security headers, body-size cap, global rate limit, request IDs, access logs."""
import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.rate_limit import client_ip, limiter

log = logging.getLogger("app.access")


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()

        # 1) body size cap (cheap rejection before parsing)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_request_bytes:
            return JSONResponse({"detail": "Request body too large."}, status_code=413)

        # 2) global per-IP rate limit (endpoint-specific limits are stricter)
        if request.url.path.startswith("/api/") and not limiter.hit(
            f"global:{client_ip(request)}", settings.global_rate_limit_per_minute, 60
        ):
            return JSONResponse(
                {"detail": "Too many requests."}, status_code=429, headers={"Retry-After": "60"}
            )

        response = await call_next(request)

        # 3) security headers (the SPA's CSP is set by nginx; API responses get a locked-down CSP)
        h = response.headers
        h["X-Request-ID"] = request_id
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            h.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

        # 4) structured access log (never logs bodies, tokens or query strings)
        log.info(json.dumps({
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "ip": client_ip(request),
        }))
        return response
