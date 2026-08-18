"""SPEC-013 §5, §6, §9, §32 — le catalogue est du code, pas une métadonnée Stripe.

Ce que ces tests protègent
──────────────────────────
Un `price_...` désigne un objet commercial chez un prestataire de paiement.
Le laisser décider d'un droit d'accès reviendrait à confier l'autorisation à
un tableau de bord que n'importe qui peut modifier, sans revue ni test.

Le point le plus important est négatif : un prix INCONNU ne doit accorder
aucun droit payant. Un défaut permissif — « si on ne sait pas, on donne
Pro » — est une faille qui attend son incident.
"""

from __future__ import annotations

import pytest
from billing_helpers import default_prices

from signals.billing import catalogue

# ─── §5 — les quatre plans, et un seul gratuit ────────────────────────────────


def test_the_catalogue_holds_exactly_the_four_declared_plans():
    assert set(catalogue.PLANS) == {"discovery", "essential", "pro", "scale"}
    assert catalogue.PURCHASABLE_PLANS == ("essential", "pro", "scale")


def test_discovery_is_never_a_stripe_subscription():
    """Un abonnement à 0 produirait une facture pour rien et un objet à réconcilier."""
    assert "discovery" not in catalogue.PURCHASABLE_PLANS
    assert "discovery" not in catalogue.MONTHLY_MINOR_UNITS
    assert "discovery" not in catalogue.LOOKUP_KEYS


@pytest.mark.parametrize(
    ("plan", "icps", "history", "territory"),
    [
        ("discovery", 1, 0, "single"),
        ("essential", 1, 30, "single"),
        ("pro", 3, 365, "multiple"),
        ("scale", 10, None, "expanded"),
    ],
)
def test_each_plan_carries_the_commercial_limits_of_the_pricing_document(
    plan: str, icps: int, history: int | None, territory: str
):
    entitlements = catalogue.PLANS[plan]
    assert entitlements.max_active_icps == icps
    assert entitlements.history_days == history
    assert entitlements.territory_mode == territory


def test_only_pro_is_recommended():
    recommended = [plan for plan in catalogue.PLANS.values() if plan.recommended]
    assert [plan.plan_code for plan in recommended] == ["pro"]


def test_scale_history_is_what_is_persisted_not_an_infinite_promise():
    """« Tout l'historique disponible » ne veut pas dire « tout l'historique »."""
    assert catalogue.SCALE.has_unlimited_history
    safe = catalogue.customer_safe_entitlements(catalogue.SCALE)
    assert safe["history_scope"] == "all_available"


# ─── §6 — 49 / 99 / 199, dans les deux devises, sans conversion ───────────────


@pytest.mark.parametrize("currency", ["chf", "eur"])
@pytest.mark.parametrize(("plan", "amount"), [("essential", 4900), ("pro", 9900), ("scale", 19900)])
def test_the_price_is_the_same_number_in_both_currencies(plan: str, currency: str, amount: int):
    """§6 — une décision commerciale, pas un taux de change."""
    assert catalogue.amount_for(plan, currency) == amount


def test_every_purchasable_plan_has_a_lookup_key_in_each_currency():
    expected = {
        "kivou_essential_monthly_chf",
        "kivou_essential_monthly_eur",
        "kivou_pro_monthly_chf",
        "kivou_pro_monthly_eur",
        "kivou_scale_monthly_chf",
        "kivou_scale_monthly_eur",
    }
    produced = {
        catalogue.lookup_key_for(plan, currency)
        for plan in catalogue.PURCHASABLE_PLANS
        for currency in catalogue.CURRENCIES
    }
    assert produced == expected


def test_an_unpurchasable_plan_has_no_lookup_key():
    with pytest.raises(catalogue.UnknownPlan):
        catalogue.lookup_key_for("discovery", "chf")


def test_an_unsupported_currency_is_refused():
    with pytest.raises(catalogue.UnknownCurrency):
        catalogue.lookup_key_for("pro", "usd")


# ─── §9 — un prix inconnu n'accorde rien ─────────────────────────────────────


def test_a_known_lookup_key_resolves_to_its_plan_and_currency():
    assert catalogue.plan_for_lookup_key("kivou_pro_monthly_eur") == ("pro", "eur")


