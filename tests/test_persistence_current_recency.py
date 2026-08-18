"""SPEC-010 closeout §1 — un statut stocké est un instantané, pas une vérité.

Le défaut visé est celui d'un feed qui vieillit sans le savoir. Un marché
matérialisé le 18 août avec `recent_award` reste `recent_award` en base pour
toujours ; si la phrase client se déduisait de cette colonne, le produit dirait
« vient de remporter » deux mois plus tard.

La séparation est donc explicite et testée dans les deux sens :

    materialized_recency_status   ce qui a été constaté le jour J — pour l'audit
    current_recency(as_of=…)      ce qui est vrai aujourd'hui — pour le client

`as_of` est toujours passé. Aucune horloge système n'est lue dans la couche de
persistance : un test qui dépend de `date.today()` cesse de tester quoi que ce
soit dès le lendemain.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest
import sqlalchemy as sa

from signals.connectors.boamp import parse_award_notice
from signals.domain.awards import Awardee, AwardeeParty, ContractAward, LotRef
from signals.domain.events import Provenance, PublicEvent
from signals.domain.values import OrganizationIdentifier, OrganizationRef
from signals.matching import MatchingEngine
from signals.matching.reference import CONSTRUCTION_INPUTS_ICP
from signals.needs import NeedGraphEngine
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.materialization import materialize_signal
from signals.persistence.repository import get_signal, list_signals
from signals.recency import assess_recency
from signals.understanding import ContractUnderstandingEngine

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
RECORDS = {
    record["idweb"]: record
    for record in json.loads((FIXTURE / "boamp_records.json").read_text(encoding="utf-8"))[
        "records"
    ]
}

MATERIALISED_ON = dt.date(2026, 8, 18)
MATERIALIZED_AT = dt.datetime(2026, 8, 18, 7, 30, tzinfo=dt.UTC)
ICP = CONSTRUCTION_INPUTS_ICP


@pytest.fixture
def connection(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    with engine.begin() as open_connection:
        yield open_connection


def synthetic_award(*, award_date: dt.date | None, notification: dt.date | None = None):
    """Un avis réel dont on ne fixe que les dates — le reste vient du BOAMP."""
    event, awards = parse_award_notice(RECORDS["26-80978"])
    original = awards[0]
    award = original.model_copy(
        update={"award_date": award_date, "contract_notification_date": notification}
    )
    return event, award


def store(connection: sa.Connection, event: PublicEvent, award: ContractAward, *, as_of: dt.date):
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    match = MatchingEngine().match(understanding, needs, ICP, as_of=as_of)
    published = event.published_at
    recency = assess_recency(
        award_date=award.award_date,
        contract_notification_date=award.contract_notification_date,
        publication_date=published,
        as_of=as_of,
    )
    return materialize_signal(
        connection,
        event=event,
        award=award,
        understanding=understanding,
        needs=needs,
        match=match,
        recency=recency,
        as_of=as_of,
        materialized_at=MATERIALIZED_AT,
    )


# ─── le cœur : lire aujourd'hui ce qui a été constaté hier ─────────────────────


def test_a_recent_award_read_five_days_later_may_still_claim_a_win(
    connection: sa.Connection,
):
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )

    assert stored.materialized_recency_status == "recent_award"
    current = stored.current_recency(as_of=dt.date(2026, 8, 23))
    assert current.status == "recent_award"
    assert current.may_claim_just_won
    assert "vient de remporter" in stored.claim(lang="fr", as_of=dt.date(2026, 8, 23))


def test_the_same_stored_row_read_ninety_days_later_must_not_claim_a_win(
    connection: sa.Connection,
):
    """Le cas exact de la SPEC : matérialisé le 18 août, lu le 18 octobre."""
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )

    assert stored.materialized_recency_status == "recent_award", "l'instantané est intact"

    current = stored.current_recency(as_of=dt.date(2026, 10, 18))
    assert current.status == "stale_award"
    assert not current.may_claim_just_won
    assert "vient de remporter" not in stored.claim(lang="fr", as_of=dt.date(2026, 10, 18))


def test_a_recent_notification_read_after_the_threshold_no_longer_claims_it(
    connection: sa.Connection,
):
    event, award = synthetic_award(award_date=None, notification=dt.date(2026, 8, 14))
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )

    assert stored.materialized_recency_status == "recently_notified_contract"
    later = stored.current_recency(as_of=dt.date(2026, 10, 18))
    assert later.status != "recently_notified_contract"
    assert "vient d'être notifié" not in stored.claim(lang="fr", as_of=dt.date(2026, 10, 18))


def test_the_award_clock_ages_while_the_stored_snapshot_does_not(
    connection: sa.Connection,
):
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )

    assert stored.materialized_award_age_days == 8
    assert stored.current_recency(as_of=dt.date(2026, 10, 18)).award_age_days == 69


def test_the_stored_snapshot_stays_available_for_audit(connection: sa.Connection):
    """Closeout §1 — les statuts historiques restent inchangés, c'est leur rôle."""
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )

    for as_of in (dt.date(2026, 8, 19), dt.date(2027, 1, 1)):
        stored.current_recency(as_of=as_of)
    reread = get_signal(connection, stored.signal_key)
    assert reread.materialized_recency_status == stored.materialized_recency_status
    assert reread.materialized_as_of == MATERIALISED_ON
    assert reread.materialized_award_age_days == 8


