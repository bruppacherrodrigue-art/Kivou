"""SIGNAL-100 — l'intégrité du banc commercial gelé (SPEC-009 §57).

Le banc est le premier gate directement relié à la valeur commerciale du
produit. Ces tests épinglent ce qui doit rester vrai de sa composition, quoi
qu'il arrive ensuite : cent signaux, tous réellement montrables, tous
disjoints des corpus antérieurs, tous prudents dans leur vocabulaire.

Aucun accès réseau : le corpus est relu sur disque.
"""

from __future__ import annotations

import collections
import json
import pathlib

import pytest

from signals.research.signal100 import (
    DOCUMENT_MODE_DISCLOSURE,
    IDENTITY_LEVELS,
    forbidden_wording_hits,
    identities,
    load_rows,
    prior_identities,
    signal_id,
)

FIXTURES = pathlib.Path("tests/fixtures/signal100")
CORPUS = FIXTURES / "signal100_corpus.json"
POOL = FIXTURES / "signal100_pool_corpus.json"
BLIND = FIXTURES / "signal100_blind.json"
TEXTS = FIXTURES / "signal100_text.json"

pytestmark = pytest.mark.skipif(
    not CORPUS.exists(), reason="le banc SIGNAL-100 n'a pas encore été construit"
)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def signals() -> list[dict]:
    return _load(CORPUS)["signals"]


class TestComposition:
    def test_exactly_one_hundred_signals(self, signals: list[dict]) -> None:
        """§13, §59 — le banc est de cent signaux, ni plus ni moins."""
        assert len(signals) == 100

    def test_every_signal_would_really_have_been_shown(self, signals: list[dict]) -> None:
        """§7 — chaque ligne représente un signal réellement montré dans le feed."""
        assert {s["score"]["decision"] for s in signals} == {"show"}

    def test_signal_ids_are_unique_and_deterministic(self, signals: list[dict]) -> None:
        """§16 — l'identité est recalculable, aucune UUID aléatoire."""
        ids = [s["signal_id"] for s in signals]
        assert len(set(ids)) == 100
        for snapshot in signals:
            ref = snapshot["award_ref"]
            recomputed = signal_id(
                (
                    ref["source_system"],
                    ref["source_notice_id"],
                    ref["notice_version"],
                    ref["source_award_id"],
                    ref["lot_identifier"],
                ),
                snapshot["icp"]["icp_id"],
                snapshot["versions"]["match_policy"],
                snapshot["versions"]["score_policy"],
            )
            assert recomputed == snapshot["signal_id"]

    def test_at_most_one_signal_per_award_lot(self, signals: list[dict]) -> None:
        """§8 — un même événement commercial n'est jamais compté deux fois."""
        keys = [tuple(sorted(s["award_ref"].items())) for s in signals]
        assert len(set(keys)) == 100

    def test_at_most_two_award_lots_per_notice(self, signals: list[dict]) -> None:
        """§8 — une notice à lots multiples ne colonise pas le banc."""
        per_notice = collections.Counter((s["source"], s["notice"]) for s in signals)
        assert max(per_notice.values()) <= 2

    def test_both_sources_are_represented(self, signals: list[dict]) -> None:
        """§13 — un moteur qui ne marche que sur une source ne suffit pas à Kivou."""
        per_source = collections.Counter(s["source"] for s in signals)
        assert per_source["ted"] >= 35
        assert per_source["simap"] >= 35


class TestFreshness:
    def test_the_pool_is_disjoint_from_every_previous_corpus(self) -> None:
        """§10 — quatre niveaux d'identité, intersection vide, ensembles non vides.

        L'assertion de non-vacuité vient en premier : une extraction cassée
        produirait zéro intersection et se lirait à tort comme une disjonction.
        """
        fresh = identities(load_rows(POOL))
        prior = prior_identities()
        for level in IDENTITY_LEVELS:
            assert fresh[level], f"niveau {level} vide : extraction d'identité cassée"
            assert prior[level], f"niveau {level} vide côté corpus antérieurs"
            assert not (fresh[level] & prior[level]), (
                f"fuite au niveau {level} : {sorted(fresh[level] & prior[level])[:5]}"
            )

    def test_every_bench_signal_comes_from_the_fresh_pool(self, signals: list[dict]) -> None:
        """Le banc ne contient rien qui ne vienne du corpus frais acquis pour SPEC-009."""
        pool_awards = identities(load_rows(POOL))["award identity"]
        for snapshot in signals:
            ref = snapshot["award_ref"]
            key = (
                ref["source_system"],
                ref["source_notice_id"],
                ref["notice_version"],
                ref["source_award_id"],
                ref["lot_identifier"],
            )
            assert key in pool_awards


