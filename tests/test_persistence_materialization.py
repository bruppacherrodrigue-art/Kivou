"""SPEC-010 §6, §7, §9, §10, §12 — un signal qui survit à un aller-retour en base.

Les données sont réelles : `tests/fixtures/france/boamp_records.json` contient
des avis d'attribution BOAMP non modifiés, et ils traversent ici la chaîne
complète — compréhension, besoins, matching, fraîcheur — avant d'être
matérialisés. Aucun objet de test n'est fabriqué là où un avis réel fait
l'affaire.

Le test qui compte le plus est celui des horloges. SPEC-009E a coûté deux
révisions pour séparer décision, notification et parution ; un stockage qui les
replierait au rechargement effacerait ce travail sans qu'aucun test d'unité ne
s'en aperçoive.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib

import pytest
import sqlalchemy as sa

from signals.connectors.boamp import parse_award_notice
from signals.domain.awards import ContractAward
from signals.matching import MatchingEngine
from signals.matching.reference import CONSTRUCTION_INPUTS_ICP, REFERENCE_ICPS
from signals.needs import NeedGraphEngine
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.materialization import materialize_signal
from signals.persistence.repository import get_signal, list_signals
from signals.persistence.schema import materialized_signal
from signals.recency import assess_recency
from signals.understanding import ContractUnderstandingEngine

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
RECORDS = {
    record["idweb"]: record
    for record in json.loads((FIXTURE / "boamp_records.json").read_text(encoding="utf-8"))[
        "records"
    ]
}

AS_OF = dt.date(2026, 8, 18)
MATERIALIZED_AT = dt.datetime(2026, 8, 18, 7, 30, tzinfo=dt.UTC)
RETRIEVED_AT = dt.datetime(2026, 8, 18, 6, 0, tzinfo=dt.UTC)
ICP = CONSTRUCTION_INPUTS_ICP


@pytest.fixture
def connection(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    with engine.begin() as open_connection:
        yield open_connection


@dataclasses.dataclass(frozen=True)
class Bundle:
    """Ce que le moteur produit déjà — l'entrée de la matérialisation (§9)."""

    event: object
    award: ContractAward
    understanding: object
    needs: object
    match: object
    recency: object


def bundle(idweb: str = "26-80978", index: int = 0, *, icp=ICP) -> Bundle:
    event, awards = parse_award_notice(RECORDS[idweb], retrieved_at=RETRIEVED_AT)
    award = awards[index]
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    match = MatchingEngine().match(understanding, needs, icp, as_of=AS_OF)
    published = event.published_at
    recency = assess_recency(
        award_date=award.award_date,
        contract_notification_date=award.contract_notification_date,
        publication_date=published.date() if isinstance(published, dt.datetime) else published,
        discovered_at=RETRIEVED_AT.date(),
        as_of=AS_OF,
    )
    return Bundle(event, award, understanding, needs, match, recency)


def store(connection: sa.Connection, item: Bundle, **overrides):
    return materialize_signal(
        connection,
        event=item.event,
        award=item.award,
        understanding=item.understanding,
        needs=item.needs,
        match=item.match,
        recency=item.recency,
        as_of=AS_OF,
        materialized_at=overrides.pop("materialized_at", MATERIALIZED_AT),
        **overrides,
    )


# ─── §12.1, §12.2 — l'award et ses dates ───────────────────────────────────────


def test_an_award_survives_a_round_trip(connection: sa.Connection):
    item = bundle()
    result = store(connection, item)
    stored = get_signal(connection, result.signal_key)

    assert stored is not None
    assert stored.award.source_award_id == item.award.source_award_id
    assert stored.award.lot_identifier == item.award.lot.identifier
    assert stored.award.title == item.award.title
    assert stored.award.cpv_main == item.award.cpv_main.code


def test_every_contract_clock_survives_exactly(connection: sa.Connection):
    """§12.2 — les dates importantes reviennent au jour près, ou pas du tout."""
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    assert stored.award.award_date == item.award.award_date
    assert stored.award.contract_signature_date == item.award.contract_signature_date
    assert stored.award.contract_notification_date == item.award.contract_notification_date
    assert stored.award.contract_start_date == item.award.contract_start_date
    assert stored.award.contract_end_date == item.award.contract_end_date


