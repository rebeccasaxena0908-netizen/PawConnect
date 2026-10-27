"""
Sign-in tokens, role checks and rate limiting for the REST API.

* JWT (PyJWT, HS256): POST /auth/login returns a token that expires after one
  hour. Every other request sends it as   Authorization: Bearer <token>.
* @require_auth            – any signed-in user (the user is put in flask.g.user)
* @require_role("Admin")   – only these roles
* @require_permission("allocate_funds") – uses the permission sets of the
  User classes in core/models.py, so the API and the UIs share one rule book.
* RateLimiter – "at most N events per minute per key" (e.g. per IP address).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import wraps

import jwt
from flask import current_app, g, request

from config import JWT_EXPIRY_SECONDS
from core import workflows as wf
from core.models import User


class ApiError(Exception):
    """Raise inside a route to send {"error": message, "details": [...]} with this status code."""

    def __init__(self, status: int, message: str, details: list[str] | None = None,
                 headers: dict | None = None):
        super().__init__(message)
        self.status, self.message = status, message
        self.details, self.headers = details or [], headers or {}


# ======================================================================= tokens
def create_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": user.user_id, "role": user.role, "iat": now, "exp": now + JWT_EXPIRY_SECONDS}
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def _user_from_token() -> User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "Please sign in.", ["Send the header  Authorization: Bearer <token>."])
    try:
        payload = jwt.decode(header[7:], current_app.config["JWT_SECRET"], algorithms=["HS256"],
                             options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "Your session has expired. Please sign in again.") from None
    except jwt.InvalidTokenError:
        raise ApiError(401, "Invalid sign-in token. Please sign in again.") from None
    user = wf.get_user(payload["sub"])            # re-read so role changes apply at once
    if user is None:
        raise ApiError(401, "This account no longer exists.")
    return user


# ======================================================================= decorators
def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        g.user = _user_from_token()
        return view(*args, **kwargs)
    return wrapper


def require_role(*roles: str):
    """@require_role("Admin", "Rescuer") – only these roles may call the endpoint."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            g.user = _user_from_token()
            if g.user.role not in roles:
                raise ApiError(403, f"{g.user.role}s can't do this.",
                               [f"Allowed roles: {', '.join(roles)}."])
            return view(*args, **kwargs)
        return wrapper
    return decorator


def require_permission(permission: str):
    """@require_permission("allocate_funds") – checked with User.can() from core/models.py."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            g.user = _user_from_token()
            if not g.user.can(permission):
                raise ApiError(403, f"{g.user.role}s can't {permission.replace('_', ' ')}.")
            return view(*args, **kwargs)
        return wrapper
    return decorator


# ======================================================================= rate limiting
class RateLimiter:
    """Sliding window: remembers when each event happened and forgets anything older than `window`."""

    def __init__(self, limit: int, window: float = 60):
        self.limit, self.window = limit, window
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque:
        events = self._events[key]
        while events and now - events[0] > self.window:
            events.popleft()
        return events

    def retry_after(self, key: str) -> int:
        """0 if the key may go ahead, otherwise seconds until it may."""
        with self._lock:
            now = time.time()
            events = self._trim(key, now)
            if len(events) < self.limit:
                return 0
            return max(1, int(self.window - (now - events[0])) + 1)

    def hit(self, key: str) -> None:
        with self._lock:
            self._trim(key, time.time()).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def check(self, key: str, what: str) -> None:
        """Raise 429 Too Many Requests if the key is over its limit."""
        wait = self.retry_after(key)
        if wait:
            raise ApiError(429, f"Too many {what}. Try again in {wait} seconds.",
                           headers={"Retry-After": str(wait)})


def client_ip() -> str:
    return request.remote_addr or "unknown"
