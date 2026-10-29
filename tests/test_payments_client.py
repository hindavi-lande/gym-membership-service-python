import io
import json
import urllib.error
import urllib.request

import pytest

from app.clients import payments
from app.errors import ApiError


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def _install_urlopen(monkeypatch, handler):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append({"request": request, "timeout": timeout})
        return handler(request, timeout)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def test_merge_payments_returns_moved_count(app, monkeypatch):
    calls = _install_urlopen(
        monkeypatch, lambda request, timeout: _FakeResponse(b'{"moved": 3}')
    )

    assert payments.merge_payments(7, 9) == {"moved": 3}

    assert len(calls) == 1
    request = calls[0]["request"]
    assert request.full_url == "http://localhost:3001/api/payments/merge"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"fromMemberId": 7, "toMemberId": 9}
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["content-type"] == "application/json"
    assert calls[0]["timeout"] == payments.DEFAULT_TIMEOUT_SECONDS


def test_merge_payments_uses_the_given_base_url(app, monkeypatch):
    calls = _install_urlopen(
        monkeypatch, lambda request, timeout: _FakeResponse(b'{"moved": 0}')
    )

    payments.merge_payments(1, 2, base_url="http://payments.test:8080/", timeout=1.5)

    assert calls[0]["request"].full_url == "http://payments.test:8080/api/payments/merge"
    assert calls[0]["timeout"] == 1.5


def test_merge_payments_maps_non_2xx_to_502(app, monkeypatch):
    def handler(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Internal Server Error", None, io.BytesIO(b"{}")
        )

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(ApiError) as exc_info:
        payments.merge_payments(1, 2)

    assert exc_info.value.status_code == 502


def test_merge_payments_maps_connection_error_to_502(app, monkeypatch):
    def handler(request, timeout):
        raise urllib.error.URLError("connection refused")

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(ApiError) as exc_info:
        payments.merge_payments(1, 2)

    assert exc_info.value.status_code == 502


def test_merge_payments_maps_timeout_to_502(app, monkeypatch):
    def handler(request, timeout):
        raise TimeoutError("timed out")

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(ApiError) as exc_info:
        payments.merge_payments(1, 2)

    assert exc_info.value.status_code == 502


def test_merge_payments_maps_non_json_body_to_502(app, monkeypatch):
    _install_urlopen(monkeypatch, lambda request, timeout: _FakeResponse(b"not json"))

    with pytest.raises(ApiError) as exc_info:
        payments.merge_payments(1, 2)

    assert exc_info.value.status_code == 502


def test_merge_payments_maps_missing_moved_to_502(app, monkeypatch):
    _install_urlopen(
        monkeypatch, lambda request, timeout: _FakeResponse(b'{"other": 1}')
    )

    with pytest.raises(ApiError) as exc_info:
        payments.merge_payments(1, 2)

    assert exc_info.value.status_code == 502
