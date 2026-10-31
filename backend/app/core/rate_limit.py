"""Fixed-window rate limiting. Uses Redis when configured (shared across workers), memory otherwise."""
import logging
import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

log = logging.getLogger("app.ratelimit")


class RateLimiter:
    def __init__(self, redis_url: str | None):
        self._redis = None
        if redis_url:
            import redis

            self._redis = redis.Redis.from_url(redis_url, socket_timeout=1)
        self._mem: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit; return True if allowed."""
        bucket = int(time.time() // window_seconds)
        full_key = f"rl:{key}:{bucket}"
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(full_key)
                pipe.expire(full_key, window_seconds + 1)
                count, _ = pipe.execute()
                return int(count) <= limit
            except Exception as exc:  # Redis outage: fall back to local memory rather than failing open
                log.warning("rate limiter redis unavailable: %s", type(exc).__name__)
        with self._lock:
            now = time.time()
            if len(self._mem) > 50_000:
                self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
            count, expiry = self._mem.get(full_key, (0, now + window_seconds))
            count += 1
            self._mem[full_key] = (count, expiry)
            return count <= limit

    def reset(self) -> None:
        with self._lock:
            self._mem.clear()


limiter = RateLimiter(get_settings().redis_url)


def client_ip(request: Request) -> str:
    # Uvicorn's --proxy-headers sets request.client from X-Forwarded-For of trusted proxies only.
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window_seconds: int):
    """FastAPI dependency: per-IP limit for a specific endpoint group."""

    def dependency(request: Request) -> None:
        if not limiter.hit(f"{name}:{client_ip(request)}", limit, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency
