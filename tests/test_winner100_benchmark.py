"""Benchmark Winner-100 — le gate qualité de la résolution des gagnants.

100 mentions d'organisations gagnantes **réelles**, extraites par nos propres
connecteurs de vrais avis TED et SIMAP : 55 SIMAP + 45 TED, 23 pays, 26 membres
de groupement, des répétitions d'une même entreprise, des écritures cyrilliques,
des noms voisins.

La **vérité terrain est indépendante du moteur** : elle ne repose que sur ce que
les sources publient (`gold_pairs.json`). Identifiant publié identique dans la
même source et le même pays → même entreprise ; identifiants différents dans la
même source → entreprises différentes. Tout le reste n'est pas étiqueté : sans
registre, ce n'est pas vérifiable, et une vérité terrain devinée ne vaut rien.

Le critère qui compte n'est pas le nombre de résolutions, c'est **zéro fusion
abusive**.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import httpx
import pytest

from signals.domain import OrganizationRef
from signals.resolution import CompanyResolver, ViesClient

FIXTURES = Path(__file__).parent / "fixtures"
BENCHMARK = FIXTURES / "winner100"
VIES_FIXTURES = FIXTURES / "vies"


@pytest.fixture(scope="module")
def mentions() -> list[dict]:
    return json.loads((BENCHMARK / "mentions.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gold() -> dict:
    return json.loads((BENCHMARK / "gold_pairs.json").read_text(encoding="utf-8"))


def offline_vies() -> ViesClient:
    """Seules les réponses VIES réellement enregistrées sont servies.

    Les autres numéros ressortent indisponibles — ce qui reproduit fidèlement la
    situation d'un run sans réseau, et vérifie au passage qu'une indisponibilité
    ne dégrade jamais une résolution en résultat négatif.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        parts = str(request.url).rstrip("/").split("/")
        path = VIES_FIXTURES / f"{parts[-3]}{parts[-1]}.json"
        if not path.exists():
            return httpx.Response(503)
        return httpx.Response(
            200, content=path.read_bytes(), headers={"Content-Type": "application/json"}
        )

    return ViesClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture(scope="module")
def run(mentions: list[dict]):
    resolver = CompanyResolver(vies=offline_vies())
    resolutions = [
        resolver.resolve(
            OrganizationRef.model_validate(row["organization"]), source_system=row["source"]
        )
        for row in mentions
    ]
    return resolver, resolutions


# ─── Composition du benchmark ───────────────────────────────────────────────────


def test_le_benchmark_couvre_bien_cent_mentions_variees(mentions: list[dict]):
    assert len(mentions) == 100
    sources = collections.Counter(row["source"] for row in mentions)
    assert sources == {"simap": 55, "ted": 45}

    countries = {row["organization"].get("country") for row in mentions}
    assert len(countries) >= 20  # 23 pays observés
    assert sum(1 for row in mentions if row["party_name"]) >= 20  # membres de groupement
    assert any(
        any(ord(char) > 0x400 for char in row["organization"]["legal_name"]) for row in mentions
    )  # écriture non latine


# ─── TARGET A — aucune fusion abusive ───────────────────────────────────────────


def test_target_a_aucune_fusion_contredite_par_la_verite_terrain(mentions, gold, run):
    """LE critère : deux mentions étiquetées « différentes » ne partagent aucune entreprise."""
    _, resolutions = run
    faux_merges = []
    for left, right, label in gold["pairs"]:
        if label != "d":
            continue
        a, b = resolutions[left], resolutions[right]
        if a.company is not None and a.company is b.company:
            faux_merges.append((mentions[left], mentions[right]))
    assert faux_merges == [], f"fusions abusives : {faux_merges[:3]}"


def test_target_a_bis_les_memes_entreprises_sont_bien_regroupees(gold, run):
    """L'inverse : ce que la source dit identique doit se retrouver ensemble."""
    _, resolutions = run
    manques = []
    for left, right, label in gold["pairs"]:
        if label != "s":
            continue
        a, b = resolutions[left], resolutions[right]
        if a.company is None or a.company is not b.company:
            manques.append((left, right))
    assert manques == []


# ─── TARGET B — toute résolution automatique est explicable ─────────────────────


def test_target_b_chaque_resolution_porte_sa_trace(run):
    _, resolutions = run
    for resolution in resolutions:
        if resolution.company is not None:
            assert resolution.basis, resolution.source_organization.legal_name
            assert all(basis.detail for basis in resolution.basis)


def test_target_b_bis_les_methodes_utilisees_sont_toutes_documentees(run):
    _, resolutions = run
    methods = {basis.method for resolution in resolutions for basis in resolution.basis}
    assert methods <= {
        "official_identifier",
        "source_local_identifier",
        "unattributed_identifier",
        "registry_lookup",
        "name_and_address",
        "fuzzy_name",
    }


# ─── TARGET C — l'ambiguïté ne devient jamais une certitude ─────────────────────


def test_target_c_aucune_entreprise_verifiee_sans_preuve_forte(run):
    """`verified` exige un identifiant officiel ou un registre — jamais un nom."""
    _, resolutions = run
    for resolution in resolutions:
        if resolution.status == "verified":
            methods = {basis.method for basis in resolution.basis if basis.supports}
            assert methods & {"official_identifier", "registry_lookup"}


def test_target_c_bis_le_nom_approche_ne_verifie_jamais(run):
    _, resolutions = run
    for resolution in resolutions:
        supporting = {b.method for b in resolution.basis if b.supports}
        assert "fuzzy_name" not in supporting


def test_target_c_ter_un_statut_incertain_ne_porte_aucune_entreprise(run):
    _, resolutions = run
    for resolution in resolutions:
        if resolution.status in ("review_required", "conflict", "unresolved"):
            assert resolution.company is None


# ─── TARGET D — 95/100 résolus ou correctement signalés ─────────────────────────


def test_target_d_au_moins_95_pour_cent_exploitables_ou_signales(run):
    _, resolutions = run
    ok = sum(
        1
        for resolution in resolutions
        if resolution.is_resolved or resolution.needs_human or resolution.status == "unresolved"
    )
    assert ok >= 95


# ─── Invariants de source ───────────────────────────────────────────────────────


def test_aucune_fusion_cross_source_par_identifiant_local(mentions, run):
    """Un `SIMAP-VENDOR-ID` ne rapproche jamais une mention TED d'une mention SIMAP."""
    _, resolutions = run
    for row, resolution in zip(mentions, resolutions, strict=True):
        for basis in resolution.basis:
            if basis.method == "source_local_identifier":
                assert row["source"] in basis.detail


def test_les_mentions_publiees_traversent_la_resolution_intactes(mentions, run):
    _, resolutions = run
    for row, resolution in zip(mentions, resolutions, strict=True):
        assert resolution.source_organization == OrganizationRef.model_validate(row["organization"])


def test_le_registre_indisponible_ne_produit_aucun_faux_negatif(run):
    """Beaucoup de TVA ne sont pas dans les fixtures : elles ressortent indisponibles."""
    _, resolutions = run
    for resolution in resolutions:
        indisponible = any("indisponible" in b.detail for b in resolution.basis)
        if indisponible:
            assert resolution.status != "conflict"
