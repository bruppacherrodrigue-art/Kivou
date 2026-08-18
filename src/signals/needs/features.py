"""Les faits d'entrée, classés par RÔLE — mécanisme, pression, temporalité.

SPEC-007R1 §8 : le Need Graph V0 comptait des faits sans distinguer ce qu'ils
prouvaient. « Type construction » et « CPV 45 » comptaient pour deux alors
qu'ils disent la même chose ; `defined_contract_period` et `several_lots`
passaient pour des indices de charge alors qu'ils ne disent rien de la charge.

R1 sépare deux rôles, et un besoin `medium` exige un fait de chaque :

- **mécanisme** — pourquoi l'exécution de CE contrat consomme ce type de
  ressource. Se lit dans la nature du travail (type, profil CPV) ;
- **pression** — pourquoi un appoint externe est plausible. Se lit dans
  l'échelle, la durée ou la complexité, jamais dans la nature du travail.

Deux faits du même rôle ne se cumulent jamais. La liste des pressions (§2.3 de
la rubrique) est exhaustive : ce qui n'y figure pas n'en est pas une.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from signals.needs.model import NeedTiming
from signals.understanding.model import Claim, ContractUnderstanding

# ─── Échelle (§9-§10) ───────────────────────────────────────────────────────────

ScaleBand = Literal["not_material", "modest", "large", "very_large", "unknown"]

COMPARABLE_CURRENCIES = frozenset({"EUR", "CHF"})
"""Les seules devises que la politique compare sans conversion. Toute autre
donne `unknown` : un montant publié n'est pas une échelle connue."""

MATERIALITY_FLOOR = 50_000
"""En dessous, un montant ne porte aucun raisonnement (§10). Un marché à 26 EUR
ou 538 RON peut être un prix unitaire, une donnée source aberrante ou un
micro-marché : dans tous les cas, il ne soutient pas un besoin `medium`."""

LARGE_FLOOR = 1_000_000
VERY_LARGE_FLOOR = 10_000_000


def scale_band(amount_claim_value: str | None) -> ScaleBand:
    """« 4500000.00 CHF » → large ; « 538 RON » → unknown ; « 26.00 EUR » → not_material."""
    if not amount_claim_value:
        return "unknown"
    try:
        raw_value, currency = amount_claim_value.rsplit(" ", 1)
        value = float(raw_value)
    except ValueError:
        return "unknown"
    if currency not in COMPARABLE_CURRENCIES:
        return "unknown"
    if value < MATERIALITY_FLOOR:
        return "not_material"
    if value >= VERY_LARGE_FLOOR:
        return "very_large"
    if value >= LARGE_FLOOR:
        return "large"
    return "modest"


# ─── Profils de ressources CPV (§13) ────────────────────────────────────────────

ConstructionProfile = Literal[
    "earthworks",
    "building_civil",
    "technical_installation",
    "finishing",
    "equipment_hire_as_deliverable",
    "general_or_unknown",
]

_CPV_PROFILES: dict[str, ConstructionProfile] = {
    "451": "earthworks",
    "452": "building_civil",
    "453": "technical_installation",
    "454": "finishing",
    "455": "equipment_hire_as_deliverable",
}
"""Le type canonique `construction` couvre des chantiers dont les intrants n'ont
rien de commun : un terrassement mobilise des engins, une installation
électrique des composants, une finition des matériaux. Le préfixe CPV est le
seul fait canonique qui les distingue. Tout ce qui n'est pas couvert —
45000000 compris — reste `general_or_unknown` : un chantier dont on ignore la
nature ne permet d'affirmer ni engins ni matériaux (§14)."""


def construction_profile(cpv: str | None) -> ConstructionProfile:
    if not cpv:
        return "general_or_unknown"
    return _CPV_PROFILES.get(cpv[:3], "general_or_unknown")


# ─── Types ──────────────────────────────────────────────────────────────────────

HUMAN_INTENSIVE_TYPES = frozenset(
    {
        "construction",
        "facility_services",
        "security_services",
        "transport_logistics",
        "maintenance_repair",
    }
)
"""Types dont l'exécution consomme structurellement du personnel.
`social_health_services` en est absent **à dessein** : son mécanisme existe mais
sa politique de pression est plus stricte (§15), il a donc sa propre règle."""

RECURRING_SERVICE_TYPES = frozenset(
    {
        "facility_services",
        "security_services",
        "social_health_services",
        "maintenance_repair",
        "transport_logistics",
    }
)
"""Services à prestations répétées, par opposition aux projets et fournitures
uniques : leur récurrence crée une mobilisation durable.

`transport_logistics` y figure par **arbitrage** du gold DEV-2 — c'était le seul
point d'instabilité entre les deux passes d'adjudication (10 couples sur 700).
L'arbitre a tranché sur la cohérence interne de la rubrique : durcir les
services sociaux en exigeant récurrence **et** échelle (§15) n'aurait aucun sens
si la récurrence seule ne suffisait pas ailleurs."""

MACHINERY_PROFILES = frozenset({"earthworks", "building_civil"})
MATERIALS_PROFILES = frozenset({"building_civil", "technical_installation", "finishing"})
DEBRIS_PROFILES = frozenset({"earthworks", "building_civil", "finishing"})
SEPARABLE_SPECIALTY_TYPES = frozenset({"construction", "engineering_architecture", "it_digital"})

_MONTHS_PER_UNIT = {"day": 1 / 30, "week": 1 / 4.3, "month": 1.0, "year": 12.0}
NEAR_TERM_DAYS = 90
RECURRING_MONTHS = 12


