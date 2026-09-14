from __future__ import annotations

import datetime as dt
from pathlib import Path

from signals.personalization.prospect_mail import (
    RenderedProspectMail,
    client_work_description,
    is_prospect_relevance_sentence,
    load_prospect_mail_catalog,
    prospect_relevance_sentence,
    render_prospect_mail,
    validate_prospect_mail,
)


def arbonis_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "director_name": "ARNAUD FRANÇOIS BERNARD JOSEPH LEFEBVRE",
        "family_key": "timber_carpentry",
        "signal_holder": "PAUL BROCHIER",
        "signal_subject": "26A0076 LOT 01 CHARPENTE / ISOLATION / COUVERTURE / ZINGUERIE",
        "signal_amount_minor_units": 25_827_634,
        "signal_currency": "eur",
        "signal_city": None,
        "signal_department": "Isère",
        "signal_decision_date": dt.date(2026, 9, 8),
        "attribution_url": "https://kivou.eu/a/kat1.signal-token",
        "signal_source_url": "https://www.boamp.fr/avis/26A0076",
        "unsubscribe_url": "https://kivou.eu/unsubscribe/unsubscribe-token",
    }
    row.update(changes)
    return row


def test_renders_the_complete_arbonis_mail_from_the_single_catalog() -> None:
    mail = render_prospect_mail(arbonis_row())

    assert mail.subject == "Paul Brochier vient de gagner un chantier charpente en Isère"
    assert mail.text.startswith("Bonjour Monsieur Lefebvre,")
    assert "Sur ce type de lot, le titulaire sous-traite souvent" in mail.text
    assert "Rodrigue / Kivou · kivou.eu" in mail.text
    assert "P.S. : Vous travaillez sur ce type de chantier ?" in mail.text
    assert "Kivou, Sion (Suisse)" not in mail.text
    assert mail.word_count <= 110
    assert mail.contract_status == "passed"
    assert mail.contract_failure is None
    assert mail.html.count("href=") == 2
    assert mail.html.count('href="https://kivou.eu/a/kat1.signal-token"') == 1
    assert '>Voir le marché</a>' in mail.html
    assert '>https://kivou.eu/a/kat1.signal-token</a>' not in mail.html
    assert "https://www.boamp.fr/avis/26A0076" not in mail.text
    assert mail.html.count('href="https://kivou.eu/unsubscribe/unsubscribe-token"') == 1
    assert '>Ne plus recevoir</a>' in mail.html
    assert '>https://kivou.eu/unsubscribe/unsubscribe-token</a>' not in mail.html


def test_client_work_description_removes_the_lot_reference() -> None:
    assert client_work_description(
        "26A0076 LOT 01 CHARPENTE / ISOLATION / COUVERTURE / ZINGUERIE"
    ) == "la charpente, l'isolation et la couverture"


def test_shared_relevance_sentence_is_the_exact_mail_family_sentence() -> None:
    assert prospect_relevance_sentence(
        family_key="roofing",
        company_city="SILLINGY",
        department="Savoie",
    ) == (
        "Sur ce type de lot, le titulaire sous-traite souvent la couverture et la "
        "zinguerie, et vous êtes couvreur-zingueur à Sillingy."
    )


def test_uses_plain_greeting_city_and_family_copy_without_raw_title() -> None:
    mail = render_prospect_mail(
        arbonis_row(
            director_name=None,
            family_key="roofing",
            signal_city="Grenoble",
            signal_department="Isère",
            signal_amount_minor_units=120_000_000,
        )
    )

    assert mail.subject == "Paul Brochier vient de gagner un chantier couverture à Grenoble"
    assert mail.text.startswith("Bonjour,\n\n")
    assert "— 1,2 M€, attribué le 8 septembre." in mail.text
    assert "Sur ce type de lot, le titulaire sous-traite souvent" in mail.text
    assert "LOT 01" not in mail.subject
    assert "LOT 01" not in mail.text
    assert "26A0076" not in mail.subject
    assert "26A0076" not in mail.text
    assert mail.contract_status == "passed"
    assert mail.contract_failure is None


def test_contract_rejects_a_retired_fragment_and_overlong_body() -> None:
    retired = "Vous fournissez " + "ou réalisez"
    invalid = RenderedProspectMail(
        subject="PAUL BROCHIER vient de gagner un chantier charpente en Isère",
        text=(
            "Bonjour,\n\n"
            + retired
            + " "
            + "mot " * 91
            + "\n\nBien à vous,\nRodrigue Bruppacher\nKivou\n\n—\n"
            + "Source : https://example.test/source\n"
            + "https://kivou.eu/a/token\nhttps://kivou.eu/unsubscribe/token"
        ),
        html="",
        word_count=92,
        contract_status="passed",
        contract_failure=None,
    )

    assert (
        validate_prospect_mail(
            invalid,
            raw_subject="26A0076 LOT 01 CHARPENTE",
            director_name=None,
        )
        == "body_contains_forbidden_fragment"
    )


