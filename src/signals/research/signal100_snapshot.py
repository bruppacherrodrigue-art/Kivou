"""Snapshots SIGNAL-100 : ce que Kivou montrerait, et ce que l'arbitre voit.

Trois objets distincts, volontairement :

* `build_snapshot` — le gel complet d'un signal (§15) : faits publics, moteurs,
  scores, preuves, versions. C'est l'archive, elle contient tout.
* `blind_view` — la vue d'adjudication (§28). Elle retire le score, la bande, la
  décision, les `rule_id` et la mécanique interne du Need Graph : l'arbitre juge
  un signal commercial, il ne vérifie pas qu'un moteur respecte ses propres
  règles.
* `render_signal_text` — la représentation textuelle déterministe (§49), pour
  SPEC-011. Ni React, ni HTML, ni CSS.

Aucun contact, aucune personne, aucun e-mail (§52) : le modèle `OrganizationRef`
ne porte que des organisations, et rien ici n'en fabrique.
"""

from __future__ import annotations

from typing import Any

from signals.matching import REFERENCE_ICP_LIBRARY_VERSION
from signals.research.signal100 import DOCUMENT_MODE_DISCLOSURE

#: Champs du Need Graph qui décrivent la mécanique interne du moteur plutôt que
#: l'hypothèse commerciale. Ils sont archivés, jamais montrés à l'arbitre (§28).
NEED_ENGINE_INTERNALS = ("rule_ids", "mechanism_facts", "pressure_facts", "engine_version")


def _winner(award: Any) -> dict[str, Any]:
    """L'identité publiée du gagnant — organisations seulement (§52)."""
    parties = []
    for party in award.awardee_parties:
        parties.append(
            {
                "name": party.name,
                "is_group": party.is_group,
                "members": [
                    {
                        "legal_name": member.organization.legal_name,
                        "country": member.organization.country,
                        "identifiers": [
                            {"scheme": i.scheme, "value": i.value}
                            for i in member.organization.identifiers
                        ],
                        "address": member.organization.address,
                        "website": member.organization.website,
                        "role": member.role,
                    }
                    for member in party.members
                ],
            }
        )
    return {"status": award.winner_status, "parties": parties}


def _money(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "amount": str(value.amount),
        "currency": value.currency,
        "vat_category": value.vat_category,
    }


def _place(location: Any) -> dict[str, Any] | None:
    if location is None:
        return None
    return location.model_dump(mode="json")


def _need(need: Any, *, blind: bool) -> dict[str, Any]:
    payload = need.model_dump(mode="json")
    if blind:
        for field in NEED_ENGINE_INTERNALS:
            payload.pop(field, None)
    return payload


def build_snapshot(run: Any, match: Any, icp: Any, *, signal_id: str) -> dict[str, Any]:
    """Le gel complet d'un signal (§15) — l'archive, pas la vue d'adjudication."""
    award = run.lot.award
    understanding = run.understanding
    selected = [need for need in run.needs.needs if need.category in set(match.matched_needs)]

    return {
        "signal_id": signal_id,
        "source": run.lot.source,
        "notice": run.lot.notice,
        "award_ref": {
            "source_system": award.event_ref.source_system,
            "source_notice_id": award.event_ref.source_notice_id,
            "notice_version": award.event_ref.notice_version,
            "source_award_id": award.source_award_id,
            "lot_identifier": (award.lot.identifier if award.lot else None),
        },
        "source_url": run.lot.event.provenance.source_url,
        "publication_date": (
            run.lot.event.published_at.isoformat() if run.lot.event.published_at else None
        ),
        "winner": _winner(award),
        "contract": {
            "title": award.title,
            "lot_title": (award.lot.title if award.lot else None),
            "contract_reference": award.contract_reference,
            "description": award.description,
            "cpv_main": str(award.cpv_main) if award.cpv_main else None,
            "cpv_additional": [str(code) for code in award.cpv_additional],
            "value": _money(award.value),
            "place_of_performance": _place(award.place_of_performance),
            "buyers": [
                {"legal_name": b.legal_name, "country": b.country}
                for b in run.lot.event.procedure_buyers
            ],
        },
        "understanding": understanding.model_dump(mode="json"),
        "needs": run.needs.model_dump(mode="json"),
        "matched_needs": list(match.matched_needs),
        "selected_needs": [_need(need, blind=False) for need in selected],
        "icp": icp.model_dump(mode="json"),
        "score": {
            "normalized_score": match.normalized_score,
            "band": match.band,
            "decision": match.decision,
            "confidence": match.confidence,
            "raw_points": match.raw_points,
            "maximum_applicable_points": match.maximum_applicable_points,
            "components": [c.model_dump(mode="json") for c in match.score_components],
        },
        "positive_reasons": list(match.positive_reasons),
        "limitations": [*match.limitations, DOCUMENT_MODE_DISCLOSURE],
        "evidence_refs": [e.model_dump(mode="json") for e in match.evidence_refs],
        "source_mode": run.needs.source_mode,
        "versions": {
            "understanding_engine": understanding.engine_version,
            "need_engine": run.needs.engine_version,
            "match_policy": match.match_policy_version,
            "score_policy": match.score_policy_version,
            "reference_icp_library": REFERENCE_ICP_LIBRARY_VERSION,
        },
    }


