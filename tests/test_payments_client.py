import httpx
import pytest

from app.clients.payments_client import (
    CALL_TIMEOUT_SECONDS,
    PaymentHistoryResult,
    PaymentsUnavailable,
    get_payment_history,
)

PAYMENTS_BASE_URL = "http://localhost:3001"


def test_get_payment_history_requests_the_member_history_endpoint(monkeypatch):
    calls = []
    rows = [
        {
            "id": 7,
            "memberId": 7,
            "type": "CHARGE",
            "status": "SUCCESS",
            "amount": "49.99",
            "refundedAmount": 2000,
            "createdAt": "2024-05-02T10:00:00.000Z",
        }
    ]

    def fake_get(url, *, timeout):
        calls.append({"url": url, "timeout": timeout})
        return httpx.Response(200, json=rows)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = get_payment_history(PAYMENTS_BASE_URL, 7)

    assert calls == [
        {
            "url": f"{PAYMENTS_BASE_URL}/api/payments/member/7",
            "timeout": CALL_TIMEOUT_SECONDS,
        }
    ]
    assert result == PaymentHistoryResult(status_code=200, payments=rows)


def test_get_payment_history_wraps_transport_errors(monkeypatch):
    def fake_get(url, *, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(PaymentsUnavailable):
        get_payment_history(PAYMENTS_BASE_URL, 7)


def test_get_payment_history_treats_a_non_list_body_as_empty(monkeypatch):
    def fake_get(url, *, timeout):
        return httpx.Response(500, json={"message": "boom"})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = get_payment_history(PAYMENTS_BASE_URL, 7)

    assert result.status_code == 500
    assert result.payments == []
