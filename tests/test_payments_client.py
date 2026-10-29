import pytest
import requests

from app.clients import payments_client
from app.errors import ApiError


class _FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = {} if body is None else body

    def json(self):
        return self._body


def test_merge_payments_posts_ids_and_timeout(app, monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _FakeResponse(200, {"movedCount": 2})

    monkeypatch.setattr(requests, "post", fake_post)

    result = payments_client.merge_payments(from_member_id=7, to_member_id=3)

    assert result == {"movedCount": 2}
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "http://localhost:3001/api/payments/merge"
    assert call["json"] == {"fromMemberId": 7, "toMemberId": 3}
    assert call["timeout"] == app.config["PAYMENTS_MERGE_TIMEOUT"]
    assert call["timeout"] is not None


def test_merge_payments_raises_502_on_error_status(app, monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse(500)

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ApiError) as error:
        payments_client.merge_payments(from_member_id=7, to_member_id=3)

    assert error.value.status_code == 502


def test_merge_payments_raises_502_on_request_exception(app, monkeypatch):
    def fake_post(url, **kwargs):
        raise requests.ConnectionError("payments service is down")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ApiError) as error:
        payments_client.merge_payments(from_member_id=7, to_member_id=3)

    assert error.value.status_code == 502
