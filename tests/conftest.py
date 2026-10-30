import urllib.error

import pytest

from app import create_app
from app.clients import payments
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


@pytest.fixture(autouse=True)
def stub_payments_client(monkeypatch):
    def _unavailable(*args, **kwargs):
        raise urllib.error.URLError("payments service unavailable")

    monkeypatch.setattr(payments, "_fetch_json", _unavailable)
    return monkeypatch
