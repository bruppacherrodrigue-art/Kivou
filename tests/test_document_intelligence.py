"""Du dossier aux exigences prouvées — le pipeline et son juge.

Ces tests portent sur ce que SPEC-006 promet de garantir : une exigence n'existe
que si son extrait se retrouve dans le texte source, un énoncé historique n'en
devient jamais une, et un dossier inaccessible produit un état, pas un vide.

Les documents utilisés sont **réels** : ils viennent de deux dossiers de marché
publiés (Portugal, Slovénie) et récupérés pendant le spike.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from signals.documents import (
    ENGINE_VERSION,
    UNTRUSTED_PROMPT_HEADER,
    DeterministicExtractor,
    RequirementCandidate,
    TenderDocument,
    TextBlock,
    classify_requirement,
    content_hash,
    coverage_for,
    detect_modality,
    extract_quantity,
    validate_candidates,
)
from signals.documents.intelligence import (
    AnalysisLimits,
    analyze_document,
    analyze_dossier,
    dedupe_requirements,
)
from signals.domain import EventRef

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "documents"
AWARD = EventRef(source_system="ted", source_notice_id="566160-2026")


def _document(name: str, data: bytes, **overrides: object) -> TenderDocument:
    fields: dict[str, object] = {
        "source_system": "ted",
        "source_procedure_id": "PT-2026-acingov",
        "name": name,
        "source_url": "https://www.acingov.pt/acingovprod/2/zonaPublica/donwloadProcedurePiece/x",
        "access_status": "available",
        "content_hash": content_hash(data),
        "byte_size": len(data),
        "retrieved_at": dt.datetime(2026, 8, 16, 15, 47, tzinfo=dt.UTC),
    }
    fields.update(overrides)
    return TenderDocument(**fields)  # type: ignore[arg-type]


def _block(text: str, locator: str = "page 1") -> TextBlock:
    return TextBlock(locator=locator, text=text, method="pdf_text", page=1)


# ─── Modalité ───────────────────────────────────────────────────────────────────


class TestModality:
    def test_obligation_is_mandatory(self) -> None:
        assert detect_modality("Le titulaire doit assurer une permanence continue.") == "mandatory"

    def test_prohibition_is_not_an_obligation(self) -> None:
        assert detect_modality("Le titulaire ne peut pas sous-traiter le lot 1.") == "prohibited"

    def test_option_is_not_an_obligation(self) -> None:
        assert detect_modality("Le titulaire peut proposer une variante technique.") == "optional"

    def test_past_contract_is_informational_not_a_requirement(self) -> None:
        assert (
            detect_modality("Le précédent titulaire devait assurer une astreinte 24/7.")
            == "informational"
        )

    def test_a_descriptive_sentence_carries_no_modality(self) -> None:
        assert (
            detect_modality("Le présent marché porte sur la rénovation d'un laboratoire.") is None
        )


# ─── Classification et quantités ────────────────────────────────────────────────


class TestClassification:
    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            (
                "Le titulaire doit mettre à disposition au minimum 4 techniciens.",
                "staffing_constraint",
            ),
            ("La sous-traitance est limitée à 30 % du montant du marché.", "subcontracting_rule"),
            ("Une permanence 24/7 doit être assurée sur le site.", "operating_hours"),
            ("Le prestataire doit être certifié ISO 27001.", "certification"),
            ("O adjudicatário deve emitir a fatura no prazo previsto.", "payment_terms"),
            ("Ponudnik mora zagotoviti vzdrževanje opreme.", "maintenance_obligation"),
        ],
    )
    def test_types_are_recognised_across_languages(self, sentence: str, expected: str) -> None:
        assert classify_requirement(sentence) == expected

    def test_an_unclassifiable_sentence_is_other_not_forced(self) -> None:
        assert (
            classify_requirement("Le titulaire doit respecter les règles applicables.") == "other"
        )

    def test_a_number_glued_to_a_unit_is_extracted(self) -> None:
        quantity = extract_quantity("La sous-traitance est limitée à 30 % du montant.")
        assert quantity is not None
        assert (quantity.value, quantity.unit) == (30.0, "%")

    @pytest.mark.parametrize(
        ("sentence", "value", "unit"),
        [
            ("um gerador de corrente com 230 Volts e proteção diferencial", 230.0, "volts"),
            ("vodoodporne mavčne plošče debeline 12,5 mm", 12.5, "mm"),
            ("uma carga útil de 3500 kg no eixo traseiro", 3500.0, "kg"),
        ],
    )
    def test_physical_units_are_quantities_too(
        self, sentence: str, value: float, unit: str
    ) -> None:
        """Un cahier des charges de fournitures chiffre en volts et en millimètres."""
        quantity = extract_quantity(sentence)
        assert quantity is not None
        assert (quantity.value, quantity.unit) == (value, unit)

    def test_a_bare_number_is_not_a_quantity(self) -> None:
        assert extract_quantity("Le lot 3 est attribué au candidat 2.") is None


class TestObligationSubject:
    """Une obligation de l'acheteur n'est pas une exigence pour le titulaire.

    Trouvé en revue manuelle sur les deux dossiers réels : « O órgão competente
    deve fundamentar a decisão de exclusão » et « Naročnik je dolžan izvajalca
    obvestiti » sont des devoirs de l'acheteur. Les retenir ferait dire à Kivou
    que le fournisseur doit motiver ses propres exclusions.
    """

    @pytest.mark.parametrize(
        "sentence",
        [
            "O órgão competente para a decisão de contratar deve fundamentar a exclusão.",
            "Naročnik je dolžan izvajalca obvestiti o vsaki spremembi internih predpisov.",
            "Le pouvoir adjudicateur doit notifier sa décision aux candidats évincés.",
            "A entidade adjudicante deve publicar o anúncio no Diário da República.",
            "The contracting authority shall notify all tenderers of its decision.",
        ],
    )
    def test_a_buyer_obligation_is_not_an_execution_requirement(self, sentence: str) -> None:
        block = _block(sentence)
        assert DeterministicExtractor().propose(block) == []

    def test_a_contractor_obligation_is_kept(self) -> None:
        block = _block("O adjudicatário deve assegurar a manutenção preventiva dos equipamentos.")
        assert DeterministicExtractor().propose(block)

    @pytest.mark.parametrize(
        "sentence",
        [
            # L'acheteur y est destinataire, pas sujet : le titulaire agit.
            "Dobavitelj mora ob koncu del predati naročniku vse evidenčne liste odpeljanih odpadkov.",
            "Izvajalec lahko v roku, ki ga določi naročnik, predloži dokaze o sprejetih ukrepih.",
            "Izvedena dela morajo biti potrjena s strani nadzornika, ki ga določi naročnik.",
            "O adjudicatário deve entregar à entidade adjudicante o relatório mensal de execução.",
        ],
    )
    def test_the_buyer_as_recipient_does_not_disqualify_the_requirement(
        self, sentence: str
    ) -> None:
        block = _block(sentence)
        assert DeterministicExtractor().propose(block), (
            "l'acheteur mentionné comme destinataire ne fait pas de la phrase son obligation"
        )

    def test_a_passive_obligation_stays_a_requirement(self) -> None:
        block = _block("Dela morajo biti izvedena po določilih veljavnih normativov in predpisov.")
        assert DeterministicExtractor().propose(block)


class TestExecutionScope:
    """SPEC-006 vise l'exécution du marché, pas la façon de déposer une offre.

    La revue manuelle de 40 exigences a montré que 15 d'entre elles n'étaient pas
    des exigences d'exécution : règles de dépôt d'offre, conditions de
    qualification, droits de l'acheteur. Neuf venaient du règlement de
    consultation et du formulaire ESPD — deux pièces qui ne disent rien de ce que
    le titulaire devra faire une fois le marché attribué.
    """

    def test_the_procedure_rules_document_yields_no_execution_requirement(self) -> None:
        rules = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        document = _document("2_Programa_Procedimento_AE.pdf", rules, kind="procedure_rules")
        result = analyze_dossier(award_ref=AWARD, source_system="ted", items=[(document, rules)])
        assert result.requirements == ()
        assert any("règles de procédure" in warning for warning in result.warnings)
        assert result.documents, "la pièce reste au dossier : elle a bien été lue"

    def test_the_specification_still_yields_its_requirements(self) -> None:
        specification = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        document = _document(
            "1_Caderno_encargos_AE.pdf", specification, kind="technical_specification"
        )
        result = analyze_dossier(
            award_ref=AWARD, source_system="ted", items=[(document, specification)]
        )
        assert len(result.requirements) > 30

    @pytest.mark.parametrize(
        "sentence",
        [
            "O júri deve solicitar aos concorrentes que, no prazo de cinco dias, procedam ao suprimento.",
            "O contraente público pode exigir o pagamento de uma pena pecuniária ao adjudicatário.",
        ],
    )
    def test_the_buyer_side_bodies_are_recognised_as_buyer(self, sentence: str) -> None:
        assert DeterministicExtractor().propose(_block(sentence)) == []

    @pytest.mark.parametrize(
        "sentence",
        [
            "V tem primeru mora gospodarski subjekt v ponudbi dokazati, da bo imel sredstva.",
            "Todos os documentos de habilitação devem ser redigidos em língua portuguesa.",
            "Pri izdelavi ponudbe mora ponudnik preučiti vse priloge in zadostiti zahtevam.",
        ],
    )
    def test_a_bid_phase_obligation_is_not_an_execution_requirement(self, sentence: str) -> None:
        assert DeterministicExtractor().propose(_block(sentence)) == []

    @pytest.mark.parametrize(
        "sentence",
        [
            "Ponudnik mora ponuditi vso opremo in storitve iz sklopa, za katerega oddaja ponudbo.",
            "V primeru skupne ponudbe morajo biti v obrazcu navedeni vsi gospodarski subjekti.",
            "Ponudnik lahko do roka za oddajo ponudb svojo ponudbo umakne ali spremeni.",
        ],
    )
    def test_the_slovenian_bid_phrasing_is_recognised_too(self, sentence: str) -> None:
        assert DeterministicExtractor().propose(_block(sentence)) == []

    def test_a_sentence_that_only_announces_a_list_is_not_a_requirement(self) -> None:
        """« La prise de force doit : » n'énonce rien — l'obligation est dans la liste.

        Garder l'amorce produirait une exigence dont l'extrait ne prouve rien.
        """
        assert DeterministicExtractor().propose(_block("b) A tomada de força deve:")) == []
        assert (
            DeterministicExtractor().propose(_block("3 - O contrato pode ser alterado por:")) == []
        )

    @pytest.mark.parametrize(
        "sentence",
        [
            "Ponudnik lahko odda ponudbo za posamezen sklop ali za oba sklopa.",
            "Jezik, v katerem mora ponudnik pripraviti ponudbo, je slovenski.",
        ],
    )
    def test_the_remaining_bid_phrasing_from_the_corpus_is_recognised(self, sentence: str) -> None:
        assert DeterministicExtractor().propose(_block(sentence)) == []

    @pytest.mark.parametrize(
        "sentence",
        [
            # Revue manuelle de 40 exigences tirées de 13 dossiers inédits : ces
            # phrases décrivent le dépôt d'offre ou la qualification, jamais
            # l'exécution du marché.
            "Ponudba mora biti pripravljena v slovenskem jeziku in oddana elektronsko.",
            "Ponudnik mora v informacijskem sistemu e-JN v razdelek Predračun naložiti dokument.",
            "Ponudnik mora za vsakega nominiranega podizvajalca predložiti tudi ESPD obrazec.",
            "Pogoj mora izpolnjevati vsak gospodarski subjekt v skupni prijavi.",
            "Vsi elektronsko oddani dokumenti morajo biti v skladu z zahtevami naročnika.",
            "A proposta deve ainda ser instruída com a Certidão Permanente de Registo Comercial.",
            "Veljavnost ponudbe mora biti pokrita z ustrezno daljšo veljavnostjo zavarovanja.",
        ],
    )
    def test_the_bid_and_qualification_register_is_excluded(self, sentence: str) -> None:
        assert DeterministicExtractor().propose(_block(sentence)) == []

    @pytest.mark.parametrize(
        "sentence",
        [
            # …et celles-ci parlent bien de l'exécution, malgré un vocabulaire proche.
            "Ponudnik mora zagotoviti vsaj 3 ustrezno certificirane strokovnjake za vzdrževanje.",
            "Svetovalna skupina mora imeti najmanj 3 člane, vključno z vodjo skupine.",
            "Iz računa mora biti razvidna vrsta, količina in cena dobavljenega blaga.",
            "Dobava mora vključevati še dodatni zaporni ventil in pripadajoče tesnilo.",
        ],
    )
    def test_an_execution_requirement_survives_the_register(self, sentence: str) -> None:
        assert DeterministicExtractor().propose(_block(sentence))

    def test_a_list_item_ending_with_a_semicolon_is_still_a_requirement(self) -> None:
        """Le cahier des charges portugais énumère ainsi : chaque item est une exigence."""
        assert DeterministicExtractor().propose(
            _block("j) Os degraus devem levar revestimento anti deslizante;")
        )

    def test_an_execution_obligation_mentioning_the_offer_is_kept(self) -> None:
        sentence = (
            "Izvajalec mora dela izvesti v rokih, ki so navedeni v pogodbi in terminskem planu."
        )
        assert DeterministicExtractor().propose(_block(sentence))


class TestVocabularyFromTheCorpus:
    """Ajouts issus de la revue des 530 exigences des deux dossiers réels."""

    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("ves vgrajeni material mora imeti ustrezne ateste", "certification"),
            (
                "Pri izstavitvi računa se mora sklicevati na številko pogodbe.",
                "payment_terms",
            ),
            (
                "O sistema de arrefecimento do motor deve ser dimensionado para 220 Volts.",
                "technical_characteristic",
            ),
            (
                "Kjer se vgradi vodoodporne mavčne plošče debeline 12,5 mm se mora uporabiti kit.",
                "technical_characteristic",
            ),
            # La moitié des obligations du cahier des charges portugais décrit le
            # véhicule lui-même : sans ces formes, elles tombaient toutes en « other ».
            (
                "a) Deve estar equipado com sistema de travagem que cumpra a legislação Nacional.",
                "technical_characteristic",
            ),
            (
                "b) O veículo deve possuir dispositivo automático de bloqueio diferencial.",
                "technical_characteristic",
            ),
            (
                "a) Deve ser construída numa armação formada por perfis devidamente fixados.",
                "technical_characteristic",
            ),
        ],
    )
    def test_the_corpus_gaps_are_closed(self, sentence: str, expected: str) -> None:
        assert classify_requirement(sentence) == expected

    def test_a_deadline_is_not_mistaken_for_a_product_characteristic(self) -> None:
        """« deve ter lugar no prazo de 30 dias » parle de délai, pas d'équipement."""
        assert (
            classify_requirement("A outorga do contrato deve ter lugar no prazo de 30 dias.")
            == "schedule_deadline"
        )