def test_the_publication_instant_keeps_its_declared_precision(connection: sa.Connection):
    """`date` et `datetime` sont deux informations différentes depuis SPEC-005."""
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    assert stored.event.published_at == item.event.published_at
    assert stored.event.published_precision == item.event.published_precision()


def test_the_discovery_timestamp_is_distinct_from_every_contract_clock(
    connection: sa.Connection,
):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    assert stored.event.discovered_at == RETRIEVED_AT
    assert stored.event.discovered_at.date() != stored.award.award_date


def test_a_monetary_amount_is_not_rounded_through_a_float(connection: sa.Connection):
    item = bundle("26-80922")
    stored = get_signal(connection, store(connection, item).signal_key)
    assert str(stored.award.amount) == str(item.award.value.amount)
    assert stored.award.currency == item.award.value.currency


# ─── §12.3 — la preuve ─────────────────────────────────────────────────────────


def test_evidence_survives_with_its_source_and_path(connection: sa.Connection):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    assert stored.evidence, "un signal affiché sans preuve n'est pas affichable"
    for row in stored.evidence:
        assert row.source_system
        assert row.source_kind
        assert row.source_url or row.source_notice_id


def test_evidence_is_never_duplicated_by_a_second_materialization(
    connection: sa.Connection,
):
    item = bundle()
    first = get_signal(connection, store(connection, item).signal_key)
    second = get_signal(connection, store(connection, item).signal_key)
    assert len(first.evidence) == len(second.evidence)


# ─── §6, §12.4 — les horloges de fraîcheur ─────────────────────────────────────


def test_the_three_clocks_survive_the_round_trip(connection: sa.Connection):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    assert stored.materialized_recency_status == item.recency.status
    assert stored.materialized_award_clock_status == item.recency.award_clock.status
    assert stored.materialized_notification_clock_status == item.recency.notification_clock.status
    assert stored.materialized_publication_clock_status == item.recency.publication_clock.status
    assert stored.materialized_award_age_days == item.recency.award_age_days
    assert stored.materialized_notification_age_days == item.recency.notification_age_days


def test_the_stored_dates_reproduce_the_stored_statuses(connection: sa.Connection):
    """§6 — la preuve la plus forte : recalculer la fraîcheur depuis la base.

    Si un statut stocké et les dates stockées divergeaient, le produit pourrait
    afficher « vient de remporter » sur un marché que ses propres dates
    démentent.
    """
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    recomputed = assess_recency(
        award_date=stored.award.award_date,
        contract_notification_date=stored.award.contract_notification_date,
        publication_date=stored.event.published_on,
        as_of=stored.materialized_as_of,
    )
    assert recomputed.status == stored.materialized_recency_status
    assert recomputed.award_clock.status == stored.materialized_award_clock_status
    assert recomputed.notification_clock.status == stored.materialized_notification_clock_status


def test_the_primary_mvp_event_survives(connection: sa.Connection):
    from signals.recency.claim import mvp_event_type

    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)
    assert stored.materialized_primary_event == mvp_event_type(item.recency.status)


def test_the_recency_policy_version_survives(connection: sa.Connection):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)
    assert stored.recency_policy_version == item.recency.policy_version


def test_safe_copy_is_regenerated_from_the_reloaded_status(connection: sa.Connection):
    """§4 — la phrase n'est pas stockée ; elle se redéduit du statut rechargé."""
    from signals.recency.claim import claim_for_status

    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)
    assert stored.claim(lang="fr", as_of=AS_OF) == claim_for_status(
        item.recency.status, company=stored.winner_name, lang="fr"
    )


def test_a_reloaded_signal_never_claims_a_win_it_cannot_support(
    connection: sa.Connection,
):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)
    if stored.materialized_recency_status != "recent_award":
        assert "vient de remporter" not in stored.claim(lang="fr", as_of=AS_OF)


# ─── §5, §12.6 — les besoins restent des inférences ────────────────────────────


def test_plausible_needs_survive_and_stay_plausible(connection: sa.Connection):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    assert len(stored.plausible_needs) == len(item.needs.needs)
    for need in stored.plausible_needs:
        assert set(need) >= {"category", "statement", "timing", "confidence"}
        assert "confirmed" not in json.dumps(need)


def test_the_contract_understanding_is_stored_as_an_inference(connection: sa.Connection):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)
    assert stored.inferred_contract_type == item.understanding.contract_type.value


