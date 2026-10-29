import json
from urllib import error, request

from flask import current_app

from app.errors import ApiError

TIMEOUT_SECONDS = 5

CHARGE_PATH = "/api/payments/charge"

HISTORY_PATH_TEMPLATE = "/api/payments/member/{member_id}"


def get_history(member_id: int) -> list[dict]:
    """GET a member's payment history from the payments service.

    Raises ApiError(503) when the payments service cannot be reached, answers
    an error status, or returns a body that is not a list of payments.
    """
    base_url = current_app.config["PAYMENTS_SERVICE_URL"]
    url = f"{base_url}{HISTORY_PATH_TEMPLATE.format(member_id=member_id)}"
    http_request = request.Request(url, method="GET")

    try:
        with request.urlopen(http_request, timeout=TIMEOUT_SECONDS) as response:
            body = _decode(response.read())
    except error.HTTPError as exc:
        raise ApiError(503, "payments service unavailable") from exc
    except (OSError, ValueError) as exc:
        # urllib.error.URLError is an OSError; JSONDecodeError is a ValueError.
        raise ApiError(503, "payments service unavailable") from exc

    if not isinstance(body, list):
        raise ApiError(503, "payments service unavailable")
    return body


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
