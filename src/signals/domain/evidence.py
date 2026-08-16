"""La preuve : d'où vient une information, et comment y revenir.

`Evidence` est **source-agnostique** par construction. Elle décrit un
emplacement dans une source — un chemin XML, un chemin JSON, une page et une
section d'un cahier des charges, une réponse de registre — sans supposer lequel.
C'est ce qui lui permettra d'accueillir demain un document de marché sans
changer de forme.

Deux natures que le modèle refuse de confondre :

**fait source** — la source l'a publié. Il n'a pas de `engine_version` : aucun
moteur ne l'a produit.

**affirmation dérivée** — nous l'avons conclu. Elle porte obligatoirement la
version du moteur qui l'a produite, sans quoi personne ne saura plus, dans six
mois, quelles règles ont donné ce résultat.

Une preuve est **immuable**. Une nouvelle analyse en crée une nouvelle ; elle ne
réécrit jamais l'ancienne.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import model_validator

from signals.domain.events import SourceSystem
from signals.domain.values import CanonicalModel, NonEmptyStr

SourceKind = Literal[
    "publication_field",
    "publication_text",
    "tender_document",
    "registry",
    "derived",
]
"""Nature de l'emplacement d'où vient l'information.

- `publication_field` : un champ structuré de l'avis (XML eForms, JSON SIMAP) ;
- `publication_text` : un passage de texte publié dans l'avis ;
- `tender_document` : un passage d'un document de marché — **prévu, pas encore
  utilisé** : SPEC-005 n'ouvre aucun document ;
- `registry` : une réponse de registre officiel (VIES, registre du commerce) ;
- `derived` : une conclusion tirée d'autres preuves par un moteur nommé.
"""

DERIVED = "derived"


class Evidence(CanonicalModel):
    """Un point d'ancrage vérifiable pour une information."""

    source_system: SourceSystem
    source_kind: SourceKind

    # Où, dans la source
    source_notice_id: NonEmptyStr | None = None
    source_procedure_id: NonEmptyStr | None = None
    source_url: NonEmptyStr | None = None
    # Chemin, champ, ou localisation lisible (« page 12, section 3.2 »).
    path: NonEmptyStr | None = None

    # Ce que la source montre, tel qu'elle le montre
    raw_value: str | None = None
    excerpt: str | None = None

    retrieved_at: dt.datetime | None = None
    # Obligatoire pour une affirmation dérivée, interdit pour un fait source.
    engine_version: NonEmptyStr | None = None

    @property
    def is_derived(self) -> bool:
        return self.source_kind == DERIVED

    @model_validator(mode="after")
    def _coherence(self) -> Evidence:
        if self.source_kind == DERIVED and not self.engine_version:
            raise ValueError(
                "une affirmation dérivée exige engine_version : sans elle, on ne saura "
                "plus quelles règles l'ont produite"
            )
        if self.source_kind != DERIVED and self.engine_version:
            raise ValueError(
                "un fait source ne porte pas de engine_version : aucun moteur ne l'a produit"
            )
        if not any((self.path, self.raw_value, self.excerpt, self.source_url)):
            raise ValueError("preuve qui ne montre rien : ni chemin, ni valeur, ni extrait, ni URL")
        return self
