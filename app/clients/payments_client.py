import httpx
from flask import current_app

from app.errors import ApiError

MERGE_PATH = "/api/payments/merge"
REQUEST_TIMEOUT_SECONDS = 5.0


def merge_payments(from_member_id: int, to_member_id: int) -> dict:
    url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/") + MERGE_PATH

    try:
        response = httpx.post(
            url,
            json={"fromMemberId": from_member_id, "toMemberId": to_member_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ApiError(502, "payments service unavailable") from exc

    if not 200 <= response.status_code <= 299:
        raise ApiError(502, "payments service unavailable")

    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(502, "payments service unavailable") from exc
