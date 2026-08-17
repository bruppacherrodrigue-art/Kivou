"""Reconstruction des unités de texte coupées par la mise en page.

SPEC-006R3 a mesuré la cause des faux rejets : six exigences sur huit étaient
correctement comprises par le modèle et refusées au seul motif que la phrase
était tronquée. Elle l'était par le PDF, pas par le rédacteur :

    page 6  « … Izvajalec mora naročniku javiti vsako okvaro na opremi, ki jo/jih »
    page 7  « Vzorec pogodbe 7  13. člen  je povzročil pri izvajanju del. »

Deviner ce recollement n'est pas le travail d'un modèle de langue : l'extracteur
dispose de l'information. Ce module l'assemble — **sans rien supprimer, sans
rien reformuler** — et garde la trace de chaque bloc source, pour que la preuve
finale cite les extraits bruts et leurs localisations d'origine.
"""

from __future__ import annotations

from signals.documents import TextBlock
from signals.documents.spans import (
    LogicalTextSpan,
    logical_spans,
    strip_running_headers,
)


def _pdf(page: int, text: str) -> TextBlock:
    return TextBlock(locator=f"page {page}", text=text, method="pdf_text", page=page)


class TestRunningHeaders:
    """Un en-tête répété sur chaque page n'est pas du texte de contrat."""

    def test_a_header_repeated_on_every_page_is_removed(self) -> None:
        pages = [
            "Vzorec pogodbe 5\nIzvajalec mora voditi evidenco porabe materiala, ki se",
            "Vzorec pogodbe 6\nnahaja na recepciji posameznega objekta.",
            "Vzorec pogodbe 7\nNaročnik je dolžan zagotoviti vodo.",
        ]
        cleaned = strip_running_headers(pages)

        assert all("Vzorec pogodbe" not in page for page in cleaned)
        assert "Izvajalec mora voditi evidenco" in cleaned[0]

    def test_a_line_that_appears_once_is_never_removed(self) -> None:
        pages = ["Titre unique\nphrase une", "autre page\nphrase deux", "encore\nphrase trois"]
        cleaned = strip_running_headers(pages)
        assert "Titre unique" in cleaned[0]

    def test_a_numbered_footer_is_removed_despite_the_changing_number(self) -> None:
        pages = [f"{n} | 91 UKC Maribor Vzdrževanje\nContenu {n}." for n in range(1, 6)]
        cleaned = strip_running_headers(pages)
        assert all("UKC Maribor" not in page for page in cleaned)
        assert "Contenu 3." in cleaned[2]

    def test_two_pages_are_too_few_to_conclude(self) -> None:
        """Sur deux pages, une ligne commune peut être une coïncidence."""
        pages = ["Entête\nphrase une", "Entête\nphrase deux"]
        assert strip_running_headers(pages) == pages