# ─── Le juge ────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_a_candidate_whose_excerpt_is_absent_is_rejected(self) -> None:
        data = b"contenu"
        block = _block("Le titulaire doit assurer la maintenance corrective du parc.")
        invented = RequirementCandidate(
            requirement_type="staffing_constraint",
            modality="mandatory",
            statement="Le titulaire doit recruter 12 ingénieurs.",
            source_excerpt="Le titulaire doit recruter 12 ingénieurs.",
            source_locator="page 1",
            confidence="high",
        )
        outcome = validate_candidates(
            [invented], block=block, document=_document("x.pdf", data), method="model"
        )
        assert outcome.accepted == []
        assert "introuvable" in outcome.rejected[0][1]

    def test_whitespace_differences_do_not_break_a_true_excerpt(self) -> None:
        data = b"contenu"
        block = _block("Le titulaire   doit assurer\nla maintenance corrective du parc.")
        candidate = RequirementCandidate(
            requirement_type="maintenance_obligation",
            modality="mandatory",
            statement="Le titulaire doit assurer la maintenance corrective du parc.",
            source_excerpt="Le titulaire doit assurer la maintenance corrective du parc.",
            source_locator="page 1",
            confidence="high",
        )
        outcome = validate_candidates(
            [candidate], block=block, document=_document("x.pdf", data), method="model"
        )
        assert len(outcome.accepted) == 1

    def test_every_accepted_requirement_carries_a_document_evidence_with_excerpt(self) -> None:
        data = b"contenu"
        sentence = "Le titulaire doit assurer la maintenance corrective du parc installé."
        block = _block(sentence, locator="page 7")
        outcome = validate_candidates(
            DeterministicExtractor().propose(block),
            block=block,
            document=_document("caderno.pdf", data),
            method="deterministic",
        )
        requirement = outcome.accepted[0]
        evidence = requirement.evidence[0]
        assert evidence.source_kind == "tender_document"
        assert evidence.excerpt == sentence
        assert "page 7" in (evidence.path or "")
        assert requirement.engine_version == ENGINE_VERSION

    def test_a_model_output_is_marked_as_such(self) -> None:
        data = b"contenu"
        sentence = "Le titulaire doit livrer un rapport mensuel d'activité au maître d'ouvrage."
        block = _block(sentence)
        candidate = RequirementCandidate(
            requirement_type="documentation_obligation",
            modality="mandatory",
            statement=sentence,
            source_excerpt=sentence,
            source_locator="page 1",
        )
        outcome = validate_candidates(
            [candidate], block=block, document=_document("x.pdf", data), method="model"
        )
        assert outcome.accepted[0].extraction_method == "model"


