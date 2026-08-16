"""Le moteur de résolution : normalisation, classement, registres, invariants.

Entièrement hors ligne. Les réponses VIES sont de **vraies** réponses de l'API
de la Commission, enregistrées telles quelles :

    LU26538172   TVA valide, titulaire divulgué (nom + adresse)
    RO6309553    TVA valide, titulaire divulgué, raison sociale plus complète
    DE238737605  TVA valide, l'État membre NE divulgue PAS le titulaire
    CZ25094769   MS_UNAVAILABLE — l'État membre n'a pas répondu
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from signals.domain import Company, OrganizationIdentifier, OrganizationRef
from signals.resolution import (
    CompanyResolution,
    CompanyResolver,
    RegistryAuthRequiredError,
    ResolutionBasis,
    ViesClient,
    ZefixClient,
    ZefixCredentials,
    classify,
)
from signals.resolution.normalize import matching_name, name_core, name_similarity, postal_code

VIES_FIXTURES = Path(__file__).parent / "fixtures" / "vies"


def vies_client() -> ViesClient:
    """Client VIES servi par les réponses réelles enregistrées."""

    def handler(request: httpx.Request) -> httpx.Response:
        parts = str(request.url).rstrip("/").split("/")
        country, number = parts[-3], parts[-1]
        path = VIES_FIXTURES / f"{country}{number}.json"
        if not path.exists():
            return httpx.Response(404)
        return httpx.Response(
            200, content=path.read_bytes(), headers={"Content-Type": "application/json"}
        )

    return ViesClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def org(name: str, **kwargs) -> OrganizationRef:
    scheme, value = kwargs.pop("scheme", None), kwargs.pop("value", None)
    kwargs.setdefault("country", "CH")
    return OrganizationRef(
        legal_name=name,
        identifiers=((OrganizationIdentifier(scheme=scheme, value=value),) if scheme else ()),
        **kwargs,
    )


# ─── Normalisation ──────────────────────────────────────────────────────────────


def test_les_variantes_d_ecriture_se_rejoignent():
    formes = ["ACME SA", "ACME S.A.", "Acme SA", "acme  sa"]
    assert len({matching_name(f) for f in formes}) == 1


def test_la_forme_juridique_ne_prouve_jamais_l_identite():
    assert name_core("Alpha SA") != name_core("Alpha Holding SA")
    assert name_similarity("Alpha SA", "Alpha Holding SA") < 1.0


def test_les_formes_juridiques_multi_mots_sont_retirees():
    """Sans cela, `MES d.o.o.` et `ROCHE d.o.o.` partageraient les jetons `d` et `o`."""
    assert name_core("MES d.o.o.") == "mes"
    assert name_core("ROCHE d.o.o.") == "roche"
    assert name_similarity("MES d.o.o.", "ROCHE d.o.o.") == 0.0


def test_les_ecritures_non_latines_sont_preservees():
    assert matching_name("Б. БРАУН МЕДИКАЛ ЕООД") == "б браун медикал еоод"
    assert matching_name("Б. БРАУН МЕДИКАЛ ЕООД") != matching_name("СИНЕРГОН ЕНЕРДЖИ ООД")


def test_le_code_postal_est_extrait_sans_etre_invente():
    assert postal_code("Schlottermilch 18, 6210, Sursee") == "6210"
    assert postal_code("Sursee") is None
    assert postal_code(None) is None


# ─── Classement des identifiants ────────────────────────────────────────────────


def test_les_trois_forces_d_identifiant():
    assert classify(OrganizationIdentifier(scheme="CHE-UID", value="CHE-1")).strength == "official"
    assert (
        classify(OrganizationIdentifier(scheme="SIMAP-VENDOR-ID", value="x")).strength
        == "source_local"
    )
    assert (
        classify(OrganizationIdentifier(scheme="TED-BT-501", value="9147")).strength
        == "unattributed"
    )
    assert classify(OrganizationIdentifier(scheme="MYSTERE", value="42")).strength == "unknown"


def test_un_scheme_inconnu_est_conserve_jamais_devine():
    classified = classify(OrganizationIdentifier(scheme="ID_PLATAFORMA", value="A-42"))
    assert classified.strength == "unknown"
    assert classified.published_value == "A-42"
    assert classified.registry is None


def test_la_valeur_publiee_survit_a_la_normalisation():
    classified = classify(OrganizationIdentifier(scheme="CHE-UID", value="CHE-123.456.789"))
    assert classified.published_value == "CHE-123.456.789"
    assert classified.matching_value == "CHE123456789"


def test_le_prefixe_pays_d_une_tva_est_conserve():
    classified = classify(OrganizationIdentifier(scheme="EU-VAT", value="LU 265 381 72"))
    assert classified.matching_value == "LU26538172"


# ─── VIES ───────────────────────────────────────────────────────────────────────


def test_vies_valide_et_divulgue_le_titulaire():
    with vies_client() as client:
        check = client.check("LU", "26538172")
    assert check.valid is True
    assert check.discloses_holder
    assert "WISAG" in check.name


def test_vies_valide_sans_divulgation_n_est_pas_un_refus():
    """L'Allemagne ne divulgue ni nom ni adresse : `---` n'est pas une réponse négative."""
    with vies_client() as client:
        check = client.check("DE", "238737605")
    assert check.valid is True
    assert check.name is None
    assert not check.discloses_holder


def test_un_etat_membre_indisponible_n_est_jamais_une_preuve_negative():
    with vies_client() as client:
        check = client.check("CZ", "25094769")
    assert check.unavailable is True
    assert check.valid is None  # ni valide ni invalide : inconnu
    assert check.detail == "MS_UNAVAILABLE"


def test_le_cache_evite_de_reinterroger_le_registre():
    with vies_client() as client:
        for _ in range(5):
            client.check("LU", "26538172")
    assert client.requests_sent == 1
    assert client.cache_hits == 4


def test_une_panne_reseau_ne_devient_pas_une_entreprise_inexistante():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("réseau coupé")

    with ViesClient(client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        check = client.check("LU", "26538172")
    assert check.unavailable is True
    assert check.valid is None


# ─── Zefix : authentification requise ───────────────────────────────────────────


def test_zefix_sans_identifiants_ne_sort_jamais_sur_le_reseau():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=[])

    client = ZefixClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.available is False
    with pytest.raises(RegistryAuthRequiredError, match="identifiants"):
        client.search_by_name("Egli Gartenbau AG")
    assert calls == []  # aucune requête émise


def test_zefix_refuse_est_distingue_d_une_panne():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = ZefixClient(
        credentials=ZefixCredentials("user", "pass"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RegistryAuthRequiredError):
        client.search_by_name("Egli Gartenbau AG")


# ─── Résolution par registre ────────────────────────────────────────────────────


def test_une_tva_validee_et_concordante_verifie_l_entreprise():
    resolver = CompanyResolver(vies=vies_client())
    resolution = resolver.resolve(
        org(
            "Wisag Cleaning Service Sàrl",
            country="LU",
            address="4, Breedewues, 1259, Senningerberg",
            scheme="TED-BT-501",
            value="LU26538172",
        ),
        source_system="ted",
    )
    assert resolution.status == "verified"
    assert resolution.company is not None
    assert any(b.method == "registry_lookup" for b in resolution.basis)
    assert "WISAG" in resolution.basis[0].detail


def test_une_tva_validee_sans_divulgation_reste_probable():
    resolver = CompanyResolver(vies=vies_client())
    resolution = resolver.resolve(
        org(
            "Fa. Missing Link Versand",
            country="DE",
            address="Str. 1, 10115, Berlin",
            scheme="TED-BT-501",
            value="DE238737605",
        ),
        source_system="ted",
    )
    assert resolution.status == "probable"
    assert "ne divulgue pas" in resolution.basis[0].detail


def test_un_registre_indisponible_ne_bloque_pas_ce_qui_est_publie():
    resolver = CompanyResolver(vies=vies_client())
    resolution = resolver.resolve(
        org(
            "SUWECO CZ, s.r.o.",
            country="CZ",
            address="Sestupná 153/11, 16200, Praha",
            scheme="TED-BT-501",
            value="CZ25094769",
        ),
        source_system="ted",
    )
    assert resolution.status == "probable"
    assert any(not b.supports and "indisponible" in b.detail for b in resolution.basis)


def test_aucun_numero_n_est_fabrique_a_partir_d_un_nom():
    """Sans identifiant publié, le registre n'est jamais interrogé."""
    client = vies_client()
    resolver = CompanyResolver(vies=client)
    resolver.resolve(
        org("Entreprise Sans Identifiant SA", address="Rue 1, 1000, Lausanne"),
        source_system="simap",
    )
    assert client.requests_sent == 0