def blind_view(snapshot: dict[str, Any], run: Any, match: Any, icp: Any) -> dict[str, Any]:
    """La vue d'adjudication (§28) — sans score, sans bande, sans décision.

    Ce que l'arbitre reçoit : des faits publics, un gagnant, un contrat, des
    preuves, l'hypothèse de besoin telle qu'elle serait montrée, l'ICP et son
    offre, le timing, le mode de production. Rien qui permette de deviner ce que
    le moteur a conclu.
    """
    selected = [need for need in run.needs.needs if need.category in set(match.matched_needs)]
    understanding = run.understanding
    return {
        "signal_id": snapshot["signal_id"],
        "source": snapshot["source"],
        "publication_date": snapshot["publication_date"],
        "source_url": snapshot["source_url"],
        "winner": snapshot["winner"],
        "contract": snapshot["contract"],
        "contract_understanding": {
            "contract_type": understanding.contract_type.value,
            "sector": understanding.sector.value,
            "object_summary": understanding.object_summary.value,
            "characteristics": [c.value for c in understanding.characteristics],
            "facts": {name: claim.value for name, claim in understanding.facts.items()},
            "buyer_country": understanding.geography.buyer_country,
            "place_of_performance": _place(understanding.geography.place_of_performance),
            "timing": understanding.timing.model_dump(mode="json"),
        },
        "derived_needs": [_need(need, blind=True) for need in selected],
        "icp": {
            "icp_id": icp.icp_id,
            "name": icp.name,
            "offer_summary": icp.offer_summary,
            "primary_need_categories": list(icp.primary_need_categories),
            "secondary_need_categories": list(icp.secondary_need_categories),
            "territories": [t.model_dump(mode="json") for t in icp.territories],
            "geography_basis": icp.geography_basis,
            "geography_policy": icp.geography_policy,
            "included_contract_types": list(icp.included_contract_types),
            "excluded_contract_types": list(icp.excluded_contract_types),
            "value_thresholds": [v.model_dump(mode="json") for v in icp.value_thresholds],
            "maximum_signal_age_days": icp.maximum_signal_age_days,
            "preferred_timings": list(icp.preferred_timings),
        },
        "evidence_refs": snapshot["evidence_refs"],
        "source_mode": snapshot["source_mode"],
        "disclosure": DOCUMENT_MODE_DISCLOSURE,
    }


# ─── Représentation textuelle déterministe (§49) ────────────────────────────────


def _winner_line(snapshot: dict[str, Any]) -> str:
    parties = snapshot["winner"]["parties"]
    if not parties:
        return "unknown"
    names = []
    for party in parties:
        label = party["name"] or " / ".join(m["legal_name"] for m in party["members"])
        countries = sorted({m["country"] for m in party["members"] if m["country"]})
        names.append(f"{label}" + (f" ({', '.join(countries)})" if countries else ""))
    return " ; ".join(names)


def _amount_line(snapshot: dict[str, Any]) -> str:
    value = snapshot["contract"]["value"]
    if not value:
        return "amount not published"
    return f"{value['amount']} {value['currency']}"


def render_signal_text(snapshot: dict[str, Any]) -> str:
    """La forme textuelle stable d'un signal (§49).

    Le vocabulaire reste hypothétique : « may become relevant », jamais « will
    buy » (§50). La limitation de mode documentaire est toujours présente (§51).
    """
    contract = snapshot["contract"]
    place = contract["place_of_performance"] or {}
    place_label = place.get("country") or "not published"
    needs = snapshot["selected_needs"]
    timing = snapshot["understanding"]["timing"]

    lines = [
        "Winner",
        f"  {_winner_line(snapshot)}",
        "",
        "Award",
        f"  {contract['title'] or contract['contract_reference'] or 'untitled'}",
        f"  published {snapshot['publication_date'] or 'unknown'} on {snapshot['source']}",
        f"  value {_amount_line(snapshot)} — place of performance {place_label}",
        "",
        "Why this matters",
        f"  {snapshot['understanding']['object_summary']['value']}",
        "",
        "Potential needs",
    ]
    for need in needs:
        lines.append(f"  - [{need['category']}] {need['statement']}")
        lines.append(f"    {need['reasoning']}")
    if not needs:
        lines.append("  - none selected")
    lines += [
        "",
        "Why it matches this ICP",
        f"  {snapshot['icp']['name']} — {snapshot['icp']['offer_summary']}",
    ]
    lines += [f"  - {reason}" for reason in snapshot["positive_reasons"]]
    lines += [
        "",
        "Timing",
        (
            f"  published {snapshot['publication_date'] or 'unknown'}"
            f" — contract start {timing.get('contract_start_date') or 'not published'}"
        ),
        "",
        "Confidence",
        f"  {snapshot['score']['confidence']}",
        "",
        "Proof",
    ]
    seen: set[str] = set()
    for evidence in snapshot["evidence_refs"]:
        ref = evidence.get("source_url") or evidence.get("source_notice_id") or ""
        label = f"  - {evidence['source_system']} {evidence.get('path') or ''} {ref}".rstrip()
        if label not in seen:
            seen.add(label)
            lines.append(label)
    if not seen:
        lines.append(f"  - {snapshot['source']} {snapshot['source_url'] or ''}".rstrip())
    lines += ["", "Limitations"]
    lines += [f"  - {limitation}" for limitation in snapshot["limitations"]]
    return "\n".join(lines)
