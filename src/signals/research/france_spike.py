"""SPIKE FRANCE — BOAMP + PLACE + DECP : la voie française est-elle meilleure ?

Le run TED sur FRA/BEL/LUX/CHE a rendu **zéro** document téléchargeable sur 600
avis : les liens BT-15 y mènent à des profils acheteurs, jamais à un fichier.
Ce module mesure si la France dispose d'une voie native plus courte.

    AWARD BOAMP → annonce liée → avis d'origine → URI documentaire → document

Ce n'est pas un connecteur. Rien n'entre dans le modèle canonique : les
structures d'ici sont locales et jetables, et le spike ne produit qu'un rapport
chiffré.

Sources vérifiées au moment du run, aucune supposée :

- **BOAMP** — API Opendatasoft v2.1 du domaine `boamp-datadila.opendatasoft.com`,
  jeu `boamp` (1,7 M d'enregistrements), licence Etalab 2.0. Chaque avis porte
  son eForms complet dans `donnees`, et les avis d'attribution portent
  `annonce_lie`, qui nomme l'avis d'origine — un chaînage natif que TED n'offre
  qu'via `procedure-identifier`.
- **DECP** — data.gouv.fr, API DECP (JSON quotidien) et fichiers consolidés,
  licence LOv2.
- **PLACE** — `place.marches-publics.gouv.fr`, mesuré comme n'importe quel hôte.

Accès : lecture seule, cadence lente, User-Agent identifiant. Les documents
publics peuvent être récupérés par les moyens ordinaires offerts à un utilisateur,
sans contournement d'authentification ni de CAPTCHA et dans le respect des CGU et
de robots.txt.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

BOAMP_API = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp"
DATAGOUV_API = "https://www.data.gouv.fr/api/1"
USER_AGENT = "Kivou-research-spike/0.1 (evaluation faisabilite; donnees publiques)"

PLACE_HOSTS = ("marches-publics.gouv.fr",)
"""PLACE — la plateforme des achats de l'État, servie sur `www.marches-publics.gouv.fr`.

Le suffixe complet est indispensable : `marches-publics.info` est un profil
acheteur privé, sans rapport, et un test de sous-chaîne les confondrait."""


# ─── Lecture d'un enregistrement BOAMP ──────────────────────────────────────────


def _walk(node: Any, key: str) -> list[Any]:
    """Toutes les valeurs portant `key`, à n'importe quelle profondeur.

    L'eForms est profondément imbriqué et sa forme varie selon le type d'avis.
    Chercher par nom de nœud évite d'écrire un chemin par variante — et surtout
    évite de rendre `None` parce que la structure a bougé d'un cran.
    """
    found: list[Any] = []
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                found.append(value)
            found.extend(_walk(value, key))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value, key))
    return found


def payload(record: dict) -> Any:
    """L'eForms de l'avis, quel que soit son emballage.

    L'API Opendatasoft rend `donnees` en **chaîne JSON**, pas en objet. Traiter
    la chaîne comme un arbre rendait zéro montant, zéro CPV et zéro URL sur un
    run de 30 avis, sans lever la moindre erreur — un échec silencieux qui se
    lisait comme une limite de la source.
    """
    raw = record.get("donnees")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    return raw


def _text(node: Any) -> str | None:
    if isinstance(node, str):
        return node.strip() or None
    if isinstance(node, dict):
        value = node.get("#text")
        return str(value).strip() or None if value is not None else None
    return None


def buyer_name(record: dict) -> str | None:
    return (record.get("nomacheteur") or None) or None


def winner_names(record: dict) -> list[str]:
    """Les titulaires publiés, dédoublonnés dans l'ordre de publication.

    BOAMP répète le même titulaire une fois par lot : la répétition est un fait
    de mise en forme, pas plusieurs entreprises.
    """
    raw = record.get("titulaire") or []
    if isinstance(raw, str):
        raw = [raw]
    seen: dict[str, None] = {}
    for name in raw:
        cleaned = (name or "").strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def amount_eur(record: dict) -> Decimal | None:
    """Le montant publié, en euros — jamais reconstitué ni additionné.

    Additionner des lots reviendrait à fabriquer un chiffre que l'avis ne dit
    pas ; on prend le montant global quand il est publié, et rien sinon.
    """
    for key in (
        "efbc:OverallMaximumFrameworkContractsAmount",
        "cbc:MaximumValueAmount",
        "cbc:TaxExclusiveAmount",
        "cbc:PayableAmount",
    ):
        for node in _walk(payload(record), key):
            if isinstance(node, dict) and node.get("@currencyID") not in (None, "EUR"):
                continue
            value = _text(node)
            if value is None:
                continue
            try:
                return Decimal(value)
            except InvalidOperation:
                continue
    return None


def cpv_codes(record: dict) -> list[str]:
    """Les codes CPV de l'eForms. `descripteur_code` est une autre nomenclature."""
    codes: list[str] = []
    for node in _walk(payload(record), "cbc:ItemClassificationCode"):
        entries = node if isinstance(node, list) else [node]
        for entry in entries:
            if isinstance(entry, dict) and entry.get("@listName") not in (None, "cpv"):
                continue
            value = _text(entry)
            if value and value not in codes:
                codes.append(value)
    return codes


def procedure_reference(record: dict) -> str | None:
    return (record.get("contractfolderid") or None) or None


# ─── Rapprochement award → consultation ─────────────────────────────────────────

LinkageStrength = Literal["exact", "strong", "ambiguous", "not_found"]