# ─── aucune horloge cachée ─────────────────────────────────────────────────────


def test_the_current_assessment_requires_an_explicit_as_of():
    """Sans `as_of`, la fonction refuse plutôt que de lire l'horloge système."""
    import inspect

    from signals.persistence.repository import StoredSignal

    signature = inspect.signature(StoredSignal.current_recency)
    assert signature.parameters["as_of"].default is inspect.Parameter.empty


def test_generating_a_claim_requires_an_explicit_as_of():
    import inspect

    from signals.persistence.repository import StoredSignal

    signature = inspect.signature(StoredSignal.claim)
    assert signature.parameters["as_of"].default is inspect.Parameter.empty


def test_no_system_clock_is_read_in_the_persistence_layer():
    """Une horloge cachée rendrait tout test non reproductible dès le lendemain."""
    for name in ("repository.py", "materialization.py", "identity.py", "opportunity.py"):
        source = (pathlib.Path("src/signals/persistence") / name).read_text(encoding="utf-8")
        for forbidden in ("date.today()", "datetime.now(", "utcnow(", "time.time("):
            assert forbidden not in source, f"{name} : {forbidden}"


# ─── le filtre ne doit pas faire passer un instantané pour l'actuel ────────────


def test_the_recency_filter_is_named_after_the_snapshot_it_reads(
    connection: sa.Connection,
):
    """Closeout §1 — `recency_status=` aurait laissé croire à une fraîcheur actuelle."""
    import inspect

    parameters = set(inspect.signature(list_signals).parameters)
    assert "materialized_recency_status" in parameters
    assert "recency_status" not in parameters


def test_filtering_on_the_snapshot_returns_the_stored_rows(connection: sa.Connection):
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    store(connection, event, award, as_of=MATERIALISED_ON)

    assert list_signals(connection, materialized_recency_status="recent_award")
    assert not list_signals(connection, materialized_recency_status="stale_award")


def test_a_listed_signal_can_still_be_reassessed_at_read_time(connection: sa.Connection):
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    store(connection, event, award, as_of=MATERIALISED_ON)

    listed = list_signals(connection, materialized_recency_status="recent_award")[0]
    assert listed.current_recency(as_of=dt.date(2026, 12, 1)).status == "stale_award"


# ─── un gagnant sans nom ne fabrique pas de phrase ─────────────────────────────


def test_a_signal_without_a_winner_name_is_refused_a_claim(connection: sa.Connection):
    """Une phrase « … vient de remporter » sans société nommée n'est pas affichable."""
    event, awards = parse_award_notice(RECORDS["26-80978"])
    anonymous = awards[0].model_copy(
        update={
            "award_date": dt.date(2026, 8, 10),
            "awardee_parties": (
                AwardeeParty(
                    members=(
                        Awardee(
                            organization=OrganizationRef(
                                legal_name="12345678901234",
                                identifiers=(
                                    OrganizationIdentifier(scheme="SIRET", value="12345678901234"),
                                ),
                            )
                        ),
                    )
                ),
            ),
        }
    )
    stored = get_signal(
        connection, store(connection, event, anonymous, as_of=MATERIALISED_ON).signal_key
    )
    assert stored.winner_name == "12345678901234"
    assert stored.claim(lang="fr", as_of=MATERIALISED_ON)


def test_a_provenance_only_event_still_reassesses(connection: sa.Connection):
    """Un avis sans date d'attribution reste évaluable — sur ses autres horloges."""
    event, award = synthetic_award(award_date=None)
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )
    current = stored.current_recency(as_of=dt.date(2027, 1, 1))
    assert current.award_clock.status == "unknown"
    assert not current.may_claim_just_won


def test_the_publication_clock_is_reassessed_too(connection: sa.Connection):
    event, award = synthetic_award(award_date=None)
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )

    assert stored.current_recency(as_of=MATERIALISED_ON).publication_clock.status == "recent"
    assert stored.current_recency(as_of=dt.date(2027, 1, 1)).publication_clock.status == "stale"


def test_a_synthetic_lot_reference_stays_intact(connection: sa.Connection):
    """Garde-fou : `model_copy` ne doit pas altérer autre chose que les dates."""
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    assert isinstance(award.lot, LotRef)
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )
    assert stored.award.lot_identifier == award.lot.identifier


def test_provenance_survives_the_reassessment(connection: sa.Connection):
    event, award = synthetic_award(award_date=dt.date(2026, 8, 10))
    stored = get_signal(
        connection, store(connection, event, award, as_of=MATERIALISED_ON).signal_key
    )
    assert isinstance(event.provenance, Provenance)
    assert stored.event.source_notice_id == event.provenance.source_notice_id
