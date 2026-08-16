"""Tests conçus pour PROVOQUER une mauvaise fusion.

Notre pire erreur n'est pas une entreprise non résolue : c'est deux entreprises
confondues. Chaque test ci-dessous construit un piège plausible et vérifie que
le moteur refuse de tomber dedans.

Les cas A, G, H et I sont des invariants d'architecture. Les cas B à F reprennent
des motifs réellement rencontrés dans le corpus TED/SIMAP.
"""

from __future__ import annotations

from signals.domain import OrganizationIdentifier, OrganizationRef
from signals.resolution import CompanyResolver
from signals.resolution.normalize import matching_name, name_core, name_similarity


def org(
    name: str,
    *,
    country: str | None = "CH",
    address: str | None = "Bahnhofstrasse 1, 8001, Zürich",
    scheme: str | None = None,
    value: str | None = None,
) -> OrganizationRef:
    identifiers = (OrganizationIdentifier(scheme=scheme, value=value),) if scheme and value else ()
    return OrganizationRef(
        legal_name=name, country=country, address=address, identifiers=identifiers
    )


def resolved_companies(resolver: CompanyResolver) -> int:
    return len(resolver.companies)


# ─── A — le nom ne fusionne jamais ──────────────────────────────────────────────


def test_a_alpha_sa_et_alpha_holding_sa_restent_distinctes():
    resolver = CompanyResolver()
    resolver.resolve(
        org("Alpha SA", scheme="CHE-UID", value="CHE-111.111.111"), source_system="simap"
    )
    resolver.resolve(
        org("Alpha Holding SA", scheme="CHE-UID", value="CHE-222.222.222"), source_system="simap"
    )
    assert resolved_companies(resolver) == 2
    assert matching_name("Alpha SA") != matching_name("Alpha Holding SA")
    assert name_core("Alpha SA") != name_core("Alpha Holding SA")


def test_a_bis_une_mention_reduite_a_un_nom_n_est_pas_une_entreprise():
    """Ni identifiant, ni adresse situable : le moteur refuse de conclure."""
    resolver = CompanyResolver()
    first = resolver.resolve(org("Alpha SA", address=None), source_system="simap")
    assert first.status == "unresolved"
    assert first.company is None
    assert resolved_companies(resolver) == 0


def test_a_ter_deux_homonymes_du_meme_pays_sans_identifiant_appellent_un_humain():
    """Même nom, même pays, adresses situables mais aucun identifiant : à vérifier."""
    resolver = CompanyResolver()
    resolver.resolve(org("Delta SA", address="Rue 1, 1000, Lausanne"), source_system="simap")
    second = resolver.resolve(
        org("Delta SA", address="Rue 9, 9000, St. Gallen"), source_system="simap"
    )
    assert second.status == "review_required"
    assert second.company is None
    assert [c.company.legal_name for c in second.candidates] == ["Delta SA"]


# ─── B — même nom, deux pays ────────────────────────────────────────────────────


def test_b_meme_nom_dans_deux_pays_ne_fusionne_pas():
    resolver = CompanyResolver()
    suisse = resolver.resolve(
        org("Example AG", country="CH", address="Rue 1, 8001, Zürich"), source_system="simap"
    )
    autrichienne = resolver.resolve(
        org("Example AG", country="AT", address="Rue 1, 8001, Wien"), source_system="simap"
    )
    assert suisse.company.country != autrichienne.company.country
    assert resolved_companies(resolver) == 2


# ─── C — même nom et même ville, identifiants officiels différents ──────────────


def test_c_identifiants_officiels_differents_empechent_la_fusion():
    resolver = CompanyResolver()
    first = resolver.resolve(
        org("Beta AG", scheme="CHE-UID", value="CHE-111.111.111"), source_system="simap"
    )
    second = resolver.resolve(
        org("Beta AG", scheme="CHE-UID", value="CHE-999.999.999"), source_system="simap"
    )
    assert resolved_companies(resolver) == 2
    assert second.company.identifier("CHE-UID") == "CHE-999.999.999"
    assert first.company.identifier("CHE-UID") == "CHE-111.111.111"


