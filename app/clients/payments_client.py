import requests
from flask import current_app

from app.errors import ApiError

CHARGE_PATH = "/api/payments/charge"
REFUND_PATH = "/api/payments/refund"
REQUEST_TIMEOUT = 10.0


def charge(payload: dict) -> dict:
    url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/") + CHARGE_PATH
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise ApiError(503, "payments service is unavailable") from exc

    if response.status_code == 402:
        raise ApiError(402, "payment was declined")
    if not response.ok:
        raise ApiError(502, f"payments service returned {response.status_code}")
    return response.json()


def refund(payload: dict) -> dict:
    url = current_app.config["PAYMENTS_SERVICE_URL"].rstrip("/") + REFUND_PATH
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise ApiError(503, "payments service is unavailable") from exc

    if not response.ok:
        raise ApiError(502, f"payments service returned {response.status_code}")
    return response.json()
