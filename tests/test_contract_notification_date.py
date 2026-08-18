"""SPEC-009E R1 §2 — les quatre dates contractuelles restent distinctes."""

from __future__ import annotations

import datetime as dt

from signals.domain.awards import ContractAward
from signals.domain.events import EventRef

REF = EventRef(source_system="decp", source_notice_id="2026T06966")


def award(**kwargs) -> ContractAward:
    return ContractAward(event_ref=REF, winner_status="undisclosed", **kwargs)


def test_a_contract_carries_a_notification_date_distinct_from_every_other_date():
    got = award(
        award_date=dt.date(2026, 7, 1),
        contract_signature_date=dt.date(2026, 7, 20),
        contract_notification_date=dt.date(2026, 7, 25),
        contract_start_date=dt.date(2026, 8, 1),
    )
    assert got.award_date == dt.date(2026, 7, 1)
    assert got.contract_signature_date == dt.date(2026, 7, 20)
    assert got.contract_notification_date == dt.date(2026, 7, 25)
    assert got.contract_start_date == dt.date(2026, 8, 1)


def test_the_notification_date_defaults_to_absent_like_every_other_date():
    assert award().contract_notification_date is None


def test_a_notification_date_alone_never_implies_an_award_date():
    """§2 — la notification est un acte du contrat, pas la décision qui l'a précédé."""
    got = award(contract_notification_date=dt.date(2026, 8, 17))
    assert got.award_date is None
    assert got.contract_signature_date is None
