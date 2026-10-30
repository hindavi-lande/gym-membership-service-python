import httpx
import pytest

from app.clients import payments_client
from app.errors import ApiError

PAYMENTS_SERVICE_URL = "http://localhost:3001"


class _FakeResponse:
    def __init__(self, status_code, body=None, json_error=None):
        self.status_code = status_code
        self._body = body
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._body


def _record_post(monkeypatch, response=None, error=None):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_merge_payments_posts_to_the_payments_service(app, monkeypatch):
    calls = _record_post(monkeypatch, response=_FakeResponse(200, {"moved": 2}))

    result = payments_client.merge_payments(4, 7)

    assert result == {"moved": 2}
    assert calls == [
        {
            "url": f"{PAYMENTS_SERVICE_URL}/api/payments/merge",
            "json": {"fromMemberId": 4, "toMemberId": 7},
            "timeout": payments_client.REQUEST_TIMEOUT_SECONDS,
        }
    ]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.TimeoutException("timed out"),
    ],
)
def test_merge_payments_maps_transport_errors_to_502(app, monkeypatch, error):
    _record_post(monkeypatch, error=error)

    with pytest.raises(ApiError) as exc_info:
        payments_client.merge_payments(1, 2)

    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "payments service unavailable"


@pytest.mark.parametrize("status_code", [400, 500])
def test_merge_payments_maps_error_responses_to_502(app, monkeypatch, status_code):
    _record_post(
        monkeypatch, response=_FakeResponse(status_code, {"message": "nope"})
    )

    with pytest.raises(ApiError) as exc_info:
        payments_client.merge_payments(1, 2)

    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "payments service unavailable"
