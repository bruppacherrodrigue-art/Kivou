"""Deterministic source-fact gates for Phase A French construction awards."""

from __future__ import annotations

import calendar
import datetime as dt
import re
import unicodedata
from urllib.parse import urlparse

from signals.phase_a_btp.contracts import (
    AwardSnapshot,
    CommercialState,
    EligibilityResult,
    EnrichmentLevel,
    FreshnessBucket,
)

DASHBOARD_MAX_AGE_DAYS = 730

_GENERIC_OBJECT_WORDS = frozenset(
    {
        "accord",
        "batiment",
        "batiments",
        "cadre",
        "construction",
        "de",
        "des",
        "du",
        "en",
        "et",
        "la",
        "le",
        "les",
        "marche",
        "operation",
        "renovation",
        "travail",
        "travaux",
    }
)
_OPERATIONAL_TERMS: tuple[tuple[str, str], ...] = (
    ("terrassement", "Spécialité technique publiée : terrassement"),
    ("demolition", "Spécialité technique publiée : démolition"),
    ("gros oeuvre", "Spécialité technique publiée : gros œuvre"),
    ("maconnerie", "Spécialité technique publiée : maçonnerie"),
    ("charpente", "Ouvrage ou spécialité publié : charpente"),
    ("couverture", "Ouvrage ou spécialité publié : couverture"),
    ("etancheite", "Spécialité technique publiée : étanchéité"),
    ("bardage", "Matériau ou spécialité publié : bardage"),
    ("menuiserie", "Équipement ou spécialité publié : menuiserie"),
    ("electricite", "Spécialité technique publiée : électricité"),
    ("chauffage", "Équipement ou spécialité publié : chauffage"),
    ("ventilation", "Équipement publié : ventilation"),
    ("climatisation", "Équipement publié : climatisation"),
    ("plomberie", "Spécialité technique publiée : plomberie"),
    ("assainissement", "Ouvrage publié : assainissement"),
    ("voirie", "Ouvrage publié : voirie"),
    ("reseau", "Ouvrage publié : réseau"),
    ("facade", "Ouvrage publié : façade"),
    ("peinture", "Matériau ou spécialité publié : peinture"),
    ("resine", "Matériau publié : résine"),
    ("beton", "Matériau publié : béton"),
    ("aluminium", "Matériau publié : aluminium"),
    ("bois", "Matériau publié : bois"),
    ("logement", "Ouvrage publié : logements"),
    ("ecole", "Ouvrage publié : école"),
    ("pont", "Ouvrage publié : pont"),
    ("mur", "Ouvrage publié : mur"),
    ("toiture", "Ouvrage publié : toiture"),
    ("bassin", "Ouvrage publié : bassin"),
    ("reservoir", "Ouvrage publié : réservoir"),
    ("pomp", "Équipement publié : groupe de pompage"),
)


def _normalized(value: str | None) -> str:
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value)
    return " ".join(
        re.findall(r"[a-z0-9]+", "".join(char for char in folded if not unicodedata.combining(char)).lower())
    )


def _object_text(award: AwardSnapshot) -> str:
    return award.lot_title or award.description or award.title or ""


def _specific_object(award: AwardSnapshot) -> bool:
    words = _normalized(_object_text(award)).split()
    if len([word for word in words if word.isalpha()]) < 4:
        return False
    distinctive = [word for word in words if len(word) >= 4 and word not in _GENERIC_OBJECT_WORDS]
    return bool(distinctive)


def _clear_awardee(value: str | None) -> bool:
    return bool(value and re.search(r"[^\W\d_]", value, re.UNICODE))


def _official_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _precise_lot(award: AwardSnapshot) -> str | None:
    candidate = award.lot_title
    if candidate and _specific_object(award):
        return f"Lot précis publié : {candidate}"
    title = award.title or ""
    match = re.search(r"\blot\s*(?:n[°o]?\s*)?\d+\s*[:\-]\s*([^;,.]{4,})", title, re.IGNORECASE)
    if match:
        return f"Lot précis publié : {match.group(1).strip()}"
    return None


def _operational_elements(award: AwardSnapshot) -> tuple[str, ...]:
    elements: list[str] = []
    lot = _precise_lot(award)
    if lot:
        elements.append(lot)
    if award.description and len(award.description.strip()) >= 40:
        excerpt = " ".join(award.description.split())
        elements.append(f"Prestation détaillée publiée : {excerpt[:220]}")
    haystack = _normalized(" ".join(filter(None, (award.title, award.lot_title, award.description))))
    for marker, label in _OPERATIONAL_TERMS:
        if marker in haystack and label not in elements:
            elements.append(label)
    if award.duration_value and award.duration_unit:
        elements.append(f"Durée publiée : {award.duration_value} {award.duration_unit}")
    if award.contract_start_date or award.contract_end_date:
        start = award.contract_start_date.isoformat() if award.contract_start_date else "non publiée"
        end = award.contract_end_date.isoformat() if award.contract_end_date else "non publiée"
        elements.append(f"Calendrier publié : {start} – {end}")
    if award.location and award.location.precise:
        place = award.location.locality or award.location.postal_code or award.location.subdivision_code
        elements.append(f"Lieu d’exécution précis publié : {place}")
    return tuple(elements)


