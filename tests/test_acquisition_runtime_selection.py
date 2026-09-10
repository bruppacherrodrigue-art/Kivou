# tests/test_acquisition_runtime_selection.py
from __future__ import annotations

import datetime as dt

import httpx
import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.acquisition_runtime.selection import (
    resolved_holder_name_for_opportunity,
    select_production_opportunity_key,
    unresolved_dynamic_holder_signal_keys,
)
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.companies.france import FrenchOfficialCompanyClient
from signals.companies.schema import saas_company, winner_enrichment_job
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    source_event,
)

NOW = dt.datetime(2026, 8, 31, 12, tzinfo=dt.UTC)


def _engine(tmp_path) -> sa.Engine:
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'selection.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
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
            acquisition_runtime_cycle,
            saas_company,
            winner_enrichment_job,
        ],
    )
    return engine


def _seed(engine, *, key: str, country: str, published_on: dt.date) -> None:
    """Insère une opportunité minimale : un événement, un award, une représentation."""

    with engine.begin() as connection:
        connection.execute(
            sa.insert(source_event).values(
                event_key=f"event-{key}",
                source_system="BOAMP",
                source_notice_id=f"notice-{key}",
                source_country=country,
                event_type="AWARD",
                published_on=published_on,
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key=f"award-{key}",
                event_key=f"event-{key}",
                cpv_additional=[],
                winner_status="undisclosed",
                awardee_parties=[],
                contract_signatories=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key=f"award-{key}", opportunity_key=key, created_at=NOW
            )
        )


_TERMINAL_STATUSES = ("SUCCEEDED", "SUPPRESSED")


def _seed_cycle(
    engine, *, opportunity_key: str, status: str, updated_at: dt.datetime = NOW
) -> None:
    """Insère un cycle. `completed_at` suit la contrainte CHECK du cycle de vie
    (schema.py:2327-2331) : posé seulement pour un statut terminal, sinon NULL.
    """

    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_cycle).values(
                cycle_ref=f"cycle-{opportunity_key}",
                opportunity_key=opportunity_key,
                config_fingerprint="f" * 64,
                status=status,
                spent_cost=0,
                started_at=NOW,
                updated_at=updated_at,
                completed_at=NOW if status in _TERMINAL_STATUSES else None,
            )
        )