# ─── Pipeline sur documents réels ───────────────────────────────────────────────


class TestAnalyzeRealDocuments:
    def test_portuguese_specification_yields_requirements_with_page_evidence(self) -> None:
        data = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        analysis = analyze_document(_document("1_Caderno_encargos_AE.pdf", data), data)

        assert analysis.blocks > 20, "un cahier des charges de 30 pages doit produire des blocs"
        assert len(analysis.requirements) > 30
        for requirement in analysis.requirements:
            evidence = requirement.evidence[0]
            assert evidence.excerpt
            assert "page " in (evidence.path or "")

    def test_slovenian_documentation_is_read_paragraph_by_paragraph(self) -> None:
        data = (FIXTURES / "dokumentacija.docx").read_bytes()
        analysis = analyze_document(_document("Dokumentacija v zvezi z oddajo.docx", data), data)

        assert len(analysis.requirements) > 30
        assert all("paragraphe " in (r.evidence[0].path or "") for r in analysis.requirements)

    def test_bill_of_quantities_evidence_points_to_a_cell(self) -> None:
        data = (FIXTURES / "popis_opreme.xlsx").read_bytes()
        analysis = analyze_document(_document("Popis opreme - SKLOP 2.xlsx", data), data)

        assert analysis.blocks > 100
        assert all("!" in (r.evidence[0].path or "") for r in analysis.requirements)

    def test_an_unsupported_format_says_so_instead_of_failing(self) -> None:
        data = b"\x00\x01\x02binaire quelconque"
        analysis = analyze_document(_document("mystere.dat", data), data)

        assert analysis.document.access_status == "unsupported"
        assert analysis.requirements == []

    def test_language_is_detected_and_attached_to_the_document(self) -> None:
        data = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        analysis = analyze_document(_document("1_Caderno_encargos_AE.pdf", data), data)
        assert analysis.document.language == "pt"


