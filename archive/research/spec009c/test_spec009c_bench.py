"""SPEC-009C — l'intégrité du banc du feed client (§43).

Un seul client, un seul ICP, un seul feed. Ces tests ne jugent pas la qualité
commerciale — c'est le gold qui la porte — ils vérifient que le banc mesure bien
ce qu'il prétend mesurer : la bonne population, le bon ICP, aucune contamination
par les corpus de développement, et aucune sortie interdite par la doctrine.

Ils sont hors ligne : tout part des fixtures gelées.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib

import pytest

from signals.research.signal100 import (
    forbidden_wording_hits,
    identities,
    load_rows,
    prior_identities,
)

FIXTURES = pathlib.Path("tests/fixtures/signal100")
CORPUS = FIXTURES / "spec009c_corpus.json"
BENCH = FIXTURES / "spec009c_bench.json"
BLIND = FIXTURES / "spec009c_blind.json"
GOLD = FIXTURES / "spec009c_gold.json"

WEDGE_ICP = "icp-construction-inputs-ch-eu-v0"
TERRITORIES = {"CH", "DE", "FR", "ES", "PT"}

CORPUS_SHA256 = "da91b4a2b70ba4bb97438dca0744d01007f7f845f4066c494a2f5d38e86dc951"
GOLD_SHA256 = "c579a1396cdffbc24d57c564172f77f8f2d600a8f6d65c7e5363c2079fdbf50b"

IMMUTABLE = (
    "Le banc SPEC-009C est gelé (§21) : corpus, gold et ICP ont été figés avant "
    "tout calcul de gate. Une empreinte qui diverge invalide l'évaluation — "
    "restaurer les octets, jamais mettre l'empreinte à jour."
)

pytestmark = pytest.mark.skipif(not GOLD.exists(), reason="le banc SPEC-009C n'existe pas encore")


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bench() -> dict:
    return _load(BENCH)


@pytest.fixture(scope="module")
def gold() -> dict:
    return _load(GOLD)


class TestFreeze:
    def test_the_corpus_and_gold_match_their_published_fingerprints(self) -> None:
        assert hashlib.sha256(CORPUS.read_bytes()).hexdigest() == CORPUS_SHA256, IMMUTABLE
        assert hashlib.sha256(GOLD.read_bytes()).hexdigest() == GOLD_SHA256, IMMUTABLE

    def test_the_gold_declares_the_corpus_it_was_measured_on(self, gold: dict) -> None:
        assert gold["corpus_sha256"] == CORPUS_SHA256

    def test_the_gold_pins_the_engine_versions_of_the_run(self, gold: dict) -> None:
        assert gold["engine_versions"] == {
            "understanding": "contract-understanding-v0.3",
            "need": "need-graph-v0.2",
            "rule_library": "need-rules-v0.5",
            "match_policy": "icp-match-v0.2",
            "score_policy": "signal-score-v0.2",
            "bkp_policy": "bkp-trade-v0.1",
            "reference_icp_library": "reference-icps-v0.1",
        }


class TestOneClientOneIcpOneFeed:
    """§3 — aucune compétition entre ICPs, aucune règle « best ICP wins »."""

    def test_every_signal_belongs_to_the_wedge_icp(self, bench: dict) -> None:
        assert bench["icp"] == WEDGE_ICP
        for signal in bench["signals"]:
            assert signal["icp"]["icp_id"] == WEDGE_ICP

    def test_no_other_icp_appears_anywhere_in_the_bench(self) -> None:
        blob = BENCH.read_text(encoding="utf-8")
        for other in (
            "icp-materials-eu",
            "icp-national-supplier",
            "icp-staffing-ch",
            "icp-ppe-safety-ch",
            "icp-plant-hire-ch",
            "icp-waste-ch",
            "icp-remote-specialist",
        ):
            assert other not in blob, other

    def test_one_signal_per_award_lot(self, bench: dict) -> None:
        """Sans compétition entre ICPs, la déduplication cross-ICP n'a pas lieu d'être."""
        refs = [json.dumps(s["award_ref"], sort_keys=True) for s in bench["signals"]]
        assert len(refs) == len(set(refs))

    def test_signal_identifiers_are_unique(self, bench: dict) -> None:
        ids = [s["signal_id"] for s in bench["signals"]]
        assert len(ids) == len(set(ids))


class TestPopulation:
    def test_every_place_of_performance_is_inside_the_declared_territory(self, bench: dict) -> None:
        """§37 — le banc ne couvre que CH, DE, FR, ES et PT."""
        for signal in bench["signals"]:
            place = signal["contract"]["place_of_performance"] or {}
            assert place.get("country") in TERRITORIES, signal["signal_id"]

    def test_every_contract_is_a_works_contract(self, bench: dict) -> None:
        for signal in bench["signals"]:
            assert signal["understanding"]["contract_type"]["value"] == "construction"

    def test_every_signal_matches_the_primary_need(self, bench: dict) -> None:
        for signal in bench["signals"]:
            assert "materials_or_components" in signal["matched_needs"]

    def test_every_signal_carries_a_trade_domain(self, bench: dict) -> None:
        for signal in bench["signals"]:
            assert signal["trade_domain"]
            assert signal["trade_domain"] != "unknown_or_general"

    def test_only_primary_trade_domains_reach_the_feed(self, bench: dict) -> None:
        """§33 — un métier secondaire descend en `borderline`, il n'atteint pas le feed."""
        domains = {s["trade_domain"] for s in bench["signals"]}
        assert domains <= {"general_building", "interior_finishing", "earthworks_demolition"}

    def test_at_most_two_award_lots_per_notice(self, bench: dict) -> None:
        counts = collections.Counter((s["source"], s["notice"]) for s in bench["signals"])
        assert max(counts.values()) <= 2


