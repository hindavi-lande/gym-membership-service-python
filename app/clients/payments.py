import http.client
import json
import urllib.error
import urllib.request

from flask import current_app

SPEND_PATH_TEMPLATE = "/api/payments/member/{member_id}/spend"


def get_member_spend(member_id: int) -> int | None:
    try:
        body = _fetch_json(_spend_url(member_id), _timeout())
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
        ValueError,
    ):
        return None

    if isinstance(body, bool) or not isinstance(body, int):
        return None
    return body


def _fetch_json(url: str, timeout: float) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _spend_url(member_id: int) -> str:
    base_url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/")
    return f"{base_url}{SPEND_PATH_TEMPLATE.format(member_id=member_id)}"


def _timeout() -> float:
    return float(current_app.config["PAYMENTS_SERVICE_TIMEOUT"])
