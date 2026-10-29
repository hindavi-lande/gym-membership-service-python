from decimal import Decimal

import httpx
import pytest

from app.clients import payments_client
from app.clients.payments_client import get_spend as real_get_spend

REQUEST_URL = "http://localhost:3001/api/payments/spend/1"


def _response(payload=None, status_code=200, *, content=None):
    request = httpx.Request("GET", REQUEST_URL)
    if content is not None:
        return httpx.Response(status_code, content=content, request=request)
    return httpx.Response(status_code, json=payload, request=request)


def _patch_get(monkeypatch, response=None, error=None, captured=None):
    monkeypatch.setattr(payments_client, "get_spend", real_get_spend)

    def fake_get(url, **kwargs):
        if captured is not None:
            captured["url"] = url
            captured["kwargs"] = kwargs
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(httpx, "get", fake_get)


def test_get_spend_returns_the_decimal_spend(app, monkeypatch):
    _patch_get(monkeypatch, _response({"memberId": 1, "spend": 149.99}))

    spend = payments_client.get_spend(1)

    assert isinstance(spend, Decimal)
    assert spend == Decimal("149.99")

    _patch_get(monkeypatch, _response({"memberId": 1, "spend": -50.0}))

    assert payments_client.get_spend(1) == Decimal("-50")


def test_get_spend_uses_the_configured_url_and_two_second_timeout(app, monkeypatch):
    captured = {}
    _patch_get(monkeypatch, _response({"memberId": 7, "spend": 0}), captured=captured)

    payments_client.get_spend(7)

    base_url = app.config["PAYMENTS_SERVICE_URL"]
    assert captured["url"] == f"{base_url.rstrip('/')}/api/payments/spend/7"
    assert captured["kwargs"]["timeout"] == 2.0
    assert payments_client.TIMEOUT_SECONDS == 2.0


def test_get_spend_returns_none_on_timeout(app, monkeypatch):
    _patch_get(monkeypatch, error=httpx.TimeoutException("timed out"))

    assert payments_client.get_spend(1) is None


def test_get_spend_returns_none_on_connection_error(app, monkeypatch):
    _patch_get(monkeypatch, error=httpx.ConnectError("connection refused"))

    assert payments_client.get_spend(1) is None


@pytest.mark.parametrize("status_code", [500, 404])
def test_get_spend_returns_none_on_error_status(app, monkeypatch, status_code):
    _patch_get(monkeypatch, _response({"message": "nope"}, status_code))

    assert payments_client.get_spend(1) is None


def test_get_spend_returns_none_on_malformed_payload(app, monkeypatch):
    _patch_get(monkeypatch, _response(content=b"not-json"))

    assert payments_client.get_spend(1) is None

    _patch_get(monkeypatch, _response({"memberId": 1}))

    assert payments_client.get_spend(1) is None

    _patch_get(monkeypatch, _response({"spend": None}))

    assert payments_client.get_spend(1) is None

    _patch_get(monkeypatch, _response({"spend": "149.99"}))

    assert payments_client.get_spend(1) is None