# ─── §7, §12.7 — idempotence ───────────────────────────────────────────────────


def test_materializing_twice_creates_a_single_customer_signal(connection: sa.Connection):
    item = bundle()
    first = store(connection, item)
    second = store(connection, item)

    assert first.signal_key == second.signal_key
    assert first.created is True
    assert second.created is False
    assert (
        connection.execute(sa.select(sa.func.count()).select_from(materialized_signal)).scalar()
        == 1
    )


def test_an_unchanged_rematerialization_does_not_bump_the_revision(
    connection: sa.Connection,
):
    item = bundle()
    assert store(connection, item).revision == 1
    assert store(connection, item).revision == 1


def test_new_engine_versions_produce_a_new_revision_of_the_same_signal(
    connection: sa.Connection,
):
    """§7 — le signal logique ne change pas ; sa révision matérialisée, si."""
    item = bundle()
    first = store(connection, item)
    second = store(connection, item, engine_version_override={"need": "need-graph-v0.3"})

    assert second.signal_key == first.signal_key
    assert second.revision == 2
    assert (
        connection.execute(sa.select(sa.func.count()).select_from(materialized_signal)).scalar()
        == 1
    )


# ─── §12.8, §12.9 — pas de collision ───────────────────────────────────────────


def test_two_lots_of_the_same_notice_are_two_signals(connection: sa.Connection):
    first = store(connection, bundle("26-80978", 0))
    second = store(connection, bundle("26-80978", 1))
    assert first.signal_key != second.signal_key
    assert len(list_signals(connection)) == 2


def test_two_icp_contexts_are_two_signals_on_the_same_award(connection: sa.Connection):
    other = next(icp for icp in REFERENCE_ICPS if icp.icp_id != ICP.icp_id)
    first = store(connection, bundle())
    second = store(connection, bundle(icp=other))

    assert first.signal_key != second.signal_key
    assert {signal.target_icp_id for signal in list_signals(connection)} == {
        ICP.icp_id,
        other.icp_id,
    }


def test_the_same_award_is_stored_once_even_across_two_icp_contexts(
    connection: sa.Connection,
):
    """Les faits ne se dupliquent pas parce que deux clients regardent le marché."""
    other = next(icp for icp in REFERENCE_ICPS if icp.icp_id != ICP.icp_id)
    store(connection, bundle())
    store(connection, bundle(icp=other))

    from signals.persistence.schema import contract_award

    assert connection.execute(sa.select(sa.func.count()).select_from(contract_award)).scalar() == 1


# ─── §8, §12.10 — provenance des versions de moteur ────────────────────────────


def test_every_engine_version_survives(connection: sa.Connection):
    item = bundle()
    stored = get_signal(connection, store(connection, item).signal_key)

    versions = stored.engine_versions
    assert versions["understanding"] == item.understanding.engine_version
    assert versions["need"] == item.needs.engine_version
    assert versions["match_policy"] == item.match.match_policy_version
    assert versions["score_policy"] == item.match.score_policy_version
    assert versions["recency_policy"] == item.recency.policy_version


def test_no_engine_version_is_hardcoded_in_the_persistence_layer():
    """§8 — les versions viennent des moteurs, jamais d'une constante du stockage."""
    import re

    for name in ("materialization.py", "schema.py", "repository.py"):
        source = (pathlib.Path("src/signals/persistence") / name).read_text(encoding="utf-8")
        assert not re.search(r"-v\d+\.\d+", source), name


# ─── §10 — lecture ─────────────────────────────────────────────────────────────


def test_an_unknown_signal_reads_as_absent_rather_than_raising(connection: sa.Connection):
    assert get_signal(connection, "inexistant") is None


def test_signals_can_be_filtered_by_the_minimal_useful_set(connection: sa.Connection):
    item = bundle()
    store(connection, item)

    assert list_signals(connection, target_icp_id=ICP.icp_id)
    assert list_signals(connection, materialized_recency_status=item.recency.status)
    assert list_signals(connection, country=item.event.provenance.source_country)
    assert not list_signals(connection, target_icp_id="icp-inexistant")


