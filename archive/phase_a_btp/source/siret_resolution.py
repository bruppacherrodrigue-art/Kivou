"""Provider-free orchestration contracts for asynchronous SIRET recovery."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from enum import StrEnum

from pydantic import model_validator

from signals.phase_a_btp.contracts import AwardSnapshot, Contract, NonEmpty


class ResolutionStatus(StrEnum):
    RESOLVED_EXISTING = "RESOLVED_EXISTING"
    QUEUED_OFFICIAL_SOURCE = "QUEUED_OFFICIAL_SOURCE"
    INVALID_SIRET = "INVALID_SIRET"


class CompanyIdentity(Contract):
    siret: NonEmpty
    legal_name: NonEmpty
    company_key: NonEmpty

    @model_validator(mode="after")
    def valid_siret(self) -> CompanyIdentity:
        if re.fullmatch(r"\d{14}", self.siret) is None:
            raise ValueError("SIRET must contain exactly fourteen digits")
        return self


class CompanyIdentityIndex(Contract):
    identities: tuple[CompanyIdentity, ...]

    @model_validator(mode="after")
    def unique_sirets(self) -> CompanyIdentityIndex:
        if len({identity.siret for identity in self.identities}) != len(self.identities):
            raise ValueError("existing identity SIRETs must be unique")
        return self

    def get(self, siret: str) -> CompanyIdentity | None:
        return next((identity for identity in self.identities if identity.siret == siret), None)


class SiretResolutionJob(Contract):
    opportunity_key: NonEmpty
    award_key: NonEmpty
    siret: NonEmpty
    source: str = "official_company_register"


class ResolutionOutcome(Contract):
    opportunity_key: NonEmpty
    status: ResolutionStatus
    legal_name: NonEmpty | None = None
    company_key: NonEmpty | None = None
    job: SiretResolutionJob | None = None


def _siret(award: AwardSnapshot) -> str | None:
    candidate = award.awardee_siret or award.awardee_name or ""
    digits = re.sub(r"\D", "", candidate)
    return digits if re.fullmatch(r"\d{14}", digits) else None


def apply_resolved_identity(
    award: AwardSnapshot,
    identity: CompanyIdentity,
    *,
    reevaluate: Callable[[AwardSnapshot], object],
) -> None:
    """Bind a source-resolved identity, then trigger deterministic re-evaluation."""

    reevaluate(
        award.model_copy(
            update={"awardee_name": identity.legal_name, "awardee_siret": identity.siret}
        )
    )


def prepare_resolution_batch(
    awards: Iterable[AwardSnapshot],
    *,
    index: CompanyIdentityIndex,
    reevaluate: Callable[[AwardSnapshot], object],
) -> tuple[ResolutionOutcome, ...]:
    """Resolve from Kivou first and emit inert official-source jobs for misses."""

    outcomes: list[ResolutionOutcome] = []
    for award in awards:
        siret = _siret(award)
        if siret is None:
            outcomes.append(
                ResolutionOutcome(
                    opportunity_key=award.opportunity_key,
                    status=ResolutionStatus.INVALID_SIRET,
                )
            )
            continue
        identity = index.get(siret)
        if identity is not None:
            apply_resolved_identity(award, identity, reevaluate=reevaluate)
            outcomes.append(
                ResolutionOutcome(
                    opportunity_key=award.opportunity_key,
                    status=ResolutionStatus.RESOLVED_EXISTING,
                    legal_name=identity.legal_name,
                    company_key=identity.company_key,
                )
            )
            continue
        outcomes.append(
            ResolutionOutcome(
                opportunity_key=award.opportunity_key,
                status=ResolutionStatus.QUEUED_OFFICIAL_SOURCE,
                job=SiretResolutionJob(
                    opportunity_key=award.opportunity_key,
                    award_key=award.award_key,
                    siret=siret,
                ),
            )
        )
    return tuple(outcomes)
