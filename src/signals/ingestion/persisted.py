"""Reconstruct approved canonical source models from persisted fact rows."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent
from signals.persistence.schema import contract_award, source_event


def _value(row: sa.Row, column: sa.Column) -> Any:
    return row._mapping[column]


def _published(raw: str | None, precision: str | None) -> dt.date | dt.datetime | None:
    if raw is None:
        return None
    return dt.date.fromisoformat(raw) if precision == "date" else dt.datetime.fromisoformat(raw)


def canonical_event(row: sa.Row) -> PublicEvent:
    """Rehydrate a public event without changing any persisted source clock."""
    return PublicEvent.model_validate(
        {
            "provenance": {
                "source_system": _value(row, source_event.c.source_system),
                "source_country": _value(row, source_event.c.source_country),
                "source_notice_id": _value(row, source_event.c.source_notice_id),
                "notice_version": _value(row, source_event.c.notice_version),
                "source_procedure_id": _value(row, source_event.c.source_procedure_id),
                "source_url": _value(row, source_event.c.source_url),
                "retrieved_at": _value(row, source_event.c.discovered_at),
            },
            "event_type": _value(row, source_event.c.event_type),
            "published_at": _published(
                _value(row, source_event.c.published_at_raw),
                _value(row, source_event.c.published_precision),
            ),
            "procedure_buyers": _value(row, source_event.c.procedure_buyers),
            "source_notice_links": _value(row, source_event.c.source_notice_links),
        }
    )


def canonical_award(row: sa.Row, event: PublicEvent) -> ContractAward:
    """Rehydrate an award from source facts, preserving every available field."""
    lot_identifier = _value(row, contract_award.c.lot_identifier)
    amount = _value(row, contract_award.c.amount)
    duration_value = _value(row, contract_award.c.duration_value)
    return ContractAward.model_validate(
        {
            "event_ref": event.ref(),
            "source_award_id": _value(row, contract_award.c.source_award_id),
            "lot": (
                {
                    "identifier": lot_identifier,
                    "title": _value(row, contract_award.c.lot_title),
                }
                if lot_identifier
                else None
            ),
            "contract_reference": _value(row, contract_award.c.contract_reference),
            "title": _value(row, contract_award.c.title),
            "description": _value(row, contract_award.c.description),
            "cpv_main": (
                {
                    "code": _value(row, contract_award.c.cpv_main),
                    "check_digit": _value(row, contract_award.c.cpv_check_digit),
                }
                if _value(row, contract_award.c.cpv_main)
                else None
            ),
            "cpv_additional": _value(row, contract_award.c.cpv_additional),
            "value": (
                {
                    "amount": Decimal(str(amount)),
                    "currency": _value(row, contract_award.c.currency),
                    "vat_category": _value(row, contract_award.c.vat_category),
                }
                if amount is not None
                else None
            ),
            "winner_status": _value(row, contract_award.c.winner_status),
            "awardee_parties": _value(row, contract_award.c.awardee_parties),
            "contract_signatories": _value(row, contract_award.c.contract_signatories),
            "place_of_performance": _value(row, contract_award.c.place_of_performance),
            "award_date": _value(row, contract_award.c.award_date),
            "contract_signature_date": _value(row, contract_award.c.contract_signature_date),
            "contract_notification_date": _value(
                row, contract_award.c.contract_notification_date
            ),
            "contract_start_date": _value(row, contract_award.c.contract_start_date),
            "contract_end_date": _value(row, contract_award.c.contract_end_date),
            "duration": (
                {
                    "value": duration_value,
                    "unit": _value(row, contract_award.c.duration_unit),
                }
                if duration_value is not None
                else None
            ),
        }
    )