def test_une_tva_dont_le_pays_ne_correspond_pas_n_est_pas_interrogee():
    client = vies_client()
    resolver = CompanyResolver(vies=client)
    resolver.resolve(
        org(
            "Société FR",
            country="FR",
            address="Rue 1, 75001, Paris",
            scheme="TED-BT-501",
            value="LU26538172",
        ),
        source_system="ted",
    )
    assert client.requests_sent == 0


# ─── Invariants du modèle ───────────────────────────────────────────────────────


def test_une_resolution_sans_trace_est_refusee():
    with pytest.raises(ValidationError, match="sans trace"):
        CompanyResolution(
            source_organization=org("X SA"),
            source_system="simap",
            status="verified",
            company=Company(legal_name="X SA"),
        )


def test_un_statut_incertain_ne_porte_aucune_entreprise():
    with pytest.raises(ValidationError, match="ne doit porter aucune entreprise"):
        CompanyResolution(
            source_organization=org("X SA"),
            source_system="simap",
            status="review_required",
            company=Company(legal_name="X SA"),
            basis=(ResolutionBasis(method="fuzzy_name", detail="x"),),
        )


def test_la_mention_source_n_est_jamais_modifiee():
    """Le fait publié survit intact à la résolution."""
    mention = org(
        "Egli Gartenbau AG Sursee",
        address="Schlottermilch 18, 6210, Sursee",
        scheme="SIMAP-VENDOR-ID",
        value="6ada7011",
    )
    resolver = CompanyResolver()
    resolution = resolver.resolve(mention, source_system="simap")
    assert resolution.source_organization == mention
    assert resolution.source_organization.legal_name == "Egli Gartenbau AG Sursee"
    assert resolution.source_organization.identifiers[0].value == "6ada7011"


