"""Le catalogue Kivou — et pourquoi Stripe n'a pas le droit de le définir.

    Stripe dit ce qui est PAYÉ. Kivou dit ce qui est PERMIS.
    ───────────────────────────────────────────────────────
    Un `price_...` désigne un objet commercial chez un prestataire de paiement ;
    il ne décrit aucune règle de produit. Laisser une métadonnée Stripe décider
    d'un droit d'accès reviendrait à confier l'autorisation à un système que
    n'importe qui peut faire évoluer depuis un tableau de bord, sans revue, sans
    test, et sans que le dépôt en garde trace.

    La correspondance va donc dans un seul sens :

        Stripe Price  →  clé de référence stable  →  plan Kivou  →  droits

    et un `Price` inconnu ne rend **aucun** droit payant. Jamais Pro « par
    défaut » : un défaut permissif est une faille qui attend son incident.

Les montants sont des décisions commerciales, pas des conversions. 49 CHF **ou**
49 EUR : le client suisse et le client français paient le même nombre, pas le
même montant converti.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

CATALOGUE_VERSION = "kivou-plans-v0.1"

PlanCode = Literal["discovery", "essential", "pro", "scale"]
PLAN_CODES: tuple[str, ...] = ("discovery", "essential", "pro", "scale")

#: Les seuls plans qu'un client peut acheter. `discovery` est un droit interne :
#: créer un abonnement Stripe à 0 ferait exister une facture pour rien, et un
#: objet de plus à réconcilier.
PURCHASABLE_PLANS: tuple[str, ...] = ("essential", "pro", "scale")

Currency = Literal["chf", "eur"]
CURRENCIES: tuple[str, ...] = ("chf", "eur")

OfferCode = Literal["founding"]
#: Une offre n'est pas un plan. `founding` donne les droits de `pro` ; l'exposer
#: comme un cinquième plan public le rendrait achetable par n'importe qui.
OFFER_CODES: tuple[str, ...] = ("founding",)

TerritoryMode = Literal["single", "multiple", "expanded"]
FilterLevel = Literal["minimum", "basic", "advanced"]
ExportLevel = Literal["none", "manual", "scheduled"]
#: SPEC-014 §15 — `priority` remplace `realtime` : Scale est éligible à chaque
#: exécution du job d'alerte, ce qui est vrai. « Temps réel » promettrait une
#: architecture qui n'existe pas, et une latence qu'aucun cron ne tient.
AlertCadence = Literal["none", "weekly", "daily", "priority"]

#: §7 — au-delà, l'offre fondateur n'est plus une offre fondateur.
FOUNDING_MAXIMUM_ACCOUNTS = 5
FOUNDING_MONTHS = 12
FOUNDING_PLAN_CODE = "pro"
#: Remise en unités mineures : 99 − 70 = 29, dans les deux devises.
FOUNDING_DISCOUNT_MINOR_UNITS = 7000
FOUNDING_EFFECTIVE_MINOR_UNITS = 2900

#: §20 — trois signaux réels, débloqués une fois pour toutes.
DISCOVERY_GRANT_LIMIT = 3

#: `None` = tout l'historique persisté disponible. Ce n'est pas « illimité » :
#: Kivou ne peut pas promettre plus que ce qu'il a réellement conservé.
UNLIMITED_HISTORY: int | None = None


@dataclasses.dataclass(frozen=True)
class PlanEntitlements:
    """Ce qu'un plan permet — du code, testable, versionné avec le dépôt."""

    plan_code: str
    max_active_icps: int
    #: Fenêtre d'historique en jours ; `None` = tout l'historique persisté.
    history_days: int | None
    territory_mode: str
    #: Nombre maximal de territoires d'un ICP actif ; `None` = non plafonné.
    #: §24 — aucun plafond n'est inventé pour Pro ou Scale juste pour
    #: différencier : Kivou n'a pas de couverture à vendre au-delà de ses
    #: sources réelles.
    max_territories_per_icp: int | None
    feed_access: bool
    detail_access: bool
    evidence_access: bool
    filter_level: str
    #: §27 — descriptif seulement. Aucun export, aucune alerte n'existe encore ;
    #: annoncer une capacité qui n'a pas d'endpoint serait une promesse fausse.
    export_level: str
    alert_cadence: str
    recommended: bool = False
    #: §20 — seul Discovery fonctionne par déblocages nominatifs.
    granted_signals: int = 0

    @property
    def is_paid(self) -> bool:
        return self.plan_code in PURCHASABLE_PLANS

    @property
    def has_unlimited_history(self) -> bool:
        return self.history_days is UNLIMITED_HISTORY


