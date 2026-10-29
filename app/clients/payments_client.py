from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import httpx
from flask import current_app

TIMEOUT_SECONDS = 2.0
CENT = Decimal("0.01")


def get_spend(member_id: int) -> Decimal | None:
    base_url = current_app.config["PAYMENTS_SERVICE_URL"]
    url = f"{base_url.rstrip('/')}/api/payments/spend/{member_id}"

    try:
        response = httpx.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    spend = payload.get("spend")
    if isinstance(spend, bool) or not isinstance(spend, (int, float)):
        return None

    try:
        return Decimal(str(spend)).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
