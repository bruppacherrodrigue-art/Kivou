from __future__ import annotations

import datetime as dt
import inspect

import pytest

from signals.phase_a_btp.contracts import (
    AwardSnapshot,
    EnrichmentLevel,
    Location,
)
from signals.phase_a_btp.eligibility import evaluate
from signals.phase_a_btp.reading import build_showcase_signal
from signals.phase_a_btp.report import build_report
from signals.phase_a_btp.selection import select_showcase
from signals.phase_a_btp.siret_resolution import (
    CompanyIdentity,
    CompanyIdentityIndex,
    ResolutionStatus,
    prepare_resolution_batch,
)

AS_OF = dt.date(2026, 9, 2)


def award(**changes: object) -> AwardSnapshot:
    values: dict[str, object] = {
        "opportunity_key": "opp_test",
        "signal_key": "sig_test",
        "award_key": "award_test",
        "awardee_name": "Entreprise Exemple",
        "awardee_siret": "12345678901234",
        "buyer_name": "Acheteur public",
        "title": "Lot 4 : couverture, étanchéité et bardage du pôle logistique",
        "lot_title": "Couverture, étanchéité et bardage",
        "description": "Pose de la couverture et du bardage du pôle logistique.",
        "cpv_main": "45260000",
        "cpv_additional": (),
        "amount": "834262.00",
        "currency": "EUR",
        "location": Location(country="FR", locality="Grenoble", subdivision_code="FRK24"),
        "event_date": AS_OF - dt.timedelta(days=20),
        "award_date": AS_OF - dt.timedelta(days=20),
        "notification_date": None,
        "publication_date": AS_OF - dt.timedelta(days=10),
        "contract_start_date": None,
        "contract_end_date": None,
        "duration_value": 16,
        "duration_unit": "month",
        "source_system": "ted",
        "source_country": "FR",
        "source_notice_id": "notice-1",
        "source_url": "https://ted.europa.eu/example",
        "dce_document_ids": (),
        "target_profile_label": "Intrants de chantier — France",
        "target_offer_summary": "Fourniture de matériaux et composants pour chantiers",
        "target_offers": ("materials_and_components",),
        "trade_domain": "general_building",
    }
    values.update(changes)
    return AwardSnapshot.model_validate(values)


def test_visible_without_dce_when_source_facts_are_specific() -> None:
    result = evaluate(award(), as_of=AS_OF)

    assert result.visible_dashboard is True
    assert result.outbound_ready is True
    assert result.enrichment_level is EnrichmentLevel.OFFICIAL_SOURCE
    assert result.operational_elements


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"awardee_name": None}, "awardee_name_missing"),
        ({"title": None, "lot_title": None, "description": None}, "object_not_specific"),
        ({"event_date": AS_OF - dt.timedelta(days=731)}, "dashboard_too_old"),
        ({"location": Location(country="FR")}, "execution_place_not_precise"),
        ({"source_url": None}, "official_link_missing"),
    ],
)
def test_each_mandatory_dashboard_gate_fails_closed(
    changes: dict[str, object], reason: str
) -> None:
    result = evaluate(award(**changes), as_of=AS_OF)

    assert result.visible_dashboard is False
    assert reason in result.reasons


def test_siret_is_recoverable_but_not_a_clear_company_name() -> None:
    result = evaluate(award(awardee_name="12345678901234"), as_of=AS_OF)

    assert result.visible_dashboard is False
    assert result.recoverable_siret is True
    assert "awardee_name_missing" in result.reasons


@pytest.mark.parametrize("title", ["Travaux de construction", "Rénovation de bâtiment"])
def test_generic_object_remains_insufficient(title: str) -> None:
    result = evaluate(
        award(
            title=title,
            lot_title=None,
            description=None,
            cpv_main="45210000",
            amount="500000.00",
            duration_value=None,
        ),
        as_of=AS_OF,
    )

    assert result.visible_dashboard is False
    assert "object_not_specific" in result.reasons


def test_amount_and_detailed_cpv_without_operational_fact_are_insufficient() -> None:
    result = evaluate(
        award(
            title="Programme immobilier public tranche annuelle",
            lot_title=None,
            description=None,
            location=Location(country="FR"),
            duration_value=None,
            contract_start_date=None,
            contract_end_date=None,
        ),
        as_of=AS_OF,
    )

    assert result.visible_dashboard is False
    assert "execution_place_not_precise" in result.reasons
    assert "operational_element_missing" in result.reasons


