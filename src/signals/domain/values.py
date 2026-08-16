"""Objets-valeur canoniques.

Aucune dépendance à SIMAP, TED ou tout autre portail : ces objets décrivent des
faits publics (un montant, un lieu, une organisation telle qu'imprimée), pas la
façon dont une source les encode. Un connecteur traduit *vers* ces objets ; il
n'en modifie jamais la forme.

Deux règles portées structurellement ici :

- **immuabilité** : un fait publié ne se corrige pas en place, il est remplacé
  par un nouvel événement (voir `PublicEvent.corrects`) ;
- **rien d'inventé** : tout champ inconnu reste absent (`None`) ; aucun défaut
  n'invente une valeur plausible.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


class CanonicalModel(BaseModel):
    """Base commune : immuable, close, sans champ inconnu toléré.

    `extra="forbid"` est délibéré : un connecteur qui voudrait faire passer un
    champ propre à sa source doit échouer bruyamment plutôt que de contaminer le
    modèle canonique.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""Chaîne réellement renseignée. Une chaîne vide n'est pas une donnée : c'est `None`."""


def _cadrer(value: Any) -> Any:
    """Majuscules + espaces retirés AVANT la validation de forme.

    `StringConstraints(to_upper=True)` ne suffit pas : pydantic v2 vérifie le
    motif avant d'appliquer la transformation, et `"chf"` serait donc rejeté.
    """
    return value.strip().upper() if isinstance(value, str) else value


CountryCode = Annotated[str, BeforeValidator(_cadrer), StringConstraints(pattern=r"^[A-Z]{2}$")]
"""ISO 3166-1 alpha-2. `CH` et `FR` se lisent pareil, quelle que soit la source."""

CurrencyCode = Annotated[str, BeforeValidator(_cadrer), StringConstraints(pattern=r"^[A-Z]{3}$")]
"""ISO 4217. Jamais de devise implicite : un montant sans devise est refusé."""


class CpvCode(CanonicalModel):
    """Code CPV — vocabulaire commun des marchés publics, utilisé par TED et par SIMAP.

    Le chiffre de contrôle (`45000000-7`) est conservé s'il est publié, jamais
    recalculé : recalculer reviendrait à affirmer une donnée que la source n'a
    pas donnée.
    """

    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{8}$")]
    check_digit: Annotated[str, StringConstraints(pattern=r"^\d$")] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accepter_forme_imprimee(cls, data: Any) -> Any:
        """Accepte `"45000000-7"` ou `"45000000"` — normalisation déterministe, sans LLM."""
        if isinstance(data, str):
            code, _, check = data.strip().partition("-")
            return {"code": code, "check_digit": check or None}
        return data

    def __str__(self) -> str:
        return self.code if self.check_digit is None else f"{self.code}-{self.check_digit}"


VatCategory = Literal["none", "standard", "special", "reduced", "foreign"]
"""Régime de TVA sous lequel un montant est publié, quand la source le dit.

Une **catégorie**, jamais un taux : le domaine ne connaît aucun pourcentage et
n'en déduit aucun. Il ne conclut pas davantage « TTC » ou « HT » — une source
qui distingue cinq régimes ne dit pas par là si la taxe est comprise dans le
chiffre ; l'affirmer serait une interprétation, pas un fait.

`None` signifie exactement une chose : la source ne publie pas cette
information. Ce n'est ni « pas de TVA » (`none`) ni un défaut implicite.
"""


class Money(CanonicalModel):
    """Un montant EST un couple valeur+devise. CHF et EUR ne se comparent pas."""

    amount: Decimal = Field(ge=0)
    currency: CurrencyCode
    # Qualificatif fiscal publié avec le montant. Deux montants de catégories
    # différentes ne décrivent pas la même chose ; les comparer sans le savoir
    # produirait des écarts silencieux entre sources.
    vat_category: VatCategory | None = None

    @model_validator(mode="before")
    @classmethod
    def _refuser_le_flottant(cls, data: Any) -> Any:
        """Un float perd des centimes en silence : la source doit passer str/int/Decimal."""
        if isinstance(data, dict) and isinstance(data.get("amount"), float):
            # ValueError et non TypeError : pydantic ne convertit en ValidationError
            # que ValueError/AssertionError.
            raise ValueError(  # noqa: TRY004
                "montant flottant refusé : passer une str, un int ou un Decimal"
            )
        return data

    def canonical_amount(self) -> str:
        """`1000`, `1000.00` et `1E+3` donnent la même chaîne — base d'une comparaison stable.

        Le régime de TVA n'y entre pas : il qualifie le montant, il n'en fait pas
        partie. L'inclure changerait l'empreinte de rapprochement d'un contrat
        dont seul le qualificatif serait publié plus tard.
        """
        return format(self.amount.normalize(), "f")


DurationUnit = Literal["day", "week", "month", "year"]


class Duration(CanonicalModel):
    """Durée telle que publiée. Jamais déduite de start/end : ce serait une inférence."""

    value: int = Field(gt=0)
    unit: DurationUnit


SubdivisionScheme = Literal["NUTS", "ISO-3166-2"]
"""Le canton suisse et la région NUTS partagent une forme : un code + son référentiel.

C'est ce couple qui rend la localisation source-agnostique. Un `canton: TEXT` en
dur bloquerait TED dès le premier avis ; un `nuts: TEXT` en dur ignorerait SIMAP.
"""


class Location(CanonicalModel):
    """Lieu d'exécution ou siège, au niveau de détail réellement publié."""

    country: CountryCode | None = None
    subdivision_code: NonEmptyStr | None = None
    subdivision_scheme: SubdivisionScheme | None = None
    locality: NonEmptyStr | None = None
    postal_code: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _coherente(self) -> Location:
        if (self.subdivision_code is None) != (self.subdivision_scheme is None):
            raise ValueError("subdivision_code et subdivision_scheme vont par paire")
        if not any(
            (
                self.country,
                self.subdivision_code,
                self.locality,
                self.postal_code,
            )
        ):
            raise ValueError("Location vide : une localisation inconnue s'écrit None")
        return self


class OrganizationIdentifier(CanonicalModel):
    """Identifiant d'organisation dans un référentiel nommé.

    `scheme` reste une chaîne libre (`CHE-UID`, `EU-VAT`, `TED-ORG-ID`…) : figer
    la liste obligerait à modifier le domaine à chaque nouveau portail.
    """

    scheme: NonEmptyStr
    value: NonEmptyStr


class OrganizationRef(CanonicalModel):
    """Une organisation TELLE QUE L'AVIS LA NOMME — mention brute, pas entité résolue.

    Ce n'est volontairement pas une `Company` : une entité suppose une identité
    résolue (« ces deux raisons sociales sont la même société »), donc de la
    réconciliation, donc de l'inférence — hors périmètre des faits publics.
    Quand `Company` existera, elle sera la table d'entités résolues et cet objet
    restera la mention d'origine, sans toucher `ContractAward`.

    Le même objet sert d'acheteur et d'attributaire : un acheteur public *est*
    une organisation, leur différence est un rôle, pas une forme.
    """

    legal_name: NonEmptyStr
    identifiers: tuple[OrganizationIdentifier, ...] = ()
    country: CountryCode | None = None
    address: NonEmptyStr | None = None
    website: NonEmptyStr | None = None

    def identifier(self, scheme: str) -> str | None:
        """Valeur dans un référentiel donné, ou `None` si l'avis ne la publie pas."""
        for candidate in self.identifiers:
            if candidate.scheme == scheme:
                return candidate.value
        return None