def test_listing_is_deterministic(connection: sa.Connection):
    store(connection, bundle("26-80978", 0))
    store(connection, bundle("26-80978", 1))
    assert [signal.signal_key for signal in list_signals(connection)] == [
        signal.signal_key for signal in list_signals(connection)
    ]


# ─── §12.11 — transaction ──────────────────────────────────────────────────────


def test_an_invalid_write_rolls_back_and_leaves_nothing_behind(tmp_path: pathlib.Path):
    """Un signal à moitié écrit serait pire qu'un signal absent."""
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)

    item = bundle()
    with (
        pytest.raises(Exception),  # noqa: B017 — la nature de l'erreur importe peu ici
        engine.begin() as connection,
    ):
        store(connection, item)
        connection.execute(sa.insert(materialized_signal).values(signal_key=None, award_key=None))

    with engine.connect() as connection:
        from signals.persistence.schema import contract_award, source_event

        for table in (source_event, contract_award, materialized_signal):
            assert connection.execute(sa.select(sa.func.count()).select_from(table)).scalar() == 0


# ─── closeout §2 — une opportunité, deux représentations sources ───────────────

LINK = json.loads((FIXTURE / "boamp_decp2022_link.json").read_text(encoding="utf-8"))
LINKED_BOAMP = next(r for r in LINK["boamp_records"] if r["idweb"] == "26-79799")
LINKED_DECP = next(r for r in LINK["decp_records"] if r["id"] == "178645481096900")


def linked_bundles():
    """Les deux faces d'un même marché, réellement rapprochées par SPEC-009E.

    Le lien est `strong` : mêmes parties, même date de notification, et accord
    sur le montant ET le CPV. C'est le seul cas qui autorise la réunion.
    """
    from signals.connectors.decp import parse_contract
    from signals.france.link import resolve_candidates, unique_strong

    boamp_event, boamp_awards = parse_award_notice(LINKED_BOAMP, retrieved_at=RETRIEVED_AT)
    boamp_award = boamp_awards[0]
    assert unique_strong(resolve_candidates(boamp_award, boamp_event, [LINKED_DECP])) is not None

    decp_event, decp_award = parse_contract(LINKED_DECP, retrieved_at=RETRIEVED_AT)
    return (boamp_event, boamp_award), (decp_event, decp_award)


def bundle_of(event, award, *, icp=ICP) -> Bundle:
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    match = MatchingEngine().match(understanding, needs, icp, as_of=AS_OF)
    published = event.published_at
    recency = assess_recency(
        award_date=award.award_date,
        contract_notification_date=award.contract_notification_date,
        publication_date=published.date() if isinstance(published, dt.datetime) else published,
        as_of=AS_OF,
    )
    return Bundle(event, award, understanding, needs, match, recency)


def test_two_strongly_linked_representations_become_one_signal(connection: sa.Connection):
    """§2 — BOAMP et DECP décrivent un seul marché : le client n'en voit qu'un."""
    (boamp_event, boamp_award), (decp_event, decp_award) = linked_bundles()

    first = store(connection, bundle_of(boamp_event, boamp_award))
    second = store(
        connection,
        bundle_of(decp_event, decp_award),
        linked_to=[boamp_award],
        link_strength="strong",
    )

    assert first.opportunity_key == second.opportunity_key
    assert first.signal_key == second.signal_key
    assert (
        connection.execute(sa.select(sa.func.count()).select_from(materialized_signal)).scalar()
        == 1
    )


def test_a_late_link_never_renames_an_already_served_signal(connection: sa.Connection):
    """Le défaut du closeout final : l'identité écrite hier ne bouge pas aujourd'hui."""
    (boamp_event, boamp_award), (decp_event, decp_award) = linked_bundles()

    day_one = store(connection, bundle_of(boamp_event, boamp_award))
    day_two = store(
        connection,
        bundle_of(decp_event, decp_award),
        linked_to=[boamp_award],
        link_strength="strong",
    )

    assert day_two.signal_key == day_one.signal_key
    assert day_two.opportunity_key == day_one.opportunity_key
    assert get_signal(connection, day_one.signal_key) is not None


