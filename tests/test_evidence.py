"""`Evidence` — la preuve canonique, source-agnostique.

Une preuve dit d'où vient une information et permet d'y revenir. Elle doit
servir aujourd'hui à un champ XML TED ou JSON SIMAP, et demain à un passage
d'un cahier des charges, sans changer de forme.

Deux natures à ne jamais confondre : un **fait source** (la source l'a publié)
et une **affirmation dérivée** (nous l'avons conclu).
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from signals.domain import Evidence

# ─── Fait source ────────────────────────────────────────────────────────────────


def test_une_preuve_de_champ_conserve_le_chemin_et_la_valeur_publiee():
    evidence = Evidence(
        source_system="simap",
        source_kind="publication_field",
        source_notice_id="223ceb19-b3d4-4556-a417-84c1d5f7a3a9",
        source_procedure_id="0d2599e8-c839-4d7d-9277-63144b4750b0",
        source_url="https://www.simap.ch/api/publications/v1/project/x/publication-details/y",
        path="decision.vendors[0].price.price",
        raw_value="934877.50",
    )
    assert evidence.path == "decision.vendors[0].price.price"
    assert evidence.raw_value == "934877.50"
    assert evidence.is_derived is False


def test_une_preuve_textuelle_conserve_l_extrait_sans_le_reecrire():
    extrait = "<p>Die Gemeinde Root realisiert ein neues Schulhaus.&nbsp;</p>"
    evidence = Evidence(
        source_system="simap",
        source_kind="publication_text",
        path="procurement.orderDescription.de",
        excerpt=extrait,
    )
    assert evidence.excerpt == extrait  # ni nettoyé, ni tronqué, ni traduit


def test_une_preuve_ted_et_une_preuve_simap_partagent_le_meme_modele():
    ted = Evidence(
        source_system="ted",
        source_kind="publication_field",
        source_notice_id="e60ad0f2-da33-4bba-a8be-e114319bbb5d",
        path="cac:ProcurementProject/cac:MainCommodityClassification",
        raw_value="79710000",
    )
    simap = Evidence(
        source_system="simap",
        source_kind="publication_field",
        source_notice_id="223ceb19",
        path="procurement.cpvCode.code",
        raw_value="45214200",
    )
    assert type(ted) is type(simap)
    assert set(type(ted).model_fields) == set(type(simap).model_fields)


# ─── Affirmation dérivée ────────────────────────────────────────────────────────


def test_une_preuve_derivee_porte_la_version_du_moteur():
    evidence = Evidence(
        source_system="simap",
        source_kind="derived",
        path="contract_type",
        raw_value="construction",
        engine_version="contract-understanding-v0.1",
    )
    assert evidence.is_derived is True
    assert evidence.engine_version == "contract-understanding-v0.1"


def test_une_affirmation_derivee_sans_version_de_moteur_est_refusee():
    """Sans version, impossible de savoir quelles règles ont produit le résultat."""
    with pytest.raises(ValidationError, match="engine_version"):
        Evidence(source_system="ted", source_kind="derived", path="contract_type")


def test_un_fait_source_ne_peut_pas_porter_une_version_de_moteur():
    """Un fait publié n'a pas été produit par un moteur : le confondre serait faux."""
    with pytest.raises(ValidationError, match="fait source"):
        Evidence(
            source_system="ted",
            source_kind="publication_field",
            path="cbc:ID",
            raw_value="x",
            engine_version="contract-understanding-v0.1",
        )


# ─── Immuabilité et ouverture ───────────────────────────────────────────────────


def test_une_preuve_est_immuable():
    """Une nouvelle analyse crée une nouvelle preuve, elle ne réécrit pas l'ancienne."""
    evidence = Evidence(source_system="ted", source_kind="publication_field", path="x")
    with pytest.raises(ValidationError):
        evidence.raw_value = "modifié"


def test_le_modele_accepte_deja_un_document_de_marche():
    """Readiness SPEC-006 : aucune migration conceptuelle ne sera nécessaire."""
    evidence = Evidence(
        source_system="simap",
        source_kind="tender_document",
        source_procedure_id="f5fba859-017d-4af2-baa5-2ffbca4e0065",
        source_url="https://example.invalid/cahier-des-charges.pdf",
        path="page 12, section 3.2",
        excerpt="Le titulaire assure la maintenance préventive.",
        retrieved_at=dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.UTC),
    )
    assert evidence.source_kind == "tender_document"
    assert evidence.is_derived is False


def test_le_modele_accepte_un_registre():
    evidence = Evidence(
        source_system="ted",
        source_kind="registry",
        source_url="https://ec.europa.eu/taxation_customs/vies/rest-api/ms/LU/vat/26538172",
        path="name",
        raw_value="WISAG CLEANING SERVICE S.A R.L.",
    )
    assert evidence.source_kind == "registry"


def test_un_type_de_source_inconnu_est_refuse():
    with pytest.raises(ValidationError):
        Evidence(source_system="ted", source_kind="rumeur", path="x")


def test_une_preuve_vide_de_contenu_est_refusee():
    """Une preuve qui ne montre rien ne prouve rien."""
    with pytest.raises(ValidationError, match="ne montre rien"):
        Evidence(source_system="ted", source_kind="publication_field")