@pytest.mark.parametrize(
    ("age_days", "ready", "bucket"),
    [
        (0, True, "0_90_days"),
        (90, True, "0_90_days"),
        (91, True, "91_180_days"),
        (180, True, "91_180_days"),
        (181, False, "181_365_days"),
        (365, False, "181_365_days"),
        (366, False, "over_one_year"),
    ],
)
def test_outbound_freshness_boundaries(age_days: int, ready: bool, bucket: str) -> None:
    result = evaluate(
        award(
            event_date=AS_OF - dt.timedelta(days=age_days),
            duration_value=None,
            contract_start_date=None,
            contract_end_date=None,
        ),
        as_of=AS_OF,
    )

    assert result.freshness_bucket.value == bucket
    assert result.outbound_ready is ready


def test_old_award_is_outbound_ready_only_while_published_execution_is_ongoing() -> None:
    ongoing = evaluate(
        award(event_date=AS_OF - dt.timedelta(days=400), duration_value=24),
        as_of=AS_OF,
    )
    ended = evaluate(
        award(
            event_date=AS_OF - dt.timedelta(days=400),
            duration_value=None,
            contract_end_date=AS_OF - dt.timedelta(days=1),
        ),
        as_of=AS_OF,
    )

    assert ongoing.outbound_ready is True
    assert ongoing.execution_probably_ongoing is True
    assert ended.outbound_ready is False
    assert ended.outbound_reason == "published_execution_not_ongoing"


def test_dce_enriches_but_never_gates_visibility() -> None:
    source_only = evaluate(award(), as_of=AS_OF)
    enriched = evaluate(award(dce_document_ids=("dce-1",)), as_of=AS_OF)

    assert source_only.visible_dashboard is enriched.visible_dashboard is True
    assert enriched.enrichment_level is EnrichmentLevel.DCE_ANALYZED


def test_commercial_reading_separates_honest_specific_needs_from_facts() -> None:
    signal = build_showcase_signal(award(), as_of=AS_OF)

    assert signal.potential_needs_title == "Besoins potentiels à qualifier"
    assert 1 <= len(signal.potential_needs) <= 3
    assert signal.official_facts.awardee == "Entreprise Exemple"
    assert signal.official_facts.source_url == "https://ted.europa.eu/example"
    for need in signal.potential_needs:
        assert "pourrait" in need.statement
        assert need.based_on in signal.operational_elements
        assert need.statement.casefold() not in {
            "matériaux et composants",
            "équipements nécessaires au chantier",
            "contacter le service achats",
        }


def test_reading_uses_only_functional_roles_and_limits_unknowns() -> None:
    signal = build_showcase_signal(
        award(contract_start_date=None, contract_end_date=None, dce_document_ids=()),
        as_of=AS_OF,
    )

    assert 1 <= len(signal.contact_roles) <= 3
    assert all("@" not in role and not any(char.isdigit() for char in role) for role in signal.contact_roles)
    assert len(signal.to_qualify) <= 3
    assert signal.recommended_action.startswith("Qualifier")


def test_reading_refuses_an_insufficient_award() -> None:
    with pytest.raises(ValueError, match="visible"):
        build_showcase_signal(award(awardee_name="12345678901234"), as_of=AS_OF)


def test_selection_diversifies_specialties_and_caps_each_awardee() -> None:
    specialties = (
        "general_building",
        "roadworks_civil",
        "technical_installation",
        "interior_finishing",
        "earthworks_demolition",
    )
    candidates = []
    for index in range(15):
        specialty = specialties[index % len(specialties)]
        candidates.append(
            build_showcase_signal(
                award(
                    opportunity_key=f"opp_{index}",
                    signal_key=f"sig_{index}",
                    award_key=f"award_{index}",
                    awardee_name="Entreprise répétée" if index < 6 else f"Entreprise {index}",
                    event_date=AS_OF - dt.timedelta(days=index),
                    award_date=AS_OF - dt.timedelta(days=index),
                    source_notice_id=f"notice-{index}",
                    trade_domain=specialty,
                ),
                as_of=AS_OF,
            )
        )

    selected = select_showcase(candidates, limit=10)

    assert len(selected) == 10
    assert len({item.opportunity_key for item in selected}) == 10
    assert sum(item.official_facts.awardee == "Entreprise répétée" for item in selected) <= 2
    assert len({item.specialty for item in selected}) >= 5


