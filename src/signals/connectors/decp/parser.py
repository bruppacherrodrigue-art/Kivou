"""DECP — les données essentielles de la commande publique française.

    Le jeu de données, et pourquoi il compte
    ────────────────────────────────────────
    COURANT   `decp-2022-marches-valides`   arrêté du 22 décembre 2022
              689 062 marchés, mis à jour quotidiennement, notifications
              jusqu'à la veille du jour de mesure.

    HÉRITÉ    `decp-v3-marches-valides`     arrêté du 22 mars 2019
              702 901 marchés, figé : la notification la plus récente y date
              du 2024-02-08.

SPEC-009E avait mesuré le second et conclu que « DECP ne peut pas dater une
victoire récente ». La conclusion était fausse, et sa cause tient en une
phrase : le nom `decp-v3` se lit comme « version 3 », donc comme le plus
récent. C'est exactement le piège que la même SPEC avait su éviter sur les
*champs* — refuser de déduire une sémantique d'un nom — sans l'appliquer au
choix de la *source*. R1 corrige la source ; la leçon est écrite ici pour
qu'elle ne se reperde pas.

    Ce que le schéma 2022 apporte
    ─────────────────────────────
    SIRET de l'acheteur, identifiants des titulaires (jusqu'à trois), montant,
    CPV, durée en mois, lieu d'exécution codé, nature, procédure, technique
    d'achat, considérations sociales et environnementales, blocs complets de
    modification et de sous-traitance.

    Ce qu'il ne comporte pas
    ────────────────────────
    Aucun champ de raison sociale — ni pour le titulaire, ni pour l'acheteur,
    ni pour la commune d'exécution. Le schéma 2019 en avait quelques-uns ;
    celui de 2022 les a supprimés. DECP **identifie** sans **nommer**, quand
    le BOAMP **nomme** sans toujours identifier.

    `CDL`
    ─────
    La chaîne littérale `"CDL"` occupe les champs vides sur la totalité des
    enregistrements observés — mêmes causes que les `2000-01-01` du BOAMP,
    mêmes conséquences si on la prend pour une valeur. Elle est traitée comme
    une absence.

    `dateNotification`
    ──────────────────
    Elle date l'acte par lequel le marché devient exécutoire pour le titulaire.
    Elle suit la décision d'attribution, parfois de plusieurs semaines, et ne la
    date donc jamais. Elle alimente `contract_notification_date` — ni
    `award_date`, ni `contract_signature_date` (R1 §2).
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from signals.domain.awards import Awardee, AwardeeParty, ContractAward
from signals.domain.events import Provenance, PublicEvent
from signals.domain.values import (
    CpvCode,
    Duration,
    Location,
    Money,
    OrganizationIdentifier,
    OrganizationRef,
)

DECP_SOURCE_SYSTEM = "decp"
DECP_SOURCE_COUNTRY = "FR"
DECP_ADAPTER_VERSION = "decp-adapter-v0.2"

DECP_DATASET = "decp-2022-marches-valides"
"""Le jeu **courant** — arrêté du 22 décembre 2022."""

DECP_LEGACY_DATASET = "decp-v3-marches-valides"
"""Le jeu **hérité** — arrêté du 22 mars 2019, figé à février 2024. Ne pas utiliser."""

#: Valeurs de remplissage du portail, à traiter comme des absences.
FILLER_VALUES: frozenset[str] = frozenset({"CDL", "NC", "N/A", "-"})

#: Types d'identifiant que le portail déclare. Le schéma décide, pas la forme
#: de la valeur : un numéro à quatorze chiffres qui se dit « TVA » n'est pas un
#: SIRET, et l'inverse est tout aussi vrai.
SIRET_SCHEME = "SIRET"

#: R1 §1, §2 — ce que chaque date du jeu courant veut dire, et si elle peut
#: porter une date d'attribution. La réponse est non partout : le schéma 2022
#: ne comporte aucune date de décision.
DECP_DATE_SEMANTICS: dict[str, dict[str, str]] = {
    "datenotification": {
        "official_semantics": "« Date de notification » (arrêté du 22 décembre 2022)",
        "canonical_field": "contract_notification_date",
        "can_represent_award_date": "NO",
        "reason": (
            "la notification rend le marché exécutoire pour le titulaire ; elle "
            "suit la décision d'attribution et ne la date pas (R1 §2)"
        ),
    },
    "datepublicationdonnees": {
        "official_semantics": ("« Date de publication des données essentielles du marché public »"),
        "canonical_field": "PublicEvent.published_at",
        "can_represent_award_date": "NO",
        "reason": "date de mise en ligne de la donnée ouverte",
    },
    "datenotificationmodificationmodification": {
        "official_semantics": "« Date de la notification de la modification »",
        "canonical_field": "(non mappé en V0)",
        "can_represent_award_date": "NO",
        "reason": "concerne un avenant, pas l'attribution initiale",
    },
    "datenotificationactesoustraitance": {
        "official_semantics": "« Date de notification de l'acte spécial de sous-traitance »",
        "canonical_field": "(non mappé en V0)",
        "can_represent_award_date": "NO",
        "reason": "concerne un sous-traitant, pas le titulaire",
    },
}


def _text(value: Any) -> str | None:
    """Le contenu d'un champ, ou `None` — le remplissage `CDL` compte pour rien."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in FILLER_VALUES:
        return None
    return text


