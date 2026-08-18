"""La forme client d'un signal — faits d'un côté, hypothèses de l'autre.

La séparation n'est pas cosmétique (§8)
──────────────────────────────────────
Un objet plat où « l'attributaire » et « le besoin plausible » se lisent
pareil transforme une hypothèse en promesse commerciale. Le contrat de
réponse porte donc deux blocs nommés : `facts`, ce que la source a publié,
et `analysis`, ce que Kivou en déduit. Aucun champ ne franchit la frontière,
et aucun nom de champ n'affirme une certitude d'achat.

Rien n'est recalculé ici (§11)
─────────────────────────────
Les besoins viennent de la ligne matérialisée, jamais d'une exécution du
Need Graph pendant une requête GET. Aucun LLM n'est appelé. La seule chose
réévaluée est la FRAÎCHEUR, parce que c'est la seule qui change toute seule.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from signals.feed import copy as feed_copy
from signals.feed import policy
from signals.feed.query import FeedSignal
from signals.recency.claim import claim_for_status

#: §13 — un chemin de preuve désigne un emplacement DANS LA SOURCE. Tout ce qui
#: ressemble à un fichier local, un artefact de recherche ou une fixture est
#: retiré : le client n'a rien à faire de l'arborescence de Kivou.
_FORBIDDEN_PATH_MARKERS: tuple[str, ...] = (
    "/home/",
    "/tmp/",
    "tests/",
    "fixtures/",
    "src/signals",
    ".json",
    ".py",
    ".jsonl",
    "scratchpad",
)


def _safe_path(path: str | None) -> str | None:
    if path is None:
        return None
    lowered = path.lower()
    if any(marker in lowered for marker in _FORBIDDEN_PATH_MARKERS):
        return None
    return path


def _amount(value: Decimal | None, currency: str | None) -> dict[str, Any] | None:
    """Un montant n'existe que complet : un nombre sans devise n'est pas un prix."""
    if value is None or currency is None:
        return None
    return {"value": str(value), "currency": currency}


def _buyer(procedure_buyers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not procedure_buyers:
        return None
    first = procedure_buyers[0]
    identifiers = first.get("identifiers") or []
    identifier = identifiers[0] if identifiers else None
    return {
        "name": first.get("legal_name"),
        "country": first.get("country"),
        "identifier": (
            None
            if identifier is None
            else {"scheme": identifier.get("scheme"), "value": identifier.get("value")}
        ),
    }


def _location(place: dict[str, Any] | None) -> dict[str, Any] | None:
    if not place:
        return None
    return {
        "country": place.get("country"),
        "locality": place.get("locality"),
        "postal_code": place.get("postal_code"),
        "subdivision_code": place.get("subdivision_code"),
    }


def _company(item: FeedSignal) -> dict[str, Any]:
    """L'identité de l'attributaire — jamais un identifiant déguisé en nom (§19)."""
    signal = item.signal
    display = item.display
    scheme = display.identifier_scheme if display else signal.winner_identifier_scheme
    value = display.identifier_value if display else signal.winner_identifier_value
    return {
        "name": display.name if display else None,
        "country": (display.country if display else None) or signal.winner_country,
        "identifier": None if value is None else {"scheme": scheme, "value": value},
    }


def _event(item: FeedSignal, *, lang: str) -> dict[str, Any]:
    """L'événement TEL QU'IL VAUT AUJOURD'HUI, et la phrase que ce statut autorise.

    La phrase vient de `recency.claim` : c'est la seule autorité sur ce que
    Kivou a le droit d'affirmer d'une date, et la dupliquer ici recréerait
    exactement l'écart que SPEC-009D a mesuré.
    """
    status = item.status
    clock_name = policy.STATUS_CLOCK.get(status)
    clock = item.recency.clocks[clock_name] if clock_name else None
    date = item.event_date
    award_clock = item.recency.award_clock
    return {
        "status": status,
        # CLOSEOUT §2 — le type CLIENT, jamais le raccourci interne de
        # `recency.claim.mvp_event_type` : celui-ci étiquetterait « publication
        # récente » un avis dont aucune date n'est exploitable.
        "type": policy.customer_event_type(status),
        "clock": clock_name,
        "date": date.isoformat() if date else None,
        "age_days": clock.age_days if clock else None,
        "headline": claim_for_status(
            status, company=item.display.name if item.display else "", lang=lang
        ),
        "why_now": feed_copy.WHY_NOW[status][lang],
        # CLOSEOUT §1 — le complément lit l'horloge d'ATTRIBUTION elle-même. Il
        # ne peut donc pas annoncer l'absence d'une date qui existe.
        "award_date_note": feed_copy.AWARD_CLOCK_NOTE[award_clock.status][lang],
        "award_clock_status": award_clock.status,
        "is_new_opportunity": status in policy.NEW_OPPORTUNITY_STATUSES,
    }


def _contract(item: FeedSignal) -> dict[str, Any]:
    """Les faits du contrat, tels que la source les publie. Aucune déduction ici."""
    award, event = item.signal.award, item.signal.event
    return {
        "title": award.title,
        "lot": award.lot_identifier,
        "lot_title": award.lot_title,
        "reference": award.contract_reference,
        "buyer": _buyer(event.procedure_buyers),
        "amount": _amount(award.amount, award.currency),
        "cpv": award.cpv_main,
        "location": _location(award.place_of_performance),
        "dates": {
            "award": _iso(award.award_date),
            "contract_notification": _iso(award.contract_notification_date),
            "publication": _iso(event.published_on),
        },
    }


def _iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def _source(item: FeedSignal) -> dict[str, Any]:
    event = item.signal.event
    return {
        "system": event.source_system,
        "country": event.source_country,
        "notice_id": event.source_notice_id,
        "procedure_id": event.source_procedure_id,
        "url": event.source_url,
    }


def _needs(item: FeedSignal, *, lang: str, full: bool) -> dict[str, Any]:
    """Les besoins PLAUSIBLES, tels qu'ils ont été matérialisés.

    Ni recalcul, ni LLM, ni remplissage : une liste vide reste une liste vide.
    Un besoin fabriqué pour que la carte paraisse complète serait exactement le
    faux signal que tout le reste du système cherche à éviter.
    """
    stored = item.signal.plausible_needs or []
    entries = []
    for need in stored:
        category = need.get("category")
        entry: dict[str, Any] = {
            "category": category,
            "label": feed_copy.translate(feed_copy.NEED_LABELS, category, lang),
            "statement": need.get("statement"),
            "confidence": need.get("confidence"),
            "timing": need.get("timing"),
            "timing_label": feed_copy.translate(
                feed_copy.NEED_TIMING_LABELS, need.get("timing"), lang
            ),
            "targeted_by_your_profile": category in (item.signal.icp_matched_needs or []),
        }
        if full:
            # `reasoning` porte explicitement le passage du fait à l'hypothèse ;
            # le validateur du domaine refuse toute formulation de certitude.
            entry["reasoning"] = need.get("reasoning")
        entries.append(entry)
    return {"note": feed_copy.PLAUSIBLE_NEEDS_NOTE[lang], "items": entries}


def _fit(item: FeedSignal, *, lang: str) -> dict[str, Any]:
    """Pourquoi Kivou montre ceci à CE client — expliqué, jamais noté (§12).

    Les raisons sont dérivées de ce qui est stocké : les besoins de l'ICP
    effectivement retrouvés, et la géographie. Aucun poids, aucun composant de
    score, aucune matrice de mise en correspondance ne sort d'ici.
    """
    signal = item.signal
    reasons: list[str] = []
    for category in signal.icp_matched_needs or []:
        label = feed_copy.translate(feed_copy.NEED_LABELS, category, lang)
        if label:
            reasons.append(feed_copy.FIT_REASONS["need"][lang].format(value=label))
    place = (signal.award.place_country or "").strip()
    if place:
        reasons.append(feed_copy.FIT_REASONS["territory"][lang].format(value=place))
    elif signal.event.source_country:
        reasons.append(
            feed_copy.FIT_REASONS["source_country"][lang].format(value=signal.event.source_country)
        )

    if signal.icp_matched_needs:
        key = "matched_needs"
    elif place:
        key = "territory_only"
    else:
        key = "targeted_profile"
    return {
        "label": feed_copy.FIT_LABELS[key][lang],
        "target_icp_id": signal.target_icp_id,
        "target_icp_label": item.target_icp_label,
        "reasons": tuple(reasons),
    }


def _analysis(item: FeedSignal, *, lang: str, full: bool) -> dict[str, Any]:
    """Le bloc des INFÉRENCES. Séparé des faits, et nommé comme tel."""
    signal = item.signal
    analysis: dict[str, Any] = {
        "plausible_needs": _needs(item, lang=lang, full=full),
        "fit": _fit(item, lang=lang),
    }
    if full:
        analysis["contract_reading"] = {
            "note": feed_copy.ANALYSIS_SUMMARY_NOTE[lang],
            "summary": signal.inferred_contract_summary,
            "contract_type": signal.inferred_contract_type,
            "sector": signal.inferred_sector,
        }
    return analysis


def _evidence(item: FeedSignal, *, lang: str) -> dict[str, Any]:
    """Les preuves, groupées par le FAIT qu'elles étayent (§14).

    Rien n'est inventé : le groupement reprend `anchors_kind` / `anchors_ref`
    tels que la persistance les a écrits. Une preuve rattachée à une hypothèse
    ne rejoint jamais les faits publics — elle va dans `analysis_inputs`, avec
    la mise en garde qui dit ce qu'elle prouve vraiment (§27.9).
    """
    public: dict[str, list[dict[str, Any]]] = {}
    inputs: dict[str, list[dict[str, Any]]] = {}
    for anchor in item.signal.evidence:
        rendered = {
            "source_system": anchor.source_system,
            "source_kind": anchor.source_kind,
            "notice_id": anchor.source_notice_id,
            "procedure_id": anchor.source_procedure_id,
            "url": anchor.source_url,
            "path": _safe_path(anchor.path),
            "excerpt": anchor.excerpt,
            "retrieved_at": (
                anchor.retrieved_at.isoformat() if anchor.retrieved_at is not None else None
            ),
        }
        if anchor.anchors_kind == "award_fact":
            public.setdefault(anchor.anchors_ref, []).append(rendered)
        elif anchor.anchors_kind == "plausible_need":
            inputs.setdefault(anchor.anchors_ref, []).append(rendered)
        # `icp_match` reste interne : il documente une décision de moteur, pas
        # un fait public, et l'exposer reviendrait à publier le raisonnement de
        # mise en correspondance que §12 garde à l'intérieur.
    return {
        "public_facts": [
            {
                "fact": name,
                "label": feed_copy.translate(feed_copy.FACT_LABELS, name, lang) or name,
                "items": tuple(items),
            }
            for name, items in sorted(public.items())
        ],
        "analysis_inputs": {
            "note": feed_copy.ANALYSIS_INPUT_NOTE[lang],
            "groups": [
                {
                    "plausible_need": name,
                    "label": feed_copy.translate(feed_copy.NEED_LABELS, name, lang) or name,
                    "items": tuple(items),
                }
                for name, items in sorted(inputs.items())
            ],
        },
    }


def feed_item(item: FeedSignal, *, lang: str) -> dict[str, Any]:
    """La carte du feed : compacte, sans preuve, sans raisonnement long (§16)."""
    feed_copy.check_language(lang)
    return {
        "signal_id": item.signal.signal_key,
        "target_icp_id": item.signal.target_icp_id,
        "company": _company(item),
        "event": _event(item, lang=lang),
        "contract": _contract(item),
        "analysis": _analysis(item, lang=lang, full=False),
        "source": _source(item),
    }


def signal_detail(item: FeedSignal, *, lang: str) -> dict[str, Any]:
    """Le détail : la carte, plus de quoi VÉRIFIER (§15)."""
    detail = feed_item(item, lang=lang)
    detail["analysis"] = _analysis(item, lang=lang, full=True)
    detail["evidence"] = _evidence(item, lang=lang)
    detail["opportunity_id"] = item.signal.opportunity_key
    detail["customer_ready"] = item.display is not None
    detail["read_at"] = None  # rempli par la route, qui seule connaît la date
    return detail
