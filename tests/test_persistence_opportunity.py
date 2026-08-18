"""SPEC-010 final closeout — une identité d'opportunité **persistée**, jamais recalculée.

Le défaut corrigé ici est subtil et sérieux. La première version calculait
`opportunity_key = hash(ensemble trié des award_key)`. C'est indépendant de
l'ordre — mais seulement si l'ensemble complet est connu dès le départ. Or il ne
l'est jamais :

    jour 1    l'avis A arrive          → opportunité O = f(A)
    jour 2    B est rapproché de A     → opportunité O = f(A, B)   ← O a CHANGÉ

Le signal aurait été renommé sous les pieds du client. Une identité
d'opportunité, une fois écrite, ne bouge plus : elle est **créée une fois** et
relue ensuite, jamais dérivée de l'appartenance courante.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa

from signals.domain.awards import Awardee, AwardeeParty, ContractAward, LotRef
from signals.domain.events import EventRef
from signals.domain.values import OrganizationRef
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.identity import award_key
from signals.persistence.opportunity import (
    COLLAPSIBLE_LINK_STRENGTHS,
    OpportunityConflict,
    ResolvedOpportunity,
    opportunity_of,
    resolve_or_create_opportunity,
)
from signals.persistence.schema import contract_award, opportunity_representation, source_event

NOW = dt.datetime(2026, 8, 18, 7, 30, tzinfo=dt.UTC)


@pytest.fixture
def connection(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    with engine.begin() as open_connection:
        yield open_connection


def award(*, system: str = "boamp", notice: str = "26-1", lot: str = "LOT-0001") -> ContractAward:
    return ContractAward(
        event_ref=EventRef(source_system=system, source_notice_id=notice),
        source_award_id="CON-0001",
        lot=LotRef(identifier=lot),
        awardee_parties=(
            AwardeeParty(members=(Awardee(organization=OrganizationRef(legal_name="Gagnant")),)),
        ),
    )


A = award()
B = award(system="decp", notice="2026S02051")
C = award(system="ted", notice="571387-2026")


def persist_facts(connection: sa.Connection, *awards: ContractAward) -> None:
    """Écrit le minimum de faits pour que la clé étrangère soit satisfaite."""
    for item in awards:
        reference = item.event_ref
        connection.execute(
            sa.insert(source_event)
            .prefix_with("OR IGNORE")
            .values(
                event_key=reference.key(),
                source_system=reference.source_system,
                source_notice_id=reference.source_notice_id,
                source_country="FR",
                event_type="award_notice",
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(contract_award)
            .prefix_with("OR IGNORE")
            .values(
                award_key=award_key(item),
                event_key=reference.key(),
                winner_status="identified",
                cpv_additional=[],
                awardee_parties=[],
                contract_signatories=[],
                created_at=NOW,
            )
        )


def resolve(connection: sa.Connection, item: ContractAward, **kwargs) -> ResolvedOpportunity:
    return resolve_or_create_opportunity(connection, item, now=NOW, **kwargs)


# ─── CAS C — création unique ───────────────────────────────────────────────────


def test_a_first_representation_creates_one_opportunity(connection: sa.Connection):
    persist_facts(connection, A)
    resolved = resolve(connection, A)
    assert resolved.created is True
    assert resolved.opportunity_key
    assert resolved.representations == (award_key(A),)


def test_the_opportunity_key_is_not_the_award_key(connection: sa.Connection):
    """Deux identités distinctes doivent se distinguer à l'œil (closeout §6)."""
    persist_facts(connection, A)
    assert resolve(connection, A).opportunity_key != award_key(A)


# ─── CAS A — représentation déjà rattachée ─────────────────────────────────────


def test_resolving_the_same_representation_twice_returns_the_same_opportunity(
    connection: sa.Connection,
):
    persist_facts(connection, A)
    first = resolve(connection, A)
    second = resolve(connection, A)
    assert second.opportunity_key == first.opportunity_key
    assert second.created is False


def test_the_mapping_is_read_from_the_database_not_recomputed(connection: sa.Connection):
    persist_facts(connection, A)
    created = resolve(connection, A)
    assert opportunity_of(connection, award_key(A)) == created.opportunity_key


# ─── CAS B — liaison TARDIVE : le cœur du closeout ─────────────────────────────


def test_a_late_strong_link_attaches_without_changing_the_opportunity(
    connection: sa.Connection,
):
    """Le défaut corrigé : attacher B ne doit pas renommer l'opportunité de A."""
    persist_facts(connection, A)
    day_one = resolve(connection, A)

    persist_facts(connection, B)
    day_two = resolve(connection, B, linked_to=[A], link_strength="strong")

    assert day_two.opportunity_key == day_one.opportunity_key
    assert day_two.created is False
    assert set(day_two.representations) == {award_key(A), award_key(B)}


def test_the_opportunity_key_survives_a_third_representation(connection: sa.Connection):
    persist_facts(connection, A, B, C)
    original = resolve(connection, A).opportunity_key
    resolve(connection, B, linked_to=[A], link_strength="strong")
    resolve(connection, C, linked_to=[A], link_strength="strong")

    assert opportunity_of(connection, award_key(A)) == original
    assert opportunity_of(connection, award_key(B)) == original
    assert opportunity_of(connection, award_key(C)) == original