def _date(value: Any) -> dt.date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _cpv(value: Any) -> CpvCode | None:
    """`45000000-7` → code 45000000, clé 7. Le tiret est la convention française."""
    text = _text(value)
    if not text:
        return None
    root, _, check = text.partition("-")
    if not root.isdigit() or len(root) != 8:
        return None
    return CpvCode(code=root, check_digit=check if check.isdigit() and len(check) == 1 else None)


def _identifier(record: dict, index: int) -> OrganizationIdentifier | None:
    """L'identifiant d'un titulaire, avec le schéma que le portail déclare."""
    scheme = _text(record.get(f"titulaire_typeidentifiant_{index}"))
    value = _text(record.get(f"titulaire_id_{index}"))
    if not scheme or not value:
        return None
    return OrganizationIdentifier(scheme=scheme, value=value)


def buyer_siret(record: dict) -> str | None:
    """Le SIRET de l'acheteur, ou `None`. Le portail ne publie pas son nom."""
    value = _text(record.get("acheteur_id"))
    return value if value and value.isdigit() and len(value) == 14 else None


def winner_sirets(record: dict) -> tuple[str, ...]:
    """Les SIRET des titulaires, dans l'ordre publié.

    Un identifiant déclaré `TVA` n'entre pas ici, même s'il ressemble à un
    numéro français : c'est le schéma déclaré qui décide, pas la forme.
    """
    found: list[str] = []
    for index in (1, 2, 3):
        identifier = _identifier(record, index)
        if identifier and identifier.scheme == SIRET_SCHEME:
            found.append(identifier.value)
    return tuple(found)


def _winners(record: dict) -> tuple[AwardeeParty, ...]:
    """Les titulaires. Sans raison sociale publiée, l'identifiant tient lieu de désignation.

    Fabriquer un nom — même « Titulaire 30102983100031 » — donnerait l'illusion
    d'une identité nommée. La valeur brute dit exactement ce que la source dit.
    """
    members: list[Awardee] = []
    for index in (1, 2, 3):
        identifier = _identifier(record, index)
        if identifier is None:
            continue
        members.append(
            Awardee(
                organization=OrganizationRef(
                    legal_name=identifier.value,
                    identifiers=(identifier,),
                    country="FR" if identifier.scheme == SIRET_SCHEME else None,
                ),
                role="sole",
            )
        )
    if not members:
        return ()
    if len(members) > 1:
        # Plusieurs titulaires sur UN marché : le portail publie un groupement,
        # pas plusieurs contrats. `typegroupementoperateurs` le confirme quand il
        # est renseigné, mais la structure suffit à ne pas les séparer.
        members = [
            Awardee(organization=member.organization, role="consortium_member")
            for member in members
        ]
    return (AwardeeParty(members=tuple(members)),)


#: Un code de département français est un code ISO 3166-2 valide une fois
#: préfixé : « 22 » → « FR-22 ». La Corse et l'outre-mer suivent la même règle.
_DEPARTMENT = re.compile(r"^(\d{2,3}|2A|2B)$")