def test_contract_rejects_raw_url_labels_in_html() -> None:
    mail = render_prospect_mail(arbonis_row())
    invalid = RenderedProspectMail(
        subject=mail.subject,
        text=mail.text,
        html=mail.html.replace(
            ">Voir le marché</a>",
            ">Lien technique</a>",
        ),
        word_count=mail.word_count,
        contract_status="passed",
        contract_failure=None,
    )

    assert (
        validate_prospect_mail(
            invalid,
            raw_subject=str(arbonis_row()["signal_subject"]),
            director_name="Arnaud Lefebvre",
        )
        == "html_link_label_invalid"
    )


def test_normalizes_compound_first_name_and_city_to_regular_case() -> None:
    mail = render_prospect_mail(
        arbonis_row(
            director_name="JEAN-PIERRE LOUIS DUPONT",
            signal_city="SAINT-ÉTIENNE",
        )
    )

    assert mail.text.startswith("Bonjour Monsieur Dupont,")
    assert mail.subject.endswith("à Saint-Étienne")
    assert mail.contract_status == "passed"


def test_keeps_a_surname_particle_in_the_greeting() -> None:
    mail = render_prospect_mail(arbonis_row(director_name="ADIL EL MANSOURI"))

    assert mail.text.startswith("Bonjour,\n\n")
    assert mail.contract_status == "passed"


def test_every_supplier_family_has_reviewed_mail_copy() -> None:
    from signals.supplier_discovery.families import load_supplier_family_catalog

    configured = {
        family.key
        for families in load_supplier_family_catalog().values()
        for family in families
    }
    source = Path("ops/config/prospect-mail.yaml").read_text(encoding="utf-8")
    catalog = load_prospect_mail_catalog()

    assert all(f"  {family_key}:" in source for family_key in configured)
    assert configured == set(catalog.families)
    assert all(
        copy.sentence.startswith("Sur ce type de lot, le titulaire sous-traite souvent ")
        and copy.trade_label
        for copy in catalog.families.values()
    )


def test_v2_contract_uses_civility_normalized_company_and_required_copy() -> None:
    mail = render_prospect_mail(
        arbonis_row(
            company_name="DUBOURGEAT EN ABREGE DUBOURGEAT SAS (RCS LYON)",
            director_name="JEAN DUPONT",
            family_key="roofing",
            signal_city="Grenoble",
            company_city="Saint-Étienne",
            distance_km=58,
        )
    )
    assert mail.text.startswith("Bonjour Monsieur Dupont,")
    assert "Paul Brochier vient d'être retenu" in mail.text
    assert (
        "Sur ce type de lot, le titulaire sous-traite souvent la couverture et la "
        "zinguerie, et vous êtes couvreur-zingueur à Saint-Étienne, à 58 km du chantier."
    ) in mail.text
    assert "Kivou repère les marchés publics attribués près de chez vous" in mail.text
    assert "Rodrigue / Kivou · kivou.eu" in mail.text
    assert (
        "P.S. : Vous travaillez sur ce type de chantier ? Un mot en retour et je vous "
        "envoie les prochains marchés de votre secteur."
    ) in mail.text
    assert "Kivou, Sion (Suisse)" not in mail.text
    assert "https://www.boamp.fr/avis/26A0076" not in mail.text
    assert mail.word_count <= 110
    assert mail.contract_status == "passed"


def test_v2_unknown_civility_uses_plain_greeting() -> None:
    mail = render_prospect_mail(arbonis_row(director_name="QZ DUPONT"))
    assert mail.text.startswith("Bonjour,")
    assert "Bonjour Xavier" not in mail.text


def test_corrected_v2_renders_alpes_zinguerie_contract() -> None:
    mail = render_prospect_mail(
        arbonis_row(
            company_name="ALPES ZINGUERIE",
            company_city="SILLINGY",
            director_name="GREGORY PAUVERT",
            family_key="roofing",
            signal_holder="CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD",
            signal_city=None,
            signal_department="Savoie",
            signal_source_url="https://data.economie.gouv.fr/source/decp",
        )
    )

    body, separator, footer = mail.text.partition("\n\n—\n")
    assert separator
    assert body.startswith("Bonjour Monsieur Pauvert,")
    assert mail.subject.startswith("CMCD vient de gagner")
    assert "CMCD vient d'être retenu" in body
    assert (
        "Sur ce type de lot, le titulaire sous-traite souvent la couverture et la "
        "zinguerie, et vous êtes couvreur-zingueur à Sillingy."
    ) in body
    assert "https://data.economie.gouv.fr/source/decp" not in mail.text
    assert "Source : registres publics et avis d'attribution officiel." in footer
    assert body.index("Kivou repère les marchés publics") < body.index("Bien à vous,")
    assert "Bien à vous,\nRodrigue / Kivou · kivou.eu" in body
    assert body.endswith(
        "P.S. : Vous travaillez sur ce type de chantier ? Un mot en retour et je vous "
        "envoie les prochains marchés de votre secteur."
    )
    assert mail.html.count("href=") == 2
    assert mail.word_count <= 110
    assert mail.contract_status == "passed"


def test_recognizes_only_a_sentence_from_the_reviewed_mail_catalogue() -> None:
    sentence = prospect_relevance_sentence(
        family_key="roofing",
        company_city="SILLINGY",
    )

    assert is_prospect_relevance_sentence(sentence) is True
    assert is_prospect_relevance_sentence("Votre offre peut intéresser ce titulaire.") is False
