from decimal import Decimal

from app.clients import payments_client

TIER_BRONZE = "BRONZE"
TIER_SILVER = "SILVER"
TIER_GOLD = "GOLD"
TIER_UNAVAILABLE = "UNAVAILABLE"

SILVER_THRESHOLD = Decimal("100")
GOLD_THRESHOLD = Decimal("500")


def tier_for_spend(spend):
    if spend < SILVER_THRESHOLD:
        return TIER_BRONZE
    if spend < GOLD_THRESHOLD:
        return TIER_SILVER
    return TIER_GOLD


def member_profile(member):
    profile = member.to_dict()
    spend = payments_client.fetch_spend(member.id)

    if spend is None:
        profile["tier"] = TIER_UNAVAILABLE
        profile["spend"] = None
    else:
        profile["tier"] = tier_for_spend(spend)
        profile["spend"] = float(spend)

    return profile