@pytest.mark.parametrize(
    "lookup_key",
    [None, "", "price_1234", "kivou_pro_yearly_chf", "kivou_enterprise_monthly_chf", "pro"],
)
def test_an_unknown_lookup_key_resolves_to_nothing(lookup_key: str | None):
    """§9 — jamais de repli sur Pro. Ne pas savoir, c'est ne rien accorder."""
    assert catalogue.plan_for_lookup_key(lookup_key) is None


@pytest.mark.parametrize("plan_code", [None, "", "enterprise", "PRO", "pro_plus"])
def test_unknown_plan_codes_fall_back_to_discovery_never_upward(plan_code: str | None):
    assert catalogue.entitlements_for(plan_code) is catalogue.DISCOVERY


def test_the_lookup_index_is_derived_from_the_keys_it_indexes():
    """Deux tables écrites à la main finiraient par diverger."""
    for plan in catalogue.PURCHASABLE_PLANS:
        for currency in catalogue.CURRENCIES:
            key = catalogue.lookup_key_for(plan, currency)
            assert catalogue.plan_for_lookup_key(key) == (plan, currency)


# ─── §7 — l'offre fondateur ──────────────────────────────────────────────────


def test_the_founding_offer_is_pro_at_twenty_nine():
    assert catalogue.FOUNDING_PLAN_CODE == "pro"
    assert (
        catalogue.MONTHLY_MINOR_UNITS["pro"]["chf"] - catalogue.FOUNDING_DISCOUNT_MINOR_UNITS
        == catalogue.FOUNDING_EFFECTIVE_MINOR_UNITS
    )
    assert catalogue.FOUNDING_EFFECTIVE_MINOR_UNITS == 2900


def test_founding_is_an_offer_and_never_a_fifth_plan():
    assert "founding" not in catalogue.PLAN_CODES
    assert "founding" in catalogue.OFFER_CODES
    assert catalogue.entitlements_for("founding") is catalogue.DISCOVERY


def test_the_founding_offer_is_capped_at_five_accounts_for_twelve_months():
    assert catalogue.FOUNDING_MAXIMUM_ACCOUNTS == 5
    assert catalogue.FOUNDING_MONTHS == 12


# ─── §11 — le catalogue public ne fuit aucun identifiant Stripe ──────────────


def test_the_public_catalogue_exposes_no_stripe_identifier():
    body = str(catalogue.public_catalogue())
    for forbidden in ("price_", "prod_", "coupon_", "cus_", "sub_", "lookup_key", "kivou_pro_"):
        assert forbidden not in body, forbidden


def test_the_public_catalogue_marks_what_can_be_bought():
    entries = {entry["plan_code"]: entry for entry in catalogue.public_catalogue()}
    assert entries["discovery"]["purchasable"] is False
    assert entries["discovery"]["monthly_price"] == {}
    assert entries["pro"]["purchasable"] is True
    assert entries["pro"]["recommended"] is True
    assert entries["pro"]["monthly_price"]["chf"]["amount_minor_units"] == 9900


def test_the_public_catalogue_describes_future_capabilities_without_promising_them():
    """§27 — export et alertes n'ont aucun endpoint ; ce sont des libellés."""
    entries = {entry["plan_code"]: entry for entry in catalogue.public_catalogue()}
    assert entries["discovery"]["entitlements"]["export_level"] == "none"
    assert entries["scale"]["entitlements"]["export_level"] == "scheduled"
    assert entries["essential"]["entitlements"]["alert_cadence"] == "weekly"


# ─── cohérence avec les objets Stripe attendus ───────────────────────────────


def test_the_expected_stripe_prices_match_the_kivou_catalogue_exactly():
    """Le catalogue de test décrit les objets que §36 doit créer chez Stripe."""
    prices = default_prices()
    assert set(prices) == {
        catalogue.lookup_key_for(plan, currency)
        for plan in catalogue.PURCHASABLE_PLANS
        for currency in catalogue.CURRENCIES
    }
    for lookup_key, price in prices.items():
        plan, currency = catalogue.plan_for_lookup_key(lookup_key)
        assert price.unit_amount == catalogue.amount_for(plan, currency)
        assert price.currency == currency
        assert price.recurring_interval == "month"
        assert price.livemode is False