# ─── Déduplication ──────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_the_same_sentence_in_two_documents_keeps_both_proofs(self) -> None:
        sentence = "Le titulaire doit assurer la maintenance corrective du parc installé."
        block = _block(sentence)
        first = validate_candidates(
            DeterministicExtractor().propose(block),
            block=block,
            document=_document("a.pdf", b"a"),
            method="deterministic",
        ).accepted
        second = validate_candidates(
            DeterministicExtractor().propose(block),
            block=block,
            document=_document("b.pdf", b"b", path_in_container="b.pdf"),
            method="deterministic",
        ).accepted

        merged = dedupe_requirements([*first, *second])
        assert len(merged) == 1
        assert len(merged[0].evidence) == 2

    def test_identical_evidence_is_not_counted_twice(self) -> None:
        sentence = "Le titulaire doit assurer la maintenance corrective du parc installé."
        block = _block(sentence)
        accepted = validate_candidates(
            DeterministicExtractor().propose(block),
            block=block,
            document=_document("a.pdf", b"a"),
            method="deterministic",
        ).accepted
        merged = dedupe_requirements([*accepted, *accepted])
        assert len(merged) == 1
        assert len(merged[0].evidence) == 1


# ─── Dossier complet ────────────────────────────────────────────────────────────


class TestAnalyzeDossier:
    def test_a_real_dossier_is_analysed_and_reports_its_coverage(self) -> None:
        specification = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        notice = (FIXTURES / "anuncio_joraa.pdf").read_bytes()
        result = analyze_dossier(
            award_ref=AWARD,
            source_system="ted",
            items=[
                (_document("1_Caderno_encargos_AE.pdf", specification), specification),
                (_document("384-II-Anuncio JORAA.pdf", notice), notice),
            ],
            tender_procedure_id="PT-2026-acingov",
        )
        assert result.coverage_status == "documents_analyzed"
        assert len(result.requirements) > 30
        assert result.engine_version == ENGINE_VERSION

    def test_an_archive_is_expanded_and_children_keep_their_container(self) -> None:
        archive = (FIXTURES / "espd-request.zip").read_bytes()
        result = analyze_dossier(
            award_ref=AWARD,
            source_system="ted",
            items=[(_document("3_espd-request.zip", archive), archive)],
        )
        children = [d for d in result.documents if d.path_in_container]
        assert {d.path_in_container for d in children} >= {"espd-request.xml", "README.txt"}
        assert all(d.container_hash == content_hash(archive) for d in children)

    def test_a_dossier_behind_authentication_is_a_result_not_an_absence(self) -> None:
        locked = TenderDocument(
            source_system="simap", name="dossier de marché", access_status="auth_required"
        )
        result = analyze_dossier(
            award_ref=EventRef(source_system="simap", source_notice_id="1512345"),
            source_system="simap",
            items=[(locked, None)],
        )
        assert result.coverage_status == "auth_required"
        assert result.requirements == ()

    def test_an_award_without_any_document_is_not_confused_with_a_locked_one(self) -> None:
        result = analyze_dossier(award_ref=AWARD, source_system="ted", items=[])
        assert result.coverage_status == "no_documents"

    def test_documents_are_read_in_relevance_order(self) -> None:
        specification = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        notice = (FIXTURES / "anuncio_joraa.pdf").read_bytes()
        result = analyze_dossier(
            award_ref=AWARD,
            source_system="ted",
            items=[
                (_document("384-II-Anuncio JORAA.pdf", notice), notice),
                (_document("1_Caderno_encargos_AE.pdf", specification), specification),
            ],
        )
        assert result.documents[0].name == "1_Caderno_encargos_AE.pdf"

    def test_a_truncated_analysis_says_what_it_dropped(self) -> None:
        specification = (FIXTURES / "caderno_encargos.pdf").read_bytes()
        notice = (FIXTURES / "anuncio_joraa.pdf").read_bytes()
        result = analyze_dossier(
            award_ref=AWARD,
            source_system="ted",
            items=[
                (_document("1_Caderno_encargos_AE.pdf", specification), specification),
                (_document("384-II-Anuncio JORAA.pdf", notice), notice),
            ],
            limits=AnalysisLimits(max_documents=1),
        )
        assert any("1 document" in warning for warning in result.warnings)