def test_both_source_representations_keep_their_own_facts(connection: sa.Connection):
    """§2 — l'identité source et sa preuve survivent indépendamment."""
    from signals.persistence.schema import contract_award, opportunity_representation

    (boamp_event, boamp_award), (decp_event, decp_award) = linked_bundles()
    store(connection, bundle_of(boamp_event, boamp_award))
    result = store(
        connection,
        bundle_of(decp_event, decp_award),
        linked_to=[boamp_award],
        link_strength="strong",
    )

    assert connection.execute(sa.select(sa.func.count()).select_from(contract_award)).scalar() == 2
    linked = (
        connection.execute(
            sa.select(opportunity_representation.c.award_key).where(
                opportunity_representation.c.opportunity_key == result.opportunity_key
            )
        )
        .scalars()
        .all()
    )
    assert len(linked) == 2


def test_two_unlinked_representations_stay_two_opportunities(connection: sa.Connection):
    """Sans rapprochement fort, chaque source reste son propre contrat."""
    (boamp_event, boamp_award), (decp_event, decp_award) = linked_bundles()
    first = store(connection, bundle_of(boamp_event, boamp_award))
    second = store(connection, bundle_of(decp_event, decp_award))

    assert first.opportunity_key != second.opportunity_key
    assert first.signal_key != second.signal_key
    assert (
        connection.execute(sa.select(sa.func.count()).select_from(materialized_signal)).scalar()
        == 2
    )


def test_a_probable_link_never_produces_a_shared_opportunity(connection: sa.Connection):
    """§7.E — un candidat faible n'empêche rien, et ne réunit rien."""
    (boamp_event, boamp_award), (decp_event, decp_award) = linked_bundles()
    first = store(connection, bundle_of(boamp_event, boamp_award))
    second = store(
        connection,
        bundle_of(decp_event, decp_award),
        linked_to=[boamp_award],
        link_strength="probable",
    )

    assert second.opportunity_key != first.opportunity_key
    assert second.signal_key != first.signal_key


def test_a_conflict_between_two_served_opportunities_is_raised_not_merged(
    connection: sa.Connection,
):
    """§3 — sûreté des faits avant déduplication automatique."""
    from signals.persistence.opportunity import OpportunityConflict

    (boamp_event, boamp_award), (decp_event, decp_award) = linked_bundles()
    first = store(connection, bundle_of(boamp_event, boamp_award))
    second = store(connection, bundle_of(decp_event, decp_award))

    with pytest.raises(OpportunityConflict):
        store(
            connection,
            bundle_of(decp_event, decp_award),
            linked_to=[boamp_award],
            link_strength="strong",
        )

    assert get_signal(connection, first.signal_key) is not None
    assert get_signal(connection, second.signal_key) is not None


# ─── closeout §4 — la révision suit le CONTENU, pas seulement les versions ─────


def test_a_changed_inference_bumps_the_revision_at_constant_engine_versions(
    connection: sa.Connection,
):
    """Le cas que la version de moteur seule n'aurait pas détecté."""
    item = bundle()
    assert store(connection, item).revision == 1

    altered = dataclasses.replace(
        item,
        understanding=item.understanding.model_copy(
            update={"sector": item.understanding.sector.model_copy(update={"value": "energy"})}
        ),
    )
    result = store(connection, altered)
    assert result.revision == 2
    assert result.updated is True

    stored = get_signal(connection, result.signal_key)
    assert stored.inferred_sector == "energy"
    assert stored.engine_versions == get_signal(connection, result.signal_key).engine_versions


def test_a_changed_score_bumps_the_revision(connection: sa.Connection):
    item = bundle()
    store(connection, item)
    altered = dataclasses.replace(
        item, match=item.match.model_copy(update={"normalized_score": 77})
    )
    assert store(connection, altered).revision == 2


def test_an_identical_rematerialization_leaves_the_fingerprint_untouched(
    connection: sa.Connection,
):
    item = bundle()
    first = get_signal(connection, store(connection, item).signal_key)
    store(connection, item)
    second = get_signal(connection, first.signal_key)
    assert second.content_fingerprint == first.content_fingerprint
    assert second.revision == first.revision == 1


def test_the_fingerprint_ignores_timestamps_so_a_replay_stays_idempotent(
    connection: sa.Connection,
):
    """Rematérialiser plus tard le même contenu ne doit pas créer de révision."""
    item = bundle()
    store(connection, item)
    later = store(connection, item, materialized_at=dt.datetime(2026, 9, 1, 9, tzinfo=dt.UTC))
    assert later.revision == 1
    assert later.updated is False