class TestLogicalSpans:
    def test_a_sentence_cut_across_two_pages_is_reassembled(self) -> None:
        blocks = [
            _pdf(6, "Izvajalec mora naročniku javiti vsako okvaro na opremi, ki jo/jih"),
            _pdf(7, "je povzročil pri izvajanju del."),
        ]
        spans = logical_spans(blocks)

        assert len(spans) == 1
        assert spans[0].text == (
            "Izvajalec mora naročniku javiti vsako okvaro na opremi, ki jo/jih "
            "je povzročil pri izvajanju del."
        )
        assert [block.locator for block in spans[0].blocks] == ["page 6", "page 7"]

    def test_a_finished_sentence_is_never_glued_to_the_next_block(self) -> None:
        blocks = [
            _pdf(1, "Izvajalec mora voditi evidenco porabe materiala."),
            _pdf(2, "Naročnik je dolžan zagotoviti vodo."),
        ]
        spans = logical_spans(blocks)
        assert len(spans) == 2

    def test_a_heading_between_two_blocks_stops_the_assembly(self) -> None:
        blocks = [
            _pdf(1, "Izvajalec mora zagotoviti opremo, ki"),
            _pdf(2, "13. člen"),
            _pdf(3, "ustreza standardom."),
        ]
        spans = logical_spans(blocks)
        assert len(spans) == 3, "un titre intercalé interdit le recollement"

    def test_two_spreadsheet_cells_are_never_merged(self) -> None:
        blocks = [
            TextBlock(
                locator="Popis!B12", text="Dobava in montaža hidranta, ki", method="xlsx_cell"
            ),
            TextBlock(locator="Popis!B13", text="ustreza standardu", method="xlsx_cell"),
        ]
        spans = logical_spans(blocks)
        assert len(spans) == 2, "une cellule est une unité en soi"

    def test_blocks_from_different_extraction_methods_are_never_merged(self) -> None:
        blocks = [
            _pdf(1, "Izvajalec mora zagotoviti opremo, ki"),
            TextBlock(locator="paragraphe 2", text="ustreza standardom.", method="docx_paragraph"),
        ]
        assert len(logical_spans(blocks)) == 2

    def test_a_new_item_of_an_enumeration_is_not_a_continuation(self) -> None:
        blocks = [
            _pdf(1, "Izvajalec mora predložiti dokazila, in sicer"),
            _pdf(2, "a) potrdilo o zavarovanju,"),
        ]
        assert len(logical_spans(blocks)) == 2

    def test_nothing_of_the_source_text_is_lost(self) -> None:
        blocks = [_pdf(1, "Première partie qui continue"), _pdf(2, "et se termine ici.")]
        spans = logical_spans(blocks)
        joined = " ".join(block.text for span in spans for block in span.blocks)
        assert joined == "Première partie qui continue et se termine ici."

    def test_three_consecutive_pages_can_form_one_span(self) -> None:
        blocks = [_pdf(1, "Un début qui"), _pdf(2, "se poursuit et"), _pdf(3, "se termine.")]
        spans = logical_spans(blocks)
        assert len(spans) == 1
        assert len(spans[0].blocks) == 3

    def test_a_span_of_one_block_keeps_its_locator(self) -> None:
        span = logical_spans([_pdf(4, "Une phrase complète.")])[0]
        assert span.locator == "page 4"

    def test_a_span_over_two_blocks_names_both(self) -> None:
        spans = logical_spans([_pdf(6, "Une phrase qui"), _pdf(7, "se termine.")])
        assert spans[0].locator == "page 6 → page 7"


class TestSourceMapping:
    """Chaque morceau d'une phrase doit pouvoir citer son bloc d'origine."""

    def test_a_sentence_inside_one_block_maps_to_that_block_only(self) -> None:
        span = logical_spans([_pdf(3, "Phrase une. Phrase deux.")])[0]
        pieces = span.pieces_for("Phrase deux.")

        assert len(pieces) == 1
        assert pieces[0].block.locator == "page 3"
        assert pieces[0].text == "Phrase deux."

    def test_a_sentence_spanning_two_blocks_maps_to_both_with_raw_excerpts(self) -> None:
        span = logical_spans(
            [_pdf(6, "Izvajalec mora javiti okvaro, ki jo/jih"), _pdf(7, "je povzročil.")]
        )[0]
        pieces = span.pieces_for("Izvajalec mora javiti okvaro, ki jo/jih je povzročil.")

        assert [piece.block.locator for piece in pieces] == ["page 6", "page 7"]
        assert pieces[0].text == "Izvajalec mora javiti okvaro, ki jo/jih"
        assert pieces[1].text == "je povzročil."
        # Chaque morceau est un extrait BRUT de son bloc — pas une recomposition.
        assert all(piece.text in piece.block.text for piece in pieces)

    def test_an_absent_sentence_maps_to_nothing(self) -> None:
        span = logical_spans([_pdf(1, "Une phrase réelle.")])[0]
        assert span.pieces_for("Une phrase inventée.") == ()

    def test_the_span_exposes_its_blocks_in_order(self) -> None:
        span = logical_spans([_pdf(1, "Un début qui"), _pdf(2, "se termine.")])[0]
        assert isinstance(span, LogicalTextSpan)
        assert [block.page for block in span.blocks] == [1, 2]


