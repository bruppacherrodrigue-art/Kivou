"""Build immutable Card Intelligence inputs from current, tenant-owned rows.

This module is an offline read boundary.  It copies published facts and the
exact active ICP snapshot; it does not interpret administrative prose, infer a
buyer or winner, contact a provider, or publish an artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal, NoReturn, cast

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import (
    PresentationInput,
    SourceActor,
    SourceFacts,
    SourceTable,
    TargetIcpSnapshot,
)
from signals.card_intelligence.contracts import (
    source_field_ref as bound_source_field_ref,
)
from signals.persistence.schema import (
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)

_UNAVAILABLE = "presentation input unavailable"
_LOCATION_FIELDS = frozenset(
    {"country", "subdivision_code", "subdivision_scheme", "locality", "postal_code"}
)


class PresentationInputUnavailable(LookupError):
    """The requested current input cannot safely be assembled.

    Missing, foreign, stale, malformed, and insufficiently evidenced inputs use
    the same exception and message so this boundary cannot be used to enumerate
    another account's resources.
    """


def _unavailable() -> NoReturn:
    raise PresentationInputUnavailable(_UNAVAILABLE)


def _clean_text(value: object, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        _unavailable()
    cleaned = " ".join(value.split())
    if not cleaned:
        if required:
            _unavailable()
        return None
    return cleaned


def _source_actor(raw: Mapping[object, object]) -> SourceActor:
    display_name = _clean_text(raw.get("legal_name"), required=True)
    assert display_name is not None
    try:
        canonical = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _unavailable()
    return SourceActor(
        actor_ref=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        display_name=display_name,
    )


def _deduplicated_actors(
    organizations: list[Mapping[object, object]], *, required: bool
) -> tuple[SourceActor, ...]:
    actors: list[SourceActor] = []
    seen: set[str] = set()
    for organization in organizations:
        actor = _source_actor(organization)
        if actor.actor_ref in seen:
            continue
        seen.add(actor.actor_ref)
        actors.append(actor)
        if len(actors) > 16:
            _unavailable()
    if required and not actors:
        _unavailable()
    return tuple(actors)


def _buyers(raw: object) -> tuple[SourceActor, ...]:
    if not isinstance(raw, list):
        _unavailable()
    organizations: list[Mapping[object, object]] = []
    for organization in raw:
        if not isinstance(organization, Mapping):
            _unavailable()
        organizations.append(organization)
    return _deduplicated_actors(organizations, required=False)


def _awardees(raw: object) -> tuple[SourceActor, ...]:
    if not isinstance(raw, list):
        _unavailable()
    organizations: list[Mapping[object, object]] = []
    for party in raw:
        if not isinstance(party, Mapping):
            _unavailable()
        members = party.get("members")
        if not isinstance(members, list) or not members:
            _unavailable()
        for member in members:
            if not isinstance(member, Mapping):
                _unavailable()
            organization = member.get("organization")
            if not isinstance(organization, Mapping):
                _unavailable()
            organizations.append(organization)
    return _deduplicated_actors(organizations, required=True)


def _location_label(raw: object) -> str | None:
    """Render only whitelisted structured location values, never free prose."""

    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) - _LOCATION_FIELDS:
        _unavailable()

    values: list[str] = []
    for field in ("locality", "postal_code", "subdivision_code", "country"):
        value = raw.get(field)
        if value is None:
            continue
        cleaned = _clean_text(value, required=True)
        assert cleaned is not None
        if cleaned not in values:
            values.append(cleaned)
    if not values:
        _unavailable()
    label = ", ".join(values)
    if len(label) > 512:
        _unavailable()
    return label


_INPUT_SELECT = (
    sa.select(
        target_icp.c.account_id.label("owned_account_id"),
        target_icp.c.target_icp_id.label("owned_target_icp_id"),
        target_icp.c.label.label("target_icp_label"),
        target_icp.c.matching_revision.label("matching_revision"),
        target_icp.c.customer_input.label("target_icp_customer_input"),
        materialized_signal.c.signal_key.label("owned_signal_key"),
        materialized_signal.c.revision.label("signal_revision"),
        materialized_signal.c.icp_matched_needs.label("icp_matched_needs"),
        contract_award.c.award_key.label("source_award_key"),
        contract_award.c.awardee_parties.label("source_awardees"),
        contract_award.c.title.label("source_award_title"),
        contract_award.c.amount.label("source_amount"),
        contract_award.c.currency.label("source_currency"),
        contract_award.c.place_of_performance.label("source_location"),
        contract_award.c.award_date.label("source_award_date"),
        contract_award.c.contract_notification_date.label("source_notification_date"),
        source_event.c.source_system.label("source_system"),
        source_event.c.event_key.label("source_event_key"),
        source_event.c.source_notice_id.label("source_notice_id"),
        source_event.c.published_on.label("source_publication_date"),
        source_event.c.procedure_buyers.label("source_buyers"),
    )
    .select_from(
        target_icp.join(
            materialized_signal,
            target_icp.c.target_icp_id == materialized_signal.c.target_icp_id,
        )
        .join(
            contract_award,
            materialized_signal.c.materialization_award_key == contract_award.c.award_key,
        )
        .join(source_event, contract_award.c.event_key == source_event.c.event_key)
    )
    .where(
        target_icp.c.account_id == sa.bindparam("owned_account_id"),
        materialized_signal.c.signal_key == sa.bindparam("owned_signal_key"),
        target_icp.c.status == "active",
        target_icp.c.plan_limit_code.is_(None),
        materialized_signal.c.invalidated_at.is_(None),
        materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
        contract_award.c.winner_status == "identified",
    )
)


def _source_binding(row_key: object) -> str:
    """Hash the exact UTF-8 bytes of a persisted key, without normalization."""

    if not isinstance(row_key, str):
        _unavailable()
    return hashlib.sha256(row_key.encode("utf-8")).hexdigest()


def _source_field_ref(*, table: str, row_key: object, column: str) -> str:
    """Versioned exact-row pointer with a closed table/column grammar."""

    try:
        return bound_source_field_ref(
            table=cast(SourceTable, table),
            binding=_source_binding(row_key),
            column=column,
        )
    except ValueError:
        _unavailable()


def _evidence_refs(
    connection: sa.Connection,
    *,
    award_key: str,
    event_key: str,
) -> tuple[str, ...]:
    """Return exact field pointers after gating on persisted award evidence."""

    field_refs = (
        _source_field_ref(table="contract_award", row_key=award_key, column="awardee_parties"),
        _source_field_ref(table="source_event", row_key=event_key, column="procedure_buyers"),
        _source_field_ref(table="contract_award", row_key=award_key, column="amount"),
        _source_field_ref(table="contract_award", row_key=award_key, column="currency"),
        _source_field_ref(table="contract_award", row_key=award_key, column="place_of_performance"),
        _source_field_ref(table="contract_award", row_key=award_key, column="award_date"),
        _source_field_ref(
            table="contract_award",
            row_key=award_key,
            column="contract_notification_date",
        ),
        _source_field_ref(table="source_event", row_key=event_key, column="published_on"),
    )
    gate = connection.execute(
        sa.select(sa.literal(1))
        .select_from(evidence)
        .where(
            evidence.c.award_key == award_key,
            evidence.c.anchors_kind == "award_fact",
        )
        .limit(1)
    ).first()
    if gate is None:
        _unavailable()
    return field_refs


def _ensure_complete_icp(snapshot: TargetIcpSnapshot) -> None:
    incomplete = (
        not snapshot.offers
        or not snapshot.territories
        or snapshot.minimum_contract_value is None
        or bool(snapshot.secondary_buyer_trades and not snapshot.buyer_trades)
    )
    if incomplete:
        _unavailable()


def build_presentation_input(
    connection: sa.Connection,
    *,
    account_id: str,
    signal_key: str,
    language: Literal["fr", "en"],
) -> PresentationInput:
    """Copy one current tenant-owned signal into the strict offline contract.

    Ownership, active status, plan eligibility, non-invalidation, and the exact
    matching revision are all predicates of the database read.  A caller never
    receives a partially assembled or stale input.
    """

    if language not in ("fr", "en"):
        _unavailable()
    try:
        row = connection.execute(
            _INPUT_SELECT,
            {"owned_account_id": account_id, "owned_signal_key": signal_key},
        ).one_or_none()
    except sa.exc.SQLAlchemyError:
        raise
    except json.JSONDecodeError:
        _unavailable()
    except (TypeError, ValueError):
        _unavailable()
    if row is None:
        _unavailable()

    try:
        snapshot = TargetIcpSnapshot.from_json_value(row.target_icp_customer_input)
        _ensure_complete_icp(snapshot)
        matched_needs_raw = row.icp_matched_needs
        if not isinstance(matched_needs_raw, list):
            _unavailable()
        award_binding = _source_binding(row.source_award_key)
        event_binding = _source_binding(row.source_event_key)
        facts = SourceFacts(
            source_award_binding=award_binding,
            source_event_binding=event_binding,
            awardees=_awardees(row.source_awardees),
            buyers=_buyers(row.source_buyers),
            award_title=_clean_text(row.source_award_title),
            amount=(Decimal(str(row.source_amount)) if row.source_amount is not None else None),
            currency=_clean_text(row.source_currency),
            location=_location_label(row.source_location),
            award_date=row.source_award_date,
            contract_notification_date=row.source_notification_date,
            publication_date=row.source_publication_date,
            source_system=_clean_text(row.source_system, required=True),
            source_notice_id=_clean_text(row.source_notice_id, required=True),
            evidence_refs=_evidence_refs(
                connection,
                award_key=row.source_award_key,
                event_key=row.source_event_key,
            ),
        )
        return PresentationInput(
            account_id=row.owned_account_id,
            signal_key=row.owned_signal_key,
            signal_revision=row.signal_revision,
            target_icp_id=row.owned_target_icp_id,
            target_icp_revision=row.matching_revision,
            language=language,
            target_icp_label=row.target_icp_label,
            target_icp_customer_input=snapshot,
            icp_matched_needs=tuple(matched_needs_raw),
            facts=facts,
        )
    except PresentationInputUnavailable:
        raise
    except (InvalidOperation, KeyError, TypeError, ValueError):
        _unavailable()


__all__ = ["PresentationInputUnavailable", "build_presentation_input"]
