from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.clients import payments_client
from app.extensions import db
from app.services import member_service

PLAN_PRICES: dict[str, Decimal] = {
    "BASIC": Decimal("29.99"),
    "STANDARD": Decimal("49.99"),
    "PREMIUM": Decimal("79.99"),
}
RENEWAL_PERIOD_DAYS: int = 30


def renew_member(member_id: int) -> date:
    member = member_service.get_member(member_id)
    plan = member.membership_plan

    payments_client.charge(
        {
            "memberId": member.id,
            "amount": float(PLAN_PRICES[plan]),
            "reason": f"{plan} plan renewal",
        }
    )

    member.renewal_date = datetime.now(UTC).date() + timedelta(days=RENEWAL_PERIOD_DAYS)
    db.session.commit()
    db.session.refresh(member)
    return member.renewal_date