DISCOVERY = PlanEntitlements(
    plan_code="discovery",
    max_active_icps=1,
    # §25 — aucune fenêtre générale. Les trois signaux débloqués restent
    # accessibles quel que soit leur âge : ils ont été donnés, pas prêtés.
    history_days=0,
    territory_mode="single",
    max_territories_per_icp=1,
    feed_access=True,
    detail_access=True,
    evidence_access=True,
    filter_level="minimum",
    export_level="none",
    alert_cadence="none",
    granted_signals=DISCOVERY_GRANT_LIMIT,
)

ESSENTIAL = PlanEntitlements(
    plan_code="essential",
    max_active_icps=1,
    history_days=30,
    territory_mode="single",
    max_territories_per_icp=1,
    feed_access=True,
    detail_access=True,
    evidence_access=True,
    filter_level="basic",
    export_level="none",
    alert_cadence="weekly",
)

PRO = PlanEntitlements(
    plan_code="pro",
    max_active_icps=3,
    history_days=365,
    territory_mode="multiple",
    max_territories_per_icp=None,
    feed_access=True,
    detail_access=True,
    evidence_access=True,
    filter_level="advanced",
    export_level="manual",
    alert_cadence="daily",
    recommended=True,
)

SCALE = PlanEntitlements(
    plan_code="scale",
    max_active_icps=10,
    history_days=UNLIMITED_HISTORY,
    territory_mode="expanded",
    max_territories_per_icp=None,
    feed_access=True,
    detail_access=True,
    evidence_access=True,
    filter_level="advanced",
    export_level="scheduled",
    alert_cadence="priority",
)

PLANS: dict[str, PlanEntitlements] = {
    plan.plan_code: plan for plan in (DISCOVERY, ESSENTIAL, PRO, SCALE)
}

#: Prix mensuels, en unités mineures, par plan et par devise. Explicites dans
#: les deux devises : aucune conversion automatique (§6).
MONTHLY_MINOR_UNITS: dict[str, dict[str, int]] = {
    "essential": {"chf": 4900, "eur": 4900},
    "pro": {"chf": 9900, "eur": 9900},
    "scale": {"chf": 19900, "eur": 19900},
}

#: §4, §6 — la référence stable côté application. Un `price_...` change quand la
#: tarification évolue ; la clé de recherche, elle, se transfère au nouveau prix.
#: C'est donc elle que le code connaît, et jamais un identifiant Stripe en dur.
LOOKUP_KEYS: dict[str, dict[str, str]] = {
    plan: {currency: f"kivou_{plan}_monthly_{currency}" for currency in CURRENCIES}
    for plan in PURCHASABLE_PLANS
}

#: L'ordre commercial des formules payantes, du plus petit au plus grand. Il
#: décide du SENS d'un changement — donc de son effet : monter est immédiat,
#: descendre attend la fin de la période déjà payée. Comparer `history_days`
#: aurait marché aujourd'hui et cassé le jour où deux plans partageraient une
#: fenêtre en se distinguant autrement.
PLAN_ORDER: tuple[str, ...] = ("essential", "pro", "scale")


def plan_rank(plan_code: str) -> int:
    """La position d'une formule payante dans l'échelle. Refuse le reste."""
    if plan_code not in PLAN_ORDER:
        raise UnknownPlan(f"formule non ordonnable : {plan_code!r} (attendu {PLAN_ORDER})")
    return PLAN_ORDER.index(plan_code)


