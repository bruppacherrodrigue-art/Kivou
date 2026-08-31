# tests/test_acquisition_runtime_selection.py
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.acquisition_runtime.selection import select_production_opportunity_key
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    contract_award,
    opportunity_representation,
    source_event,
)

NOW = dt.datetime(2026, 8, 31, 12, tzinfo=dt.UTC)


def _engine(tmp_path) -> sa.Engine:
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
            opportunity_representation,
            acquisition_runtime_cycle,
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


def _seed_cycle(engine, *, opportunity_key: str, status: str) -> None:
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
                updated_at=NOW,
                completed_at=NOW if status in _TERMINAL_STATUSES else None,
            )
        )


def test_no_eligible_opportunity_returns_none(tmp_path) -> None:
    assert (
        select_production_opportunity_key(
            _engine(tmp_path), country="FR", observed_at=NOW
        )
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
    vivier empêcherait cette reprise au lieu de la protéger."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed_cycle(engine, opportunity_key="fr-newer", status="FAILED")
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-newer"
    )


def test_an_opportunity_whose_cycle_was_cancelled_is_selectable_again(
    tmp_path,
) -> None:
    """CANCELLED n'est pas terminal, pour la même raison que FAILED."""

    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed_cycle(engine, opportunity_key="fr-newer", status="CANCELLED")
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-newer"
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
