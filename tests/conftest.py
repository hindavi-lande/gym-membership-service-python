from collections.abc import Iterator

import pytest

from app import create_app
from app.clients import payments_client
from app.errors import ApiError
from app.extensions import db


@pytest.fixture()
def app():
    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "PAYMENTS_SERVICE_URL": "http://localhost:3001",
        }
    )

    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


class PaymentsHistory:
    """Stand-in for payments_client.get_history with configurable behaviour."""

    def __init__(self) -> None:
        self.member_ids: list[int] = []
        self.payload: list[dict] = []
        self.error: ApiError | None = None

    def set(self, payload: list[dict]) -> None:
        self.payload = payload

    def fail_with(self, error: ApiError) -> None:
        self.error = error

    def __len__(self) -> int:
        return len(self.member_ids)

    def __iter__(self) -> Iterator[int]:
        return iter(self.member_ids)


@pytest.fixture(autouse=True)
def payments_history(monkeypatch: pytest.MonkeyPatch) -> PaymentsHistory:
    history = PaymentsHistory()

    def fake_get_history(member_id: int) -> list[dict]:
        history.member_ids.append(member_id)
        if history.error is not None:
            raise history.error
        return history.payload

    monkeypatch.setattr(payments_client, "get_history", fake_get_history)
    return history
