import requests
from flask import current_app

from app.errors import ApiError


def merge_payments(from_member_id: int, to_member_id: int) -> dict:
    base_url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/")
    payload = {"fromMemberId": from_member_id, "toMemberId": to_member_id}

    try:
        response = requests.post(
            f"{base_url}/api/payments/merge",
            json=payload,
            timeout=current_app.config["PAYMENTS_MERGE_TIMEOUT"],
        )
    except requests.RequestException as exc:
        raise ApiError(502, "Payments service could not be reached") from exc

    if response.status_code != 200:
        raise ApiError(502, "Payments service failed to merge payments")

    return response.json()