def test_selection_keeps_newest_signal_first_inside_each_specialty() -> None:
    newer = build_showcase_signal(
        award(
            opportunity_key="new",
            signal_key="new",
            award_key="new",
            source_notice_id="new",
        ),
        as_of=AS_OF,
    )
    older = build_showcase_signal(
        award(
            opportunity_key="old",
            signal_key="old",
            award_key="old",
            event_date=AS_OF - dt.timedelta(days=100),
            duration_value=None,
            source_notice_id="old",
        ),
        as_of=AS_OF,
    )

    selected = select_showcase([older, newer], limit=2)

    assert [item.opportunity_key for item in selected] == ["new", "old"]


def test_selection_avoids_multiple_lots_from_the_same_notice() -> None:
    same_market = [
        build_showcase_signal(
            award(
                opportunity_key=f"same_{index}",
                signal_key=f"same_{index}",
                award_key=f"same_{index}",
                source_notice_id="one-market",
            ),
            as_of=AS_OF,
        )
        for index in range(3)
    ]
    other = build_showcase_signal(
        award(
            opportunity_key="other",
            signal_key="other",
            award_key="other",
            source_notice_id="other-market",
        ),
        as_of=AS_OF,
    )

    selected = select_showcase([*same_market, other], limit=10)

    assert len([item for item in selected if item.official_facts.source_notice_id == "one-market"]) == 1


def test_report_counts_unique_btp_freshness_outbound_siret_and_dce() -> None:
    rows = [
        award(
            opportunity_key=f"opp_{index}",
            signal_key=f"sig_{index}",
            award_key=f"award_{index}",
            awardee_name=f"Entreprise {index}",
            event_date=AS_OF - dt.timedelta(days=age),
            award_date=AS_OF - dt.timedelta(days=age),
            duration_value=None if age > 180 else 12,
            dce_document_ids=("dce-one",) if index == 0 else (),
            source_notice_id=f"notice-{index}",
            trade_domain=("general_building", "roadworks_civil")[index % 2],
        )
        for index, age in enumerate((10, 100, 200, 500, 20, 30, 40, 50, 60, 70))
    ]
    rows.extend(
        [
            award(
                opportunity_key="recoverable",
                signal_key="recoverable",
                award_key="recoverable",
                awardee_name="12345678901234",
                awardee_siret="12345678901234",
                source_notice_id="recoverable",
            ),
            award(
                opportunity_key="outside",
                signal_key="outside",
                award_key="outside",
                cpv_main="72000000",
                source_notice_id="outside",
            ),
        ]
    )

    report = build_report(rows, as_of=AS_OF)

    assert report.corpus_total == 12
    assert report.btp_total == 11
    assert report.exploitable_total == 10
    assert report.insufficient_total == 1
    assert report.siret_recovery_candidates == 1
    assert report.dce_available == 1
    assert report.freshness.days_0_90 == 7
    assert report.freshness.days_91_180 == 1
    assert report.freshness.days_181_365 == 1
    assert report.freshness.over_one_year == 1
    assert report.outbound_ready_total == 8
    assert len(report.showcase) == 10


def test_siret_resolution_uses_existing_kivou_identity_then_reevaluates() -> None:
    reevaluated: list[AwardSnapshot] = []
    source = award(awardee_name="12345678901234", awardee_siret="12345678901234")
    index = CompanyIdentityIndex(
        identities=(
            CompanyIdentity(
                siret="12345678901234",
                legal_name="Entreprise Résolue",
                company_key="cmp_existing",
            ),
        )
    )

    outcomes = prepare_resolution_batch([source], index=index, reevaluate=reevaluated.append)

    assert outcomes[0].status is ResolutionStatus.RESOLVED_EXISTING
    assert outcomes[0].legal_name == "Entreprise Résolue"
    assert reevaluated[0].awardee_name == "Entreprise Résolue"


def test_unresolved_siret_becomes_official_source_queue_work_without_network() -> None:
    reevaluated: list[AwardSnapshot] = []
    source = award(awardee_name="12345678901234", awardee_siret="12345678901234")

    outcomes = prepare_resolution_batch(
        [source], index=CompanyIdentityIndex(identities=()), reevaluate=reevaluated.append
    )

    assert outcomes[0].status is ResolutionStatus.QUEUED_OFFICIAL_SOURCE
    assert outcomes[0].job is not None
    assert outcomes[0].job.siret == "12345678901234"
    assert reevaluated == []

    import signals.phase_a_btp.siret_resolution as module

    source_code = inspect.getsource(module)
    assert "requests" not in source_code
    assert "httpx" not in source_code
    assert "urlopen" not in source_code