# ─── D — même identifiant officiel, ponctuation du nom différente ───────────────


def test_d_meme_identifiant_officiel_malgre_la_ponctuation():
    """`CHE-123.456.789` et `CHE123456789` désignent la même IDE."""
    resolver = CompanyResolver()
    first = resolver.resolve(
        org("ACME S.A.", scheme="CHE-UID", value="CHE-123.456.789"), source_system="simap"
    )
    second = resolver.resolve(
        org("Acme SA", scheme="CHE-UID", value="CHE123456789"), source_system="simap"
    )
    assert second.status == "verified"
    assert second.company is first.company or second.company.legal_name == first.company.legal_name
    assert resolved_companies(resolver) == 1
    assert "Acme SA" in second.company.aliases  # la mention est conservée, pas écrasée
    assert [str(b) for b in second.basis] == ["+ official_identifier: CHE-UID CHE123456789"]


def test_d_bis_un_identifiant_malforme_n_est_jamais_reparé():
    resolver = CompanyResolver()
    first = resolver.resolve(
        org("Gamma AG", scheme="CHE-UID", value="CHE-123.456.789"), source_system="simap"
    )
    second = resolver.resolve(
        org("Gamma AG", scheme="CHE-UID", value="CHE-123.456.78"), source_system="simap"
    )
    assert resolved_companies(resolver) == 2  # 8 chiffres ≠ 9, aucun complément
    assert first.company.identifier("CHE-UID") != second.company.identifier("CHE-UID")


# ─── E — identifiant local, à l'intérieur d'une source ──────────────────────────


def test_e_meme_identifiant_simap_reconnait_la_meme_organisation():
    resolver = CompanyResolver()
    resolver.resolve(
        org("Vebego AG", scheme="SIMAP-VENDOR-ID", value="7ddb5c5e-8731-49d2"),
        source_system="simap",
    )
    again = resolver.resolve(
        org("VEBEGO AG", scheme="SIMAP-VENDOR-ID", value="7ddb5c5e-8731-49d2"),
        source_system="simap",
    )
    assert again.status == "probable"
    assert again.company is not None
    assert resolved_companies(resolver) == 1
    assert any("simap uniquement" in b.detail for b in again.basis)


# ─── F — LE piège : identifiant local identique dans deux sources ───────────────


def test_f_un_identifiant_local_ne_traverse_jamais_les_sources():
    """Deux portails peuvent employer la même valeur sans le moindre rapport."""
    resolver = CompanyResolver()
    swiss = resolver.resolve(
        org(
            "Alpha AG",
            country="CH",
            address="Rue 1, 8001, Zürich",
            scheme="SIMAP-VENDOR-ID",
            value="COLLISION-1",
        ),
        source_system="simap",
    )
    european = resolver.resolve(
        org(
            "Beta Srl",
            country="IT",
            address="Via 2, 20100, Milano",
            scheme="TED-ORG-ID",
            value="COLLISION-1",
        ),
        source_system="ted",
    )
    assert swiss.company.country != european.company.country
    assert resolved_companies(resolver) == 2

    # même scheme, même valeur, mais deux sources : toujours pas de fusion
    third = resolver.resolve(
        org(
            "Alpha AG",
            country="CH",
            address="Rue 1, 8001, Zürich",
            scheme="SIMAP-VENDOR-ID",
            value="COLLISION-1",
        ),
        source_system="ted",
    )
    assert not any(b.method == "source_local_identifier" for b in third.basis)


# ─── G — accents et translittérations ───────────────────────────────────────────


def test_g_muller_et_mueller_ne_fusionnent_pas():
    resolver = CompanyResolver()
    umlaut = resolver.resolve(
        org("Müller Bau AG", address="Rue 1, 8001, Zürich"), source_system="simap"
    )
    latin = resolver.resolve(
        org("Mueller Bau AG", address="Rue 1, 8001, Zürich"), source_system="simap"
    )
    assert umlaut.company.legal_name != latin.company.legal_name
    assert name_similarity("Müller Bau AG", "Mueller Bau AG") < 1.0


