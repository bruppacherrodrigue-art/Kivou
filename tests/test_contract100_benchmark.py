"""Benchmark Contract-100 — le gate qualité de la compréhension contractuelle.

100 adjudications **réelles** extraites par nos connecteurs de vrais avis :
55 SIMAP + 45 TED, 19 pays acheteurs, 12 familles de contrat, 57 avec lot,
9 sans montant publié, 55 descriptions en HTML, 2 groupements.

Les critères qui comptent, dans l'ordre :

1. **aucune classification `high` fausse** — une erreur affichée avec assurance
   est pire qu'un `unknown` assumé ;
2. **aucun besoin commercial dans un résumé** — un résumé contractuel n'est pas
   un signal de vente ;
3. **couverture de preuve de 100 %** sur les affirmations matérielles.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from signals.domain import ContractAward, PublicEvent
from signals.understanding import ContractUnderstandingEngine, contract_type_for_cpv

BENCHMARK = Path(__file__).parent / "fixtures" / "contract100" / "awards.json"

# Formulations qui transformeraient un résumé en signal commercial (§38).
BUSINESS_NEED_PHRASES = (
    "will need",
    "likely",
    "should hire",
    "will buy",
    "probably purchase",
    "aura besoin",
    "devra recruter",
    "va acheter",
    "probablement",
    "sans doute",
    "wird benötigen",
    "dürfte",
    "opportunité",
    "opportunity",
)


@pytest.fixture(scope="module")
def corpus() -> list[dict]:
    return json.loads(BENCHMARK.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def understandings(corpus: list[dict]):
    engine = ContractUnderstandingEngine()
    results = []
    for row in corpus:
        event = PublicEvent.model_validate(row["event"])
        award = ContractAward.model_validate(row["award"])
        results.append((row, award, engine.understand(award, event)))
    return results


# ─── Composition ────────────────────────────────────────────────────────────────


def test_le_benchmark_couvre_cent_contrats_varies(corpus: list[dict]):
    assert len(corpus) == 100
    sources = collections.Counter(row["source"] for row in corpus)
    assert sources == {"simap": 55, "ted": 45}

    familles = {
        contract_type_for_cpv((row["award"].get("cpv_main") or {}).get("code")) for row in corpus
    }
    assert len(familles) >= 10  # 12 familles observées
    assert sum(1 for row in corpus if row["award"].get("value") is None) >= 5  # valeur absente
    assert sum(1 for row in corpus if row["award"].get("lot")) >= 20  # multi-lot
    assert sum(1 for row in corpus if "<" in (row["award"].get("description") or "")) >= 20  # HTML
    assert len({row["event"]["provenance"]["source_country"] for row in corpus}) >= 15


# ─── Métrique principale : aucune erreur affichée avec assurance ────────────────


def test_aucune_classification_sure_ne_contredit_le_cpv(understandings):
    """Une classification `high` ou `medium` s'appuie toujours sur le CPV publié."""
    for row, award, understanding in understandings:
        claim = understanding.contract_type
        if claim.confidence in ("high", "medium"):
            attendu = contract_type_for_cpv(award.cpv_main.code if award.cpv_main else None)
            assert claim.value == attendu, row["notice"]


def test_une_contradiction_entre_cpv_et_texte_abaisse_toujours_la_confiance(understandings):
    for _, _, understanding in understandings:
        claim = understanding.contract_type
        if claim.rule and "divergence" in claim.rule:
            assert claim.confidence == "low"


def test_toute_classification_incertaine_est_explicitement_incertaine(understandings):
    """Aucun `unknown` ne se présente comme sûr."""
    for _, _, understanding in understandings:
        if understanding.contract_type.value == "unknown":
            assert understanding.contract_type.confidence == "low"


# ─── Résumés ────────────────────────────────────────────────────────────────────


def test_aucun_resume_ne_contient_de_besoin_commercial(understandings):
    for row, _, understanding in understandings:
        resume = understanding.object_summary.value.casefold()
        for phrase in BUSINESS_NEED_PHRASES:
            assert phrase not in resume, f"{row['notice']} : « {phrase} »"


def test_chaque_resume_ne_cite_que_des_valeurs_publiees(understandings):
    """Le titre publié apparaît tel quel : aucune reformulation, donc aucune invention."""
    for _, award, understanding in understandings:
        if award.title:
            assert award.title in understanding.object_summary.value


def test_chaque_resume_est_adosse_a_des_preuves(understandings):
    for _, _, understanding in understandings:
        assert understanding.object_summary.evidence


# ─── Couverture de preuve ───────────────────────────────────────────────────────


def test_la_couverture_de_preuve_est_totale(understandings):
    for row, _, understanding in understandings:
        assert understanding.evidence_coverage == 1.0, row["notice"]


def test_les_faits_critiques_remontent_tous_a_leur_avis(understandings):
    """Gagnant, montant, CPV, acheteur, date : chacun cite son champ d'origine."""
    for row, award, understanding in understandings:
        facts = understanding.facts
        assert "winner" in facts and facts["winner"].evidence
        assert "cpv" in facts and facts["cpv"].evidence
        if award.value is not None:
            assert facts["amount"].evidence[0].path == "value"
        for claim in facts.values():
            assert claim.kind == "source_fact"
            evidence = claim.evidence[0]
            assert evidence.source_system == row["source"]
            assert evidence.source_notice_id
            assert evidence.path


def test_les_preuves_ted_et_simap_partagent_le_meme_modele(understandings):
    chemins = collections.defaultdict(set)
    for row, _, understanding in understandings:
        chemins[row["source"]].add(understanding.facts["cpv"].evidence[0].path)
    assert chemins["simap"] == {"procurement.cpvCode.code"}
    assert chemins["ted"] == {
        "cac:ProcurementProject/cac:MainCommodityClassification/cbc:ItemClassificationCode"
    }


# ─── Le fait brut reste intact ──────────────────────────────────────────────────


def test_aucun_award_n_est_modifie_par_la_comprehension(corpus: list[dict], understandings):
    engine = ContractUnderstandingEngine()
    for row in corpus:
        award = ContractAward.model_validate(row["award"])
        avant = award.model_dump_json()
        engine.understand(award, PublicEvent.model_validate(row["event"]))
        assert award.model_dump_json() == avant


def test_le_moteur_est_reproductible(corpus: list[dict]):
    engine = ContractUnderstandingEngine()
    row = corpus[0]
    event = PublicEvent.model_validate(row["event"])
    award = ContractAward.model_validate(row["award"])
    assert engine.understand(award, event) == engine.understand(award, event)


def test_toute_donnee_derivee_porte_la_version_du_moteur(understandings):
    for _, _, understanding in understandings:
        assert understanding.engine_version == "contract-understanding-v0.3"