# ─── Frontière modèle de langue ─────────────────────────────────────────────────


class TestModelBoundary:
    def test_the_untrusted_header_forbids_following_document_instructions(self) -> None:
        lowered = UNTRUSTED_PROMPT_HEADER.casefold()
        assert "untrusted" in lowered
        assert "instruction" in lowered

    def test_a_model_that_invents_a_requirement_produces_nothing(self) -> None:
        class InventingModel:
            name = "menteur"
            version = "0.0"

            def propose(self, block: TextBlock) -> list[RequirementCandidate]:
                return [
                    RequirementCandidate(
                        requirement_type="staffing_constraint",
                        modality="mandatory",
                        statement="Le titulaire doit recruter 40 ingénieurs.",
                        source_excerpt="Le titulaire doit recruter 40 ingénieurs.",
                        source_locator=block.locator,
                        confidence="high",
                    )
                ]

        data = (FIXTURES / "anuncio_joraa.pdf").read_bytes()
        analysis = analyze_document(
            _document("anuncio.pdf", data), data, model=InventingModel(), deterministic=False
        )
        assert analysis.requirements == []
        assert analysis.rejected, "le rejet doit être tracé, pas silencieux"


# ─── Couverture ─────────────────────────────────────────────────────────────────


class TestCoverage:
    def test_coverage_is_not_a_quality_measure(self) -> None:
        readable = TenderDocument(
            source_system="ted", name="a.pdf", access_status="available", content_hash="a" * 64
        )
        assert coverage_for((readable,), 0) == "partial_documents"
        assert coverage_for((readable,), 12) == "documents_analyzed"

    def test_external_only_is_the_normal_ted_case(self) -> None:
        pointer = TenderDocument(
            source_system="ted",
            source_url="https://www.marches-publics.gouv.fr/entreprise",
            access_status="external",
        )
        assert coverage_for((pointer,), 0) == "external_only"
