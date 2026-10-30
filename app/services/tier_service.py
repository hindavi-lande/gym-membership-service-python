from app.clients import payments

TIER_BRONZE = "BRONZE"
TIER_SILVER = "SILVER"
TIER_GOLD = "GOLD"
TIER_UNAVAILABLE = "UNAVAILABLE"

SILVER_MIN_CENTS = 10_000
GOLD_MIN_CENTS = 50_000


def tier_for_spend(spend_cents: int | None) -> str:
    if spend_cents is None:
        return TIER_UNAVAILABLE
    if spend_cents >= GOLD_MIN_CENTS:
        return TIER_GOLD
    if spend_cents >= SILVER_MIN_CENTS:
        return TIER_SILVER
    return TIER_BRONZE


def tier_and_spend(member_id: int) -> dict:
    spend = payments.get_member_spend(member_id)
    return {"tier": tier_for_spend(spend), "spend": spend}
