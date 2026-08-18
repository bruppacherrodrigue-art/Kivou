"""SIGNAL-MATCH-FINAL — le gel du held-out final de matching (SPEC-008 §42).

Corpus, gold et bibliothèque d'ICPs sont gelés depuis le 17 août 2026, AVANT
toute exécution du moteur de matching. Ces tests épinglent les empreintes des
octets sur disque, la re-sérialisation des ICPs de référence, la composition du
gold, les versions de politique déclarées et la disjonction avec DEV (contrat
100) et le held-out SPEC-007 : toute modification ultérieure doit casser ici.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib

from signals.matching import (
    MATCH_POLICY_VERSION,
    REFERENCE_ICP_LIBRARY_VERSION,
    REFERENCE_ICPS,
    SCORE_POLICY_VERSION,
)

FIXTURES = pathlib.Path("tests/fixtures/matching")
DEV_AWARDS = pathlib.Path("tests/fixtures/contract100/awards.json")
SPEC007_CORPUS = pathlib.Path("tests/fixtures/needs/need_final_corpus.json")

REFERENCE_ICPS_SHA256 = "698cb112eaa6478eb4680e8513cf036dc22d7651437a356f0637967361400fb2"
FINAL_CORPUS_SHA256 = "441f0d10614ea1ad05d5948b530a9dab22f9fba7d25143b14aa66435cf62c006"
FINAL_GOLD_SHA256 = "7e183446b7bfa63dc18e153c5ade2edb6ffce7565df354cc809b3e6ece75b583"

DECLARED_SHA256 = {
    "reference_icps.json": REFERENCE_ICPS_SHA256,
    "signal_match_final_corpus.json": FINAL_CORPUS_SHA256,
    "signal_match_final_gold.json": FINAL_GOLD_SHA256,
}

# Vocabulaire fermé de la rubrique icp-match-rubric-v1 (SPEC-008 §42).
GRADES = {"strong_match", "plausible_match", "no_match", "insufficient_data"}

IMMUTABLE = (
    "Le corpus et le gold du held-out final de matching sont IMMUABLES "
    "(SPEC-008 §42) : ils ont été gelés avant toute exécution du moteur. "
    "Une divergence d'empreinte invalide l'évaluation finale — il faut "
    "restaurer les octets gelés, jamais mettre l'empreinte à jour."
)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: pathlib.Path) -> list[dict]:
    """Renvoie les lignes d'un corpus, qu'il soit une liste nue ou un objet `rows`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else payload["rows"]


def _identities(rows: list[dict]) -> dict[str, set]:
    """Extrait les quatre niveaux d'identité déclarés par `disjointness` du corpus.

    Publication (`source` + `notice`), notice source (`provenance.source_notice_id`),
    procédure (`provenance.source_procedure_id`) et identité d'award
    (`award.event_ref` + `source_award_id` + identifiant de lot).
    """
    publications: set[tuple] = set()
    notices: set[tuple] = set()
    procedures: set[tuple] = set()
    awards: set[tuple] = set()
    for row in rows:
        provenance = row["event"]["provenance"]
        system = provenance["source_system"]
        publications.add((row["source"], row["notice"]))
        notices.add((system, provenance["source_notice_id"]))
        if provenance.get("source_procedure_id") is not None:
            procedures.add((system, provenance["source_procedure_id"]))
        award = row["award"]
        event_ref = award["event_ref"]
        awards.add(
            (
                event_ref["source_system"],
                event_ref["source_notice_id"],
                event_ref.get("notice_version"),
                award.get("source_award_id"),
                (award.get("lot") or {}).get("identifier"),
            )
        )
    return {
        "publication": publications,
        "notice": notices,
        "procedure": procedures,
        "award identity": awards,
    }


class TestFreeze:
    def test_frozen_fixtures_match_declared_sha256(self) -> None:
        """Les trois fixtures gelées sont octet pour octet celles de SPEC-008 §42."""
        observed = {name: _sha(FIXTURES / name) for name in DECLARED_SHA256}
        assert observed == DECLARED_SHA256, (
            f"{IMMUTABLE}\nattendu : {DECLARED_SHA256}\nobservé : {observed}"
        )

    def test_reference_icp_library_still_serializes_to_frozen_fixture(self) -> None:
        """`REFERENCE_ICPS` re-sérialisé est identique au gel : attrape toute retouche d'ICP."""
        frozen = _load(FIXTURES / "reference_icps.json")
        # WEDGE-HARDENING R1 §14 ajoute deux champs de ciblage métier au modèle.
        # Le gel est l'archive de SPEC-008 : on le compare donc sur les champs qui
        # existaient alors, et on vérifie séparément que les nouveaux sont VIDES
        # sur les sept ICPs gelés — c'est ce qui prouve qu'aucun ne change de
        # comportement. Toute autre retouche d'un ICP casse toujours ici.
        added_since_freeze = ("primary_trade_domains", "secondary_trade_domains")
        current = [icp.model_dump(mode="json") for icp in REFERENCE_ICPS]
        for icp in current:
            for field in added_since_freeze:
                assert icp.pop(field) == [], (
                    f"{IMMUTABLE}\nl'ICP gelé {icp['icp_id']!r} déclare un corps de "
                    "métier : il ne produirait plus les mêmes signaux qu'au gel."
                )
        serialized = current
        assert REFERENCE_ICP_LIBRARY_VERSION == frozen["version"], (
            f"{IMMUTABLE}\nversion de bibliothèque attendue : {frozen['version']!r}, "
            f"observée : {REFERENCE_ICP_LIBRARY_VERSION!r}"
        )
        assert serialized == frozen["icps"], (
            f"{IMMUTABLE}\nUn ICP de référence a changé depuis le gel : les scores "
            "du held-out final ne seraient plus comparables."
        )