class TestSnapshotCompleteness:
    def test_every_snapshot_names_a_winner(self, signals: list[dict]) -> None:
        """§3, §57 — sans « WHO », il n'y a pas de signal commercial."""
        for snapshot in signals:
            assert snapshot["winner"]["status"] == "identified"
            assert snapshot["winner"]["parties"]
            for party in snapshot["winner"]["parties"]:
                assert party["members"]
                assert all(member["legal_name"] for member in party["members"])

    def test_every_snapshot_carries_evidence(self, signals: list[dict]) -> None:
        """§24 — un fait affiché sans preuve est un fait qu'on ne peut pas défendre."""
        for snapshot in signals:
            assert snapshot["evidence_refs"], snapshot["signal_id"]

    def test_every_snapshot_carries_a_matched_need_an_icp_and_a_score(
        self, signals: list[dict]
    ) -> None:
        """§15 — les quatre piliers du snapshot ne sont jamais optionnels."""
        for snapshot in signals:
            assert snapshot["matched_needs"]
            assert snapshot["selected_needs"]
            assert snapshot["icp"]["icp_id"]
            assert isinstance(snapshot["score"]["normalized_score"], int)
            assert snapshot["score"]["normalized_score"] > 0

    def test_every_snapshot_declares_its_engine_versions(self, signals: list[dict]) -> None:
        """§15 — un banc sans versions n'est pas rejouable."""
        for snapshot in signals:
            versions = snapshot["versions"]
            assert versions["match_policy"] == "icp-match-v0.1"
            assert versions["score_policy"] == "signal-score-v0.2"
            assert versions["reference_icp_library"] == "reference-icps-v0.1"
            assert versions["need_engine"]
            assert versions["understanding_engine"]

    def test_no_contact_data_anywhere(self, signals: list[dict]) -> None:
        """§52 — le signal s'arrête à l'entreprise gagnante.

        Le modèle `OrganizationRef` ne porte ni personne ni contact ; ce test
        interdit qu'un champ de ce genre apparaisse par une évolution future.
        """
        forbidden = ("email", "phone", "linkedin", "contact_person", "first_name", "last_name")
        blob = json.dumps(signals, ensure_ascii=False).lower()
        for field in forbidden:
            assert f'"{field}"' not in blob


class TestDocumentMode:
    def test_every_signal_is_metadata_fallback(self, signals: list[dict]) -> None:
        """§5 — SPEC-006 reste désactivée, le banc n'utilise aucun document."""
        assert {s["source_mode"] for s in signals} == {"metadata_fallback"}

    def test_every_signal_discloses_that_the_need_is_inferred(self, signals: list[dict]) -> None:
        """§51 — la limitation conceptuelle existe dans chaque snapshot."""
        for snapshot in signals:
            assert DOCUMENT_MODE_DISCLOSURE in snapshot["limitations"]

    def test_no_experimental_document_requirement_leaked_in(self, signals: list[dict]) -> None:
        """§5 — aucune sortie expérimentale de Document Intelligence n'est consommée."""
        blob = json.dumps(signals, ensure_ascii=False)
        assert "document_supported" not in blob
        assert "document-confirmed" not in blob

    def test_the_auto_document_requirements_flag_is_still_off(self) -> None:
        """La précondition de SPEC-009 tient toujours au moment du banc."""
        from signals.documents import AUTO_DOCUMENT_REQUIREMENTS_ENABLED

        assert AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False

    def test_confidence_never_exceeds_medium(self, signals: list[dict]) -> None:
        """§57 — sans document validé, aucun signal ne prétend à une confiance haute."""
        assert {s["score"]["confidence"] for s in signals} <= {"medium", "low"}


class TestWordingSafety:
    def test_no_certainty_wording_in_any_snapshot(self, signals: list[dict]) -> None:
        """§50 — aucune formulation d'achat certain, en français comme en anglais."""
        for snapshot in signals:
            blob = json.dumps(snapshot, ensure_ascii=False)
            assert forbidden_wording_hits(blob) == (), snapshot["signal_id"]

    def test_no_certainty_wording_in_the_rendered_signal(self) -> None:
        """§49, §50 — la représentation textuelle destinée à SPEC-011 est sûre."""
        texts = _load(TEXTS)
        assert len(texts) == 100
        for signal, text in texts.items():
            assert forbidden_wording_hits(text) == (), signal

    def test_the_rendered_signal_keeps_its_sections(self) -> None:
        """§49 — la structure conceptuelle est stable pour SPEC-011."""
        expected = (
            "Winner",
            "Award",
            "Why this matters",
            "Potential needs",
            "Why it matches this ICP",
            "Timing",
            "Confidence",
            "Proof",
        )
        for text in _load(TEXTS).values():
            for section in expected:
                assert f"\n{section}\n" in f"\n{text}\n", section


class TestBlindView:
    def test_the_adjudication_view_hides_every_engine_conclusion(self) -> None:
        """§28 — sans cela, l'arbitre vérifierait le moteur au lieu de juger le signal."""
        blind = _load(BLIND)["signals"]
        assert len(blind) == 100
        blob = json.dumps(blind, ensure_ascii=False)
        for leaked in (
            "normalized_score",
            "score_components",
            "band",
            "decision",
            "rule_ids",
            "mechanism_facts",
            "pressure_facts",
            "raw_points",
        ):
            assert f'"{leaked}"' not in blob, leaked

    def test_the_adjudication_view_still_carries_what_is_needed_to_judge(self) -> None:
        """§28 — faits publics, gagnant, contrat, besoin dérivé, ICP, preuve, timing."""
        for view in _load(BLIND)["signals"]:
            assert view["winner"]["parties"]
            assert view["contract"]["title"] or view["contract"]["contract_reference"]
            assert view["derived_needs"]
            assert view["icp"]["offer_summary"]
            assert view["evidence_refs"]
            assert view["contract_understanding"]["timing"]
            assert view["source_mode"] == "metadata_fallback"
            assert view["disclosure"] == DOCUMENT_MODE_DISCLOSURE

    def test_the_blind_view_covers_the_same_signals_as_the_bench(self, signals: list[dict]) -> None:
        blind_ids = {view["signal_id"] for view in _load(BLIND)["signals"]}
        assert blind_ids == {snapshot["signal_id"] for snapshot in signals}
