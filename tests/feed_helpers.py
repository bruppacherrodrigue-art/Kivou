"""Fabriques partagées des tests SPEC-012 — des signaux réels, pas des maquettes.

Tout part de fixtures publiées : un avis BOAMP français, un avis SIMAP suisse
riche en besoins, et le couple BOAMP × DECP fortement rapproché de SPEC-009E.
Les tests ne construisent donc jamais un signal « idéal » qui n'existerait pas
dans les données réelles — c'est ce qui a permis à SPEC-009C de découvrir tard
que le métier ne modélisait pas ce qu'il croyait.

Les dates ne sont jamais retouchées. Pour observer un signal vieillir, les
tests changent `as_of` à la LECTURE, ce qui est exactement ce que le produit
fait en production.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import sqlalchemy as sa

from signals.accounts.icp_input import TargetIcpInput
from signals.accounts.service import create_target_icp, sign_up
from signals.matching import MatchingEngine
from signals.matching.reference import CONSTRUCTION_INPUTS_ICP
from signals.needs import NeedGraphEngine
from signals.persistence.materialization import materialize_signal
from signals.recency import assess_recency
from signals.understanding import ContractUnderstandingEngine

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
FRANCE = FIXTURES / "france"
SIMAP = FIXTURES / "simap"

RETRIEVED_AT = dt.datetime(2026, 8, 18, 9, 0, tzinfo=dt.UTC)
MATERIALIZED_AT = RETRIEVED_AT
#: Le jour où les signaux sont matérialisés. Les lectures s'en écartent exprès.
MATERIALIZED_ON = dt.date(2026, 8, 18)

PASSWORD = "un-mot-de-passe-assez-long"
#: CLOSEOUT §3 — origine SYNTHÉTIQUE pour la validation CSRF. Ce n'est pas une
#: URL de retour, mais un nom d'hôte réel et obsolète laissé dans des fixtures
#: finit par être recopié dans une documentation de déploiement.
ORIGIN = "https://kivou.test"

#: L'identifiant d'ICP de recherche de SPEC-010 — antérieur à tout compte.
RESEARCH_ICP_ID = "icp-construction-inputs-ch-eu-v0"

COMPLETE_ICP_INPUT = {
    "offers": ["materials_and_components"],
    "buyer_trades": ["building_construction"],
    "territories": ["CH"],
    "minimum_contract_value": {"currency": "CHF", "minimum_amount": 1000},
}

BOAMP_RECORDS = {
    record["idweb"]: record
    for record in json.loads((FRANCE / "boamp_records.json").read_text(encoding="utf-8"))["records"]
}

#: Attribué le 2026-07-17, publié le 2026-08-18 : la même ligne est
#: `recent_award` fin juillet, `aging_award` mi-août et `stale_award` en octobre.
BOAMP_AGING = "26-80978"
#: Sans date de décision publiée : seule la parution parle.
BOAMP_PUBLICATION_ONLY = "26-80922"

LINK = json.loads((FRANCE / "boamp_decp2022_link.json").read_text(encoding="utf-8"))
#: Le couple fortement rapproché de SPEC-009E : le même contrat, vu par les deux
#: portails français. Il sert à prouver qu'il ne fait qu'UN signal client.
LINKED_BOAMP = next(record for record in LINK["boamp_records"] if record["idweb"] == "26-79799")
LINKED_DECP = next(record for record in LINK["decp_records"] if record["id"] == "178645481096900")

#: SIMAP, trois besoins plausibles dont deux retenus par l'ICP de référence.
SIMAP_RICH = "33112-02"


def simap_award(name: str):
    from signals.connectors.simap import map_publication, parse_publication

    publication = parse_publication(
        json.loads((SIMAP / f"{name}.json").read_text(encoding="utf-8"))
    )
    extraction = map_publication(publication, retrieved_at=RETRIEVED_AT)
    return extraction.event, extraction.awards


def boamp_award(idweb: str):
    from signals.connectors.boamp import parse_award_notice

    return parse_award_notice(BOAMP_RECORDS[idweb], retrieved_at=RETRIEVED_AT)


def publication_date(event) -> dt.date | None:
    published = event.published_at
    if published is None:
        return None
    return published.date() if isinstance(published, dt.datetime) else published


def materialize(
    connection: sa.Connection,
    event,
    award,
    *,
    target_icp_id: str,
    as_of: dt.date = MATERIALIZED_ON,
    linked_to=(),
    link_strength: str = "unresolved",
):
    """Fait passer un avis réel dans toute la chaîne, pour l'ICP indiqué."""
    profile = CONSTRUCTION_INPUTS_ICP.model_copy(update={"icp_id": target_icp_id})
    understanding = ContractUnderstandingEngine().understand(award, event)
    needs = NeedGraphEngine().derive(understanding)
    match = MatchingEngine().match(understanding, needs, profile, as_of=as_of)
    recency = assess_recency(
        award_date=award.award_date,
        contract_notification_date=award.contract_notification_date,
        publication_date=publication_date(event),
        as_of=as_of,
    )
    return materialize_signal(
        connection,
        event=event,
        award=award,
        understanding=understanding,
        needs=needs,
        match=match,
        recency=recency,
        as_of=as_of,
        materialized_at=MATERIALIZED_AT,
        linked_to=list(linked_to),
        link_strength=link_strength,
    )


def materialize_boamp(connection: sa.Connection, idweb: str, *, target_icp_id: str, lot: int = 0):
    event, awards = boamp_award(idweb)
    return materialize(connection, event, awards[lot], target_icp_id=target_icp_id)


def materialize_simap(connection: sa.Connection, name: str, *, target_icp_id: str, lot: int = 0):
    event, awards = simap_award(name)
    return materialize(connection, event, awards[lot], target_icp_id=target_icp_id)


def make_account(connection: sa.Connection, email: str, company: str) -> str:
    return sign_up(
        connection,
        email=email,
        password=PASSWORD,
        company_name=company,
        locale="fr",
        now=RETRIEVED_AT,
        session_ttl=dt.timedelta(days=30),
    ).account_id


def make_icp(
    connection: sa.Connection, account_id: str, label: str = "Intrants", **overrides
) -> str:
    return create_target_icp(
        connection,
        account_id=account_id,
        label=label,
        customer_input=TargetIcpInput.model_validate({**COMPLETE_ICP_INPUT, **overrides}),
        now=RETRIEVED_AT,
    ).target_icp_id


def pin_session_cookie(client, response) -> None:
    """Désamorce la bombe des deux horloges (classe rtl-02).

    Le cookie de session est daté par l'horloge métier figée du test, mais le
    porte-cookies du client l'évalue à l'heure RÉELLE : dès que le réel dépasse
    la date figée plus le TTL de session (14 jours), le cookie « expire » et
    chaque appel suivant répond 401 — détonation constatée le 2026-09-01 à
    09:00 UTC, quatorze jours après RETRIEVED_AT. On réinscrit donc le cookie
    sans date d'expiration : les deux horloges ne se croisent plus jamais.
    """

    for header in response.headers.get_list("set-cookie"):
        first = header.split(";", 1)[0]
        name, _, value = first.partition("=")
        if name and value and "Max-Age=0" not in header:
            client.cookies.set(name.strip(), value.strip())
            return
    raise AssertionError("aucun cookie de session dans la réponse d'inscription")