def test_the_reverse_arrival_order_also_yields_a_single_opportunity(
    connection: sa.Connection,
):
    """§7.B — l'ordre d'arrivée change la valeur de la clé, jamais leur nombre."""
    persist_facts(connection, A, B)
    first = resolve(connection, B)
    second = resolve(connection, A, linked_to=[B], link_strength="strong")

    assert second.opportunity_key == first.opportunity_key
    assert (
        connection.execute(
            sa.select(sa.func.count(sa.distinct(opportunity_representation.c.opportunity_key)))
        ).scalar()
        == 1
    )


# ─── §3 — deux opportunités déjà séparées ne fusionnent pas toutes seules ──────


def test_two_already_separate_opportunities_raise_an_explicit_conflict(
    connection: sa.Connection,
):
    persist_facts(connection, A, B)
    first = resolve(connection, A)
    second = resolve(connection, B)
    assert first.opportunity_key != second.opportunity_key

    with pytest.raises(OpportunityConflict) as excinfo:
        resolve(connection, A, linked_to=[B], link_strength="strong")

    message = str(excinfo.value)
    assert first.opportunity_key in message
    assert second.opportunity_key in message


def test_a_conflict_leaves_both_opportunities_and_all_facts_intact(
    connection: sa.Connection,
):
    """§3 — SÛRETÉ DES FAITS avant déduplication automatique."""
    persist_facts(connection, A, B)
    first = resolve(connection, A)
    second = resolve(connection, B)

    with pytest.raises(OpportunityConflict):
        resolve(connection, A, linked_to=[B], link_strength="strong")

    assert opportunity_of(connection, award_key(A)) == first.opportunity_key
    assert opportunity_of(connection, award_key(B)) == second.opportunity_key
    assert connection.execute(sa.select(sa.func.count()).select_from(contract_award)).scalar() == 2


def test_the_conflict_names_both_sides_so_a_human_can_arbitrate(
    connection: sa.Connection,
):
    persist_facts(connection, A, B)
    resolve(connection, A)
    resolve(connection, B)
    with pytest.raises(OpportunityConflict, match="réconciliation"):
        resolve(connection, B, linked_to=[A], link_strength="strong")


# ─── §4 — une représentation appartient à UNE seule opportunité ───────────────


def test_a_representation_can_never_be_attached_to_two_opportunities(
    connection: sa.Connection,
):
    """La contrainte est structurelle : la base refuse, pas seulement le code."""
    persist_facts(connection, A)
    resolved = resolve(connection, A)

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key=award_key(A),
                opportunity_key=f"autre-{resolved.opportunity_key}",
                created_at=NOW,
            )
        )


def test_many_representations_may_share_one_opportunity(connection: sa.Connection):
    persist_facts(connection, A, B, C)
    resolve(connection, A)
    resolve(connection, B, linked_to=[A], link_strength="strong")
    resolve(connection, C, linked_to=[B], link_strength="strong")
    assert (
        connection.execute(
            sa.select(sa.func.count()).select_from(opportunity_representation)
        ).scalar()
        == 3
    )


# ─── §7.E — un lien faible n'empêche rien, et ne réunit rien ──────────────────


@pytest.mark.parametrize("strength", ["probable", "unresolved", "ambiguous"])
def test_a_non_strong_link_never_collapses_two_representations(
    connection: sa.Connection, strength: str
):
    persist_facts(connection, A, B)
    first = resolve(connection, A)
    second = resolve(connection, B, linked_to=[A], link_strength=strength)

    assert second.opportunity_key != first.opportunity_key
    assert second.created is True


def test_a_weak_candidate_never_blocks_a_normal_materialization(
    connection: sa.Connection,
):
    """§7.E — l'existence d'un candidat non fort ne doit rien empêcher."""
    persist_facts(connection, A, B)
    resolve(connection, A)
    resolved = resolve(connection, B, linked_to=[A], link_strength="probable")
    assert resolved.opportunity_key
    assert opportunity_of(connection, award_key(B)) == resolved.opportunity_key


def test_only_a_strong_link_is_collapsible():
    assert COLLAPSIBLE_LINK_STRENGTHS == frozenset({"strong"})


# ─── invariants de forme ──────────────────────────────────────────────────────


def test_no_fuzzy_comparison_exists_in_the_module():
    """Aucun rapprochement flou dans le CODE, docstrings retirées."""
    import ast
    import inspect

    from signals.persistence import opportunity

    tree = ast.parse(inspect.getsource(opportunity))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value.value = ""
    code = ast.unparse(tree).lower()
    for forbidden in ("difflib", "levenshtein", "fuzz", "ratio", "similar", "distance"):
        assert forbidden not in code, forbidden


def test_the_resolver_never_reads_a_system_clock():
    import inspect

    assert (
        inspect.signature(resolve_or_create_opportunity).parameters["now"].default
        is inspect.Parameter.empty
    )


def test_a_resolved_opportunity_is_frozen(connection: sa.Connection):
    persist_facts(connection, A)
    resolved = resolve(connection, A)
    assert isinstance(resolved, ResolvedOpportunity)
    with pytest.raises(AttributeError):
        resolved.opportunity_key = "autre"  # type: ignore[misc]


def test_representations_are_returned_sorted(connection: sa.Connection):
    persist_facts(connection, A, B)
    resolve(connection, A)
    resolved = resolve(connection, B, linked_to=[A], link_strength="strong")
    assert list(resolved.representations) == sorted(resolved.representations)


def test_an_unmapped_award_has_no_opportunity(connection: sa.Connection):
    assert opportunity_of(connection, award_key(A)) is None


def test_two_unrelated_awards_stay_two_opportunities(connection: sa.Connection):
    persist_facts(connection, A, C)
    assert resolve(connection, A).opportunity_key != resolve(connection, C).opportunity_key
