import re
import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import (
    AGENT_API_KEY,
    SUPERVISOR_API_KEY,
    BORROWER_ID_PATTERN,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)

BORROWER_ID_RE = re.compile(BORROWER_ID_PATTERN)

# role -> api_key mapping (keys are secrets, roles are derived)
_API_KEY_TO_ROLE = {
    AGENT_API_KEY: "agent",
    SUPERVISOR_API_KEY: "supervisor",
}

# In-memory rate limit buckets: client_id -> [timestamps]
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_last_cleanup_time = 0.0


def resolve_role_from_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key or not api_key.strip():
        return None
    return _API_KEY_TO_ROLE.get(api_key.strip())


def require_role(api_key: Optional[str], allowed_roles: set[str]) -> str:
    role = resolve_role_from_api_key(api_key)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation.",
        )
    return role


def validate_borrower_id(borrower_id: str) -> str:
    if not borrower_id or not BORROWER_ID_RE.match(borrower_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid borrower ID format.",
        )
    return borrower_id


def _client_id(request: Request, api_key: Optional[str]) -> str:
    if api_key:
        return f"key:{api_key[:8]}"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def check_rate_limit(request: Request, api_key: Optional[str] = None) -> None:
    global _last_cleanup_time
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    cid = _client_id(request, api_key)

    bucket = _rate_buckets[cid]
    _rate_buckets[cid] = [t for t in bucket if t > window_start]

    if not _rate_buckets[cid]:
        _rate_buckets.pop(cid, None)
        bucket = []
    else:
        bucket = _rate_buckets[cid]

    # Periodic cleanup of all inactive/expired clients to prevent memory leaks
    if now - _last_cleanup_time > 60.0:
        expired_keys = []
        for key, timestamps in list(_rate_buckets.items()):
            active = [t for t in timestamps if t > window_start]
            if not active:
                expired_keys.append(key)
            else:
                _rate_buckets[key] = active
        for key in expired_keys:
            _rate_buckets.pop(key, None)
        _last_cleanup_time = now

    if len(bucket) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )

    if cid not in _rate_buckets:
        _rate_buckets[cid] = []
    _rate_buckets[cid].append(now)


def reset_rate_limits() -> None:
    """Test helper — clears in-memory rate limit state."""
    _rate_buckets.clear()


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "****"
    return phone[:4] + "*" * (len(phone) - 7) + phone[-3:]


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "****"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = local[0] + "***"
    return f"{masked_local}@{domain}"


def redact_borrower_for_list(borrower: dict, role: str) -> dict:
    """List view: mask PII for agents; supervisors see full records."""
    record = dict(borrower)
    if role == "agent":
        record["phone"] = mask_phone(record.get("phone", ""))
        record["email"] = mask_email(record.get("email", ""))
        record.pop("ai_prompt_sent", None)
        record.pop("ai_raw_response", None)
    return record


def redact_borrower_for_detail(borrower: dict, role: str) -> dict:
    """Detail view: agents get full contact info but no AI audit payloads."""
    record = dict(borrower)
    if role == "agent":
        record.pop("ai_prompt_sent", None)
        record.pop("ai_raw_response", None)
    return record


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none';"
        )
        return response
