"""Le moteur de résolution — déterministe, conservateur, traçable.

**Priorité absolue : précision.** Une entreprise non résolue coûte un contrôle
humain ; deux entreprises fusionnées à tort corrompent tout ce qui sera construit
au-dessus. À chaque arbitrage, le moteur choisit de ne pas conclure.

Les paliers, du plus fort au plus faible :

1. **identifiant officiel** — même registre nommé, même valeur → identité forte ;
2. **identifiant local à une source** — reconnaît une organisation *dans sa
   source*, jamais entre deux portails ;
3. **registre officiel** — VIES valide un numéro de TVA déjà publié et, quand
   l'État membre le divulgue, corrobore le nom ;
4. **nom + adresse** — correspondance stricte : `probable` au mieux ;
5. **nom approché** — produit des candidats et rien d'autre. **Jamais** de fusion.

Aucun LLM n'intervient. Aucune décision n'est prise sans trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from signals.domain import AwardeeParty, Company, OrganizationRef, SourceSystem
from signals.resolution.identifiers import (
    ClassifiedIdentifier,
    classify,
    vat_country,
    vat_parts,
)
from signals.resolution.model import (
    CompanyCandidate,
    CompanyResolution,
    PartyResolution,
    ResolutionBasis,
    ResolutionStatus,
)
from signals.resolution.normalize import (
    matching_name,
    name_core,
    name_similarity,
    postal_code,
)
from signals.resolution.registries import RegistryAuthRequiredError, RegistryError, ViesClient

# Seuil de GÉNÉRATION DE CANDIDATS, pas de décision. Calibré sur le corpus réel
# (voir THRESHOLD STUDY) : au-dessous, les paires observées sont massivement des
# entreprises différentes. Aucun score, si haut soit-il, ne fusionne quoi que ce
# soit — il ne fait qu'appeler un humain.
CANDIDATE_SIMILARITY = 0.6

# Un noyau de nom plus court que cela est trop générique pour même suggérer.
MIN_CORE_LENGTH = 4


@dataclass
class _Record:
    """Une entreprise connue du run, avec toutes ses clés de rapprochement."""

    company: Company
    verified: bool = False
    sources: set[str] = field(default_factory=set)
    mentions: int = 0
    official_keys: set[tuple[str, str]] = field(default_factory=set)
    local_keys: set[tuple[str, str, str]] = field(default_factory=set)
    unattributed_keys: set[tuple[str, str, str, str | None]] = field(default_factory=set)
    name_keys: set[tuple[str, str | None, str | None]] = field(default_factory=set)


@dataclass
class ResolverStats:
    """De quoi mesurer le moteur, y compris ce qu'il a refusé de faire."""

    mentions: int = 0
    vies_attempted: int = 0
    vies_valid: int = 0
    vies_invalid: int = 0
    vies_unavailable: int = 0
    vies_cache_hits: int = 0
    zefix_attempted: int = 0
    zefix_auth_required: int = 0
    registry_errors: int = 0
    automatic_links: int = 0


