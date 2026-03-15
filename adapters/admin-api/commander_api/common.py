import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "timeout",
}


def error_response(
    error,
    status_code: int = 500,
    error_code: str = "commander_error",
    details: dict | None = None,
):
    safe_details = details if isinstance(details, dict) else {}
    payload = {
        "ok": False,
        "error": str(error),
        "error_code": error_code,
        "details": safe_details,
    }
    return JSONResponse(payload, status_code=status_code)


def _exception_default_status(error: Any) -> int:
    if isinstance(error, HTTPException):
        return int(error.status_code)
    if isinstance(error, ValueError):
        return 400
    if isinstance(error, PermissionError):
        return 403
    if isinstance(error, FileNotFoundError):
        return 404
    if isinstance(error, TimeoutError):
        return 504
    return 500


def _exception_message(error: Any) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, str):
            return detail
        if isinstance(detail, Mapping):
            return str(detail.get("error") or detail)
        return str(detail)
    return str(error)


def _default_error_code(status_code: int, error: Any) -> str:
    mapped = _HTTP_ERROR_CODES.get(status_code)
    if mapped:
        return mapped
    if isinstance(error, ValueError):
        return "invalid_input"
    return "commander_error"


def exception_response(
    error: Any,
    *,
    status_code: int | None = None,
    error_code: str | None = None,
    details: Mapping[str, Any] | None = None,
):
    resolved_status = int(status_code if status_code is not None else _exception_default_status(error))
    resolved_code = error_code or _default_error_code(resolved_status, error)
    resolved_details = dict(details) if isinstance(details, Mapping) else {}
    return error_response(
        _exception_message(error),
        status_code=resolved_status,
        error_code=resolved_code,
        details=resolved_details,
    )
