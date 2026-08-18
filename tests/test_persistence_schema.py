"""SPEC-010 §3, §4, §5 — ce que le schéma promet, et ce qu'il refuse de dire.

Deux familles de tests.

Les premiers vérifient la **portabilité** : le schéma est déclaré une fois et
doit produire un DDL valide pour PostgreSQL comme pour SQLite. La compilation
du DDL PostgreSQL se fait sans serveur, ce qui rend la garantie de §3
vérifiable dans la suite ordinaire.

Les seconds vérifient la **doctrine**. `FAIT ≠ INFÉRENCE ≠ CERTITUDE
COMMERCIALE` n'est pas une intention de rédaction : aucun nom de colonne ne
doit pouvoir laisser croire qu'un besoin plausible est un achat confirmé.
"""

from __future__ import annotations

import re

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from signals.persistence.schema import (
    FACT_TABLES,
    FORBIDDEN_COLUMN_PATTERNS,
    INFERENCE_TABLES,
    METADATA,
    contract_award,
    evidence,
    materialized_signal,
    opportunity_representation,
    source_event,
)

ALL_TABLES = (
    source_event,
    contract_award,
    evidence,
    opportunity_representation,
    materialized_signal,
)


def columns(table: sa.Table) -> set[str]:
    return {column.name for column in table.columns}


# ─── §3 — portabilité PostgreSQL, testée sans serveur ──────────────────────────


@pytest.mark.parametrize("table", ALL_TABLES, ids=lambda table: table.name)
def test_every_table_compiles_to_postgresql_ddl(table: sa.Table):
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert ddl.startswith("\nCREATE TABLE")
    assert table.name in ddl


@pytest.mark.parametrize("table", ALL_TABLES, ids=lambda table: table.name)
def test_every_table_compiles_to_sqlite_ddl(table: sa.Table):
    """SQLite sert aux tests ; la production reste PostgreSQL."""
    assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=sqlite.dialect()))


def test_no_column_uses_a_postgresql_only_type():
    """Un type propre à un dialecte casserait l'exécution des tests sur SQLite."""
    for table in ALL_TABLES:
        for column in table.columns:
            module = type(column.type).__module__
            assert "dialects" not in module, f"{table.name}.{column.name} : {column.type!r}"


def test_json_payloads_use_the_portable_json_type():
    """`JSONB` serait plus rapide en production, et indisponible en test.

    Le gain n'est pas mesurable sur le volume actuel ; la portabilité, si.
    """
    json_columns = [
        (table.name, column.name)
        for table in ALL_TABLES
        for column in table.columns
        if isinstance(column.type, sa.JSON)
    ]
    assert json_columns, "le schéma porte bien des charges structurées"


def test_every_table_carries_explicit_timestamps():
    """§3 — horodatages explicites, jamais implicites."""
    for table in ALL_TABLES:
        assert "created_at" in columns(table), table.name


# ─── §5 — faits, inférences, et rien qui les confonde ──────────────────────────


def test_the_fact_and_inference_tables_are_declared_and_disjoint():
    assert FACT_TABLES and INFERENCE_TABLES
    assert set(FACT_TABLES).isdisjoint(INFERENCE_TABLES)
    assert set(FACT_TABLES) | set(INFERENCE_TABLES) == {table.name for table in ALL_TABLES}


def test_facts_live_in_the_fact_tables():
    assert set(FACT_TABLES) == {
        "source_event",
        "contract_award",
        "evidence",
        "opportunity_representation",
    }


def test_inferences_live_apart_from_the_facts():
    assert set(INFERENCE_TABLES) == {"materialized_signal"}


@pytest.mark.parametrize("table", ALL_TABLES, ids=lambda table: table.name)
def test_no_column_name_claims_a_confirmed_purchase(table: sa.Table):
    """§5 — `confirmed_need`, `purchase_intent`, `will_buy` et équivalents.

    Le nom d'une colonne survit à tous les commentaires : c'est lui qu'un
    développeur pressé lira dans six mois.
    """
    for column in table.columns:
        for pattern in FORBIDDEN_COLUMN_PATTERNS:
            assert not re.search(pattern, column.name), (
                f"{table.name}.{column.name} correspond au motif interdit {pattern!r}"
            )


def test_the_forbidden_patterns_actually_catch_the_named_examples():
    """Le garde-fou doit attraper ce que la SPEC nomme, sinon il ne garde rien."""
    for name in (
        "confirmed_need",
        "purchase_intent_confirmed",
        "will_buy",
        "needs_confirmed",
        "guaranteed_demand",
    ):
        assert any(re.search(pattern, name) for pattern in FORBIDDEN_COLUMN_PATTERNS), name


def test_the_need_column_is_named_as_a_plausibility():
    assert "plausible_needs" in columns(materialized_signal)
    assert "needs" not in columns(materialized_signal)


def test_the_contract_summary_is_named_as_an_inference():
    assert "inferred_contract_summary" in columns(materialized_signal)


# ─── §4, §6 — ce que chaque table doit porter ──────────────────────────────────


