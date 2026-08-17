"""Document-100 — ce que 100 attributions TED réelles disent de l'accès aux dossiers.

Corpus : les 100 avis d'attribution publiés les plus récents au 16 août 2026,
chacun suivi jusqu'à ses documents (`tests/fixtures/documents/document100.json`).

Ce que le corpus a mesuré, et que ces tests figent :

    identifiant de procédure (BT-04)      100 / 100
    avis d'appel d'offres retrouvé         74 / 100
    URL documentaire publiée (BT-15)       74 /  74   des avis retrouvés
    fichier réellement téléchargeable       1 /  75   des URL suivies

La dernière ligne est le fait central de SPEC-006 : **TED ne sert pas les
documents, il publie l'adresse d'un portail national**. Un moteur qui traiterait
cette adresse comme un document annoncerait des dossiers vides ; un moteur qui
traiterait son inaccessibilité comme une absence effacerait des marchés qui ont
bel et bien un cahier des charges.
"""

from __future__ import annotations

import collections
import json
import pathlib

import pytest

from signals.documents import TenderDocument, coverage_for

CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "documents" / "document100.json").read_text()
)
RECORDS = CORPUS["records"]
STATUSES = collections.Counter(
    document["status"] for record in RECORDS for document in record["documents"]
)


def _documents(record: dict) -> tuple[TenderDocument, ...]:
    return tuple(
        TenderDocument(
            source_system="ted",
            source_procedure_id=record["procedure_id"],
            source_notice_id=record["tender_notice"],
            source_url=document["url"],
            media_type=document["media_type"],
            access_status=document["status"],
            content_hash=document["content_hash"],
            byte_size=document["bytes"],
        )
        for document in record["documents"]
    )


class TestCorpusShape:
    def test_the_corpus_holds_one_hundred_real_awards(self) -> None:
        assert len(RECORDS) == 100
        assert len({record["award"] for record in RECORDS}) == 100

    def test_every_award_carries_its_procedure_identifier(self) -> None:
        assert all(record["procedure_id"] for record in RECORDS)


class TestAwardToTenderLinkage:
    def test_the_measured_linkage_rate_is_recorded(self) -> None:
        linked = sum(1 for record in RECORDS if record["tender_notice"])
        assert linked == 74, "taux mesuré : 74 % — sous la cible de 90 % de la spécification"

    def test_every_tender_notice_found_publishes_a_documents_url(self) -> None:
        linked = [record for record in RECORDS if record["tender_notice"]]
        assert all(record["document_urls"] for record in linked)


class TestAccessReality:
    def test_a_portal_page_is_the_normal_case_not_a_document(self) -> None:
        assert STATUSES["external"] == 66
        assert STATUSES["available"] == 1

    def test_the_downloadable_rate_is_the_finding_that_shapes_the_module(self) -> None:
        followed = sum(STATUSES.values())
        assert followed == 75
        assert STATUSES["available"] / followed < 0.02

    @pytest.mark.parametrize("record", RECORDS, ids=[r["award"] for r in RECORDS])
    def test_coverage_is_recomputed_identically_from_the_document_states(
        self, record: dict
    ) -> None:
        documents = _documents(record)
        computed = coverage_for(documents, 0)

        if not documents:
            assert computed == "no_documents"
            return
        expected = {
            "external": "external_only",
            "auth_required": "auth_required",
            "not_found": "download_failed",
            "download_failed": "download_failed",
            "available": "partial_documents",
        }[record["coverage"]]
        assert computed == expected

    def test_a_published_url_is_never_reported_as_no_documents(self) -> None:
        """Dès qu'une adresse a été publiée, le marché a un dossier.

        Qu'elle soit verrouillée, morte ou en panne ne change rien à ce fait :
        `no_documents` reste réservé aux procédures où **rien** n'a été référencé.
        """
        for record in RECORDS:
            if record["documents"]:
                assert coverage_for(_documents(record), 0) != "no_documents"


class TestPortalDispersion:
    def test_the_documents_live_on_dozens_of_national_portals(self) -> None:
        from urllib.parse import urlparse

        hosts = {
            urlparse(url).netloc for record in RECORDS for url in record["document_urls"] if url
        }
        assert len(hosts) >= 40, (
            "écrire un connecteur par portail n'est pas tenable : "
            f"{len(hosts)} hôtes distincts pour 74 procédures"
        )


# ─── Qualité des exigences : revue manuelle ─────────────────────────────────────

GOLD = json.loads(
    (
        pathlib.Path(__file__).parent / "fixtures" / "documents" / "requirements_gold.json"
    ).read_text()
)


class TestRequirementQualityGate:
    """40 exigences relues une à une, tirées de dossiers jamais inspectés.

    Le verdict manuel distingue une **exigence d'exécution du titulaire** de ce
    qui n'en est pas : règle de dépôt d'offre, condition de qualification,
    obligation de l'acheteur, fragment sans contenu normatif.

    Le chiffre mesuré — 52,5 % — est **en dessous** de la cible de SPEC-006. Ce
    test ne le maquille pas : il empêche qu'il baisse, et il baissera au premier
    élargissement imprudent des motifs.
    """

    def test_the_gold_review_is_intact(self) -> None:
        assert len(GOLD["rows"]) == 40
        assert sum(1 for row in GOLD["rows"] if row["verdict"] == "real") == 21

    def test_the_measured_precision_does_not_regress(self) -> None:
        from signals.documents import DeterministicExtractor, TextBlock

        extractor = DeterministicExtractor()
        extracted = [
            row
            for row in GOLD["rows"]
            if extractor.propose(
                TextBlock(locator="page 1", text=row["excerpt"], method="pdf_text")
            )
        ]
        real = [row for row in extracted if row["verdict"] == "real"]
        precision = len(real) / len(extracted)

        assert precision >= GOLD["measured"]["precision"], (
            f"précision retombée à {precision:.3f} sous les "
            f"{GOLD['measured']['precision']:.3f} relevés à la main"
        )

    def test_no_requirement_of_the_gold_set_lacks_its_excerpt(self) -> None:
        """La garantie qui, elle, tient : 100 % des exigences citent leur passage."""
        assert all(row["excerpt"].strip() for row in GOLD["rows"])


