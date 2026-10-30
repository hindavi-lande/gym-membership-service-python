from dataclasses import dataclass
from typing import Any

import httpx

CALL_TIMEOUT_SECONDS = 5.0


class PaymentsUnavailable(Exception):
    """Raised when the payments service cannot be reached."""


@dataclass(frozen=True)
class ChargeResult:
    status_code: int
    body: dict[str, Any]


def post_charge(
    base_url: str,
    payload: dict,
    timeout: float = CALL_TIMEOUT_SECONDS,
) -> ChargeResult:
    url = f"{base_url}/api/payments/charge"
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise PaymentsUnavailable(f"Payments service unreachable: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return ChargeResult(status_code=response.status_code, body=body)


def post_refund(
    base_url: str,
    payload: dict,
    timeout: float = CALL_TIMEOUT_SECONDS,
) -> ChargeResult:
    url = f"{base_url}/api/payments/refund"
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise PaymentsUnavailable(f"Payments service unreachable: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return ChargeResult(status_code=response.status_code, body=body)
