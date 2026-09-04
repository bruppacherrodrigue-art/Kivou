"""L'événement public et sa provenance.

`PublicEvent` = « une publication a eu lieu, dans ce système, à cette date ».
Il ne porte aucune donnée contractuelle : celles-ci vivent dans `ContractAward`,
parce qu'une même publication peut en porter plusieurs (lots).

La provenance est isolée dans son propre objet : elle décrit d'où vient
l'information, jamais ce que l'information affirme. Un connecteur supplémentaire
étend `SourceSystem` et rien d'autre.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, model_validator

from signals.domain.values import (
    CanonicalModel,
    CountryCode,
    NonEmptyStr,
    OrganizationRef,
)

_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _instant_publie(value: Any) -> Any:
    """`"2026-08-16"` reste une date ; `"2026-08-16T09:42:17+02:00"` reste un instant.

    Le choix du type EST l'information de précision : pas de champ `precision`
    parallèle à tenir cohérent, pas d'objet enveloppe. `date` et `datetime` sont
    deux types distincts que Pydantic sait sérialiser tels quels.
    """
    if isinstance(value, str):
        text = value.strip()
        return (
            dt.date.fromisoformat(text)
            if _DATE_ONLY.fullmatch(text)
            else (dt.datetime.fromisoformat(text))
        )
    return value


PublicationInstant = Annotated[
    # `strict` sur CHAQUE membre : sans lui, Pydantic accepterait de promouvoir une
    # date en datetime à minuit (heure inventée) ou de tronquer un datetime en date
    # (précision perdue). Les deux trahiraient la source.
    Annotated[dt.date, Field(strict=True)] | Annotated[dt.datetime, Field(strict=True)],
    BeforeValidator(_instant_publie),
]
"""Publication à la précision RÉELLEMENT publiée — `date` ou `datetime`, jamais l'un pour l'autre."""

SourceSystem = Literal["simap", "ted", "boamp", "decp", "intelliprocure", "manual"]
"""Portails connus. Ajouter un pays = ajouter une valeur ici, rien d'autre.

La France en occupe deux, et la distinction est un fait, pas une commodité :
`boamp` publie l'**événement** — un avis d'attribution daté, paru tel jour —
tandis que `decp` publie la **donnée essentielle** du contrat, des mois ou des
années plus tard. Les fondre sous un seul `fr` effacerait précisément l'écart
temporel que SPEC-009E mesure.

`manual` couvre la saisie humaine (correction supervisée, jeu de test) : elle
doit être traçable comme n'importe quelle autre origine, pas déguisée en source
officielle.
"""

EventType = Literal[
    "tender_notice", "award_notice", "award_correction", "award_cancellation", "other"
]
"""Nature de la publication officielle, distincte des contrats qu'elle peut porter."""


class EventRef(CanonicalModel):
    """Référence stable vers un événement public — l'ancêtre de la future clé étrangère.

    Le triplet (système, identifiant de notice, version) est la seule chose dont
    un `ContractAward` a besoin pour être rattaché à son origine, sans dépendre
    d'un identifiant interne qui n'existe pas encore.
    """

    source_system: SourceSystem
    source_notice_id: NonEmptyStr
    notice_version: NonEmptyStr | None = None

    def key(self) -> str:
        """Forme textuelle déterministe, réutilisable telle quelle comme clé d'unicité."""
        return f"{self.source_system}:{self.source_notice_id}:{self.notice_version or ''}"


class Provenance(CanonicalModel):
    """D'où vient l'information — jamais ce qu'elle affirme.

    Séparer provenance et données métier est ce qui permet à `ContractAward` de
    n'avoir aucun champ propre à TED ou à SIMAP. La provenance FINE (champ ou
    passage source, niveau de confiance) relèvera de `Evidence`, dans une SPEC
    ultérieure : ici, la granularité est l'enregistrement.
    """

    source_system: SourceSystem
    source_country: CountryCode
    source_notice_id: NonEmptyStr
    notice_version: NonEmptyStr | None = None
    # La PROCÉDURE dont cet avis rend compte — distincte de l'avis lui-même.
    # Plusieurs avis (appel d'offres, adjudication, corrections) partagent cette
    # valeur ; elle n'entre donc pas dans l'identité de l'événement. C'est par
    # elle que se rattacheront plus tard l'appel d'offres d'origine et ses
    # documents.
    source_procedure_id: NonEmptyStr | None = None
    source_url: NonEmptyStr | None = None
    retrieved_at: dt.datetime | None = None

    def ref(self) -> EventRef:
        return EventRef(
            source_system=self.source_system,
            source_notice_id=self.source_notice_id,
            notice_version=self.notice_version,
        )


class PublicEvent(CanonicalModel):
    """Une publication officielle constatée.

    `published_at` (quand la source a publié) et `event_date` (quand le fait
    décrit s'est produit) sont distincts : un avis d'adjudication publié en mars
    peut relater une décision de janvier. Les confondre fausserait toute
    chronologie commerciale construite plus tard dessus.

    Il porte aussi les acheteurs de la procédure : la source les publie une fois
    par avis, pas contrat par contrat. Les recopier sur chaque contrat
    affirmerait une portée que la source ne donne pas.

    `published_at` conserve la précision publiée — date seule ou instant horodaté.
    La fraîcheur d'un signal se mesure en heures ; arrondir à la journée dès
    l'ingestion détruirait une information qu'aucun traitement ultérieur ne peut
    reconstituer. `event_date` reste une date : les sources datent une décision
    d'adjudication au jour, et inventer une précision serait le symétrique du
    même défaut.
    """

    provenance: Provenance
    event_type: EventType
    published_at: PublicationInstant | None = None
    event_date: dt.date | None = None
    corrects: EventRef | None = None
    # Les acheteurs de la PROCÉDURE, publiés une fois pour tout l'avis et partagés
    # par tous ses contrats. Distincts des signataires d'un contrat donné
    # (`ContractAward.contract_signatories`) : une centrale d'achat peut mener la
    # procédure sans signer le contrat. Les confondre effacerait qui achète
    # réellement.
    procedure_buyers: tuple[OrganizationRef, ...] = ()

    def ref(self) -> EventRef:
        return self.provenance.ref()

    def published_precision(self) -> Literal["date", "datetime"] | None:
        """Ce que la source a réellement donné — lisible sans inspecter les types."""
        if self.published_at is None:
            return None
        return "datetime" if isinstance(self.published_at, dt.datetime) else "date"

    def natural_key(self) -> str:
        """Deux imports produisant cette clé décrivent le même événement publié.

        La version de notice en fait partie : une correction TED est un événement
        distinct, pas une mise à jour de l'original — les faits publiés ne se
        réécrivent pas.
        """
        return self.ref().key()

    @model_validator(mode="after")
    def _correction_coherente(self) -> PublicEvent:
        if self.corrects is None:
            return self
        if self.event_type not in ("award_correction", "award_cancellation"):
            raise ValueError(f"event_type='{self.event_type}' ne corrige aucun événement antérieur")
        if self.corrects.source_system != self.provenance.source_system:
            raise ValueError("un événement ne corrige qu'un événement du même système source")
        if self.corrects == self.ref():
            raise ValueError("un événement ne peut se corriger lui-même")
        return self


class TenderNotice(CanonicalModel):
    """Faits minimaux nécessaires pour capturer un dossier avant l'attribution."""

    event: PublicEvent
    title: NonEmptyStr | None = None
    cpv_main: Annotated[str, Field(pattern=r"^\d{8}$")] | None = None
    submission_deadline: dt.datetime | None = None
    document_urls: tuple[NonEmptyStr, ...] = ()
