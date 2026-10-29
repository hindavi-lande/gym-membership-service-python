import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from app.errors import ApiError

CHARGE_PATH = "/api/payments/charge"
REQUEST_TIMEOUT_SECONDS = 5


def charge(payload: dict) -> dict:
    url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/") + CHARGE_PATH
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read() or b"{}")
    except HTTPError as exc:
        raw = exc.read() or b""
        if exc.code == 402:
            raise ApiError(402, _message_from_error_body(raw, "Payment was declined")) from exc
        raise ApiError(
            502, _message_from_error_body(raw, "Payments service returned an error")
        ) from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise ApiError(503, "Payments service is unavailable") from exc


def _message_from_error_body(raw: bytes, fallback: str) -> str:
    if not raw:
        return fallback
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        return fallback
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message:
            return message
    return fallback