def test_un_alias_provient_toujours_d_une_mention_observee():
    resolver = CompanyResolver()
    resolver.resolve(
        org("ACME S.A.", scheme="CHE-UID", value="CHE-123.456.789"), source_system="simap"
    )
    resolver.resolve(
        org("Acme SA", scheme="CHE-UID", value="CHE-123.456.789"), source_system="simap"
    )
    company = resolver.companies[0]
    assert company.legal_name == "ACME S.A."
    assert company.aliases == ("Acme SA",)


def test_un_alias_ne_se_duplique_pas():
    with pytest.raises(ValidationError):
        Company(legal_name="A SA", aliases=("B SA", "B SA"))


def test_le_site_web_reste_absent():
    """La recherche de site relève de l'Acquisition Engine, pas de la résolution."""
    resolver = CompanyResolver()
    resolver.resolve(org("Egli AG", address="Rue 1, 6210, Sursee"), source_system="simap")
    assert all(company.website is None for company in resolver.companies)


# ─── Groupements ────────────────────────────────────────────────────────────────


def test_un_groupement_est_resolu_membre_par_membre():
    from signals.domain import Awardee, AwardeeParty

    party = AwardeeParty(
        name="Konsorcjum ABC",
        members=(
            Awardee(
                organization=org(
                    "Agencja Ochrony Zubrzycki", country="PL", address="ul. 1, 40001, Katowice"
                ),
                role="consortium_lead",
            ),
            Awardee(
                organization=org(
                    "SOLID SECURITY Sp. z o.o.", country="PL", address="ul. 2, 00002, Warszawa"
                ),
                role="consortium_member",
            ),
        ),
    )
    resolver = CompanyResolver()
    resolution = resolver.resolve_party(party, source_system="ted")

    assert resolution.party_name == "Konsorcjum ABC"
    assert len(resolution.members) == 2
    # le groupement lui-même ne devient jamais une entreprise
    assert all(company.legal_name != "Konsorcjum ABC" for company in resolver.companies)
    assert len(resolver.companies) == 2
