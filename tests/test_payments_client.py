import json
from decimal import Decimal
from urllib.error import HTTPError, URLError

import pytest

from app.clients import payments_client


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body


def respond_with(response):
    def _urlopen(url, timeout=None):
        return response

    return _urlopen


def test_returns_none_on_timeout(app, monkeypatch):
    def _urlopen(url, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(payments_client, "urlopen", _urlopen)

    with app.app_context():
        assert payments_client.fetch_spend(1) is None


def test_returns_none_on_connection_failure(app, monkeypatch):
    def _urlopen(url, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr(payments_client, "urlopen", _urlopen)

    with app.app_context():
        assert payments_client.fetch_spend(1) is None


def test_returns_none_on_error_status(app, monkeypatch):
    def _urlopen(url, timeout=None):
        raise HTTPError(url, 500, "Internal Server Error", None, None)

    monkeypatch.setattr(payments_client, "urlopen", _urlopen)

    with app.app_context():
        assert payments_client.fetch_spend(1) is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        json.dumps({"memberId": 1, "spend": "twelve"}).encode(),
        json.dumps({"memberId": 1}).encode(),
    ],
)
def test_returns_none_on_malformed_body(app, monkeypatch, body):
    monkeypatch.setattr(payments_client, "urlopen", respond_with(FakeResponse(200, body)))

    with app.app_context():
        assert payments_client.fetch_spend(1) is None


def test_reads_the_spend_from_a_successful_response(app, monkeypatch):
    body = json.dumps({"memberId": 1, "spend": 123.456}).encode()
    monkeypatch.setattr(payments_client, "urlopen", respond_with(FakeResponse(200, body)))

    with app.app_context():
        assert payments_client.fetch_spend(1) == Decimal("123.46")
