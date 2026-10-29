import json
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from flask import current_app

PAYMENTS_TIMEOUT_SECONDS = 2
CENT = Decimal("0.01")

# Every one of these means the spend cannot be known: the payments service is
# down, too slow, answered with an error status, or sent something we cannot
# read. They are all handled the same way - no retry, no exception escaping.
_FAILED_LOOKUP = (
    HTTPError,
    URLError,
    TimeoutError,
    ConnectionError,
    json.JSONDecodeError,
    DecimalException,
    KeyError,
    TypeError,
    ValueError,
)


def fetch_spend(member_id) -> Decimal | None:
    """Return the member's spend rounded to cents, or None if it is unavailable.

    Makes exactly one request with a fixed timeout and never retries.
    """
    url = (
        current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/")
        + f"/api/payments/member/{member_id}/spend"
    )

    try:
        response = urlopen(url, timeout=PAYMENTS_TIMEOUT_SECONDS)
        if response.status != 200:
            return None
        spend = json.loads(response.read())["spend"]
        if isinstance(spend, bool) or not isinstance(spend, (int, float)):
            return None
        return Decimal(str(spend)).quantize(CENT, rounding=ROUND_HALF_UP)
    except _FAILED_LOOKUP:
        return None
