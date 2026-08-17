"""SIGNAL-100 GOLD — le gel commercial et la baseline qu'il établit (SPEC-009 §32).

Le corpus, le gold et la rubrique ont été gelés APRÈS l'adjudication et AVANT
toute comparaison aux scores Kivou. Ces tests épinglent les octets, la
composition du gold, la trace des deux perspectives et le résultat des gates.

Ce sont des archives : elles ne bougent pas quand les moteurs évolueront. Si une
empreinte diverge, c'est le gel qu'il faut restaurer — jamais l'empreinte qu'il
faut mettre à jour.
"""

from __future__ import annotations

import collections
import json
import pathlib

import pytest

from signals.research.signal100_adjudication import (
    DIMENSIONS,
    VERDICTS,
    needs_arbitration,
    resolve,
)
from signals.research.signal100_freeze import engine_version_set, sha256_of
from signals.research.signal100_metrics import agreement, evaluate_gates, headline, safety

FIXTURES = pathlib.Path("tests/fixtures/signal100")
GOLD = FIXTURES / "signal100_gold.json"
CORPUS = FIXTURES / "signal100_corpus.json"
SEAL = FIXTURES / "signal100_seal.json"

CORPUS_SHA256 = "7996beae4a7c1c609f2db1e7eea647f32beb4c06eb3349071e613aceb224aebf"
GOLD_SHA256 = "21be11fc89d27eb8a229b22213454073b0a02cfd2d23bc6b0b6833aaf1d3e5af"

#: La composition gelée du 17 août 2026 — la baseline commerciale du MVP.
FROZEN_COMPOSITION = {"A": 5, "B": 47, "C": 38, "D": 10}

IMMUTABLE = (
    "Le banc SIGNAL-100 et son gold commercial sont IMMUABLES (SPEC-009 §32) : "
    "ils ont été gelés après adjudication et avant toute lecture des scores. "
    "Une divergence d'empreinte invalide l'évaluation — restaurer les octets "
    "gelés, jamais mettre l'empreinte à jour."
)

pytestmark = pytest.mark.skipif(
    not GOLD.exists(), reason="le gold SIGNAL-100 n'a pas encore été produit"
)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return _load(GOLD)["records"]


class TestSeal:
    def test_the_frozen_fingerprints_match_the_bytes_on_disk(self) -> None:
        assert sha256_of(CORPUS) == CORPUS_SHA256, IMMUTABLE
        assert sha256_of(GOLD) == GOLD_SHA256, IMMUTABLE

    def test_the_seal_declares_the_same_fingerprints(self) -> None:
        seal = _load(SEAL)
        assert seal["signal100_corpus_sha256"] == CORPUS_SHA256
        assert seal["signal100_gold_sha256"] == GOLD_SHA256
        assert seal["commercial_rubric_version"] == "commercial-signal-rubric-v1"

    def test_the_seal_pins_the_engine_versions_of_the_run(self) -> None:
        """§32, §62 — le banc n'est comparable qu'à versions égales."""
        assert (
            _load(SEAL)["engine_version_set"]
            == engine_version_set()
            == {
                "understanding_engine": "contract-understanding-v0.1",
                "need_engine": "need-graph-v0.1",
                "match_policy": "icp-match-v0.1",
                "score_policy": "signal-score-v0.2",
                "reference_icp_library": "reference-icps-v0.1",
            }
        )

    def test_the_seal_pins_the_frozen_icp_library(self) -> None:
        """La bibliothèque d'ICPs est celle gelée par SPEC-008 §42, inchangée."""
        assert (
            _load(SEAL)["icp_library_sha256"]
            == "698cb112eaa6478eb4680e8513cf036dc22d7651437a356f0637967361400fb2"
        )