class TestDoctrine:
    def test_every_signal_stays_in_metadata_mode(self, bench: dict) -> None:
        """§41 — SPEC-006 reste désactivée ; aucun document de marché n'est lu."""
        for signal in bench["signals"]:
            assert signal["source_mode"] == "metadata_fallback"

    def test_no_signal_claims_more_than_medium_confidence(self, bench: dict) -> None:
        for signal in bench["signals"]:
            assert signal["score"]["confidence"] in ("low", "medium")

    def test_every_signal_carries_its_evidence(self, bench: dict) -> None:
        for signal in bench["signals"]:
            assert signal["evidence_refs"], signal["signal_id"]

    def test_no_signal_uses_certainty_wording(self, bench: dict) -> None:
        """La frontière de vérité de la rubrique §1 : jamais d'intention d'achat."""
        for signal in bench["signals"]:
            for need in signal["selected_needs"]:
                for text in (need["statement"], need["reasoning"]):
                    assert not forbidden_wording_hits(text), signal["signal_id"]

    def test_the_experimental_verifier_never_touched_the_bench(self) -> None:
        """§5 — le module SPEC-009A reste expérimental et hors production."""
        blob = BENCH.read_text(encoding="utf-8") + GOLD.read_text(encoding="utf-8")
        for marker in ("commercial-verifier", "deepseek", "openrouter", "final_decision"):
            assert marker not in blob.lower(), marker


class TestDisjointness:
    """§7 — intersection nulle avec TOUS les corpus antérieurs."""

    def test_no_identity_is_shared_with_any_prior_corpus(self) -> None:
        prior = prior_identities()
        for level, values in identities(load_rows(FIXTURES / "signal100_pool_corpus.json")).items():
            prior[level] |= values
        mine = identities(load_rows(CORPUS))
        for level in ("publication", "notice", "procedure", "award identity"):
            assert mine[level], f"niveau {level} vide côté SPEC-009C"
            assert prior[level], f"niveau {level} vide côté antérieur"
            assert not (mine[level] & prior[level]), level


class TestBlindView:
    """§16 — l'adjudicateur ne voit que ce qu'un client verrait."""

    def test_the_blind_view_hides_every_engine_internal(self) -> None:
        blob = json.dumps(_load(BLIND)["signals"], ensure_ascii=False)
        for field in (
            "normalized_score",
            "raw_points",
            "band",
            "decision",
            "rule_ids",
            "mechanism_facts",
            "pressure_facts",
            "trade_domain",
            "trade_domain_source",
            "bkp_codes",
            "primary_trade_domains",
            "gold_verdict",
            "primary_failure_layer",
        ):
            assert f'"{field}"' not in blob, field

    def test_the_blind_view_covers_the_whole_bench(self, bench: dict) -> None:
        blind = _load(BLIND)
        assert blind["count"] == len(blind["signals"]) == len(bench["signals"])
        assert {s["signal_id"] for s in blind["signals"]} == {
            s["signal_id"] for s in bench["signals"]
        }


class TestGoldIntegrity:
    def test_every_record_keeps_both_perspectives_and_its_arbitration(self, gold: dict) -> None:
        for record in gold["records"]:
            assert record["review_a"]["signal_id"] == record["signal_id"]
            assert record["review_b"]["signal_id"] == record["signal_id"]
            assert "arbitration" in record
            assert record["final_source"] in ("arbitration", "most_severe")

    def test_every_failing_signal_names_one_responsible_layer(self, gold: dict) -> None:
        for record in gold["records"]:
            failing = record["final_verdict"] in ("C", "D")
            assert (record["primary_failure_layer"] is not None) == failing, record["signal_id"]

    def test_the_frozen_composition_is_the_observed_one(self, gold: dict) -> None:
        """Les chiffres du rapport, tels qu'observés — jamais retouchés."""
        assert gold["composition_verdicts"] == {"A": 30, "B": 34, "C": 31, "D": 5}
        assert gold["natural_shows"] == 110
        assert gold["funnel"]["award_lots"] == 2001