class TestHeaderAwareAssembly:
    """Le cas réel : un en-tête de page s'intercale au milieu d'une phrase coupée."""

    def _pages(self):
        return [
            _pdf(5, "Vzorec pogodbe 5\nIzvajalec mora naročniku javiti vsako okvaro na opremi, ki"),
            _pdf(6, "Vzorec pogodbe 6\nje povzročil pri izvajanju del."),
            _pdf(7, "Vzorec pogodbe 7\nNaročnik je dolžan zagotoviti vodo."),
        ]

    def test_the_sentence_is_reassembled_without_the_running_header(self) -> None:
        spans = logical_spans(self._pages())
        joined = " ".join(span.text for span in spans)

        assert "Vzorec pogodbe" not in joined
        assert (
            "Izvajalec mora naročniku javiti vsako okvaro na opremi, ki "
            "je povzročil pri izvajanju del." in joined
        )

    def test_the_two_pieces_are_raw_excerpts_of_their_own_page(self) -> None:
        spans = logical_spans(self._pages())
        span = next(s for s in spans if "javiti" in s.text)
        pieces = span.pieces_for(
            "Izvajalec mora naročniku javiti vsako okvaro na opremi, ki je povzročil pri izvajanju del."
        )

        assert [piece.block.locator for piece in pieces] == ["page 5", "page 6"]
        for piece in pieces:
            assert piece.text in piece.block.text, "chaque preuve cite son bloc, mot pour mot"

    def test_the_raw_blocks_are_never_modified(self) -> None:
        pages = self._pages()
        logical_spans(pages)
        assert pages[0].text.startswith("Vzorec pogodbe 5")

    def test_stripping_can_be_disabled(self) -> None:
        spans = logical_spans(self._pages(), strip_headers=False)
        assert "Vzorec pogodbe" in " ".join(span.text for span in spans)


class TestPipelineEvidence:
    """Une exigence à cheval sur deux pages doit porter DEUX preuves."""

    def test_a_requirement_split_across_pages_carries_one_evidence_per_block(self) -> None:
        import datetime as dt

        from signals.documents import TenderDocument, content_hash
        from signals.documents.classification import SemanticClassification
        from signals.documents.intelligence import requirement_from
        from signals.documents.spans import logical_spans

        blocks = [
            _pdf(6, "Izvajalec mora naročniku javiti vsako okvaro na opremi, ki"),
            _pdf(7, "je povzročil pri izvajanju del."),
        ]
        span = logical_spans(blocks)[0]
        excerpt = (
            "Izvajalec mora naročniku javiti vsako okvaro na opremi, ki "
            "je povzročil pri izvajanju del."
        )
        document = TenderDocument(
            source_system="ted",
            name="vzorec pogodbe.pdf",
            access_status="available",
            content_hash=content_hash(b"x"),
            retrieved_at=dt.datetime(2026, 8, 16, tzinfo=dt.UTC),
        )
        classification = SemanticClassification(
            phase="execution",
            obligated_actor="contractor",
            modality="mandatory",
            requirement_type="documentation_obligation",
            context_status="sufficient",
            source_excerpt=excerpt,
            confidence="high",
        )

        requirement = requirement_from(
            classification,
            document=document,
            locator=span.locator,
            method="model",
            pieces=span.pieces_for(excerpt),
        )

        assert len(requirement.evidence) == 2
        assert "page 6" in (requirement.evidence[0].path or "")
        assert "page 7" in (requirement.evidence[1].path or "")
        # Chaque preuve cite le texte brut de SA page — aucune citation recomposée.
        assert requirement.evidence[0].excerpt in blocks[0].text
        assert requirement.evidence[1].excerpt in blocks[1].text
        # L'énoncé, lui, est la phrase complète et lisible.
        assert requirement.statement == excerpt

    def test_a_requirement_inside_one_block_still_carries_one_evidence(self) -> None:
        import datetime as dt

        from signals.documents import TenderDocument, content_hash
        from signals.documents.classification import SemanticClassification
        from signals.documents.intelligence import requirement_from
        from signals.documents.spans import logical_spans

        sentence = "Izvajalec mora voditi evidenco porabe materiala."
        span = logical_spans([_pdf(3, sentence)])[0]
        document = TenderDocument(
            source_system="ted",
            name="a.pdf",
            access_status="available",
            content_hash=content_hash(b"x"),
            retrieved_at=dt.datetime(2026, 8, 16, tzinfo=dt.UTC),
        )
        requirement = requirement_from(
            SemanticClassification(
                phase="execution",
                obligated_actor="contractor",
                modality="mandatory",
                requirement_type="documentation_obligation",
                context_status="sufficient",
                source_excerpt=sentence,
                confidence="high",
            ),
            document=document,
            locator=span.locator,
            method="model",
            pieces=span.pieces_for(sentence),
        )
        assert len(requirement.evidence) == 1
        assert requirement.evidence[0].excerpt == sentence