def test_the_source_event_identifies_the_originating_publication():
    assert {
        "event_key",
        "source_system",
        "source_notice_id",
        "source_country",
        "source_url",
        "published_at_raw",
        "published_on",
        "discovered_at",
    } <= columns(source_event)


def test_the_award_carries_the_four_contract_clocks_separately():
    """§6 — les horloges de SPEC-009E ne doivent jamais se replier l'une sur l'autre."""
    assert {
        "award_date",
        "contract_signature_date",
        "contract_notification_date",
        "contract_start_date",
        "contract_end_date",
    } <= columns(contract_award)


def test_the_award_carries_the_customer_relevant_facts():
    assert {
        "award_key",
        "event_key",
        "source_award_id",
        "lot_identifier",
        "title",
        "cpv_main",
        "amount",
        "currency",
        "winner_status",
        "awardee_parties",
        "place_country",
    } <= columns(contract_award)


def test_evidence_can_be_traced_back_to_its_source():
    assert {
        "source_system",
        "source_notice_id",
        "source_url",
        "source_kind",
        "path",
        "excerpt",
        "engine_version",
    } <= columns(evidence)


def test_the_materialized_signal_reproduces_every_clock_after_reload():
    assert {
        "materialized_recency_status",
        "materialized_primary_event",
        "materialized_award_clock_status",
        "materialized_notification_clock_status",
        "materialized_publication_clock_status",
        "materialized_award_age_days",
        "materialized_notification_age_days",
        "materialized_publication_age_days",
        "materialized_as_of",
        "recency_policy_version",
    } <= columns(materialized_signal)


def test_no_recency_column_can_be_mistaken_for_current_truth():
    """Closeout §1 — chaque colonne de fraîcheur dit qu'elle est un instantané."""
    for name in columns(materialized_signal):
        if "recency" in name or "clock" in name or "age_days" in name or name == "as_of":
            assert name.startswith("materialized_") or name == "recency_policy_version", name


def test_the_materialized_signal_carries_its_engine_provenance():
    assert "engine_versions" in columns(materialized_signal)


def test_the_materialized_signal_carries_its_revision():
    """§7 — le signal logique et la révision matérialisée sont distincts."""
    assert {"signal_key", "revision", "materialized_at"} <= columns(materialized_signal)


def test_the_revision_is_driven_by_a_content_fingerprint():
    """Closeout §4 — un changement de contenu doit être détectable sans version."""
    assert "content_fingerprint" in columns(materialized_signal)


def test_the_materialized_signal_references_its_client_owned_target_icp():
    """Closeout §3 — un signal appartient à un TargetICP possédé par UN compte."""
    assert "target_icp_id" in columns(materialized_signal)
    assert "icp_id" not in columns(materialized_signal)
    assert "account_id" not in columns(materialized_signal), "aucun compte fictif anticipé"


def test_the_materialized_signal_points_at_an_opportunity_not_only_a_source_award():
    """Closeout §2 — l'identité montrée au client est celle du contrat réel."""
    assert {"opportunity_key", "materialization_award_key"} <= columns(materialized_signal)


def test_an_opportunity_records_every_source_representation_it_collapses():
    assert {"opportunity_key", "award_key"} <= columns(opportunity_representation)


def test_a_source_representation_belongs_to_exactly_one_opportunity():
    """Closeout §4 — `award_key` est la clé primaire, donc unique par construction."""
    assert [c.name for c in opportunity_representation.primary_key.columns] == ["award_key"]


def test_the_signal_names_its_materialization_representation_explicitly():
    """Closeout §6 — un champ `award_key` sur un signal serait pris pour l'identité."""
    assert "materialization_award_key" in columns(materialized_signal)
    assert "award_key" not in columns(materialized_signal)


def test_no_marketing_copy_is_stored_as_a_source_of_truth():
    """§4 — la phrase client se régénère du statut ; la stocker la ferait diverger."""
    for name in columns(materialized_signal):
        assert "claim_text" not in name
        assert "copy" not in name


# ─── intégrité relationnelle ───────────────────────────────────────────────────


def test_every_table_declares_a_primary_key():
    for table in ALL_TABLES:
        assert list(table.primary_key.columns), table.name


def test_the_award_is_bound_to_its_source_event():
    assert any(
        constraint.column_keys == ["event_key"]
        for constraint in contract_award.foreign_key_constraints
    )


def test_the_signal_is_bound_to_the_award_that_materialized_it():
    assert any(
        constraint.column_keys == ["materialization_award_key"]
        for constraint in materialized_signal.foreign_key_constraints
    )


def test_one_logical_signal_exists_per_award_and_icp_context():
    """§7 — la contrainte d'unicité est ce qui rend l'idempotence structurelle."""
    unique = {
        tuple(sorted(constraint.columns.keys()))
        for constraint in materialized_signal.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert ("opportunity_key", "target_icp_id") in unique


def test_the_metadata_holds_exactly_the_declared_tables():
    assert set(METADATA.tables) == {table.name for table in ALL_TABLES}
