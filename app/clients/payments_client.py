import json
from urllib import error, request

from flask import current_app

from app.errors import ApiError

TIMEOUT_SECONDS = 5

CHARGE_PATH = "/api/payments/charge"


def charge(payload: dict) -> dict:
    """POST a charge to the payments service and return its JSON response.

    Raises ApiError(402) when the payments service declines the charge and
    ApiError(503) when it cannot be reached or answers anything else.
    """
    url = f"{current_app.config['PAYMENTS_SERVICE_URL']}{CHARGE_PATH}"
    http_request = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=TIMEOUT_SECONDS) as response:
            return _decode(response.read())
    except error.HTTPError as exc:
        if exc.code == 402:
            raise ApiError(402, _error_message(exc)) from exc
        raise ApiError(503, "payments service unavailable") from exc
    except (OSError, ValueError) as exc:
        # urllib.error.URLError is an OSError; JSONDecodeError is a ValueError.
        raise ApiError(503, "payments service unavailable") from exc


def _decode(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def _error_message(exc: error.HTTPError) -> str:
    try:
        body = _decode(exc.read())
    except (OSError, ValueError):
        return "payment declined"
    message = body.get("message") if isinstance(body, dict) else None
    if isinstance(message, str) and message:
        return message
    return "payment declined"