@dataclass(frozen=True)
class NeedFeatures:
    """Ce que les règles ont le droit de voir — et le rôle de chaque fait."""

    contract_type: str
    construction_profile: ConstructionProfile
    scale_band: ScaleBand
    several_lots: bool
    long_duration: bool
    defined_period: bool
    consortium: bool
    duration_months: float | None
    timing: NeedTiming
    # WEDGE-HARDENING R1 §19, §22 — deux faits canoniques, jamais du texte
    # reformulé : l'objet tel que l'avis le publie, et le corps de métier tel
    # que le CPV le porte.
    published_object: str | None
    trade_domain: str
    claims: dict[str, Claim]

    # ── rôle A : mécanisme ──────────────────────────────────────────────────
    def mechanism(self, name: str) -> bool:
        profile = self.construction_profile
        construction = self.contract_type == "construction"
        return {
            "human_intensive_type": self.contract_type in HUMAN_INTENSIVE_TYPES,
            "social_health_service": self.contract_type == "social_health_services",
            "construction_machinery": construction and profile in MACHINERY_PROFILES,
            "construction_materials": construction and profile in MATERIALS_PROFILES,
            "construction_debris": construction and profile in DEBRIS_PROFILES,
            "construction_site": construction,
            "transport_fleet": self.contract_type == "transport_logistics",
            "separable_specialties": self.contract_type in SEPARABLE_SPECIALTY_TYPES,
        }[name]

    # ── rôle B : pression ───────────────────────────────────────────────────
    def pressure(self, name: str) -> bool:
        known_scale = self.scale_band in ("modest", "large", "very_large")
        large = self.scale_band in ("large", "very_large")
        return {
            "large_scale": large,
            "known_nontrivial_scale": known_scale,
            "long_recurring_duration": self.recurring_service,
            "recurring_with_scale": self.recurring_service and known_scale,
            "parallel_lots_with_scale": self.several_lots and known_scale,
            "distinct_specialties": self.consortium,
            "near_term_start": self.timing in ("immediate", "near_term"),
            # Explicitement JAMAIS des pressions (§11-§12) — nommés pour que les
            # tests puissent le vérifier, et pour qu'aucune règle ne les cite.
            "defined_period": False,
            "several_lots_alone": False,
        }[name]

    @property
    def recurring_service(self) -> bool:
        return (
            self.contract_type in RECURRING_SERVICE_TYPES
            and self.duration_months is not None
            and self.duration_months >= RECURRING_MONTHS
        )


PRESSURE_FACTS: dict[str, str] = {
    "large_scale": "amount",
    "known_nontrivial_scale": "amount",
    "long_recurring_duration": "long_duration",
    "recurring_with_scale": "amount",
    "parallel_lots_with_scale": "lot",
    "distinct_specialties": "consortium_award",
    # La date de début vit dans `ContractTiming`, qui n'est pas porté par un
    # `Claim` : le fait est nommé, mais il n'apporte aucune preuve — celle du
    # mécanisme suffit à ancrer le besoin.
    "near_term_start": "contract_start_date",
}
"""Le claim d'entrée qui fonde chaque pression : c'est ce qui lie un besoin aux
preuves des FAITS, jamais à une preuve du futur."""

MECHANISM_FACTS: dict[str, str] = {
    "human_intensive_type": "contract_type",
    "social_health_service": "contract_type",
    "construction_machinery": "cpv",
    "construction_materials": "cpv",
    "construction_debris": "cpv",
    "construction_site": "contract_type",
    "transport_fleet": "contract_type",
    "separable_specialties": "contract_type",
}


def _timing_of(cu: ContractUnderstanding, *, recurring: bool) -> NeedTiming:
    """§19 — déterministe, jamais inventé. Référence : la date de publication."""
    if recurring:
        return "recurring"
    start = cu.timing.contract_start_date
    published = cu.timing.published_at
    if start is None or published is None:
        return "unknown"
    published_date = published.date() if hasattr(published, "date") else published
    delta = (start - published_date).days
    if delta <= 30:
        return "immediate"
    if delta <= NEAR_TERM_DAYS:
        return "near_term"
    return "medium_term"


def extract_features(cu: ContractUnderstanding) -> NeedFeatures:
    characteristics = {c.value for c in cu.characteristics}
    contract_type = cu.contract_type.value

    duration_months: float | None = None
    if cu.timing.duration_value and cu.timing.duration_unit in _MONTHS_PER_UNIT:
        duration_months = cu.timing.duration_value * _MONTHS_PER_UNIT[cu.timing.duration_unit]

    recurring = (
        contract_type in RECURRING_SERVICE_TYPES
        and duration_months is not None
        and duration_months >= RECURRING_MONTHS
    )

    amount_claim = cu.facts.get("amount")
    cpv_claim = cu.facts.get("cpv")
    claims: dict[str, Claim] = {"contract_type": cu.contract_type, **cu.facts}
    for characteristic in cu.characteristics:
        claims[characteristic.value] = characteristic

    return NeedFeatures(
        contract_type=contract_type,
        construction_profile=construction_profile(cpv_claim.value if cpv_claim else None),
        scale_band=scale_band(amount_claim.value if amount_claim else None),
        several_lots="several_lots" in characteristics,
        long_duration="long_duration" in characteristics,
        defined_period="defined_contract_period" in characteristics,
        consortium=bool(characteristics & {"consortium_award", "multiple_contractors"}),
        duration_months=duration_months,
        timing=_timing_of(cu, recurring=recurring),
        published_object=(
            cu.facts["published_object"].value if "published_object" in cu.facts else None
        ),
        trade_domain=cu.trade_domain.value if cu.trade_domain else "unknown_or_general",
        claims=claims,
    )