# ─── Rapprochement award → appel d'offres ───────────────────────────────────────


class TestLinkageMetrics:
    """SPEC-006R : séparer « je n'ai pas trouvé » de « il n'y a rien à trouver ».

    Un marché négocié sans publication préalable n'a **pas** d'appel d'offres
    public. Le compter comme un échec de rapprochement mesure la réalité du
    droit de la commande publique, pas la qualité du code.
    """

    def test_coverage_and_accuracy_are_two_different_numbers(self) -> None:
        from signals.documents.discovery import LinkageOutcome, linkage_metrics

        outcomes = [
            LinkageOutcome("a", "p1", "t1", "linked", verified=True),
            LinkageOutcome("b", "p2", "t2", "linked", verified=True),
            LinkageOutcome("c", "p3", None, "tender_not_publicly_resolvable"),
            LinkageOutcome("d", "p4", None, "tender_not_publicly_resolvable"),
        ]
        metrics = linkage_metrics(outcomes)

        assert metrics["evaluated"] == 4
        assert metrics["linkage_coverage"] == 0.5
        assert metrics["eligible"] == 2
        assert metrics["linkage_accuracy_when_available"] == 1.0

    def test_a_wrong_link_lowers_accuracy_not_coverage(self) -> None:
        from signals.documents.discovery import LinkageOutcome, linkage_metrics

        outcomes = [
            LinkageOutcome("a", "p1", "t1", "linked", verified=True),
            LinkageOutcome("b", "p2", "t9", "linked", verified=False),
        ]
        metrics = linkage_metrics(outcomes)

        assert metrics["linkage_coverage"] == 1.0
        assert metrics["linkage_accuracy_when_available"] == 0.5

    def test_an_award_without_procedure_identifier_is_not_eligible(self) -> None:
        from signals.documents.discovery import LinkageOutcome, linkage_metrics

        metrics = linkage_metrics([LinkageOutcome("a", None, None, "no_procedure_id")])
        assert metrics["eligible"] == 0
        assert metrics["linkage_accuracy_when_available"] is None

    def test_an_unreviewed_link_is_not_counted_as_correct(self) -> None:
        from signals.documents.discovery import LinkageOutcome, linkage_metrics

        metrics = linkage_metrics([LinkageOutcome("a", "p1", "t1", "linked")])
        assert metrics["reviewed"] == 0
        assert metrics["linkage_accuracy_when_available"] is None

    def test_no_fuzzy_linkage_is_attempted(self) -> None:
        """SPEC-006R interdit acheteur + CPV + titre + fenêtre : un mauvais
        cahier des charges serait bien pire qu'un dossier absent."""
        import pathlib

        source = pathlib.Path("src/signals/documents/discovery.py").read_text().casefold()
        for interdit in ("fuzzy", "similarity", "levenshtein", "rapidfuzz"):
            assert interdit not in source


LINKAGE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "documents" / "linkage800.json").read_text()
)


class TestLinkageOnEightHundredAwards:
    """SPEC-006R : la couverture est plafonnée par la source, la justesse ne l'est pas.

    Sur 800 attributions réelles, **aucune** des 176 non rapprochées n'a d'avis
    d'appel d'offres dans TED sous son identifiant de procédure — vérifié un par
    un. Le taux de 78 % n'est donc pas un défaut de rapprochement : c'est ce que
    la source publie.
    """

    def _outcomes(self):
        from signals.documents.discovery import LinkageOutcome

        return [
            LinkageOutcome(
                award=row["award"],
                procedure_id=row["procedure_id"],
                tender_notice_id=row["tender_notice_id"],
                status=row["status"],
                notices_sharing_identifier=row["notices_sharing_identifier"],
                verified=row["verified"],
            )
            for row in LINKAGE["rows"]
        ]

    def test_the_population_is_eight_hundred_real_awards(self) -> None:
        assert len(LINKAGE["rows"]) == 800
        assert len({row["award"] for row in LINKAGE["rows"]}) == 800

    def test_coverage_is_what_the_source_allows(self) -> None:
        from signals.documents.discovery import linkage_metrics

        metrics = linkage_metrics(self._outcomes())
        assert metrics["linked"] == 624
        assert metrics["linkage_coverage"] == pytest.approx(0.78)

    def test_accuracy_when_available_is_measured_on_reviewed_links(self) -> None:
        from signals.documents.discovery import linkage_metrics

        metrics = linkage_metrics(self._outcomes())
        assert metrics["reviewed"] == 20
        assert metrics["linkage_accuracy_when_available"] == 1.0

    def test_every_unlinked_award_was_checked_to_have_no_tender_notice(self) -> None:
        unlinked = [row for row in LINKAGE["rows"] if row["status"] != "linked"]
        assert len(unlinked) == 176
        assert all(row["status"] == "tender_not_publicly_resolvable" for row in unlinked)

    def test_an_unresolvable_tender_is_not_counted_as_a_failed_link(self) -> None:
        from signals.documents.discovery import linkage_metrics

        metrics = linkage_metrics(self._outcomes())
        assert metrics["eligible"] == 624
        assert metrics["not_publicly_resolvable"] == 176