def _seed_dynamic_siret_holder(engine, *, resolved_name: str | None) -> None:
    identity_fingerprint = "d" * 64
    with engine.begin() as connection:
        connection.execute(
            sa.insert(target_icp).values(
                target_icp_id="icp-dynamic",
                account_id="account-dynamic",
                label="Bâtiment AURA",
                status="active",
                matching_revision=1,
                customer_input={},
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(source_event).values(
                event_key="event-dynamic",
                source_system="BOAMP",
                source_notice_id="notice-dynamic",
                source_country="FR",
                event_type="AWARD",
                published_on=NOW.date(),
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key="award-dynamic",
                event_key="event-dynamic",
                title="Construction d'un équipement public",
                amount=100_000,
                currency="EUR",
                winner_status="identified",
                awardee_parties=[],
                contract_signatories=[],
                cpv_additional=[],
                place_of_performance={"subdivision_code": "FRK26"},
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key="award-dynamic",
                opportunity_key="opportunity-dynamic",
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(materialized_signal).values(
                signal_key="signal-dynamic",
                opportunity_key="opportunity-dynamic",
                materialization_award_key="award-dynamic",
                target_icp_id="icp-dynamic",
                target_icp_revision=1,
                revision=1,
                content_fingerprint="c" * 64,
                materialized_recency_status="recent_award",
                materialized_award_clock_status="known",
                materialized_notification_clock_status="unknown",
                materialized_publication_clock_status="known",
                materialized_as_of=NOW.date(),
                recency_policy_version="test-v1",
                winner_name="12345678901234",
                winner_country="FR",
                winner_identifier_scheme="SIRET",
                winner_identifier_value="12345678901234",
                company_identity_fingerprint=identity_fingerprint,
                inferred_trade_domain="general_building",
                plausible_needs=[],
                icp_matched_needs=[],
                engine_versions={},
                materialized_at=NOW,
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(for_you_sentence).values(
                for_you_id="for-you-dynamic",
                signal_key="signal-dynamic",
                target_icp_id="icp-dynamic",
                signal_fingerprint="c" * 64,
                profile_fingerprint="p" * 64,
                policy_version="test-v1",
                sentence="Dans votre zone et votre secteur.",
                fallback_sentence="Dans votre zone et votre secteur.",
                provenance="generated",
                state="completed",
                input_snapshot={},
                model_fit="strong",
                created_at=NOW,
                updated_at=NOW,
                completed_at=NOW,
            )
        )
        connection.execute(
            sa.insert(winner_enrichment_job).values(
                signal_key="signal-dynamic",
                status="pending",
                attempt_count=0,
                queued_at=NOW,
                updated_at=NOW,
            )
        )
        if resolved_name is not None:
            connection.execute(
                sa.insert(saas_company).values(
                    company_key="company-dynamic",
                    identity_fingerprint=identity_fingerprint,
                    identity_method="official_identifier",
                    identity_validation={},
                    source_award_key="award-dynamic",
                    origin_signal_key="signal-dynamic",
                    official_name=resolved_name,
                    official_country="FR",
                    official_identifiers=[
                        {"scheme": "SIRET", "value": "12345678901234"}
                    ],
                    official_source="official_register",
                    official_observed_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def test_no_eligible_opportunity_returns_none(tmp_path) -> None:
    assert (
        select_production_opportunity_key(
            _engine(tmp_path), country="FR", observed_at=NOW
        )
        is None
    )


def test_production_selection_accepts_the_selected_vertical_and_region(tmp_path) -> None:
    """Production selection must scope the signal before choosing recency."""

    assert (
        select_production_opportunity_key(
            _engine(tmp_path),
            country="FR",
            vertical="general_building",
            region="Auvergne-Rhône-Alpes",
            observed_at=NOW,
        )
        is None
    )


def test_dynamic_selection_accepts_centre_val_de_loire_for_staging_stock(
    tmp_path,
) -> None:
    assert (
        select_production_opportunity_key(
            _engine(tmp_path),
            country="FR",
            vertical="general_building",
            region="Centre-Val de Loire",
            observed_at=NOW,
        )
        is None
    )


def test_dynamic_selection_requires_a_resolved_name_for_a_siret_only_holder(
    tmp_path,
) -> None:
    unresolved = _engine(tmp_path / "unresolved")
    _seed_dynamic_siret_holder(unresolved, resolved_name=None)

    assert (
        select_production_opportunity_key(
            unresolved,
            country="FR",
            vertical="general_building",
            region="Auvergne-Rhône-Alpes",
            observed_at=NOW,
        )
        is None
    )
    assert unresolved_dynamic_holder_signal_keys(
        unresolved,
        country="FR",
        vertical="general_building",
        region="Auvergne-Rhône-Alpes",
        observed_at=NOW,
    ) == ("signal-dynamic",)

    def official_company(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "12345678901234"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "nom_raison_sociale": "ENTREPRISE OFFICIELLE",
                        "siege": {
                            "siret": "12345678901234",
                            "adresse": "1 rue du Test 69000 Lyon",
                        },
                        "matching_etablissements": [],
                    }
                ]
            },
        )

    with unresolved.begin() as connection:
        result = run_winner_enrichment_batch(
            connection,
            now=NOW,
            worker_ref="acquisition-holder-resolution",
            limit=45,
            retry_failed=True,
            official_company_provider=FrenchOfficialCompanyClient(
                transport=httpx.MockTransport(official_company),
                clock=lambda: NOW,
            ),
            signal_keys=("signal-dynamic",),
        )

    assert result.processed == result.partial == 1
    assert (
        select_production_opportunity_key(
            unresolved,
            country="FR",
            vertical="general_building",
            region="Auvergne-Rhône-Alpes",
            observed_at=NOW,
        )
        == "opportunity-dynamic"
    )
    assert (
        unresolved_dynamic_holder_signal_keys(
            unresolved,
            country="FR",
            vertical="general_building",
            region="Auvergne-Rhône-Alpes",
            observed_at=NOW,
        )
        == ()
    )
    assert (
        resolved_holder_name_for_opportunity(unresolved, "opportunity-dynamic")
        == "ENTREPRISE OFFICIELLE"
    )
    with unresolved.begin() as connection:
        connection.execute(
            sa.update(saas_company).values(
                official_name="12345678901234",
                official_source="public_notice",
            )
        )
    assert (
        select_production_opportunity_key(
            unresolved,
            country="FR",
            vertical="general_building",
            region="Auvergne-Rhône-Alpes",
            observed_at=NOW,
        )
        is None
    )
    assert (
        resolved_holder_name_for_opportunity(unresolved, "opportunity-dynamic")
        is None
    )


def test_the_most_recent_french_opportunity_is_selected(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="ch-newest", country="CH", published_on=dt.date(2026, 8, 31))
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-newer"
    )


def test_an_opportunity_already_succeeded_by_a_cycle_is_never_selected_again(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed_cycle(engine, opportunity_key="fr-newer", status="SUCCEEDED")
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-older"
    )


def test_an_opportunity_suppressed_by_a_cycle_is_never_selected_again(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed_cycle(engine, opportunity_key="fr-newer", status="SUPPRESSED")
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-older"
    )


def test_an_opportunity_whose_cycle_failed_is_selectable_again(tmp_path) -> None:
    """FAILED n'est pas terminal : `resume_or_create_cycle` (store.py:411-412)
    reprend un cycle FAILED plutôt que d'en créer un nouveau. L'exclure du
    vivier empêcherait cette reprise au lieu de la protéger. Le cycle est ici
    au-delà du refroidissement de 20 heures : c'est la reprise qu'on teste,
    pas encore l'exclusion temporaire (couverte séparément ci-dessous)."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed_cycle(
        engine,
        opportunity_key="fr-newer",
        status="FAILED",
        updated_at=NOW - dt.timedelta(hours=21),
    )
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-newer"
    )


def test_an_opportunity_whose_cycle_was_cancelled_is_selectable_again(
    tmp_path,
) -> None:
    """CANCELLED n'est pas terminal, pour la même raison que FAILED — et,
    comme FAILED, au-delà du refroidissement de 20 heures."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed_cycle(
        engine,
        opportunity_key="fr-newer",
        status="CANCELLED",
        updated_at=NOW - dt.timedelta(hours=21),
    )
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-newer"
    )