class CompanyResolver:
    """Résout des `OrganizationRef` en `Company`, sans jamais toucher aux awards."""

    def __init__(
        self,
        *,
        vies: ViesClient | None = None,
        zefix: object | None = None,
        candidate_similarity: float = CANDIDATE_SIMILARITY,
    ) -> None:
        self._records: list[_Record] = []
        self._vies = vies
        self._zefix = zefix
        self._candidate_similarity = candidate_similarity
        self.stats = ResolverStats()

    # ─── Surface publique ───────────────────────────────────────────────────────

    @property
    def companies(self) -> tuple[Company, ...]:
        return tuple(record.company for record in self._records)

    def clusters(self) -> tuple[tuple[Company, int, frozenset[str]], ...]:
        """(entreprise, nombre de mentions rattachées, sources d'origine)."""
        return tuple(
            (record.company, record.mentions, frozenset(record.sources)) for record in self._records
        )

    def resolve_party(self, party: AwardeeParty, *, source_system: SourceSystem) -> PartyResolution:
        """Un groupement n'est pas une entreprise : chaque membre est résolu seul.

        Le nom du groupement est conservé tel qu'il a été publié, mais il ne
        devient jamais une `Company` — aucune source observée ne publie d'entité
        juridique propre pour un groupement.
        """
        return PartyResolution(
            party_name=party.name,
            members=tuple(
                self.resolve(member.organization, source_system=source_system)
                for member in party.members
            ),
        )

    def resolve(
        self, organization: OrganizationRef, *, source_system: SourceSystem
    ) -> CompanyResolution:
        """Résout UNE mention publiée. La mention elle-même n'est jamais modifiée."""
        self.stats.mentions += 1
        identifiers = [classify(identifier) for identifier in organization.identifiers]
        basis: list[ResolutionBasis] = []

        conflict = self._detect_conflicts(organization, identifiers, basis)
        if conflict is not None:
            return conflict

        match = (
            self._match_official(organization, identifiers, basis)
            or self._match_source_local(organization, identifiers, source_system, basis)
            or self._match_unattributed(organization, identifiers, source_system, basis)
            or self._match_name_address(organization, identifiers, basis)
        )
        if match is not None:
            record, status = match
            self._attach(
                record, organization, source_system, identifiers, verified=status == "verified"
            )
            self.stats.automatic_links += 1
            return CompanyResolution(
                source_organization=organization,
                source_system=source_system,
                status=status,
                company=record.company,
                confidence=1.0 if status == "verified" else 0.9,
                basis=tuple(basis),
            )

        return self._resolve_new(organization, identifiers, source_system, basis)

    # ─── Paliers de rapprochement ───────────────────────────────────────────────

    def _match_official(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        basis: list[ResolutionBasis],
    ) -> tuple[_Record, ResolutionStatus] | None:
        """Palier 1 — même registre nommé, même valeur."""
        for identifier in identifiers:
            if identifier.strength != "official":
                continue
            for record in self._records:
                if identifier.key in record.official_keys:
                    basis.append(
                        ResolutionBasis(
                            method="official_identifier",
                            detail=f"{identifier.scheme} {identifier.published_value}",
                        )
                    )
                    return record, "verified"
        return None

    def _match_source_local(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        source_system: SourceSystem,
        basis: list[ResolutionBasis],
    ) -> tuple[_Record, ResolutionStatus] | None:
        """Palier 2 — identifiant interne au portail, valable DANS ce portail seul.

        La clé porte le système source : deux portails peuvent employer la même
        valeur sans le moindre rapport, et rien ici ne les rapprochera.
        """
        for identifier in identifiers:
            if identifier.strength != "source_local":
                continue
            key = (source_system, identifier.scheme, identifier.matching_value)
            for record in self._records:
                if key in record.local_keys:
                    divergent = self._contradicts(record, identifiers)
                    if divergent is not None:
                        basis.append(
                            ResolutionBasis(
                                method="official_identifier",
                                detail=(
                                    f"{divergent.scheme} {divergent.published_value} diffère de "
                                    "l'identifiant officiel déjà rattaché"
                                ),
                                supports=False,
                            )
                        )
                        continue
                    basis.append(
                        ResolutionBasis(
                            method="source_local_identifier",
                            detail=(
                                f"{identifier.scheme} {identifier.published_value} "
                                f"(portée : {source_system} uniquement)"
                            ),
                        )
                    )
                    return record, "probable"
        return None

    def _match_unattributed(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        source_system: SourceSystem,
        basis: list[ResolutionBasis],
    ) -> tuple[_Record, ResolutionStatus] | None:
        """Palier 2b — identifiant national dont le registre n'est pas nommé.

        Même source ET même pays : sans ces deux garde-fous, on rapprocherait un
        SIRET français d'un numéro d'organisation norvégien qui partageraient
        leurs chiffres.
        """
        for identifier in identifiers:
            if identifier.strength != "unattributed":
                continue
            key = (
                source_system,
                identifier.scheme,
                identifier.matching_value,
                organization.country,
            )
            for record in self._records:
                if key in record.unattributed_keys:
                    divergent = self._contradicts(record, identifiers)
                    if divergent is not None:
                        basis.append(
                            ResolutionBasis(
                                method="official_identifier",
                                detail=(
                                    f"{divergent.scheme} {divergent.published_value} diffère de "
                                    "l'identifiant officiel déjà rattaché"
                                ),
                                supports=False,
                            )
                        )
                        continue
                    basis.append(
                        ResolutionBasis(
                            method="unattributed_identifier",
                            detail=(
                                f"{identifier.scheme} {identifier.published_value} "
                                f"— registre non nommé, même source et même pays"
                            ),
                        )
                    )
                    return record, "probable"
        return None

    def _contradicts(
        self, record: _Record, identifiers: list[ClassifiedIdentifier]
    ) -> ClassifiedIdentifier | None:
        """Un identifiant publié DIFFÉRENT sous le même référentiel sépare les entités.

        C'est la contrepartie du palier 1 : si un même registre attribue deux
        valeurs distinctes, ce sont deux entreprises — quelle que soit la
        ressemblance du nom ou de l'adresse. Sans ce garde-fou, `Beta AG`
        CHE-111.111.111 et `Beta AG` CHE-999.999.999, voisines de rue, seraient
        fusionnées par le palier 4.
        """
        known = {registry: value for registry, value in record.official_keys}
        for identifier in identifiers:
            if identifier.strength != "official":
                continue
            registry, value = identifier.key
            if registry in known and known[registry] != value:
                return identifier
        return None

    def _match_name_address(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        basis: list[ResolutionBasis],
    ) -> tuple[_Record, ResolutionStatus] | None:
        """Palier 4 — nom normalisé + pays + code postal, tous trois présents.

        Le palier le plus faible qui rapproche encore : il ne s'applique jamais
        contre un identifiant officiel divergent.
        """
        key = self._name_key(organization)
        if key is None:
            return None
        for record in self._records:
            if key in record.name_keys:
                divergent = self._contradicts(record, identifiers)
                if divergent is not None:
                    basis.append(
                        ResolutionBasis(
                            method="official_identifier",
                            detail=(
                                f"nom et adresse concordants, mais {divergent.scheme} "
                                f"{divergent.published_value} diffère de celui déjà connu"
                            ),
                            supports=False,
                        )
                    )
                    continue
                basis.append(
                    ResolutionBasis(
                        method="name_and_address",
                        detail=f"nom normalisé « {key[0]} », pays {key[1]}, NPA {key[2]}",
                    )
                )
                return record, "probable"
        return None

    # ─── Nouvelle entreprise, ou refus de conclure ──────────────────────────────

    def _resolve_new(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        source_system: SourceSystem,
        basis: list[ResolutionBasis],
    ) -> CompanyResolution:
        candidates = self._fuzzy_candidates(organization)
        registry = self._consult_registry(organization, identifiers, basis)

        if registry == "conflict":
            return CompanyResolution(
                source_organization=organization,
                source_system=source_system,
                status="conflict",
                basis=tuple(basis),
                candidates=candidates,
            )

        # Palier 5 — un nom approché n'est jamais une preuve, dans aucun sens.
        #
        # Il appelle un humain UNIQUEMENT quand la mention n'a rien d'autre pour
        # se distinguer. Si elle porte un identifiant qui ne correspond à aucune
        # entreprise connue, cet identifiant est au contraire une preuve de
        # DISTINCTION : c'est le cas réel de « SOLID SECURITY Sp. z o. o. » face
        # à « SOLID Sp. z o. o. » (similarité 0.50), deux membres distincts d'un
        # même groupement polonais.
        if candidates:
            distinguishing = [i for i in identifiers if i.strength != "unknown"]
            basis.append(
                ResolutionBasis(
                    method="fuzzy_name",
                    detail=(
                        f"{len(candidates)} entreprise(s) au nom proche"
                        + (
                            "; identifiant propre distinct de chacune"
                            if distinguishing
                            else " et aucun identifiant pour les départager"
                        )
                    ),
                    supports=False,
                )
            )
            if not distinguishing and registry != "verified":
                return CompanyResolution(
                    source_organization=organization,
                    source_system=source_system,
                    status="review_required",
                    basis=tuple(basis),
                    candidates=candidates,
                )

        if not self._has_enough_published(organization, identifiers):
            basis.append(
                ResolutionBasis(
                    method="name_and_address",
                    detail="mention réduite à un nom : ni identifiant, ni adresse situable",
                    supports=False,
                )
            )
            return CompanyResolution(
                source_organization=organization,
                source_system=source_system,
                status="unresolved",
                basis=tuple(basis),
                candidates=candidates,
            )

        if registry == "unavailable" and not basis:
            return CompanyResolution(
                source_organization=organization,
                source_system=source_system,
                status="registry_unavailable",
                basis=tuple(basis),
                candidates=candidates,
            )

        status: ResolutionStatus = "verified" if registry == "verified" else "probable"
        if not basis:
            basis.append(
                ResolutionBasis(
                    method="name_and_address",
                    detail="première mention : nom et localisation publiés, aucun registre consulté",
                )
            )
        record = self._create(
            organization, source_system, identifiers, verified=status == "verified"
        )
        return CompanyResolution(
            source_organization=organization,
            source_system=source_system,
            status=status,
            company=record.company,
            confidence=1.0 if status == "verified" else 0.7,
            basis=tuple(basis),
            candidates=candidates,
        )

    def _consult_registry(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        basis: list[ResolutionBasis],
    ) -> str | None:
        """Palier 3 — VIES, sur un numéro DÉJÀ publié. Jamais un numéro deviné."""
        if self._vies is None:
            return None
        for identifier in identifiers:
            parts = vat_parts(identifier.published_value)
            if parts is None:
                continue
            prefix, number = parts
            # Le préfixe doit s'accorder au pays publié : sans cela, on
            # interrogerait le registre d'un autre État sur des chiffres qui n'y
            # veulent rien dire.
            if organization.country and vat_country(prefix) != organization.country:
                continue
            self.stats.vies_attempted += 1
            check = self._vies.check(prefix, number)
            if check.unavailable:
                self.stats.vies_unavailable += 1
                basis.append(
                    ResolutionBasis(
                        method="registry_lookup",
                        detail=f"VIES indisponible pour {prefix} ({check.detail}) — non concluant",
                        supports=False,
                    )
                )
                return "unavailable"
            if not check.valid:
                self.stats.vies_invalid += 1
                if identifier.strength == "official":
                    basis.append(
                        ResolutionBasis(
                            method="registry_lookup",
                            detail=f"VIES déclare {prefix}{number} invalide",
                            supports=False,
                        )
                    )
                    return "conflict"
                # Scheme non attribué : la valeur n'était simplement pas un
                # numéro de TVA. Ce n'est pas une contradiction.
                continue
            self.stats.vies_valid += 1
            if not check.discloses_holder:
                basis.append(
                    ResolutionBasis(
                        method="registry_lookup",
                        detail=(
                            f"VIES : TVA {prefix}{number} valide ; "
                            f"l'État membre ne divulgue pas le titulaire"
                        ),
                    )
                )
                return "probable"
            similarity = name_similarity(organization.legal_name, check.name or "")
            if similarity >= self._candidate_similarity:
                basis.append(
                    ResolutionBasis(
                        method="registry_lookup",
                        detail=(
                            f"VIES : TVA {prefix}{number} valide, titulaire « {check.name} » "
                            f"concordant avec la mention"
                        ),
                    )
                )
                return "verified"
            basis.append(
                ResolutionBasis(
                    method="registry_lookup",
                    detail=(
                        f"VIES : TVA {prefix}{number} valide mais titulaire « {check.name} » "
                        f"sans rapport avec « {organization.legal_name} »"
                    ),
                    supports=False,
                )
            )
            return "conflict"
        return None

    # ─── Contradictions ─────────────────────────────────────────────────────────

    def _detect_conflicts(
        self,
        organization: OrganizationRef,
        identifiers: list[ClassifiedIdentifier],
        basis: list[ResolutionBasis],
    ) -> CompanyResolution | None:
        """Un même identifiant officiel sur un pays incompatible n'est pas une fusion."""
        for identifier in identifiers:
            if identifier.strength != "official":
                continue
            for record in self._records:
                if identifier.key not in record.official_keys:
                    continue
                known = record.company.country
                if known and organization.country and known != organization.country:
                    basis.append(
                        ResolutionBasis(
                            method="official_identifier",
                            detail=(
                                f"{identifier.scheme} {identifier.published_value} déjà rattaché "
                                f"à une entreprise du pays {known}, mention publiée en "
                                f"{organization.country}"
                            ),
                            supports=False,
                        )
                    )
                    return CompanyResolution(
                        source_organization=organization,
                        source_system="manual",
                        status="conflict",
                        basis=tuple(basis),
                    )
        return None

    # ─── Candidats et création ──────────────────────────────────────────────────

    def _fuzzy_candidates(self, organization: OrganizationRef) -> tuple[CompanyCandidate, ...]:
        """Palier 5 — suggestions classées. Ne décide rien, jamais."""
        core = name_core(organization.legal_name)
        if len(core) < MIN_CORE_LENGTH:
            # Un nom trop court est générique : suggérer serait du bruit dangereux.
            return ()
        scored = []
        for record in self._records:
            # Deux pays publiés différents ne sont pas la même entité juridique :
            # une filiale nationale est une entreprise à part entière (§ filiales).
            # Suggérer un rapprochement serait suggérer une erreur.
            if (
                organization.country
                and record.company.country
                and organization.country != record.company.country
            ):
                continue
            score = name_similarity(organization.legal_name, record.company.legal_name)
            if score >= self._candidate_similarity:
                scored.append(
                    CompanyCandidate(
                        company=record.company,
                        score=score,
                        basis=(
                            ResolutionBasis(
                                method="fuzzy_name",
                                detail=(
                                    f"noyau « {core} » proche de "
                                    f"« {name_core(record.company.legal_name)} » ({score:.2f})"
                                ),
                                supports=False,
                            ),
                        ),
                    )
                )
        return tuple(sorted(scored, key=lambda c: -(c.score or 0))[:5])

    def _has_enough_published(
        self, organization: OrganizationRef, identifiers: list[ClassifiedIdentifier]
    ) -> bool:
        """Un nom seul ne fait pas une entreprise établie."""
        if identifiers:
            return True
        return bool(organization.country and postal_code(organization.address))

    def _name_key(self, organization: OrganizationRef) -> tuple[str, str | None, str | None] | None:
        postal = postal_code(organization.address)
        normalized = matching_name(organization.legal_name)
        # Un nom qui ne laisse rien après normalisation ne rapproche rien : sans
        # ce garde-fou, toutes les mentions de ce genre partageraient une clé.
        if not normalized or not organization.country or not postal:
            return None
        return (normalized, organization.country, postal)

    def _create(
        self,
        organization: OrganizationRef,
        source_system: SourceSystem,
        identifiers: list[ClassifiedIdentifier],
        *,
        verified: bool,
    ) -> _Record:
        record = _Record(
            company=Company(
                legal_name=organization.legal_name,
                identifiers=organization.identifiers,
                country=organization.country,
                address=organization.address,
            ),
            verified=verified,
        )
        self._records.append(record)
        self._index(record, organization, source_system, identifiers)
        return record

    def _attach(
        self,
        record: _Record,
        organization: OrganizationRef,
        source_system: SourceSystem,
        identifiers: list[ClassifiedIdentifier],
        *,
        verified: bool,
    ) -> None:
        """Rattache une mention à une entreprise connue, sans jamais la réécrire."""
        record.company = record.company.with_alias(organization)
        record.verified = record.verified or verified
        self._index(record, organization, source_system, identifiers)

    def _index(
        self,
        record: _Record,
        organization: OrganizationRef,
        source_system: SourceSystem,
        identifiers: list[ClassifiedIdentifier],
    ) -> None:
        record.mentions += 1
        record.sources.add(source_system)
        for identifier in identifiers:
            if identifier.strength == "official":
                record.official_keys.add(identifier.key)
            elif identifier.strength == "source_local":
                record.local_keys.add((source_system, identifier.scheme, identifier.matching_value))
            elif identifier.strength == "unattributed":
                record.unattributed_keys.add(
                    (
                        source_system,
                        identifier.scheme,
                        identifier.matching_value,
                        organization.country,
                    )
                )
        key = self._name_key(organization)
        if key is not None:
            record.name_keys.add(key)


__all__ = [
    "CANDIDATE_SIMILARITY",
    "CompanyResolver",
    "RegistryAuthRequiredError",
    "RegistryError",
    "ResolverStats",
]
