"""Classement et normalisation des identifiants d'organisation.

Tous les identifiants ne prouvent pas la même chose. Trois forces, et la
frontière entre elles est ce qui empêche une fusion abusive :

`official`
    Le référentiel est **nommé** par la source et connu : IDE suisse, TVA
    intracommunautaire, LEI, NIF. Un même identifiant officiel désigne la même
    entité juridique.

`source_local`
    Un identifiant interne au portail : `SIMAP-VENDOR-ID`, `TED-ORG-ID`. Il
    reconnaît une organisation **à l'intérieur de sa source** et nulle part
    ailleurs. Deux portails peuvent employer la même valeur sans aucun rapport.

`unattributed`
    Une valeur qui ressemble à un identifiant national, mais dont la source ne
    nomme pas le registre — cas de `TED-BT-501`, qui porte selon les avis un
    SIRET français, un numéro d'organisation norvégien ou un numéro de TVA. On
    la conserve et on la compare, on ne prétend pas savoir ce qu'elle est.

Une valeur mal formée n'est jamais réparée pour devenir valide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from signals.domain import OrganizationIdentifier

IdentifierStrength = Literal["official", "source_local", "unattributed", "unknown"]

# Schemes dont le référentiel est explicitement nommé par une source.
OFFICIAL_SCHEMES = {
    "CHE-UID": "ch-uid",
    "CH-UID": "ch-uid",
    "IDE": "ch-uid",
    "EU-VAT": "eu-vat",
    "VAT": "eu-vat",
    "LEI": "lei",
    "NIF": "nif",
    "NIPC": "nif",
}

# Schemes internes à un portail : utiles dans leur source, muets en dehors.
SOURCE_LOCAL_SCHEMES = {"SIMAP-VENDOR-ID", "SIMAP-ORG-ID", "TED-ORG-ID"}

# Schemes portant une valeur nationale dont le registre n'est pas nommé.
UNATTRIBUTED_SCHEMES = {"TED-BT-501"}

_VAT = re.compile(
    r"^(AT|BE|BG|HR|CY|CZ|DK|EE|FI|FR|DE|EL|HU|IE|IT|LV|LT|LU|MT|NL|PL|PT|RO|SK|SI|ES|SE|XI)"
    r"([0-9A-Z]{2,12})$"
)
_CHE_UID = re.compile(r"^CHE(\d{9})$")
_LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")

# Le préfixe TVA ne suit pas toujours le code pays ISO.
_VAT_COUNTRY = {"EL": "GR", "XI": "GB"}


@dataclass(frozen=True)
class ClassifiedIdentifier:
    """Un identifiant publié, avec ce qu'on sait — et ne sait pas — de sa portée."""

    scheme: str
    published_value: str
    matching_value: str
    strength: IdentifierStrength
    registry: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Clé de rapprochement : le registre quand il est connu, sinon le scheme."""
        return (self.registry or self.scheme, self.matching_value)


def normalize_value(scheme: str, value: str) -> str:
    """Forme de comparaison d'un identifiant. La valeur publiée reste intacte.

    Seuls les séparateurs sans portée sémantique disparaissent : `CHE-123.456.789`
    et `CHE123456789` désignent la même IDE. Les zéros significatifs et le
    préfixe pays d'un numéro de TVA sont conservés.
    """
    compact = re.sub(r"[\s.\-/]", "", value).upper()
    if scheme.upper() in {"LEI"}:
        return compact
    return compact


def classify(identifier: OrganizationIdentifier) -> ClassifiedIdentifier:
    """Range un identifiant sans jamais deviner un référentiel absent."""
    scheme = identifier.scheme
    matching = normalize_value(scheme, identifier.value)
    registry = OFFICIAL_SCHEMES.get(scheme.upper())

    if registry:
        return ClassifiedIdentifier(scheme, identifier.value, matching, "official", registry)
    if scheme in SOURCE_LOCAL_SCHEMES:
        return ClassifiedIdentifier(scheme, identifier.value, matching, "source_local")
    if scheme in UNATTRIBUTED_SCHEMES:
        return ClassifiedIdentifier(scheme, identifier.value, matching, "unattributed")
    # Scheme inconnu : conservé tel quel, jamais interprété.
    return ClassifiedIdentifier(scheme, identifier.value, matching, "unknown")


def vat_parts(value: str) -> tuple[str, str] | None:
    """Décompose un numéro de TVA intracommunautaire, ou `None` s'il n'en est pas un.

    Reconnaître une **forme** n'est pas affirmer un référentiel : la fonction dit
    « cette valeur a la forme d'un numéro de TVA », rien de plus. C'est VIES qui
    tranchera.
    """
    match = _VAT.match(normalize_value("", value))
    return (match.group(1), match.group(2)) if match else None


def vat_country(prefix: str) -> str:
    """Code pays ISO correspondant au préfixe TVA (`EL` → `GR`, `XI` → `GB`)."""
    return _VAT_COUNTRY.get(prefix, prefix)


def looks_like_swiss_uid(value: str) -> bool:
    return bool(_CHE_UID.match(normalize_value("", value)))


def looks_like_lei(value: str) -> bool:
    return bool(_LEI.match(normalize_value("LEI", value)))