def _place(record: dict) -> Location | None:
    """Le lieu d'exécution, à la précision que le portail déclare lui-même.

    `lieuexecution_typecode` dit si le code est un code postal, un code commune,
    un département, une région ou un pays. Le deviner d'après sa longueur
    produirait des codes postaux imaginaires — et le schéma 2022 ne publie plus
    aucun nom de commune qui permettrait de rattraper l'erreur.

    Trois des cinq types ne sont pas représentables dans `Location` : le code
    commune (dont les valeurs observées vont de « 83107 » à « COMM »), le code
    région et le code pays. Ils sont laissés de côté plutôt que rangés sous un
    schéma qui ne les décrit pas.
    """
    code = _text(record.get("lieuexecution_code"))
    kind = _text(record.get("lieuexecution_typecode"))
    if not code:
        return None
    if kind == "Code postal":
        return Location(country="FR", postal_code=code)
    if kind == "Code département" and _DEPARTMENT.fullmatch(code):
        return Location(
            country="FR", subdivision_code=f"FR-{code}", subdivision_scheme="ISO-3166-2"
        )
    return Location(country="FR")


def _money(record: dict) -> Money | None:
    """Le montant publié — que le schéma qualifie lui-même de **maximum**.

    « Montant HT forfaitaire ou estimé maximum en euros ». Ce n'est donc pas
    nécessairement la valeur de l'offre retenue, et c'est ce qui explique les
    écarts avec les montants publiés par le BOAMP.
    """
    raw = record.get("montant")
    if raw is None or _text(raw) is None:
        return None
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if amount < 0:
        return None
    return Money(amount=amount, currency="EUR")


def _duration(record: dict) -> Duration | None:
    raw = record.get("dureemois")
    text = _text(raw)
    if text is None:
        return None
    try:
        months = int(float(text))
    except ValueError:
        return None
    return Duration(value=months, unit="month") if months > 0 else None


def _buyers(record: dict) -> tuple[OrganizationRef, ...]:
    siret = buyer_siret(record)
    if siret is None:
        return ()
    return (
        OrganizationRef(
            legal_name=siret,
            identifiers=(OrganizationIdentifier(scheme=SIRET_SCHEME, value=siret),),
            country="FR",
        ),
    )


def parse_contract(
    record: dict, *, retrieved_at: dt.datetime | None = None
) -> tuple[PublicEvent, ContractAward]:
    """Un enregistrement DECP courant → un événement et son contrat canoniques.

    DECP est autonome : il porte son propre identifiant de marché, ses parties
    et son montant. Il ne réclame donc aucun parent BOAMP. Ce qu'il ne porte
    pas — une date de décision, un nom d'entreprise — reste absent.
    """
    identifier = _text(record.get("id"))
    if not identifier:
        raise ValueError("enregistrement DECP sans `id` : aucune identité de contrat")

    event = PublicEvent(
        provenance=Provenance(
            source_system=DECP_SOURCE_SYSTEM,
            source_country=DECP_SOURCE_COUNTRY,
            source_notice_id=identifier,
            source_url=(
                f"https://data.economie.gouv.fr/explore/dataset/{DECP_DATASET}"
                f"/table/?q={identifier}"
            ),
            retrieved_at=retrieved_at,
        ),
        event_type="award_notice",
        published_at=_date(record.get("datepublicationdonnees")),
        procedure_buyers=_buyers(record),
    )
    winners = _winners(record)
    contract = ContractAward(
        event_ref=event.ref(),
        source_award_id=identifier,
        contract_reference=_text(record.get("idaccordcadre")),
        title=_text(record.get("objet")),
        cpv_main=_cpv(record.get("codecpv")),
        value=_money(record),
        winner_status="identified" if winners else "undisclosed",
        awardee_parties=winners,
        place_of_performance=_place(record),
        duration=_duration(record),
        # R1 §2 — aucune de ces deux dates n'existe dans le schéma 2022.
        award_date=None,
        contract_signature_date=None,
        # La seule date contractuelle que le registre publie.
        contract_notification_date=_date(record.get("datenotification")),
    )
    return event, contract
