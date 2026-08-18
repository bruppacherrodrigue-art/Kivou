"""Facturation Stripe, droits et paywall Discovery — SPEC-013.

Stripe dit ce qui est payé (`gateway`), Kivou dit ce qui est permis
(`catalogue`), le service traduit l'un en l'autre, et rien d'autre n'accorde
un droit.
"""

from signals.billing.attempts import CheckoutInProgress, StoredAttempt, current_attempt
from signals.billing.catalogue import (
    CURRENCIES,
    DISCOVERY_GRANT_LIMIT,
    FOUNDING_MAXIMUM_ACCOUNTS,
    PLAN_CODES,
    PURCHASABLE_PLANS,
    PlanEntitlements,
    entitlements_for,
    lookup_key_for,
    plan_for_lookup_key,
    public_catalogue,
)
from signals.billing.checkout import (
    CheckoutConfiguration,
    PreparedCheckout,
    open_checkout_session,
    open_portal,
    prepare_checkout,
)
from signals.billing.service import (
    BillingError,
    BillingState,
    StoredSubscription,
    billing_state,
    ensure_stripe_customer,
    entitlements,
    synchronize_subscription,
)
from signals.billing.webhooks import HANDLED_EVENT_TYPES, WebhookOutcome, handle_event

__all__ = [
    "CURRENCIES",
    "DISCOVERY_GRANT_LIMIT",
    "FOUNDING_MAXIMUM_ACCOUNTS",
    "HANDLED_EVENT_TYPES",
    "PLAN_CODES",
    "PURCHASABLE_PLANS",
    "BillingError",
    "BillingState",
    "CheckoutConfiguration",
    "CheckoutInProgress",
    "PlanEntitlements",
    "PreparedCheckout",
    "StoredAttempt",
    "StoredSubscription",
    "WebhookOutcome",
    "billing_state",
    "current_attempt",
    "ensure_stripe_customer",
    "entitlements",
    "entitlements_for",
    "handle_event",
    "lookup_key_for",
    "open_checkout_session",
    "open_portal",
    "plan_for_lookup_key",
    "prepare_checkout",
    "public_catalogue",
    "synchronize_subscription",
]
