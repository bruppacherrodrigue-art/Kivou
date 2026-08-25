"""One-shot permissioned composition for company supplier discovery."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import AcquisitionError, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.policy.contracts import BudgetUsage, PolicyRequest
from signals.policy.gateway import PolicyGateway
from signals.supplier_discovery.contracts import (
    ApolloOrganizationCandidate,
    ApolloProviderError,
    DiscoveryAuthorizationInput,
    DiscoveryRunStart,
    DiscoveryRunStatus,
    DiscoveryServiceResult,
    SupplierSearchNotActionable,
    SupplierSearchProfile,
    SupplierTargetingConfig,
)
from signals.supplier_discovery.identity import acquisition_identity_for
from signals.supplier_discovery.provider import SupplierDiscoveryProvider
from signals.supplier_discovery.seed import (
    build_profile_from_seed,
    resolve_acquisition_seed,
)
from signals.supplier_discovery.store import SupplierDiscoveryStore


def _canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class SupplierDiscoveryService:
    def __init__(
        self,
        engine: Engine,
        *,
        provider: SupplierDiscoveryProvider,
        policy_gateway: PolicyGateway | None = None,
        supplier_store: SupplierDiscoveryStore | None = None,
        acquisition_store: AcquisitionStore | None = None,
        profile_resolver: (
            Callable[[str, SupplierTargetingConfig], SupplierSearchProfile] | None
        ) = None,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._policy = policy_gateway or PolicyGateway(engine)
        self._suppliers = supplier_store or SupplierDiscoveryStore(engine)
        self._acquisition = acquisition_store or AcquisitionStore(engine)
        self._profile_resolver = profile_resolver or self._resolve_persisted_profile
        self._clock = clock

    def discover(
        self,
        opportunity_key: str,
        targeting: SupplierTargetingConfig,
        authorization: DiscoveryAuthorizationInput,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
        discovery_run_id: str,
        correlation_id: str,
    ) -> DiscoveryServiceResult:
        profile = self._profile_resolver(opportunity_key, targeting)
        if profile.signal_ref != f"procurement-opportunity:{opportunity_key}":
            raise ValueError("resolved supplier profile does not match opportunity key")
        if not profile.need_categories or not profile.keyword_tags:
            raise SupplierSearchNotActionable
        profile_payload = profile.model_dump(mode="json")
        canonical_arguments = _canonical_json(
            {"profile": profile_payload, "provider": "apollo"}
        )
        action_fingerprint = hashlib.sha256(canonical_arguments.encode()).hexdigest()
        request = PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="discover_suppliers",
            target_ref=profile.signal_ref,
            acquisition_opportunity_id=None,
            expected_opportunity_version=None,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            qa_signal_ref=authorization.qa_signal_ref,
            canonical_arguments=canonical_arguments,
            action_fingerprint=action_fingerprint,
            scope=authorization.scope,
            proposed_cost=authorization.proposed_cost,
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=authorization.reason_codes,
            evidence_refs=authorization.evidence_refs,
            evidence=authorization.evidence,
            compliance=authorization.compliance,
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
            approval_grants=authorization.approval_grants,
            supervisor_plan_id=authorization.supervisor_plan_id,
            supervisor_action_index=authorization.supervisor_action_index,
            supervisor_version=authorization.supervisor_version,
            skill_version=authorization.skill_version,
        )
        decision = self._policy.evaluate_and_record(
            request,
            evaluated_at=evaluated_at,
            budget_usage=budget_usage,
        )
        if not decision.executable:
            return DiscoveryServiceResult(decision=decision)

        ownership = self._suppliers.start_run(
            DiscoveryRunStart(
                discovery_run_id=discovery_run_id,
                policy_evaluation_id=decision.evaluation_id,
                profile=profile,
                provider_request_fingerprint=action_fingerprint,
                started_at=self._now(),
                correlation_id=correlation_id,
            )
        )
        if not ownership.owned:
            return DiscoveryServiceResult(decision=decision, run=ownership.run)

        counters: dict[str, object] = {
            "pages_requested": 0,
            "provider_total_entries": None,
            "partial_results_only": None,
            "records_returned": 0,
            "records_accepted": 0,
            "records_rejected": 0,
            "rejection_reason_counts": {},
            "duplicates": 0,
            "opportunities_created": 0,
        }
        opportunity_ids: list[str] = []
        expected_total_entries: int | None = None
        expected_total_pages: int | None = None
        expected_partial_results = False

        for page_number in range(1, profile.max_pages + 1):
            counters["pages_requested"] = int(counters["pages_requested"]) + 1
            provider_observed_at = self._now()
            try:
                page = self._provider.search_page(
                    profile, page=page_number, observed_at=provider_observed_at
                )
            except ApolloProviderError as exc:
                run = self._finish_failure(
                    discovery_run_id,
                    completed_at=self._now(),
                    counters=counters,
                    error=exc,
                )
                return DiscoveryServiceResult(
                    decision=decision,
                    run=run,
                    opportunity_ids=tuple(dict.fromkeys(opportunity_ids)),
                    provider_called=True,
                )

            current_partial_results = page.partial_results_only is True
            if page_number == 1:
                expected_total_entries = page.total_entries
                expected_total_pages = page.total_pages
                expected_partial_results = current_partial_results
            elif (
                page.total_entries != expected_total_entries
                or page.total_pages != expected_total_pages
                or current_partial_results != expected_partial_results
            ):
                run = self._suppliers.finish_run(
                    discovery_run_id,
                    status=(
                        DiscoveryRunStatus.PARTIAL
                        if int(counters["records_accepted"])
                        else DiscoveryRunStatus.FAILED
                    ),
                    completed_at=self._now(),
                    error_category="malformed_response",
                    error_detail="pagination_changed_during_run",
                    **counters,
                )
                return DiscoveryServiceResult(
                    decision=decision,
                    run=run,
                    opportunity_ids=tuple(dict.fromkeys(opportunity_ids)),
                    provider_called=True,
                )

            counters["provider_total_entries"] = page.total_entries
            counters["partial_results_only"] = page.partial_results_only
            counters["records_returned"] = int(counters["records_returned"]) + len(
                page.candidates
            ) + len(page.rejections)
            counters["records_rejected"] = int(counters["records_rejected"]) + len(
                page.rejections
            )
            reason_counts = counters["rejection_reason_counts"]
            assert isinstance(reason_counts, dict)
            for rejection in page.rejections:
                reason_counts[rejection.reason_code] = (
                    int(reason_counts.get(rejection.reason_code, 0)) + 1
                )

            if (
                page.total_entries > profile.search_too_broad_threshold
                or page.partial_results_only is True
            ):
                run = self._suppliers.finish_run(
                    discovery_run_id,
                    status=DiscoveryRunStatus.SEARCH_TOO_BROAD,
                    completed_at=self._now(),
                    error_category=(
                        "provider_limit"
                        if page.partial_results_only is True
                        else "search_too_broad"
                    ),
                    **counters,
                )
                return DiscoveryServiceResult(
                    decision=decision, run=run, provider_called=True
                )

            if (
                page.total_entries > 0
                and not page.candidates
                and not page.rejections
            ):
                run = self._suppliers.finish_run(
                    discovery_run_id,
                    status=(
                        DiscoveryRunStatus.PARTIAL
                        if int(counters["records_accepted"])
                        else DiscoveryRunStatus.FAILED
                    ),
                    completed_at=self._now(),
                    error_category="malformed_response",
                    error_detail="unexpected_empty_page",
                    **counters,
                )
                return DiscoveryServiceResult(
                    decision=decision,
                    run=run,
                    opportunity_ids=tuple(dict.fromkeys(opportunity_ids)),
                    provider_called=True,
                )

            for candidate in page.candidates:
                if int(counters["records_accepted"]) >= profile.candidate_cap:
                    break
                if candidate.primary_domain in profile.excluded_domains:
                    counters["records_rejected"] = (
                        int(counters["records_rejected"]) + 1
                    )
                    reason_counts["excluded_supplier_domain"] = (
                        int(reason_counts.get("excluded_supplier_domain", 0)) + 1
                    )
                    continue
                try:
                    opportunity_id, supplier_created, opportunity_created = (
                        self._persist_candidate(profile, candidate)
                    )
                except (AcquisitionError, sa.exc.SQLAlchemyError, ValueError) as exc:
                    run = self._suppliers.finish_run(
                        discovery_run_id,
                        status=(
                            DiscoveryRunStatus.PARTIAL
                            if int(counters["records_accepted"])
                            else DiscoveryRunStatus.FAILED
                        ),
                        completed_at=self._now(),
                        error_category="persistence_error",
                        error_detail=type(exc).__name__,
                        **counters,
                    )
                    return DiscoveryServiceResult(
                        decision=decision,
                        run=run,
                        opportunity_ids=tuple(dict.fromkeys(opportunity_ids)),
                        provider_called=True,
                    )
                counters["records_accepted"] = int(counters["records_accepted"]) + 1
                counters["duplicates"] = int(counters["duplicates"]) + int(
                    not supplier_created
                )
                counters["opportunities_created"] = int(
                    counters["opportunities_created"]
                ) + int(opportunity_created)
                opportunity_ids.append(opportunity_id)
            if (
                int(counters["records_accepted"]) >= profile.candidate_cap
                or page_number >= page.total_pages
            ):
                break

        run = self._suppliers.finish_run(
            discovery_run_id,
            status=DiscoveryRunStatus.SUCCESS,
            completed_at=self._now(),
            **counters,
        )
        return DiscoveryServiceResult(
            decision=decision,
            run=run,
            opportunity_ids=tuple(dict.fromkeys(opportunity_ids)),
            provider_called=True,
        )

    def _resolve_persisted_profile(
        self, opportunity_key: str, targeting: SupplierTargetingConfig
    ) -> SupplierSearchProfile:
        seed = resolve_acquisition_seed(self._engine, opportunity_key)
        return build_profile_from_seed(seed, targeting=targeting)

    def _finish_failure(
        self,
        discovery_run_id: str,
        *,
        completed_at: dt.datetime,
        counters: dict[str, object],
        error: ApolloProviderError,
    ):
        return self._suppliers.finish_run(
            discovery_run_id,
            status=(
                DiscoveryRunStatus.PARTIAL
                if int(counters["records_accepted"])
                else DiscoveryRunStatus.FAILED
            ),
            completed_at=completed_at,
            error_category=error.category,
            error_detail=error.detail,
            retry_after=error.retry_after,
            **counters,
        )

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("supplier discovery clock must be timezone-aware")
        return value

    def _persist_candidate(
        self,
        profile: SupplierSearchProfile,
        candidate: ApolloOrganizationCandidate,
    ) -> tuple[str, bool, bool]:
        with self._engine.begin() as connection:
            supplier = self._suppliers.upsert_supplier_in_transaction(connection, candidate)
            identity_key = acquisition_identity_for(
                profile.signal_ref, supplier.supplier.supplier_ref
            )
            identity_fingerprint = _fingerprint(
                {
                    "signal_ref": profile.signal_ref,
                    "supplier_ref": supplier.supplier.supplier_ref,
                }
            )
            created = self._acquisition.create_opportunity_in_transaction(
                connection,
                identity_key=identity_key,
                signal_ref=profile.signal_ref,
                supplier_ref=supplier.supplier.supplier_ref,
                idempotency_key=f"supplier_create:{identity_fingerprint}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-supplier-discovery",
                reason_codes=("supplier_candidate_discovered",),
                evidence_refs=(profile.signal_ref,),
            )
            if not created.replayed:
                initialized = self._acquisition.append_in_transaction(
                    connection,
                    created.projection.acquisition_opportunity_id,
                    event_type=EventType.NEXT_ACTION_SET,
                    expected_version=1,
                    idempotency_key=f"supplier_next:{identity_fingerprint}",
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-supplier-discovery",
                    payload={"next_action": "find_decision_makers"},
                )
                opportunity_id = initialized.projection.acquisition_opportunity_id
            else:
                opportunity_id = created.projection.acquisition_opportunity_id
            return opportunity_id, supplier.created, not created.replayed