def test_g_bis_les_accents_seuls_ne_distinguent_pas():
    """`Zürich` et `Zurich` dans le même nom désignent bien la même entreprise."""
    assert matching_name("Café Zürich SA") == matching_name("Cafe Zurich SA")


def test_g_ter_deux_ecritures_non_latines_ne_se_confondent_pas():
    """Cas réel du corpus : deux entreprises bulgares distinctes.

    Une normalisation qui ne garderait que `[a-z0-9]` les réduirait toutes deux
    à la chaîne vide — et les rapprocherait.
    """
    resolver = CompanyResolver()
    first = resolver.resolve(
        org("Б. БРАУН МЕДИКАЛ ЕООД", country="BG", address="ул. 1, 1000, София"),
        source_system="ted",
    )
    second = resolver.resolve(
        org("СИНЕРГОН ЕНЕРДЖИ ООД", country="BG", address="ул. 1, 1000, София"),
        source_system="ted",
    )
    assert matching_name("Б. БРАУН МЕДИКАЛ ЕООД") != ""
    assert first.company.legal_name != second.company.legal_name
    assert resolved_companies(resolver) == 2


# ─── H — noms courts et génériques ──────────────────────────────────────────────


def test_h_un_nom_trop_court_ne_declenche_aucune_suggestion():
    resolver = CompanyResolver()
    resolver.resolve(
        org("ABC SA", scheme="CHE-UID", value="CHE-111.111.111"), source_system="simap"
    )
    other = resolver.resolve(
        org("ABC SA", country="FR", address="Rue 2, 75001, Paris"), source_system="ted"
    )
    assert other.candidates == ()  # noyau « abc » : trop générique pour même suggérer
    assert other.company.country != resolver.companies[0].country


# ─── I — filiales et implantations nationales ───────────────────────────────────


def test_i_les_filiales_nationales_restent_distinctes():
    resolver = CompanyResolver()
    suisse = resolver.resolve(
        org("Example Schweiz AG", country="CH", address="Rue 1, 8001, Zürich"),
        source_system="simap",
    )
    allemande = resolver.resolve(
        org("Example Deutschland GmbH", country="DE", address="Str. 1, 10115, Berlin"),
        source_system="ted",
    )
    francaise = resolver.resolve(
        org("Example France SAS", country="FR", address="Rue 1, 75001, Paris"), source_system="ted"
    )
    assert len({id(r.company) for r in (suisse, allemande, francaise)}) == 3
    assert resolved_companies(resolver) == 3


# ─── Cas réel : deux membres d'un même groupement ───────────────────────────────


def test_membres_de_groupement_au_nom_proche_restent_distincts():
    """Cas réel TED : « SOLID SECURITY Sp. z o. o. » et « SOLID Sp. z o. o. ».

    Similarité 0.50 — le maximum observé entre deux entreprises distinctes du
    corpus. Leurs identifiants publiés diffèrent : c'est une preuve de
    distinction, pas un motif de vérification.
    """
    resolver = CompanyResolver()
    security = resolver.resolve(
        org(
            "SOLID SECURITY Sp. z o. o.",
            country="PL",
            address="ul. 1, 00-001, Warszawa",
            scheme="TED-BT-501",
            value="5261029614",
        ),
        source_system="ted",
    )
    solid = resolver.resolve(
        org(
            "SOLID Sp. z o. o.",
            country="PL",
            address="ul. 2, 00-002, Kraków",
            scheme="TED-BT-501",
            value="6760076868",
        ),
        source_system="ted",
    )
    assert security.company.legal_name != solid.company.legal_name
    assert solid.status == "probable"
    assert resolved_companies(resolver) == 2


def test_aucune_fusion_n_est_decidee_sans_trace():
    """Toute résolution portant une entreprise porte au moins une raison."""
    resolver = CompanyResolver()
    for name in ("Un SA", "Deux SA", "Trois SA"):
        resolution = resolver.resolve(
            org(name, scheme="CHE-UID", value=f"CHE-{abs(hash(name)) % 900 + 100}.000.000"),
            source_system="simap",
        )
        if resolution.company is not None:
            assert resolution.basis