def _concrete_information(award: AwardSnapshot) -> tuple[str, ...]:
    facts: list[str] = []
    if award.cpv_main and award.cpv_main != "45000000":
        facts.append("detailed_cpv")
    if award.amount is not None and award.currency is not None:
        facts.append("amount")
    if _precise_lot(award):
        facts.append("precise_lot")
    if award.description and len(award.description.strip()) >= 40:
        facts.append("detailed_service")
    if award.cpv_additional:
        facts.append("additional_cpv")
    if award.duration_value and award.duration_unit:
        facts.append("duration")
    if award.contract_start_date or award.contract_end_date:
        facts.append("calendar")
    return tuple(facts)


def _bucket(age_days: int) -> FreshnessBucket:
    if age_days <= 90:
        return FreshnessBucket.DAYS_0_90
    if age_days <= 180:
        return FreshnessBucket.DAYS_91_180
    if age_days <= 365:
        return FreshnessBucket.DAYS_181_365
    return FreshnessBucket.OVER_ONE_YEAR


def _add_months(value: dt.date, months: int) -> dt.date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    return dt.date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _estimated_end(award: AwardSnapshot) -> dt.date | None:
    if award.contract_end_date:
        return award.contract_end_date
    if not award.duration_value or not award.duration_unit:
        return None
    start = award.contract_start_date or award.event_date
    if not start:
        return None
    unit = _normalized(award.duration_unit)
    if unit in {"day", "days", "jour", "jours"}:
        return start + dt.timedelta(days=award.duration_value)
    if unit in {"week", "weeks", "semaine", "semaines"}:
        return start + dt.timedelta(weeks=award.duration_value)
    if unit in {"month", "months", "mois"}:
        return _add_months(start, award.duration_value)
    if unit in {"year", "years", "an", "ans", "annee", "annees"}:
        return _add_months(start, award.duration_value * 12)
    return None


def evaluate(award: AwardSnapshot, *, as_of: dt.date) -> EligibilityResult:
    """Evaluate one source snapshot without a provider call or mutable state."""

    event_date = award.event_date
    age_days = (as_of - event_date).days if event_date else DASHBOARD_MAX_AGE_DAYS + 1
    bucket = _bucket(max(age_days, 0))
    operational = _operational_elements(award)
    concrete = _concrete_information(award)
    reasons: list[str] = []

    if not (award.cpv_main and award.cpv_main.startswith("45")):
        reasons.append("outside_france_btp_cpv")
    if not _clear_awardee(award.awardee_name):
        reasons.append("awardee_name_missing")
    if not _specific_object(award):
        reasons.append("object_not_specific")
    if event_date is None:
        reasons.append("commercial_date_missing")
    elif age_days < 0:
        reasons.append("commercial_date_in_future")
    elif age_days > DASHBOARD_MAX_AGE_DAYS:
        reasons.append("dashboard_too_old")
    if not (award.location and award.location.precise):
        reasons.append("execution_place_not_precise")
    if not _official_url(award.source_url):
        reasons.append("official_link_missing")
    if len(concrete) < 2:
        reasons.append("concrete_information_below_two")
    if not operational:
        reasons.append("operational_element_missing")

    visible = not reasons
    estimated_end = _estimated_end(award)
    ongoing = estimated_end is not None and estimated_end >= as_of
    if not visible:
        outbound = False
        outbound_reason = "signal_not_visible"
    elif age_days <= 90:
        outbound = True
        outbound_reason = "award_0_90_days"
    elif age_days <= 180:
        outbound = True
        outbound_reason = "award_91_180_days"
    elif ongoing:
        outbound = True
        outbound_reason = "published_execution_probably_ongoing"
    else:
        outbound = False
        outbound_reason = "published_execution_not_ongoing"

    state = (
        CommercialState.OUTBOUND_READY
        if outbound
        else CommercialState.VISIBLE_DASHBOARD
        if visible
        else CommercialState.INSUFFICIENT
    )
    raw_siret = award.awardee_siret or award.awardee_name or ""
    recoverable = not _clear_awardee(award.awardee_name) and bool(
        re.fullmatch(r"\d{14}", re.sub(r"\D", "", raw_siret))
    )
    return EligibilityResult(
        visible_dashboard=visible,
        outbound_ready=outbound,
        commercial_state=state,
        enrichment_level=(
            EnrichmentLevel.DCE_ANALYZED
            if award.dce_document_ids
            else EnrichmentLevel.OFFICIAL_SOURCE
        ),
        freshness_bucket=bucket,
        age_days=max(age_days, 0),
        execution_probably_ongoing=ongoing,
        outbound_reason=outbound_reason,
        concrete_information=concrete,
        operational_elements=operational,
        reasons=tuple(reasons),
        recoverable_siret=recoverable,
    )
