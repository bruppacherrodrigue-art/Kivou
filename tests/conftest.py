"""Fabriques partagées pour les tests du vérificateur commercial (SPEC-009A).

Une vue aveugle synthétique, façonnable trait par trait. Elle a exactement la
forme produite par SPEC-009 — c'est ce qui garantit que ces tests portent sur le
vrai contrat d'entrée, et pas sur une structure inventée pour l'occasion.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import re
import shutil
import warnings
from typing import Any

import pytest
from filelock import FileLock

_FULL_BENCHMARK_SUITES = frozenset(
    {
        "test_contract100_benchmark.py",
        "test_document100_benchmark.py",
        "test_winner100_benchmark.py",
    }
)

# These modules exercise historical upgrade/downgrade transitions, revision
# topology, or dialect-specific migration SQL.  Keep the list exact: an
# ordinary application test mentioning "migration" must remain in the fast
# suite unless it deliberately joins this exhaustive CI gate.
EXHAUSTIVE_MIGRATION_SUITES = frozenset(
    {
        "test_accounts_migration_and_ownership.py",
        "test_acquisition_migration.py",
        "test_acquisition_runtime_authorization_migration.py",
        "test_acquisition_runtime_migration.py",
        "test_alert_recipient_context_migration.py",
        "test_campaign_factory_migration.py",
        "test_card_presentation_migration.py",
        "test_company_engagement_migration.py",
        "test_company_research_migration.py",
        "test_compliance_migration.py",
        "test_contact_discovery_migration.py",
        "test_contact_waterfall_migration.py",
        "test_contract_award_text_capacity_migration.py",
        "test_conversion_tracking_migration.py",
        "test_decision_engine_migration.py",
        "test_for_you_sentence_migration.py",
        "test_ingestion_migration.py",
        "test_learning_migration.py",
        "test_persistence_migrations.py",
        "test_personalization_migration.py",
        "test_portal_capture_migration.py",
        "test_reliability_operations_migration.py",
        "test_response_intelligence_migration.py",
        "test_saas_company_migration.py",
        "test_signal_notes_migration.py",
        "test_supplier_directory_migration.py",
        "test_supplier_discovery_migration.py",
        "test_transactional_email_migration.py",
        "test_winner_enrichment_migration.py",
    }
)


def is_slow_suite_path(path: pathlib.Path) -> bool:
    """Route only full corpus gates and exhaustive migration modules to CI."""

    return path.name in _FULL_BENCHMARK_SUITES or path.name in EXHAUSTIVE_MIGRATION_SUITES


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if is_slow_suite_path(pathlib.Path(str(item.path))):
            item.add_marker(pytest.mark.slow)


def copy_migrated_sqlite_template(
    template: pathlib.Path, destination: pathlib.Path
) -> pathlib.Path:
    """Copy the immutable HEAD-schema template to a fresh test-owned database."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, destination)
    return destination


def shared_migrated_sqlite_template_path(worker_basetemp: pathlib.Path) -> pathlib.Path:
    """Return one template path shared by every xdist worker in this run."""

    session_root = (
        worker_basetemp.parent
        if worker_basetemp.name.startswith("popen-gw")
        else worker_basetemp
    )
    return session_root / "kivou-migrated-head.db"


