import json
import threading
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.clients import payments_client
from app.errors import ApiError
from app.extensions import db
from app.models import Member


def create_member(client, membershipPlan="PREMIUM", email="renew@example.com"):
    response = client.post(
        "/api/members",
        json={
            "firstName": "Jane",
            "lastName": "Doe",
            "email": email,
            "membershipPlan": membershipPlan,
        },
    )
    assert response.status_code == 201
    return response.get_json()


@pytest.fixture()
def recorded_charges(monkeypatch):
    calls = []

    def fake_charge(payload):
        calls.append(payload)
        return None

    monkeypatch.setattr(payments_client, "charge", fake_charge)
    return calls


def set_renewal_date(app, member_id, renewal_date):
    with app.app_context():
        member = db.session.get(Member, member_id)
        member.renewal_date = renewal_date
        db.session.commit()


@pytest.mark.parametrize(
    ("plan", "expected_amount"),
    [("BASIC", 29.99), ("STANDARD", 49.99), ("PREMIUM", 79.99)],
)
def test_renew_charges_the_plan_price_with_the_plan_reason(
    client, recorded_charges, plan, expected_amount
):
    member = create_member(client, membershipPlan=plan)

    response = client.post(f"/api/members/{member['id']}/renew")

    assert response.status_code == 200
    assert recorded_charges == [
        {
            "memberId": member["id"],
            "amount": expected_amount,
            "reason": f"{plan} plan renewal",
        }
    ]


def test_renew_returns_the_utc_date_30_days_from_today(client, recorded_charges):
    member = create_member(client)

    response = client.post(f"/api/members/{member['id']}/renew")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"renewalDate"}
    expected = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    assert body["renewalDate"] == expected
    assert client.get(f"/api/members/{member['id']}").get_json()["renewalDate"] == expected


def test_renew_returns_402_and_leaves_renewal_date_unchanged(client, app, monkeypatch):
    member = create_member(client)
    set_renewal_date(app, member["id"], date(2030, 1, 1))

    def failing_charge(payload):
        raise ApiError(402, "Payment failed")

    monkeypatch.setattr(payments_client, "charge", failing_charge)

    response = client.post(f"/api/members/{member['id']}/renew")

    assert response.status_code == 402
    body = response.get_json()
    assert "renewalDate" not in body
    assert "message" in body
    assert client.get(f"/api/members/{member['id']}").get_json()["renewalDate"] == "2030-01-01"


def test_renew_returns_503_when_the_payments_service_is_unreachable(client, app):
    member = create_member(client)
    set_renewal_date(app, member["id"], date(2030, 1, 1))
    app.config["PAYMENTS_SERVICE_URL"] = "http://127.0.0.1:1"

    response = client.post(f"/api/members/{member['id']}/renew")

    assert response.status_code == 503
    body = response.get_json()
    assert "renewalDate" not in body
    assert "message" in body
    assert client.get(f"/api/members/{member['id']}").get_json()["renewalDate"] == "2030-01-01"


def test_renew_returns_404_for_an_unknown_member_and_does_not_call_payments(
    client, recorded_charges
):
    response = client.post("/api/members/999999/renew")

    assert response.status_code == 404
    body = response.get_json()
    assert "renewalDate" not in body
    assert "message" in body
    assert recorded_charges == []


class _RecordingChargeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append(
            {
                "path": self.path,
                "method": self.command,
                "content_type": self.headers.get("Content-Type"),
                "body": body,
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def test_charge_posts_the_json_body_to_the_payments_charge_path(app):
    server = HTTPServer(("127.0.0.1", 0), _RecordingChargeHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        app.config["PAYMENTS_SERVICE_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
        payload = {"memberId": 7, "amount": 49.99, "reason": "STANDARD plan renewal"}

        payments_client.charge(payload)

        assert server.requests == [
            {
                "path": "/api/payments/charge",
                "method": "POST",
                "content_type": "application/json",
                "body": payload,
            }
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
