"""Lecture d'une publication SIMAP — structure seulement, aucune traduction.

Ce module produit une image fidèle du modèle SIMAP, dans son propre vocabulaire
(`project`, `publication`, `vendor`, `procOffice`, `referencingPub`). Il ne
connaît pas le modèle canonique : la traduction vit dans `mapping.py`.

Il ne fonctionne que sur du JSON, jamais sur le réseau.

**Le modèle SIMAP n'est pas le modèle eForms.** Rien n'y ressemble à un
`SettledContract` :

    Project  (id UUID + projectNumber)          la procédure durable
      └── Publication  (id UUID + publicationNumber « 33112-02 »)
            ├── type : tender | award | direct_award | revocation | abandonment…
            ├── lot            0..1  — une publication porte AU PLUS un lot,
            │                          un projet à lots produit donc plusieurs
            │                          publications d'adjudication
            ├── referencingPub 0..1  — la publication d'appel d'offres d'origine
            └── decision.vendors 0..n — les adjudicataires, chacun avec SON prix

Il n'existe **aucun identifiant de contrat** dans SIMAP, et **aucune structure
de groupement** : `vendors` est une liste plate. Le connecteur n'en invente ni
l'un ni l'autre.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from signals.connectors.simap.errors import SimapParseError

# Types de publication qui annoncent une attribution.
AWARD_PUB_TYPES = ("award", "direct_award")

# Ordre de repli quand la langue de création n'est pas renseignée.
LANGUAGE_FALLBACK = ("de", "fr", "it", "en")


@dataclass(frozen=True)
class SimapAddress:
    """Une organisation telle que SIMAP la publie (acheteur ou adjudicataire)."""

    name: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    canton: str | None = None
    country: str | None = None
    organization_id: str | None = None
    email: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class SimapVendor:
    """`decision.vendors[]` — un adjudicataire, avec son propre prix et son rang."""

    vendor_id: str | None
    name: str | None
    address: SimapAddress | None = None
    price: Decimal | None = None
    currency: str | None = None
    vat_type: str | None = None  # no_vat | full | special | reduced | foreign_vat
    rank: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class SimapLot:
    """Le lot auquel se rapporte la publication, quand le projet en a."""

    lot_id: str
    lot_number: int | None = None
    title: str | None = None
    sub_type: str | None = None


@dataclass(frozen=True)
class SimapReferencedPublication:
    """`referencingPub` — la publication d'origine à laquelle l'adjudication répond."""

    publication_id: str | None
    publication_number: str | None = None
    pub_type: str | None = None
    publication_date: str | None = None


@dataclass(frozen=True)
class SimapOrderAddress:
    """Lieu d'exécution. Publié par la recherche, PAS par le détail d'adjudication."""

    country: str | None = None
    canton: str | None = None
    postal_code: str | None = None
    city: str | None = None


@dataclass(frozen=True)
class SimapPublication:
    """Une publication SIMAP complète, encore entièrement en vocabulaire SIMAP."""

    publication_id: str
    publication_number: str | None
    project_id: str
    project_number: str | None
    publication_date: str | None
    pub_type: str | None
    project_type: str | None
    project_sub_type: str | None
    process_type: str | None
    corrected: bool | None
    lots_type: str | None
    creation_language: str | None
    title: str | None
    order_description: str | None
    proc_office: SimapAddress | None
    procurement_recipient: SimapAddress | None
    lot: SimapLot | None
    referencing_pub_id: str | None
    referencing_pub: SimapReferencedPublication | None
    cpv_main: str | None
    cpv_additional: tuple[str, ...]
    vendors: tuple[SimapVendor, ...]
    award_decision_date: str | None
    number_of_submissions: int | None
    total_price_selection: str | None
    has_project_documents: bool | None
    order_address: SimapOrderAddress | None = None
    published_on_ted: bool | None = None
    external_reference: dict[str, Any] | None = field(default=None, repr=False)


def load_json(raw: str | bytes) -> Any:
    """Décode en gardant les nombres EXACTS.

    `parse_float=Decimal` n'est pas un détail : un prix de marché lu en float
    perdrait des centimes avant même d'atteindre `Money`, qui refuse justement
    les flottants.
    """
    return json.loads(raw, parse_float=Decimal)


def parse_publication(
    payload: Any, *, search_entry: dict[str, Any] | None = None
) -> SimapPublication:
    """Lit un `publication-details` d'adjudication. Lève `SimapParseError` sinon.

    `search_entry` est la ligne de recherche correspondante, quand on l'a : elle
    seule publie le lieu d'exécution (`orderAddress`), absent du détail.
    """
    if isinstance(payload, (str, bytes)):
        payload = load_json(payload)
    if not isinstance(payload, dict):
        raise SimapParseError("réponse SIMAP inattendue : objet JSON attendu")

    base = payload.get("base")
    if not isinstance(base, dict) or not base.get("id") or not base.get("projectId"):
        raise SimapParseError("publication sans bloc `base` exploitable")

    pub_type = payload.get("type") or base.get("type")
    if pub_type not in AWARD_PUB_TYPES:
        raise SimapParseError(
            f"type de publication '{pub_type}' — attendu {' ou '.join(AWARD_PUB_TYPES)}"
        )

    procurement = payload.get("procurement") or {}
    project_info = payload.get("project-info") or {}
    decision = payload.get("decision") or {}
    language = base.get("creationLanguage")

    return SimapPublication(
        publication_id=base["id"],
        publication_number=base.get("publicationNumber"),
        project_id=base["projectId"],
        project_number=base.get("projectNumber"),
        publication_date=base.get("publicationDate"),
        pub_type=pub_type,
        project_type=base.get("projectType"),
        project_sub_type=(search_entry or {}).get("projectSubType") or procurement.get("orderType"),
        process_type=base.get("processType"),
        corrected=(search_entry or {}).get("corrected"),
        lots_type=base.get("lotsType"),
        creation_language=language,
        title=_translation(base.get("title") or project_info.get("title"), language),
        order_description=_translation(procurement.get("orderDescription"), language),
        proc_office=_address(project_info.get("procOfficeAddress"), language),
        procurement_recipient=_address(project_info.get("procurementRecipientAddress"), language),
        lot=_lot(payload.get("lot"), language),
        referencing_pub_id=base.get("referencingPubId"),
        referencing_pub=_referencing(payload.get("referencingPub")),
        cpv_main=(procurement.get("cpvCode") or {}).get("code"),
        cpv_additional=tuple(
            c["code"] for c in (procurement.get("additionalCpvCodes") or []) if c.get("code")
        ),
        vendors=_vendors(decision.get("vendors") or [], language),
        award_decision_date=decision.get("awardDecisionDate"),
        number_of_submissions=_int(decision.get("numberOfSubmissions")),
        total_price_selection=decision.get("totalPriceSelection"),
        has_project_documents=payload.get("hasProjectDocuments"),
        order_address=_order_address((search_entry or {}).get("orderAddress"), language),
        published_on_ted=project_info.get("publicationTed"),
        external_reference=procurement.get("externalReference"),
    )


# ─── Lecture des fragments ──────────────────────────────────────────────────────


def _translation(value: Any, language: str | None) -> str | None:
    """SIMAP publie chaque texte en 4 langues. On prend celle de rédaction.

    Aucune traduction n'est fabriquée : à défaut de la langue de rédaction, la
    première réellement remplie, dans un ordre fixe pour rester déterministe.
    """
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    order = ([language] if language else []) + list(LANGUAGE_FALLBACK)
    for code in order:
        text = value.get(code)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _address(value: Any, language: str | None) -> SimapAddress | None:
    if not isinstance(value, dict):
        return None
    return SimapAddress(
        name=_translation(value.get("name"), language),
        street=_translation(value.get("street"), language),
        postal_code=_clean(value.get("postalCode")),
        city=_translation(value.get("city"), language),
        canton=_clean(value.get("cantonId")),
        country=_clean(value.get("countryId")),
        organization_id=_clean(value.get("id")),
        email=_clean(value.get("email")),
        url=_translation(value.get("url"), language),
    )


def _vendors(rows: list[Any], language: str | None) -> tuple[SimapVendor, ...]:
    vendors = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = row.get("price") or {}
        amount = price.get("price")
        vendors.append(
            SimapVendor(
                vendor_id=_clean(row.get("vendorId")),
                name=_clean(row.get("vendorName")),
                address=_address(row.get("vendorAddress"), language),
                price=Decimal(str(amount)) if amount is not None else None,
                currency=_clean(price.get("currency")),
                vat_type=_clean(price.get("vatType")),
                rank=_int(row.get("rank")),
                note=_translation(row.get("note"), language),
            )
        )
    return tuple(vendors)


def _lot(value: Any, language: str | None) -> SimapLot | None:
    if not isinstance(value, dict) or not value.get("id"):
        return None
    return SimapLot(
        lot_id=value["id"],
        lot_number=_int(value.get("lotNumber")),
        title=_translation(value.get("title"), language),
        sub_type=_clean(value.get("projectSubType")),
    )


def _referencing(value: Any) -> SimapReferencedPublication | None:
    if not isinstance(value, dict):
        return None
    return SimapReferencedPublication(
        publication_id=_clean(value.get("publicationId")),
        publication_number=_clean(value.get("publicationNumber")),
        pub_type=_clean(value.get("pubType")),
        publication_date=_clean(value.get("publicationDate")),
    )


def _order_address(value: Any, language: str | None) -> SimapOrderAddress | None:
    if not isinstance(value, dict):
        return None
    address = SimapOrderAddress(
        country=_clean(value.get("countryId")),
        canton=_clean(value.get("cantonId")),
        postal_code=_clean(value.get("postalCode")),
        city=_translation(value.get("city"), language),
    )
    return address if any(vars(address).values()) else None


def _clean(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