@dataclass(frozen=True)
class Linkage:
    """Comment l'avis d'attribution désigne sa consultation d'origine."""

    strength: LinkageStrength
    notice_ids: tuple[str, ...] = ()
    procedure_reference: str | None = None


def linkage(record: dict) -> Linkage:
    """Le rapprochement, par identifiants publiés uniquement.

    Aucun rapprochement par ressemblance de titre : deux marchés de nettoyage
    portent le même objet sans être la même procédure, et une mesure de
    faisabilité fondée sur des faux liens ne mesurerait rien.
    """
    linked = record.get("annonce_lie") or []
    if isinstance(linked, str):
        linked = [linked]
    linked = [str(x).strip() for x in linked if str(x).strip()]
    folder = procedure_reference(record)

    if len(linked) == 1:
        return Linkage("exact", tuple(linked), folder)
    if len(linked) > 1:
        return Linkage("ambiguous", tuple(linked), folder)
    if folder:
        return Linkage("strong", (), folder)
    return Linkage("not_found", (), None)


# ─── URI documentaires ──────────────────────────────────────────────────────────

_URI_KEYS = ("cbc:URI", "cbc:EndpointID")


def document_urls(record: dict) -> list[str]:
    """Les adresses documentaires publiées par l'avis, dédoublonnées.

    On lit `CallForTendersDocumentReference` — la référence au dossier de
    consultation. Ce que l'adresse dessert (un fichier ou une page de portail)
    est précisément ce que le spike doit mesurer, pas supposer.
    """
    references = _walk(payload(record), "cac:CallForTendersDocumentReference")
    urls: list[str] = []
    for reference in references:
        for key in _URI_KEYS:
            for node in _walk(reference, key):
                value = _text(node)
                if value and value.lower().startswith("http"):
                    decoded = html.unescape(value)
                    if decoded not in urls:
                        urls.append(decoded)
    return urls


def buyer_profile_urls(record: dict) -> list[str]:
    """Les adresses de profil acheteur citées, quelles qu'elles soient."""
    urls: list[str] = []
    for key in ("cbc:EndpointID", "cbc:URI", "cbc:WebsiteURI"):
        for node in _walk(payload(record), key):
            value = _text(node)
            if value and value.lower().startswith("http"):
                decoded = html.unescape(value)
                if decoded not in urls:
                    urls.append(decoded)
    return urls


_KNOWN_PROFILES = (
    "marches-publics.info",
    "achatpublic.com",
    "maximilien.fr",
    "e-marchespublics.com",
    "klekoon.com",
    "omnikles.com",
    "marches-securises.fr",
    "atline.fr",
    "aws-france.com",
)


def classify_host(url: str) -> str | None:
    """L'hôte, ou rien. Les profils connus gardent leur nom de marque."""
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return None
    if not host or "." not in host:
        return None
    if any(host.endswith(place) for place in PLACE_HOSTS):
        return "place"
    for known in _KNOWN_PROFILES:
        if known in host:
            return known
    return host


# ─── Nature des documents français ──────────────────────────────────────────────

_FRENCH_DOC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CCTP", re.compile(r"\bcctp\b|cahier des clauses techniques", re.IGNORECASE)),
    ("CCAP", re.compile(r"\bccap\b|cahier des clauses administratives", re.IGNORECASE)),
    ("RC", re.compile(r"\brc\b|reglement de (la )?consultation", re.IGNORECASE)),
    ("BPU", re.compile(r"\bbpu\b|bordereau des prix", re.IGNORECASE)),
    ("DQE", re.compile(r"\bdqe\b|detail quantitatif", re.IGNORECASE)),
    ("DPGF", re.compile(r"\bdpgf\b|decomposition du prix", re.IGNORECASE)),
    ("planning", re.compile(r"planning|calendrier|delais d.execution", re.IGNORECASE)),
    ("contract", re.compile(r"acte d.engagement|\bae\b|projet de (marche|contrat)", re.IGNORECASE)),
    ("technical_specification", re.compile(r"specification|cahier des charges", re.IGNORECASE)),
    ("annex", re.compile(r"annexe", re.IGNORECASE)),
)

EXECUTION_DOC_TYPES = frozenset(
    {"CCTP", "CCAP", "BPU", "DQE", "DPGF", "planning", "contract", "technical_specification"}
)
"""Ce qui décrit l'exécution. `RC` en est exclu : un règlement de consultation
dit comment déposer une offre, pas ce que le titulaire devra faire — le compter
gonflerait le taux sans rien apporter au Document Intelligence."""


def french_document_type(name: str) -> str:
    """La nature d'une pièce française, d'après son nom seul."""
    for label, pattern in _FRENCH_DOC_PATTERNS:
        if pattern.search(name or ""):
            return label
    return "other"


# ─── Résultat par award ─────────────────────────────────────────────────────────


@dataclass
class AwardProbe:
    """Ce qu'un award français a réellement donné, étape par étape."""

    idweb: str
    dateparution: str | None = None
    buyer: str | None = None
    winners: list[str] = field(default_factory=list)
    amount: Decimal | None = None
    cpv: list[str] = field(default_factory=list)
    procedure_reference: str | None = None
    linkage_strength: LinkageStrength = "not_found"
    linked_notice: str | None = None
    document_urls: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    fetch_statuses: list[str] = field(default_factory=list)
    documents_downloaded: int = 0
    documents_extractable: int = 0
    execution_documents: list[str] = field(default_factory=list)
    candidates: int = 0

    def as_dict(self) -> dict[str, object]:
        data = self.__dict__.copy()
        data["amount"] = str(self.amount) if self.amount is not None else None
        return data