class TestGoldComposition:
    def test_one_hundred_records_with_the_frozen_composition(self, records: list[dict]) -> None:
        assert len(records) == 100
        composition = collections.Counter(r["final_verdict"] for r in records)
        assert dict(composition) == FROZEN_COMPOSITION, IMMUTABLE
        assert _load(GOLD)["composition"] == FROZEN_COMPOSITION

    def test_verdicts_and_dimensions_stay_inside_the_closed_rubric(
        self, records: list[dict]
    ) -> None:
        assert {r["final_verdict"] for r in records} <= set(VERDICTS)
        for record in records:
            for dimension, allowed in DIMENSIONS.items():
                assert record["final_dimensions"][dimension] in allowed

    def test_every_record_keeps_both_independent_perspectives(self, records: list[dict]) -> None:
        """§29, §30 — le gold conserve A, B, l'arbitrage et le verdict final."""
        for record in records:
            assert record["review_a"]["signal_id"] == record["signal_id"]
            assert record["review_b"]["signal_id"] == record["signal_id"]
            assert "arbitration" in record
            assert record["final_source"] in ("arbitration", "most_severe")

    def test_arbitration_happened_exactly_where_the_spec_requires_it(
        self, records: list[dict]
    ) -> None:
        """§30 — ni arbitrage manquant, ni arbitrage superflu."""
        for record in records:
            required = needs_arbitration(record["review_a"], record["review_b"])
            assert (record["arbitration"] is not None) == required, record["signal_id"]

    def test_the_final_verdict_is_reproducible_from_the_declared_rule(
        self, records: list[dict]
    ) -> None:
        """La résolution a été déclarée avant adjudication : elle doit se rejouer."""
        for record in records:
            resolved = resolve(record["review_a"], record["review_b"], record["arbitration"])
            assert resolved["final_verdict"] == record["final_verdict"], record["signal_id"]

    def test_every_failing_signal_names_one_responsible_layer(self, records: list[dict]) -> None:
        """§45 — chaque C et D est rattaché à une seule couche primaire."""
        for record in records:
            failing = record["final_verdict"] in ("C", "D")
            assert (record["primary_failure_layer"] is not None) == failing, record["signal_id"]


class TestFrozenBaseline:
    """La baseline commerciale du 17 août 2026 — telle qu'observée, non retouchée."""

    def test_the_headline_metrics_are_the_frozen_ones(self, records: list[dict]) -> None:
        head = headline(records)
        assert head["signals_evaluated"] == 100
        assert head["actionable_rate"] == 5.0
        assert head["useful_precision"] == 52.0
        assert head["weak_rate"] == 38.0
        assert head["false_rate"] == 10.0

    def test_the_safety_counters_are_the_frozen_ones(self, records: list[dict]) -> None:
        """Les faits et les preuves tiennent ; le besoin et le ciblage, non."""
        counters = safety(records)
        assert counters["factual_integrity_rate"] == 100.0
        assert counters["proof_coverage"] == 100.0
        assert counters["critical_overclaiming"] == 0
        assert counters["critical_false_signals"] == 9
        assert counters["timing_errors"] == 4

    def test_the_commercial_doctrine_was_stable_enough_to_be_trusted(
        self, records: list[dict]
    ) -> None:
        """§31 — c'est ce gate qui rend le reste du banc interprétable.

        Sans lui, un mauvais résultat pourrait n'être qu'un désaccord de
        rubrique. 98 % d'accord à un grade près écarte cette lecture.
        """
        stability = agreement(records)
        assert stability["agreement_within_one_grade_rate"] >= 90.0
        assert stability["agreement_within_one_grade_rate"] == 98.0
        assert stability["exact_agreement_rate"] == 73.0
        assert stability["arbitrations"] == 14

    def test_the_run_did_not_pass_and_says_exactly_why(self, records: list[dict]) -> None:
        """§59, §61 — le verdict est NOT DONE, et les gates échoués sont nommés.

        Ce test archive un échec réel. Il ne devra pas être « réparé » : quand
        un moteur progressera, c'est un NOUVEAU banc qu'il faudra construire,
        sur des données fraîches, pas celui-ci qu'il faudra réécrire.
        """
        result = evaluate_gates(records)
        assert result["signal_count_is_100"] is True
        assert result["verdict"] == "SPEC-009 NOT DONE"
        assert set(result["failed_gates"]) == {
            "useful_precision",
            "actionable_rate",
            "weak_rate",
            "false_rate",
            "critical_false_signals",
            "timing_errors",
            "top20_useful_precision",
            "top20_critical_false",
            "source_useful_precision[ted]",
            "source_useful_precision[simap]",
        }

    def test_the_gates_that_did_hold_are_named_too(self, records: list[dict]) -> None:
        """Un échec global n'efface pas ce qui tient : les faits et les preuves."""
        gates = evaluate_gates(records)["gates"]
        for name in (
            "factual_integrity_rate",
            "proof_coverage",
            "critical_overclaiming",
            "rubric_agreement_within_one",
        ):
            assert gates[name]["passed"], name
