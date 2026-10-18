"""
Stripe payment configuration.

Single source for the Stripe API key, the billing mode and the webhook secret.
Used by app/routes/billing.py and any other modules that need to know whether
real Stripe integration is active.

Moved from server.py during M16.8 refactor (2026-05-06).

R0-01 (AUD-045): mock billing is no longer switched on by a MISSING key. It is
allowed only when it is asked for explicitly (``BILLING_PROVIDER=mock``) AND the
deployment says explicitly that it is a development or test environment
(``ENV=development`` / ``ENV=test`` — the same ``ENV`` variable
app/utils/crypto.py reads). An unset ``ENV`` forbids mock: fail closed. Without
mock and without a complete Stripe configuration, billing is "unconfigured" and
the checkout refuses (503) instead of changing the plan.

Everything here is read from the environment at CALL time, so a process can
never keep a mock decision that its environment no longer grants.
"""
import os

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")

#: The only environments in which mock billing may run.
MOCK_ALLOWED_ENVS = ("development", "test")

BILLING_MODE_MOCK = "mock"
BILLING_MODE_STRIPE = "stripe"
BILLING_MODE_UNCONFIGURED = "unconfigured"


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


def stripe_webhook_secret() -> str:
    """The webhook signing secret, or ``""`` when it is not configured."""
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()


def is_mock_billing_allowed() -> bool:
    """Mock only on explicit request in an explicitly non-production environment."""
    provider = os.environ.get("BILLING_PROVIDER", "").strip().lower()
    env = os.environ.get("ENV", "").strip().lower()
    return provider == BILLING_MODE_MOCK and env in MOCK_ALLOWED_ENVS


def billing_mode() -> str:
    """``mock``, ``stripe`` or ``unconfigured``.

    ``stripe`` needs the API key, both price ids AND the webhook secret: without
    the secret a paid checkout could never activate the plan (the webhook
    refuses unsigned events), so selling would take money for nothing.
    """
    if is_mock_billing_allowed():
        return BILLING_MODE_MOCK
    if is_stripe_configured() and stripe_webhook_secret():
        return BILLING_MODE_STRIPE
    return BILLING_MODE_UNCONFIGURED


# Kept for the ``server.py`` re-export. It is an import-time snapshot of
# ``is_mock_billing_allowed()`` and is NOT consulted by app/routes/billing.py,
# which asks ``billing_mode()`` on every request.
STRIPE_MOCK_MODE = is_mock_billing_allowed()