@pytest.fixture(scope="session")
def migrated_sqlite_template(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Build one clean SQLite database at Alembic HEAD for the whole pytest run."""

    from signals.persistence.database import create_database_engine, migrate_to_latest

    template = shared_migrated_sqlite_template_path(tmp_path_factory.getbasetemp())
    template.parent.mkdir(parents=True, exist_ok=True)
    lock = template.with_suffix(".lock")
    with FileLock(lock):
        if not template.exists():
            partial = template.with_name(f".{template.name}.{os.getpid()}.part")
            engine = create_database_engine(f"sqlite+pysqlite:///{partial}")
            try:
                migrate_to_latest(engine)
            finally:
                engine.dispose()
            partial.replace(template)
    return template


@pytest.fixture
def migrated_sqlite_path(
    migrated_sqlite_template: pathlib.Path, tmp_path: pathlib.Path
) -> pathlib.Path:
    """Give one test an isolated copy of the worker's migrated template."""

    return copy_migrated_sqlite_template(migrated_sqlite_template, tmp_path / "kivou-head.db")


@pytest.fixture
def migrated_sqlite_engine(migrated_sqlite_path: pathlib.Path):
    """Open and dispose a per-test engine backed by an isolated HEAD-schema copy."""

    from signals.persistence.database import create_database_engine

    engine = create_database_engine(f"sqlite+pysqlite:///{migrated_sqlite_path}")
    try:
        yield engine
    finally:
        engine.dispose()


def make_blind(**overrides: Any) -> dict[str, Any]:
    """Une vue aveugle plausible et complète, modifiable par sections.

    Les surcharges sont fusionnées section par section : un test qui ne veut
    changer que le timing n'a pas à réécrire le contrat entier.
    """
    blind: dict[str, Any] = {
        "signal_id": "a" * 64,
        "source": "simap",
        "publication_date": "2026-08-10",
        "source_url": "https://www.simap.ch/api/publications/v1/project/p/publication-details/q",
        "winner": {
            "status": "identified",
            "parties": [
                {
                    "name": None,
                    "is_group": False,
                    "members": [
                        {
                            "legal_name": "Bauunternehmung Meier AG",
                            "country": "CH",
                            "identifiers": [],
                            "address": "Industriestrasse 4, 3000 Bern",
                            "website": None,
                            "role": "sole",
                        }
                    ],
                }
            ],
        },
        "contract": {
            "title": "Travaux de gros oeuvre pour la nouvelle ecole primaire",
            "lot_title": None,
            "contract_reference": "LOT-01",
            "description": (
                "Le marche porte sur les travaux de gros oeuvre, les fondations et la "
                "structure porteuse du batiment scolaire, avec une duree de chantier de "
                "dix-huit mois et des interventions sur un site en exploitation."
            ),
            "cpv_main": "45214200",
            "cpv_additional": [],
            "value": {"amount": "4200000", "currency": "CHF", "vat_category": None},
            "place_of_performance": {"country": "CH", "locality": "Bern"},
            "buyers": [{"legal_name": "Stadt Bern", "country": "CH"}],
        },
        "contract_understanding": {
            "contract_type": "construction",
            "sector": "education",
            "object_summary": "Travaux de gros oeuvre pour une ecole primaire a Bern",
            "characteristics": ["chantier de longue duree"],
            "facts": {"amount": "4200000 CHF"},
            "buyer_country": "CH",
            "place_of_performance": {"country": "CH", "locality": "Bern"},
            "timing": {
                "published_at": "2026-08-10",
                "award_date": "2026-08-01",
                "contract_signature_date": None,
                "contract_start_date": "2026-09-15",
                "contract_end_date": "2028-03-15",
                "duration_value": 18,
                "duration_unit": "month",
                "days_between_award_and_start": 45,
                "contract_span_days": 547,
                "derived_from": ["award", "duration"],
            },
        },
        "derived_needs": [
            {
                "category": "workforce_capacity",
                "statement": "Un besoin de capacite en personnel de chantier peut devenir pertinent.",
                "reasoning": (
                    "Un chantier de gros oeuvre de dix-huit mois mobilise des equipes "
                    "que l'attributaire peut ne pas avoir entierement disponibles."
                ),
                "timing": "near_term",
                "externalisability": "high",
                "confidence": "medium",
                "evidence_refs": [],
                "supporting_facts": [],
                "source_mode": "metadata_fallback",
            }
        ],
        "icp": {
            "icp_id": "icp-staffing-ch",
            "name": "Agence d'interim BTP — Suisse",
            "offer_summary": "Mise a disposition de personnel qualifie pour chantiers.",
            "primary_need_categories": ["workforce_capacity"],
            "secondary_need_categories": ["specialist_subcontracting"],
            "territories": [{"country": "CH", "subdivision_code": None}],
            "geography_basis": "place_of_performance",
            "geography_policy": "required",
            "included_contract_types": [],
            "excluded_contract_types": ["it_digital", "research"],
            "included_sectors": [],
            "excluded_sectors": [],
            "value_thresholds": [
                {"currency": "CHF", "minimum_amount": 250000.0, "maximum_amount": None}
            ],
            "maximum_signal_age_days": 90,
            "preferred_timings": ["immediate", "near_term", "recurring"],
        },
        "evidence_refs": [
            {
                "source_system": "simap",
                "source_kind": "publication_field",
                "source_notice_id": "q",
                "source_procedure_id": "p",
                "source_url": "https://www.simap.ch/api/publications/v1/project/p/x/q",
                "path": "procurement.cpvCode.code",
                "raw_value": "45214200",
                "excerpt": None,
            },
            {
                "source_system": "simap",
                "source_kind": "publication_field",
                "source_notice_id": "q",
                "source_procedure_id": "p",
                "source_url": "https://www.simap.ch/api/publications/v1/project/p/x/q",
                "path": "procurement.description",
                "raw_value": None,
                "excerpt": "Travaux de gros oeuvre",
            },
        ],
        "source_mode": "metadata_fallback",
        "disclosure": (
            "Need inferred from public award information. "
            "No validated execution requirement was available."
        ),
    }

    for section, value in overrides.items():
        if isinstance(value, dict) and isinstance(blind.get(section), dict):
            merged = {**blind[section], **value}
            # Le timing est imbriqué : le surcharger partiellement doit rester possible.
            if "timing" in value and isinstance(value["timing"], dict):
                merged["timing"] = {**blind[section]["timing"], **value["timing"]}
            blind[section] = merged
        else:
            blind[section] = value
    return blind


@pytest.fixture
def blind() -> dict[str, Any]:
    return make_blind()


# ─── Bases PostgreSQL jetables ────────────────────────────────────────────────
#
# Un scénario rejoué contre un vrai PostgreSQL crée une base par test. Sans
# suppression, chaque test laisse une base ET un pool de connexions vivants sur
# le serveur : une suite complète finit par épuiser `max_connections`, et les
# échecs qui en résultent n'ont plus aucun rapport avec le code testé.

_DISPOSABLE_DATABASES: list[tuple] = []


def disposable_database_url(admin_url: str, name: str) -> str:
    """L'URL d'une base jetable, dérivée de celle de l'administration.

    Deux pièges se rejoignent ici, et le second a réellement cassé
    l'authentification pendant cette PR :

    - découper l'URL à la main (`rsplit`) perd ses paramètres — `?sslmode=require`
      disparaît, et la base jetable se connecte autrement que l'admin qui vient
      de réussir ;
    - `str(URL)` MASQUE le mot de passe en `***`, ce qui produit une URL
      d'apparence correcte et une authentification refusée.

    `render_as_string(hide_password=False)` est la seule forme connectable.
    `str()` reste la seule forme journalisable — les deux coexistent, et les
    confondre fait soit échouer la connexion, soit fuiter un secret.
    """
    import sqlalchemy as sa

    return sa.engine.make_url(admin_url).set(database=name).render_as_string(
        hide_password=False
    )


def register_disposable_database(engine, admin, name: str) -> None:
    """Inscrit une base jetable à supprimer après le test en cours."""
    _DISPOSABLE_DATABASES.append((engine, admin, name))


#: Les nettoyages qui ont ÉCHOUÉ, cumulés sur toute la session. Un test qui a
#: réussi ne doit pas devenir rouge à cause d'un démontage, mais la SESSION doit
#: l'être : sans cela, la suite resterait verte pendant que les bases
#: s'accumulent — exactement la panne que ce nettoyage existe pour empêcher.
_CLEANUP_FAILURES: list[str] = []


def _redact(text: str) -> str:
    """Retire d'un message toute forme d'identifiant de connexion.

    Les erreurs de pilote citent volontiers l'URL qui a échoué, mot de passe
    compris. Ce texte part dans un avertissement puis dans un rapport de CI :
    il ne doit rien porter qui ouvre quoi que ce soit.
    """
    without_credentials = re.sub(r"://[^\s/@]*@", "://<masque>@", text)
    return re.sub(r"(?i)(password|pwd)\s*=\s*\S+", r"\1=<masque>", without_credentials)


def drain_disposable_databases(registry: list[tuple]) -> list[str]:
    """Supprime TOUTES les bases inscrites, et rend les échecs rencontrés.

    Chaque base est traitée isolément : un échec sur la première ne doit pas
    laisser les suivantes derrière elle. Les erreurs sont donc collectées, pas
    propagées — et c'est la fin de session qui les rend visibles.

    Extrait de la fixture pour être testable : prouver « la seconde base est
    tout de même supprimée » demande de provoquer un échec sur la première, ce
    qu'un test ne peut pas faire à travers un `yield`.
    """
    import sqlalchemy as sa

    failures: list[str] = []
    while registry:
        engine, admin, name = registry.pop()
        try:
            engine.dispose()
            with admin.connect() as connection:
                connection.execution_options(isolation_level="AUTOCOMMIT").execute(
                    sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                )
        except Exception as error:  # noqa: BLE001 - on collecte, on n'interrompt pas
            failures.append(f"{name} : {type(error).__name__}: {_redact(str(error))}")
        finally:
            with contextlib.suppress(Exception):
                admin.dispose()
    return failures


@pytest.fixture(autouse=True)
def _drop_disposable_databases():
    """Supprime, après CHAQUE test, les bases jetables qu'il a créées.

    Placé ici plutôt que dans la fixture qui les crée : trois fichiers
    l'appellent directement via `__wrapped__`, et ne bénéficieraient donc pas
    d'un nettoyage attaché à cette seule fixture.
    """
    yield
    failures = drain_disposable_databases(_DISPOSABLE_DATABASES)
    if failures:
        _CLEANUP_FAILURES.extend(failures)
        warnings.warn(
            "nettoyage de base jetable en échec : " + " | ".join(failures),
            stacklevel=2,
        )


def pytest_sessionfinish(session, exitstatus):
    """Rend la SESSION rouge si un nettoyage a échoué.

    Un avertissement seul laisserait la suite verte pendant que les bases
    s'accumulent, et la panne ressurgirait bien plus tard — épuisement de
    `max_connections` ou de disque — dans une exécution sans rapport. C'est
    précisément le troc « échec franc contre dérive silencieuse » que ce
    correctif défait.
    """
    if not _CLEANUP_FAILURES:
        return
    session.exitstatus = 1
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "nettoyage des bases jetables EN ÉCHEC", red=True)
        for failure in _CLEANUP_FAILURES:
            reporter.write_line(f"  - {failure}")
        reporter.write_line(
            "  Ces bases subsistent sur le serveur : la session est marquée en échec "
            "pour que l'accumulation ne passe pas inaperçue."
        )
