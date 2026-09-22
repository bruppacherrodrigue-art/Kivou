"""Bounded, resumable B1 Apollo calls over Kivou's isolated SHADOW census."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from functools import partial
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import (
    CensusBudgetExceeded,
    CensusLimits,
    CensusPartition,
    CensusReviewRequired,
)
from signals.acquisition_programs.census_b0 import B0Runner
from signals.acquisition_programs.census_b1 import B1PlanStore
from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.mail_provider import MailProviderDetector
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialMatch,
    OfficialSourceRetryLater,
)
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.contact_discovery.contracts import ApolloEnrichedPerson, PeopleSearchPage
from signals.persistence.schema import (
    acquisition_census_b0_entry,
    acquisition_census_b1_entry,
    acquisition_census_b1_plan,
    acquisition_census_call,
    acquisition_census_candidate,
    acquisition_census_permit,
    acquisition_census_run,
)
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient
from signals.supplier_discovery.contracts import SupplierSearchPage


class _BoundLegalResolver(LegalPageResolver):
    def __init__(self, resolver: LegalPageResolver, *, run_id: str,
                 company_id: str) -> None:
        self.resolver = resolver
        self.run_id = run_id
        self.company_id = company_id

    def resolve(self, domain: str, *, at: dt.datetime,
                run_id: str | None = None, company_id: str | None = None) -> dict:
        if run_id not in (None, self.run_id) or company_id not in (None, self.company_id):
            raise ValueError("B1 legal-page accounting context cannot change")
        return self.resolver.resolve(domain, at=at, run_id=self.run_id,
                                     company_id=self.company_id)


class _DeferredOfficialMatcher(OfficialCompanyMatcher):
    """Keep technical contact yield when the optional registry needs retry."""

    def __init__(self, matcher: OfficialCompanyMatcher) -> None:
        self.matcher = matcher

    def assess_with_legal_page(self, candidate, *, resolver, at: dt.datetime) -> OfficialMatch:
        try:
            return self.matcher.assess_with_legal_page(candidate, resolver=resolver, at=at)
        except OfficialSourceRetryLater:
            return OfficialMatch(
                legal_status="UNKNOWN", match_confidence="NO_MATCH", observed_at=at,
                match_reasons=("SOURCE_TEMPORARILY_UNAVAILABLE",),
            )


class B1Runner(B0Runner):
    """Reuse B0 contact qualification with a distinct B1 permit and ledger."""

    def __init__(self, engine: Engine, *, census_id: str, permit_id: str,
                 config: AcquisitionProgramConfig, limits: CensusLimits,
                 database_id: str, configuration_hash: str,
                 contacts: ApolloContactDiscoveryClient,
                 organizations: ApolloOrganizationSearchClient,
                 account_probe: Callable[[], ApolloAccountState],
                 detector: MailProviderDetector,
                 official: OfficialCompanyMatcher,
                 legal_pages: LegalPageResolver,
                 suppression_keys: SuppressionIdentityKeyring) -> None:
        super().__init__(engine, census_id=census_id, permit_id=permit_id,
                         config=config, limits=limits, database_id=database_id,
                         configuration_hash=configuration_hash,
                         contacts=contacts, account_probe=account_probe,
                         detector=detector, official=official,
                         legal_pages=legal_pages, suppression_keys=suppression_keys)
        self.organizations = organizations
        self.b1 = B1PlanStore(engine)
        self._free_search_calibrated = True

    def _credit_state(self, *, credits: int) -> ApolloAccountState:
        state = self.account_probe()
        balance = state.credit_balances.get("lead_credit")
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_b1_plan).where(
                acquisition_census_b1_plan.c.plan_id == self.permit_id,
            )).mappings().one()
        if (not state.credential_valid or balance is None or
                balance < 1000 + credits or balance > plan["pool_before"]):
            raise CensusBudgetExceeded("B1 prepaid reserve, account or top-up guard failed")
        return state

    def _call(self, *, candidate_id: str, partition_id: str, kind: str, subject: str,
              credits: int, at: dt.datetime, invoke: Callable[[], Any],
              model: type[PeopleSearchPage | ApolloEnrichedPerson]) -> tuple[Any, dict]:
        if kind not in {"PEOPLE_SEARCH", "PERSON_ENRICH"} or credits not in {0, 1}:
            raise ValueError("B1 only allows free leader search or one-credit enrichment")
        with self.engine.connect() as connection:
            prior = connection.execute(sa.select(acquisition_census_call.c.status).where(
                acquisition_census_call.c.census_id == self.census_id,
                acquisition_census_call.c.kind == kind,
                acquisition_census_call.c.subject_hash == hashlib.sha256(subject.encode()).hexdigest(),
                acquisition_census_call.c.attempt == 1,
            )).scalar_one_or_none()
        before = self._credit_state(credits=credits) if prior != "COMPLETED" and credits else None

        def decode(value: object) -> Any:
            if value == {"none": True}:
                return None
            return model.model_validate(value)

        result, call_id = self.store.execute_call(
            self.census_id, kind=kind, subject=subject,
            partition_id=partition_id, credits=credits,
            candidate_slots=1 if kind == "PEOPLE_SEARCH" else 0,
            at=at, invoke=invoke,
            encode=lambda value: value.model_dump(mode="json") if value is not None
            else {"none": True}, decode=decode,
        )
        after = self._credit_state(credits=0) if before is not None else None
        delta = (None if before is None or after is None else
                 before.credit_balances["lead_credit"] - after.credit_balances["lead_credit"])
        if delta is not None and (delta < 0 or delta > credits):
            raise CensusReviewRequired("B1 Apollo credit change is ambiguous")
        return result, {"call_id": call_id, "kind": kind, "reserved": credits,
                        "observed_pool_delta": delta,
                        "cache_hit": prior == "COMPLETED"}

    def _process(self, row: dict, stratum: dict, *, at: dt.datetime) -> dict:
        original = self.legal_pages
        original_official = self.official
        self.legal_pages = _BoundLegalResolver(
            original, run_id=self.census_id, company_id=row["candidate_id"],
        )
        self.official = _DeferredOfficialMatcher(original_official)
        try:
            result = super()._process(row, stratum, at=at)
        finally:
            self.legal_pages = original
            self.official = original_official
        if result.get("classification") == "SUPPRESSED":
            # Suppressed contacts remain in the private audit evidence, but
            # never advance the 500-address usable-base stopping condition.
            result["verified_email"] = False
            return result
        email = result.get("email")
        if email and result.get("verified_email"):
            with self.engine.connect() as connection:
                prior_b0 = connection.execute(sa.select(acquisition_census_b0_entry.c.result).where(
                    acquisition_census_b0_entry.c.status == "COMPLETE",
                )).scalars().all()
                prior_b1 = connection.execute(sa.select(acquisition_census_b1_entry.c.result).where(
                    acquisition_census_b1_entry.c.status == "COMPLETE",
                )).scalars().all()
            if any(isinstance(item, dict) and item.get("email") == email
                   for item in (*prior_b0, *prior_b1)):
                result.update(classification="DUPLICATE_EMAIL", decision="NO_SEND",
                              reason_codes=["DUPLICATE_EMAIL"], verified_email=False)
        return result

    def _complete_entry(self, entry: dict, *, at: dt.datetime) -> None:
        with self.engine.connect() as connection:
            candidate = connection.execute(sa.select(acquisition_census_candidate).where(
                acquisition_census_candidate.c.candidate_id == entry["candidate_id"],
            )).mappings().one()
        result = self._process(dict(candidate), entry["stratum"], at=at)
        with self.engine.begin() as connection:
            current = connection.execute(sa.select(acquisition_census_b1_entry).where(
                acquisition_census_b1_entry.c.plan_id == self.permit_id,
                acquisition_census_b1_entry.c.candidate_id == entry["candidate_id"],
            ).with_for_update()).mappings().one()
            if current["status"] == "COMPLETE":
                return
            if current["status"] != "PLANNED":
                raise CensusReviewRequired("B1 company checkpoint requires review")
            connection.execute(sa.update(acquisition_census_b1_entry).where(
                acquisition_census_b1_entry.c.plan_id == self.permit_id,
                acquisition_census_b1_entry.c.candidate_id == entry["candidate_id"],
            ).values(status="COMPLETE", result=result, completed_at=at))

    def _new_verified(self) -> int:
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(
                acquisition_census_b1_entry.c.candidate_id,
                acquisition_census_b1_entry.c.result,
            ).where(
                acquisition_census_b1_entry.c.candidate_id.in_(sa.select(
                    acquisition_census_candidate.c.candidate_id,
                ).where(acquisition_census_candidate.c.census_id == self.census_id)),
                acquisition_census_b1_entry.c.status == "COMPLETE",
            )).all()
        return sum(bool(isinstance(result, dict) and result.get("verified_email"))
                   for result in dict(rows).values())

    def run(self, *, at: dt.datetime, micro_only: bool = False,
            max_actions: int = 25) -> dict:
        if micro_only:
            raise ValueError("B1 uses one bounded frozen plan, not B0 micro mode")
        if not 1 <= max_actions <= 100:
            raise ValueError("B1 invocation action cap must be between 1 and 100")
        with self.engine.connect() as connection:
            permit = connection.execute(sa.select(acquisition_census_permit).where(
                acquisition_census_permit.c.permit_id == self.permit_id,
            )).mappings().one()
            baseline = connection.scalar(sa.select(sa.func.count()).select_from(
                acquisition_census_b0_entry).where(
                acquisition_census_b0_entry.c.status == "COMPLETE",
                acquisition_census_b0_entry.c.result["verified_email"].as_boolean().is_(True),
            )) or 0
        if permit["phase"] != "FRANCE_B1_READY_BASE" or permit["status"] != "ACTIVE":
            raise ValueError("active B1 permit required")
        if baseline != 80:
            raise ValueError("B1 baseline must be the 80 verified B0 addresses")
        self.store.bind_permit(
            permit_id=self.permit_id, phase="FRANCE_B1_READY_BASE",
            configuration_hash=self.configuration_hash, database_id=self.database_id,
        )
        self.store.start(self.census_id, self.limits, at=at,
                         phase="FRANCE_B1_READY_BASE", sample_plan_id=self.permit_id)
        self._credit_state(credits=0)
        with self.engine.connect() as connection:
            partition_rows = connection.execute(sa.select(acquisition_census_run.c.census_id).where(
                acquisition_census_run.c.census_id == self.census_id,
            )).all()
        if len(partition_rows) != 1:
            raise ValueError("B1 run identity is missing")
        actions = 0
        while baseline + self._new_verified() < 500 and actions < max_actions:
            now = dt.datetime.now(dt.UTC)
            with self.engine.connect() as connection:
                next_entry = connection.execute(sa.select(acquisition_census_b1_entry).where(
                    acquisition_census_b1_entry.c.plan_id == self.permit_id,
                    acquisition_census_b1_entry.c.status == "PLANNED",
                ).order_by(acquisition_census_b1_entry.c.selection_rank).limit(1)).mappings().one_or_none()
            if next_entry is not None:
                self._complete_entry(dict(next_entry), at=now)
                actions += 1
                continue
            progress = self.b1.summary(self.permit_id)
            if progress["companies_planned"] >= progress["caps"]["max_companies"]:
                break
            next_page = self.b1.next_planned_page(self.permit_id)
            if next_page is None:
                break
            from signals.persistence.schema import acquisition_census_partition

            with self.engine.connect() as connection:
                part = connection.execute(sa.select(acquisition_census_partition).where(
                    acquisition_census_partition.c.partition_id == next_page["partition_id"],
                )).mappings().one()
            profile = CensusPartition.from_row(dict(part))
            page_subject = f'{next_page["partition_id"]}:{next_page["page"]}'
            with self.engine.connect() as connection:
                prior_page = connection.execute(sa.select(acquisition_census_call.c.status).where(
                    acquisition_census_call.c.census_id == self.census_id,
                    acquisition_census_call.c.kind == "ORG_SEARCH",
                    acquisition_census_call.c.subject_hash ==
                    hashlib.sha256(page_subject.encode()).hexdigest(),
                    acquisition_census_call.c.attempt == 1,
                )).scalar_one_or_none()
            before = self._credit_state(credits=1) if prior_page != "COMPLETED" else None
            page, call_id = self.store.execute_call(
                self.census_id, kind="ORG_SEARCH",
                subject=page_subject,
                partition_id=next_page["partition_id"],
                credits=1, candidate_slots=profile.per_page, at=now,
                invoke=partial(self.organizations.search_page, profile,
                               page=next_page["page"], observed_at=now),
                encode=lambda value: value.model_dump(mode="json"),
                decode=SupplierSearchPage.model_validate,
            )
            if before is not None:
                after = self._credit_state(credits=0)
                delta = before.credit_balances["lead_credit"] - after.credit_balances["lead_credit"]
                if delta < 0 or delta > 1:
                    raise CensusReviewRequired("B1 page credit change is ambiguous")
            self.b1.record_page(self.census_id, self.permit_id, next_page["partition_id"],
                                page, call_id=call_id, at=now)
            self.b1.add_observed_google_companies(self.census_id, self.permit_id,
                                                   detector=self.detector, at=now)
            actions += 1
        return {**self.b1.summary(self.permit_id), "invocation_actions": actions}
