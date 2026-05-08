"""
Stripe payment configuration.

Single source for Stripe API key and mock mode detection. Used by
app/routes/billing.py and any other modules that need to know whether
real Stripe integration is active.

Moved from server.py during M16.8 refactor (2026-05-06).
"""
import os

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")


def is_stripe_configured() -> bool:
    """Check if Stripe is properly configured for real payments.

    Returns False when:
    - STRIPE_API_KEY is missing or is the placeholder ``sk_test_emergent``
    - STRIPE_PRICE_ID_PRO or STRIPE_PRICE_ID_ENTERPRISE are missing
    """
    api_key = os.environ.get("STRIPE_API_KEY", "")
    if not api_key or api_key == "sk_test_emergent" or api_key.startswith("sk_test_emergent"):
        return False
    pro_price = os.environ.get("STRIPE_PRICE_ID_PRO")
    enterprise_price = os.environ.get("STRIPE_PRICE_ID_ENTERPRISE")
    return bool(pro_price and enterprise_price)


# When True, Stripe API calls are simulated for development/testing.
# Real Stripe integration requires:
#   STRIPE_API_KEY, STRIPE_PRICE_ID_PRO, STRIPE_PRICE_ID_ENTERPRISE, STRIPE_WEBHOOK_SECRET
STRIPE_MOCK_MODE = not is_stripe_configured()
