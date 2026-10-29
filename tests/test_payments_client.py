import io
import json
from urllib.error import HTTPError, URLError

import pytest

from app.clients import payments_client
from app.errors import ApiError


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_charge_returns_the_decoded_body(app, monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(b'{"id": 1, "status": "SUCCESS", "amount": 49.99}')

    monkeypatch.setattr(payments_client, "urlopen", fake_urlopen)

    result = payments_client.charge(
        {"memberId": 1, "amount": 49.99, "reason": "PREMIUM plan renewal"}
    )

    assert result == {"id": 1, "status": "SUCCESS", "amount": 49.99}
    assert captured["url"] == "http://localhost:3001/api/payments/charge"
    assert captured["payload"]["reason"] == "PREMIUM plan renewal"
    assert captured["timeout"] == payments_client.REQUEST_TIMEOUT_SECONDS


def test_charge_raises_402_on_a_declined_charge(app, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise HTTPError(
            request.full_url,
            402,
            "Payment Required",
            None,
            io.BytesIO(b'{"message": "Card declined"}'),
        )

    monkeypatch.setattr(payments_client, "urlopen", fake_urlopen)

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge({"memberId": 1, "amount": 49.99})

    assert excinfo.value.status_code == 402
    assert excinfo.value.message == "Card declined"


def test_charge_uses_a_fallback_message_when_the_402_body_is_not_json(app, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise HTTPError(request.full_url, 402, "Payment Required", None, io.BytesIO(b"nope"))

    monkeypatch.setattr(payments_client, "urlopen", fake_urlopen)

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge({"memberId": 1, "amount": 49.99})

    assert excinfo.value.status_code == 402
    assert excinfo.value.message == "Payment was declined"


def test_charge_raises_502_when_the_service_errors(app, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b'{"message": "boom"}'),
        )

    monkeypatch.setattr(payments_client, "urlopen", fake_urlopen)

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge({"memberId": 1, "amount": 49.99})

    assert excinfo.value.status_code == 502
    assert excinfo.value.message == "boom"


def test_charge_raises_503_when_the_service_is_unreachable(app, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise URLError(ConnectionRefusedError("Connection refused"))

    monkeypatch.setattr(payments_client, "urlopen", fake_urlopen)

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge({"memberId": 1, "amount": 49.99})

    assert excinfo.value.status_code == 503
    assert excinfo.value.message == "Payments service is unavailable"


def test_charge_raises_503_on_a_timeout(app, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(payments_client, "urlopen", fake_urlopen)

    with pytest.raises(ApiError) as excinfo:
        payments_client.charge({"memberId": 1, "amount": 49.99})

    assert excinfo.value.status_code == 503