class TestGoldComposition:
    def test_frozen_gold_composition(self) -> None:
        """680 lignes = 85 award-lots × 8 ICPs, avec la composition gelée des grades."""
        gold = _load(FIXTURES / "signal_match_final_gold.json")
        rows = gold["rows"]
        assert len(rows) == 680
        per_case = collections.Counter(row["case_id"] for row in rows)
        assert len(per_case) == 85
        assert set(per_case.values()) == {8}
        assert len({row["icp_id"] for row in rows}) == 8
        composition = collections.Counter(row["grade"] for row in rows)
        assert dict(composition) == {
            "no_match": 556,
            "strong_match": 57,
            "plausible_match": 50,
            "insufficient_data": 17,
        }
        assert gold["composition"] == dict(composition)

    def test_grades_are_from_the_closed_rubric_vocabulary(self) -> None:
        """Aucun grade hors du vocabulaire fermé de la rubrique."""
        gold = _load(FIXTURES / "signal_match_final_gold.json")
        assert {row["grade"] for row in gold["rows"]} <= GRADES


class TestDeclaredPolicies:
    def test_frozen_gold_declares_policy_versions(self) -> None:
        """Le bloc `frozen` cite les versions de politique et les SHA réellement sur disque."""
        frozen = _load(FIXTURES / "signal_match_final_gold.json")["frozen"]
        assert frozen["match_rubric_version"] == "icp-match-rubric-v1"
        assert frozen["match_policy_version"] == "icp-match-v0.1"
        assert frozen["reference_icp_library_version"] == REFERENCE_ICP_LIBRARY_VERSION
        assert frozen["corpus_sha256"] == _sha(FIXTURES / "signal_match_final_corpus.json")
        assert frozen["reference_icp_sha256"] == _sha(FIXTURES / "reference_icps.json")

    def test_the_gold_keeps_the_score_policy_version_of_its_own_run(self) -> None:
        """Le gold date son run : il porte `v0.1`, la version courante est `v0.2`.

        SPEC-008R §5 fait évoluer la sémantique publique de `ScoreBand`, mais §1
        interdit de toucher au gold — dont le SHA est gelé. La divergence est donc
        la bonne réponse : le gold est l'archive d'un run, pas un miroir du code.
        Ce qui doit rester vrai, c'est que les **décisions** n'ont pas bougé, ce
        que vérifie le rerun de non-régression.
        """
        frozen = _load(FIXTURES / "signal_match_final_gold.json")["frozen"]
        assert frozen["score_policy_version"] == "signal-score-v0.1"
        assert SCORE_POLICY_VERSION == "signal-score-v0.2"
        # WEDGE-HARDENING R1 §17 ajoute la porte « corps de métier » au matching :
        # même raisonnement, même conclusion. Le gold garde `icp-match-v0.1`.
        assert frozen["match_policy_version"] == "icp-match-v0.1"
        assert MATCH_POLICY_VERSION == "icp-match-v0.2"


class TestDisjointness:
    def test_final_corpus_is_disjoint_from_dev_and_spec007(self) -> None:
        """Aucune publication, notice, procédure ou award ne fuit depuis DEV ou SPEC-007."""
        final = _identities(_rows(FIXTURES / "signal_match_final_corpus.json"))
        dev = _identities(_rows(DEV_AWARDS))
        spec007 = _identities(_rows(SPEC007_CORPUS))
        for level, identities in final.items():
            assert identities, f"niveau d'identité {level} vide : extraction incorrecte"
            assert not (identities & dev[level]), (
                f"Fuite DEV au niveau {level} : {sorted(identities & dev[level])}"
            )
            assert not (identities & spec007[level]), (
                f"Fuite SPEC-007 au niveau {level} : {sorted(identities & spec007[level])}"
            )
