from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.acquisition_runtime.catalog_selection import select_assisted_catalog_signals
from signals.companies.schema import saas_company
from signals.persistence.schema import (
    METADATA,
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.supplier_discovery.families import supplier_family_keys

NOW = dt.datetime(2026, 9, 18, 9, tzinfo=dt.UTC)
TODAY = NOW.date()


def _engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'catalog-selection.sqlite'}",
        future=True,
    )
    METADATA.create_all(
        engine,
        tables=[
            source_event,
            contract_award,
            materialized_signal,
            for_you_sentence,
            target_icp,
            opportunity_representation,
            saas_company,
        ],
    )
    return engine


def _seed_notice(
    engine: sa.Engine,
    *,
    key: str,
    title: str,
    vertical: str,
    opportunity_key: str | None = None,
    subdivision: str = "FR-38",
    decision_date: dt.date = TODAY,
    official_holder: bool = True,
    official_holder_identifier: bool = True,
    materialize: bool = True,
    award_date: dt.date | None = None,
) -> None:
    opportunity_key = opportunity_key or key
    fingerprint = (key.replace("-", "") + "0" * 64)[:64]
    with engine.begin() as connection:
        if connection.scalar(
            sa.select(sa.func.count()).select_from(target_icp)
        ) == 0:
            connection.execute(
                sa.insert(target_icp).values(
                    target_icp_id="icp-catalog",
                    account_id="account-catalog",
                    label="Catalogue AURA",
                    status="active",
                    matching_revision=1,
                    customer_input={},
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        connection.execute(
            sa.insert(source_event).values(
                event_key=f"event-{key}",
                source_system="boamp",
                source_notice_id=f"notice-{key}",
                source_country="FR",
                event_type="award_notice",
                published_on=decision_date,
                source_url=f"https://www.boamp.fr/avis/{key}",
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key=f"award-{key}",
                event_key=f"event-{key}",
                title=title,
                award_date=award_date,
                contract_notification_date=decision_date,
                amount=100_000,
                currency="EUR",
                winner_status="identified",
                awardee_parties=[
                    {
                        "name": f"TITULAIRE {key.upper()}",
                        "members": [
                            {
                                "organization": {
                                    "legal_name": f"TITULAIRE {key.upper()}",
                                    "identifiers": [
                                        {
                                            "scheme": "SIRET",
                                            "value": "44005586100010",
                                        }
                                    ],
                                    "country": "FR",
                                    "address": None,
                                    "website": None,
                                },
                                "role": "sole",
                            }
                        ],
                    }
                ],
                contract_signatories=[],
                cpv_additional=[],
                place_of_performance={
                    "country": "FR",
                    "subdivision_code": subdivision,
                    "subdivision_scheme": "ISO-3166-2",
                },
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key=f"award-{key}",
                opportunity_key=opportunity_key,
                created_at=NOW,
            )
        )
        if not materialize:
            return
        connection.execute(
            sa.insert(materialized_signal).values(
                signal_key=f"signal-{key}",
                opportunity_key=opportunity_key,
                materialization_award_key=f"award-{key}",
                target_icp_id="icp-catalog",
                target_icp_revision=1,
                revision=1,
                content_fingerprint=fingerprint,
                materialized_recency_status="recent_award",
                materialized_award_clock_status="known",
                materialized_notification_clock_status="known",
                materialized_publication_clock_status="known",
                materialized_as_of=decision_date,
                recency_policy_version="test-v1",
                winner_name="44005586100010",
                winner_country="FR",
                winner_identifier_scheme="SIRET",
                winner_identifier_value="44005586100010",
                company_identity_fingerprint=fingerprint,
                inferred_trade_domain=vertical,
                plausible_needs=[],
                icp_matched_needs=[],
                engine_versions={},
                materialized_at=NOW,
                created_at=NOW,
            )
        )
        if official_holder:
            connection.execute(
                sa.insert(saas_company).values(
                    company_key=f"company-{key}",
                    identity_fingerprint=fingerprint,
                    identity_method="official_identifier",
                    identity_validation={},
                    source_award_key=f"award-{key}",
                    origin_signal_key=f"signal-{key}",
                    official_name=f"TITULAIRE {key.upper()}",
                    official_country="FR",
                    official_identifiers=(
                        [{"scheme": "SIRET", "value": "44005586100010"}]
                        if official_holder_identifier
                        else []
                    ),
                    official_source="official_register",
                    official_observed_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def test_catalog_selection_keeps_only_exact_family_notices_with_official_holders(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _seed_notice(
        engine,
        key="opp-electrical",
        title="Électricité courants forts et courants faibles",
        vertical="technical_installation",
    )
    _seed_notice(
        engine,
        key="opp-timber-roofing",
        title="Charpente bois et couverture",
        vertical="special_civil",
    )
    _seed_notice(
        engine,
        key="opp-insulation-no-holder",
        title="Isolation thermique",
        vertical="technical_installation",
        official_holder=False,
    )
    _seed_notice(
        engine,
        key="opp-insulation-holder-without-siren",
        title="Isolation de bâtiments publics",
        vertical="technical_installation",
        official_holder_identifier=False,
    )
    _seed_notice(
        engine,
        key="opp-electrical-outside",
        title="Électricité d'un bâtiment public",
        vertical="technical_installation",
        subdivision="FR-75",
    )
    _seed_notice(
        engine,
        key="opp-electrical-stale",
        title="Électricité d'un bâtiment ancien",
        vertical="technical_installation",
        decision_date=NOW.date() - dt.timedelta(days=31),
    )

    inventory = select_assisted_catalog_signals(
        engine,
        country="FR",
        region="Auvergne-Rhône-Alpes",
        observed_at=NOW,
    )

    assert set(inventory) == set(supplier_family_keys())
    assert [
        notice.signal.opportunity_key
        for notice in inventory["electrical"].notices
    ] == ["opp-electrical"]
    assert inventory["timber_carpentry"].notices == ()
    assert inventory["timber_carpentry"].zero_reason == "no_mono_avis"
    assert inventory["roofing"].notices == ()
    assert inventory["insulation"].notices == ()
    assert inventory["insulation"].zero_reason == "no_official_holder"


def test_catalog_selection_does_not_consult_runtime_cycles(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed_notice(
        engine,
        key="opp-electrical",
        title="Électricité courants forts",
        vertical="technical_installation",
    )

    first = select_assisted_catalog_signals(
        engine,
        country="FR",
        region="Auvergne-Rhône-Alpes",
        observed_at=NOW,
    )
    second = select_assisted_catalog_signals(
        engine,
        country="FR",
        region="Auvergne-Rhône-Alpes",
        observed_at=NOW,
    )

    assert first == second


def test_catalog_selection_binds_eligibility_rendering_and_holder_to_exact_award(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _seed_notice(
        engine,
        key="eligible-aura",
        opportunity_key="opp-shared",
        title="Électricité du collège actuel",
        vertical="technical_installation",
        subdivision="FR-38",
        decision_date=TODAY,
    )
    # This second representation is deliberately more complete, but ineligible:
    # it is in Paris and its decision lies in the future.  Catalog selection must
    # never admit the AURA award and then render this other representation.
    _seed_notice(
        engine,
        key="future-paris",
        opportunity_key="opp-shared",
        title="Électricité du siège parisien futur",
        vertical="technical_installation",
        subdivision="FR-75",
        decision_date=TODAY + dt.timedelta(days=10),
        award_date=TODAY + dt.timedelta(days=10),
        official_holder=False,
        materialize=False,
    )

    inventory = select_assisted_catalog_signals(
        engine,
        country="FR",
        region="Auvergne-Rhône-Alpes",
        observed_at=NOW,
    )

    notices = inventory["electrical"].notices
    assert len(notices) == 1
    assert notices[0].award_key == "award-eligible-aura"
    assert notices[0].signal.opportunity_key == "opp-shared"
    assert notices[0].signal.subject == "Électricité du collège actuel"
    assert notices[0].signal.source_url == "https://www.boamp.fr/avis/eligible-aura"
    assert notices[0].signal.decision_date == TODAY


def test_catalog_selection_rejects_a_holder_from_another_award_representation(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _seed_notice(
        engine,
        key="eligible-source",
        opportunity_key="opp-holder-source",
        title="Électricité de l'école",
        vertical="technical_installation",
    )
    _seed_notice(
        engine,
        key="other-source",
        opportunity_key="opp-holder-source",
        title="Électricité autre représentation",
        vertical="technical_installation",
        materialize=False,
        official_holder=False,
    )
    with engine.begin() as connection:
        connection.execute(
            sa.update(saas_company)
            .where(saas_company.c.company_key == "company-eligible-source")
            .values(source_award_key="award-other-source")
        )

    inventory = select_assisted_catalog_signals(
        engine,
        country="FR",
        region="Auvergne-Rhône-Alpes",
        observed_at=NOW,
    )

    assert inventory["electrical"].notices == ()
    assert inventory["electrical"].mono_notice_count == 1
    assert inventory["electrical"].missing_official_holder_count == 1
    assert inventory["electrical"].zero_reason == "no_official_holder"