def test_a_cycle_updated_within_the_cooldown_is_not_reselected_whatever_its_status(
    tmp_path,
) -> None:
    """A cycle parked WAITING on a human approval, updated less than 20 hours
    ago, is not reselected. Without this, the hourly timer would re-pick the
    same opportunity every run while it waits — monopolising the pool
    instead of freeing it for the next candidate."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed_cycle(
        engine,
        opportunity_key="fr-newer",
        status="WAITING",
        updated_at=NOW - dt.timedelta(hours=1),
    )
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-older"
    )


def test_a_cycle_updated_just_under_20_hours_ago_is_still_excluded(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-only", country="FR", published_on=dt.date(2026, 8, 30))
    _seed_cycle(
        engine,
        opportunity_key="fr-only",
        status="WAITING",
        updated_at=NOW - dt.timedelta(hours=20) + dt.timedelta(minutes=1),
    )
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        is None
    )


def test_a_cycle_updated_exactly_20_hours_ago_is_selectable(tmp_path) -> None:
    """The boundary is inclusive on the selectable side: exactly 20 hours
    elapsed counts as "beyond" the cooldown, not "less than" it."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-only", country="FR", published_on=dt.date(2026, 8, 30))
    _seed_cycle(
        engine,
        opportunity_key="fr-only",
        status="WAITING",
        updated_at=NOW - dt.timedelta(hours=20),
    )
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-only"
    )


def test_a_terminal_cycle_stays_excluded_long_after_the_cooldown(tmp_path) -> None:
    """A terminal cycle is excluded forever — the cooldown only ever adds
    exclusions on top of the terminal rule, it never shortens it."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed_cycle(
        engine,
        opportunity_key="fr-newer",
        status="SUCCEEDED",
        updated_at=NOW - dt.timedelta(days=365),
    )
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-older"
    )


def test_a_publication_in_the_future_is_not_selected(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-future", country="FR", published_on=dt.date(2026, 9, 30))
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        is None
    )


def test_selection_is_stable_across_two_reads(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-one", country="FR", published_on=dt.date(2026, 8, 30))
    first = select_production_opportunity_key(engine, country="FR", observed_at=NOW)
    second = select_production_opportunity_key(engine, country="FR", observed_at=NOW)
    assert first == second == "fr-one"


def test_a_naive_timestamp_is_refused(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        select_production_opportunity_key(
            _engine(tmp_path),
            country="FR",
            observed_at=dt.datetime(2026, 8, 31, 12),  # noqa: DTZ001
        )


def test_a_tie_on_the_same_publication_date_is_broken_by_opportunity_key(
    tmp_path,
) -> None:
    """Hardening beyond the brief: proves the ordering is genuinely total.

    Two representations can share a `published_on`. Without a deterministic
    tie-break, the winner would depend on the database's row order — which
    SQLAlchemy/SQLite do not guarantee across runs or query plans. Seeding
    the higher opportunity_key first checks that insertion order plays no
    role: only the tie-break (`opportunity_key.asc()`) decides.
    """

    engine = _engine(tmp_path)
    _seed(engine, key="fr-zzz", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="fr-aaa", country="FR", published_on=dt.date(2026, 8, 30))
    first = select_production_opportunity_key(engine, country="FR", observed_at=NOW)
    second = select_production_opportunity_key(engine, country="FR", observed_at=NOW)
    assert first == second == "fr-aaa"
