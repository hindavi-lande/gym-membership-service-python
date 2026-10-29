import json
import socket
import urllib.error
import urllib.request

from flask import current_app

from app.errors import ApiError

TIMEOUT_SECONDS = 5


def charge(payload: dict) -> None:
    base_url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/")
    url = f"{base_url}/api/payments/charge"
    http_request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(http_request, timeout=TIMEOUT_SECONDS) as response:
            if 200 <= response.status < 300:
                return None
            raise ApiError(503, f"Payments service returned status {response.status}")
    except urllib.error.HTTPError as exc:
        message = _error_message(exc)
        if exc.code == 402:
            raise ApiError(402, message) from exc
        raise ApiError(503, message) from exc
    except (urllib.error.URLError, OSError, socket.timeout) as exc:
        raise ApiError(503, "Payments service is unavailable") from exc


def _error_message(exc: urllib.error.HTTPError) -> str:
    fallback = f"Payments service returned status {exc.code}"
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return fallback
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return body["message"]
    return fallback