PRODUCT_NAMES: dict[str, str] = {
    "essential": "Kivou Essential",
    "pro": "Kivou Pro",
    "scale": "Kivou Scale",
}

FOUNDING_COUPON_LOOKUP = "kivou_founding_12m"


class UnknownPlan(ValueError):
    """Plan absent du catalogue — jamais rattrapé par un défaut permissif."""


class UnknownCurrency(ValueError):
    """Devise hors des deux devises facturables."""


def entitlements_for(plan_code: str | None) -> PlanEntitlements:
    """Les droits d'un plan. Tout ce qui n'est pas reconnu retombe sur Discovery.

    C'est le seul repli du système, et il est **restrictif** : un plan inconnu
    ne peut pas accorder plus que le gratuit.
    """
    if plan_code is None:
        return DISCOVERY
    return PLANS.get(plan_code, DISCOVERY)


def lookup_key_for(plan_code: str, currency: str) -> str:
    """La clé de recherche Stripe d'un plan payant. Refuse tout le reste."""
    if plan_code not in PURCHASABLE_PLANS:
        raise UnknownPlan(f"plan non achetable : {plan_code!r} (attendu {PURCHASABLE_PLANS})")
    if currency not in CURRENCIES:
        raise UnknownCurrency(f"devise non facturable : {currency!r} (attendu {CURRENCIES})")
    return LOOKUP_KEYS[plan_code][currency]


def amount_for(plan_code: str, currency: str) -> int:
    """Le montant mensuel en unités mineures."""
    lookup_key_for(plan_code, currency)
    return MONTHLY_MINOR_UNITS[plan_code][currency]


#: L'index inverse : d'une clé de recherche vers son plan et sa devise. Construit
#: à partir de `LOOKUP_KEYS`, donc impossible à désynchroniser.
_BY_LOOKUP_KEY: dict[str, tuple[str, str]] = {
    key: (plan, currency) for plan, keys in LOOKUP_KEYS.items() for currency, key in keys.items()
}


def plan_for_lookup_key(lookup_key: str | None) -> tuple[str, str] | None:
    """`(plan_code, currency)` d'une clé approuvée, ou `None`.

    `None` signifie « ce prix ne fait partie d'aucun plan Kivou », et l'appelant
    doit alors n'accorder AUCUN droit payant (§9).
    """
    if lookup_key is None:
        return None
    return _BY_LOOKUP_KEY.get(lookup_key)


def public_catalogue() -> tuple[dict[str, object], ...]:
    """Le catalogue tel qu'un client le voit — sans un seul identifiant Stripe."""
    entries = []
    for plan in (DISCOVERY, ESSENTIAL, PRO, SCALE):
        prices = MONTHLY_MINOR_UNITS.get(plan.plan_code, {})
        entries.append(
            {
                "plan_code": plan.plan_code,
                "purchasable": plan.plan_code in PURCHASABLE_PLANS,
                "recommended": plan.recommended,
                "monthly_price": {
                    currency: {"amount_minor_units": amount, "currency": currency}
                    for currency, amount in sorted(prices.items())
                },
                "entitlements": customer_safe_entitlements(plan),
            }
        )
    return tuple(entries)


def customer_safe_entitlements(plan: PlanEntitlements) -> dict[str, object]:
    """Les capacités, telles qu'on peut les annoncer sans mentir."""
    return {
        "max_active_icps": plan.max_active_icps,
        "history_days": plan.history_days,
        "history_scope": "all_available" if plan.has_unlimited_history else "window",
        "territory_mode": plan.territory_mode,
        "max_territories_per_icp": plan.max_territories_per_icp,
        "feed_access": plan.feed_access,
        "detail_access": plan.detail_access,
        "evidence_access": plan.evidence_access,
        "filter_level": plan.filter_level,
        "export_level": plan.export_level,
        "alert_cadence": plan.alert_cadence,
        "granted_signals": plan.granted_signals,
    }