class TestRealDevThreeFragments:
    """Les coupures réelles qui ont fait échouer le gate v0.2.

    Texte brut copié tel quel depuis les documents DEV-3 : la coupure n'est pas
    au saut de page mais **au milieu de la ligne**, imposée par la mise en page.
    Sept des huit exigences perdues au run v0.2 redeviennent des phrases entières.
    """

    def test_a_slovenian_obligation_broken_mid_line_is_restored(self) -> None:
        from signals.documents.language import sentences

        raw = (
            "Izvajalec mora voditi evidenco porabe sanitarno -higienskega mate riala, "
            "ki se nahaja na recepciji \nposameznega objekta. Evidenco bo pripra vil "
            "naročnik  ter jo pravočasno dostavljal na navedeno \nmesto."
        )
        span = logical_spans([_pdf(6, raw)])[0]
        first = sentences(span.text)[0]

        assert first.endswith("posameznega objekta.")
        # La vue préserve la longueur des séparateurs recollés (R5 §7) : la
        # comparaison se fait donc aux espaces près, comme partout ailleurs.
        from signals.documents.language import normalize_for_match

        assert normalize_for_match("recepciji posameznega objekta") in normalize_for_match(first)

    def test_the_repair_preserves_offsets_so_evidence_stays_raw(self) -> None:
        raw = (
            "Izvajalec mora javiti vsako okvaro na opremi, ki jo/jih \npovzročijo njegovi čistilci."
        )
        block = _pdf(6, raw)
        span = logical_spans([block])[0]
        excerpt = (
            "Izvajalec mora javiti vsako okvaro na opremi, ki jo/jih povzročijo njegovi čistilci."
        )

        pieces = span.pieces_for(excerpt)
        assert len(pieces) == 1
        # L'extrait rendu est celui du bloc BRUT — retour à la ligne compris.
        assert pieces[0].text in block.text
        assert "\n" in pieces[0].text

    def test_a_line_ending_a_sentence_is_never_glued_to_the_next(self) -> None:
        from signals.documents.language import sentences

        raw = "Izvajalec mora voditi evidenco.\nNaročnik je dolžan zagotoviti vodo."
        span = logical_spans([_pdf(1, raw)])[0]
        assert len(sentences(span.text)) == 2

    def test_a_bullet_on_the_next_line_is_never_glued(self) -> None:
        raw = "Izvajalec mora predložiti dokazila, in sicer\n- potrdilo o zavarovanju,"
        span = logical_spans([_pdf(1, raw)])[0]
        assert "\n" in span.text, "une puce reste sur sa ligne"
