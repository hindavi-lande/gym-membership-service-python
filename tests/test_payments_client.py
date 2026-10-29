import pytest

from app.clients import payments_client
from app.errors import ApiError

payload = {"memberId": 1, "amount": 29.99, "reason": "BASIC plan renewal"}


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self.body


def stub_post(monkeypatch, response):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return response

    monkeypatch.setattr(payments_client.requests, "post", fake_post)
    return calls


def test_charge_posts_to_the_charge_path(app, monkeypatch):
    recorded = {"id": 1, "memberId": 1, "type": "CHARGE", "status": "SUCCESS"}
    calls = stub_post(monkeypatch, FakeResponse(201, recorded))

    body = payments_client.charge(payload)

    assert body == recorded
    assert calls == [
        {
            "url": app.config["PAYMENTS_SERVICE_URL"].rstrip("/") + "/api/payments/charge",
            "json": payload,
            "timeout": payments_client.REQUEST_TIMEOUT,
        }
    ]


def test_charge_does_not_duplicate_a_trailing_slash(app, monkeypatch):
    app.config["PAYMENTS_SERVICE_URL"] = "http://localhost:3001/"
    calls = stub_post(monkeypatch, FakeResponse(200, {"id": 1}))

    payments_client.charge(payload)

    assert calls[0]["url"] == "http://localhost:3001/api/payments/charge"


def test_charge_raises_402_for_a_declined_charge(app, monkeypatch):
    stub_post(monkeypatch, FakeResponse(402, {"message": "payment was declined"}))

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge(payload)

    assert excinfo.value.status_code == 402


def test_charge_raises_503_when_the_service_is_unreachable(app, monkeypatch):
    def failing_post(url, json=None, timeout=None):
        raise payments_client.requests.ConnectionError("connection refused")

    monkeypatch.setattr(payments_client.requests, "post", failing_post)

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge(payload)

    assert excinfo.value.status_code == 503
