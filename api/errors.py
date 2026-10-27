"""
One error shape for the whole API:

    {"error": "Short message for a person", "details": ["each problem", "..."]}

Business errors from core/workflows.py are translated to HTTP status codes:
    ValidationError → 422   NotFound → 404   Conflict → 409
    PaymentDeclined → 402   PermissionDenied → 403   DeliveryFailed (e-mail) → 503
    GatewayError (payment gateway) → 502
"""
from __future__ import annotations

from flask import jsonify
from werkzeug.exceptions import HTTPException

from api.security import ApiError
from core import workflows as wf


def error_response(status: int, message: str, details: list[str] | None = None, headers=None):
    response = jsonify({"error": message, "details": details or []})
    response.status_code = status
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def _flatten(messages, prefix: str = "") -> list[str]:
    """webargs/marshmallow errors {"json": {"amount": ["Not a number."]}} → ["amount: Not a number."]"""
    if isinstance(messages, dict):
        out = []
        for key, value in messages.items():
            name = "" if key in ("json", "form", "files", "query", "_schema") else str(key)
            out += _flatten(value, f"{prefix}.{name}".strip(".") if name else prefix)
        return out
    if isinstance(messages, (list, tuple)):
        return [d for item in messages for d in _flatten(item, prefix)]
    return [f"{prefix}: {messages}" if prefix else str(messages)]


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _api_error(error: ApiError):
        return error_response(error.status, error.message, error.details, error.headers)

    @app.errorhandler(wf.NotFound)
    def _not_found(error):
        return error_response(404, error.problems[0], error.problems)

    @app.errorhandler(wf.Conflict)
    def _conflict(error):
        return error_response(409, error.problems[0], error.problems)

    @app.errorhandler(wf.GatewayError)
    def _gateway(error):
        return error_response(502, error.problems[0], error.problems)

    @app.errorhandler(wf.DeliveryFailed)
    def _not_delivered(error):
        return error_response(503, error.problems[0], error.problems)

    @app.errorhandler(wf.PaymentDeclined)
    def _declined(error):
        return error_response(402, error.problems[0], error.problems)

    @app.errorhandler(wf.ValidationError)
    def _invalid(error):
        return error_response(422, "Please fix the highlighted problems.", error.problems)

    @app.errorhandler(wf.PermissionDenied)
    def _forbidden(error):
        return error_response(403, str(error), [str(error)])

    @app.errorhandler(HTTPException)
    def _http(error: HTTPException):
        data = getattr(error, "data", None) or {}          # filled in by webargs for bad bodies
        details = _flatten(data.get("messages", {})) if data else []
        message = "Please fix the highlighted problems." if details else error.description
        return error_response(error.code or 500, message, details)

    @app.errorhandler(Exception)
    def _crash(error: Exception):
        app.logger.exception("Unexpected error")
        return error_response(500, "Something went wrong on the server.", [])
