"""Permissioned, bounded Apollo contact discovery orchestration."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import (
    AcquisitionState,
    ActorType,
    EventType,
    OpportunityConcurrencyConflict,
)
from signals.acquisition.store import AcquisitionStore
from signals.contact_discovery.contracts import (
    ApolloContactProviderError,
    ContactAuthorizationInput,
    ContactDiscoveryEvaluationRequiresFreshAttempt,
    ContactDiscoveryNotActionable,
    ContactDiscoveryServiceResult,
    ContactObservation,
    ContactRunIdentityConflict,
    ContactRunStart,
    ContactRunStatus,
    DecisionMakerSearchProfile,
)
from signals.contact_discovery.identity import contact_ref_for
from signals.contact_discovery.profile import build_decision_maker_profile
from signals.contact_discovery.provider import ContactDiscoveryProvider
from signals.contact_discovery.ranking import classify_title, rank_candidates
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.policy.contracts import BudgetUsage, PolicyRequest
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_from_row
from signals.supplier_discovery.store import SupplierDiscoveryStore


def _canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ContactDiscoveryService:
    def __init__(
        self,
        engine: Engine,
        *,
        provider: ContactDiscoveryProvider,
        policy_gateway: PolicyGateway | None = None,
        contact_store: ContactDiscoveryStore | None = None,
        acquisition_store: AcquisitionStore | None = None,
        supplier_store: SupplierDiscoveryStore | None = None,
        profile_builder: Callable[..., DecisionMakerSearchProfile] = (
            build_decision_maker_profile
        ),
        profile_upgrade_requeue: tuple[str, str] | None = None,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._policy = policy_gateway or PolicyGateway(engine)
        self._contacts = contact_store or ContactDiscoveryStore(engine, clock=clock)
        self._acquisition = acquisition_store or AcquisitionStore(engine, clock=clock)
        self._suppliers = supplier_store or SupplierDiscoveryStore(engine, clock=clock)
        self._policy_store = PolicyStore(engine)
        self._profile_builder = profile_builder
        if profile_upgrade_requeue is not None:
            source_version, target_version = profile_upgrade_requeue
            if (
                not source_version
                or not target_version
                or source_version == target_version
                or len(source_version) > 64
                or len(target_version) > 64
            ):
                raise ValueError("contact profile upgrade requeue is invalid")
        self._profile_upgrade_requeue = profile_upgrade_requeue
        self._clock = clock

    def find(
        self,
        opportunity_id: str,
        authorization: ContactAuthorizationInput,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
        contact_discovery_run_id: str,
        correlation_id: str,
        authorize_profile_upgrade_requeue: Callable[[], None] | None = None,
    ) -> ContactDiscoveryServiceResult:
        existing_run = self._contacts.get_run_by_policy(authorization.evaluation_id)
        if existing_run is not None:
            self._require_existing_run_binding(
                existing_run, opportunity_id=opportunity_id, authorization=authorization
            )
            return ContactDiscoveryServiceResult(run=existing_run)
        with self._engine.connect() as connection:
            if (
                self._policy_store.evaluation_row(connection, authorization.evaluation_id)
                is not None
            ):
                raise ContactDiscoveryEvaluationRequiresFreshAttempt(authorization.evaluation_id)

        opportunity = self._acquisition.get_opportunity(opportunity_id)
        if not self._profile_upgrade_candidate(opportunity):
            self._require_actionable(opportunity)
        assert opportunity.supplier_ref is not None
        supplier = self._suppliers.get_supplier(opportunity.supplier_ref)
        profile = DecisionMakerSearchProfile.model_validate(
            self._profile_builder(
                acquisition_opportunity_id=opportunity_id,
                supplier_ref=supplier.supplier_ref,
                provider_organization_id=supplier.provider_organization_id,
            )
        )
        opportunity = self._requeue_profile_upgrade(
            opportunity,
            profile,
            authorize=authorize_profile_upgrade_requeue,
            correlation_id=correlation_id,
        )
        self._require_actionable(opportunity)
        arguments = _canonical_json(
            {"profile": profile.model_dump(mode="json"), "provider": "apollo"}
        )
        action_fingerprint = hashlib.sha256(arguments.encode()).hexdigest()
        request = self._policy_request(
            authorization,
            opportunity_id=opportunity_id,
            expected_version=opportunity.stream_version,
            arguments=arguments,
            action_fingerprint=action_fingerprint,
        )
        decision = self._policy.evaluate_and_record(
            request, evaluated_at=evaluated_at, budget_usage=budget_usage
        )
        if not decision.executable:
            return ContactDiscoveryServiceResult(decision=decision)

        ownership = self._contacts.start_run(
            ContactRunStart(
                contact_discovery_run_id=contact_discovery_run_id,
                acquisition_opportunity_id=opportunity_id,
                supplier_ref=supplier.supplier_ref,
                policy_evaluation_id=decision.evaluation_id,
                profile=profile,
                provider_request_fingerprint=action_fingerprint,
                expected_post_policy_version=opportunity.stream_version + 1,
                started_at=self._now(),
                correlation_id=correlation_id,
            )
        )
        if not ownership.owned:
            return ContactDiscoveryServiceResult(decision=decision, run=ownership.run)
        return self._execute(ownership.run, profile, decision)

    def resume_started(
        self,
        run_id: str,
        *,
        authorize_recovery: Callable[[], None],
    ) -> ContactDiscoveryServiceResult | None:
        """Replay one indeterminate Apollo contact run from durable Policy truth."""

        try:
            run = self._contacts.get_run(run_id)
        except sa.exc.NoResultFound:
            return None
        decision = self._durable_decision(run)
        if run.status is not ContactRunStatus.STARTED:
            return ContactDiscoveryServiceResult(decision=decision, run=run)
        authorize_recovery()
        ownership = self._contacts.claim_recovery(run_id)
        if not ownership.owned:
            return ContactDiscoveryServiceResult(
                decision=decision,
                run=ownership.run,
            )
        profile = DecisionMakerSearchProfile.model_validate(
            ownership.run.search_profile
        )
        return self._execute(ownership.run, profile, decision)

    def _durable_decision(self, run):
        profile = DecisionMakerSearchProfile.model_validate(run.search_profile)
        with self._engine.connect() as connection:
            row = self._policy_store.evaluation_row(
                connection, run.policy_evaluation_id
            )
        if row is None or not (
            row["acquisition_opportunity_id"] == run.acquisition_opportunity_id
            and row["command"] == "find_decision_makers"
            and row["target_ref"]
            == self._expected_target(run.acquisition_opportunity_id)
            and row["action_fingerprint"] == run.provider_request_fingerprint
            and run.search_profile_fingerprint == profile.profile_fingerprint
        ):
            raise ContactRunIdentityConflict(run.policy_evaluation_id)
        decision = decision_from_row(row)
        if not decision.executable:
            raise ContactRunIdentityConflict(run.policy_evaluation_id)
        return decision

    def _execute(self, run, profile, decision) -> ContactDiscoveryServiceResult:
        search_observed_at = self._now()
        try:
            page = self._provider.search_people(profile, observed_at=search_observed_at)
        except ApolloContactProviderError as exc:
            finished = self._finish_failed(run, exc)
            return ContactDiscoveryServiceResult(
                decision=decision, run=finished, provider_called=True
            )

        returned = len(page.candidates) + len(page.rejections)
        counters: dict[str, object] = {
            "people_search_requests": 1,
            "provider_total_entries": page.total_entries,
            "search_results_returned": returned,
            "search_results_truncated": page.total_entries > returned,
            "candidates_eligible": 0,
            "candidates_rejected": len(page.rejections),
            "enrichment_attempts": 0,
            "attempted_contact_refs": (),
        }
        if page.total_entries > 0 and not page.candidates and not page.rejections:
            error = ApolloContactProviderError(
                "malformed_response", detail="unexpected_empty_search_page"
            )
            finished = self._finish_failed(run, error, counters=counters)
            return ContactDiscoveryServiceResult(
                decision=decision, run=finished, provider_called=True
            )
        if page.total_entries > profile.search_too_broad_threshold:
            return self._complete_without_contact(
                run,
                decision,
                ContactRunStatus.CONTACT_SEARCH_TOO_BROAD,
                counters,
            )

        available = tuple(candidate for candidate in page.candidates if candidate.has_email)
        counters["candidates_rejected"] = int(counters["candidates_rejected"]) + (
            len(page.candidates) - len(available)
        )
        ranked = rank_candidates(available)
        counters["candidates_eligible"] = len(ranked)
        counters["candidates_rejected"] = int(counters["candidates_rejected"]) + (
            len(available) - len(ranked)
        )
        if not ranked:
            return self._complete_without_contact(
                run, decision, ContactRunStatus.NO_CANDIDATE, counters
            )

        attempted: list[str] = []
        for ranked_candidate in ranked[: profile.max_enrichment_attempts]:
            provider_person_id = ranked_candidate.candidate.provider_person_id
            attempted.append(contact_ref_for("apollo", provider_person_id, run.supplier_ref))
            counters["enrichment_attempts"] = int(counters["enrichment_attempts"]) + 1
            counters["attempted_contact_refs"] = tuple(attempted)
            try:
                enriched = self._provider.enrich_person(provider_person_id, observed_at=self._now())
            except ApolloContactProviderError as exc:
                finished = self._finish_failed(run, exc, counters=counters)
                return ContactDiscoveryServiceResult(
                    decision=decision, run=finished, provider_called=True
                )
            if enriched is None:
                counters["candidates_rejected"] = int(counters["candidates_rejected"]) + 1
                continue
            if (
                enriched.provider_person_id != provider_person_id
                or enriched.provider_organization_id != profile.provider_organization_id
            ):
                counters["candidates_rejected"] = int(counters["candidates_rejected"]) + 1
                continue
            classification = (
                classify_title(enriched.title)
                if enriched.title is not None
                else None
            )
            if enriched.title is not None and classification is None:
                counters["candidates_rejected"] = int(counters["candidates_rejected"]) + 1
                continue
            current_title = enriched.title or ranked_candidate.candidate.title
            normalized_title = (
                classification.normalized_title
                if classification is not None
                else ranked_candidate.normalized_title
            )
            role_tier = (
                classification.role_tier
                if classification is not None
                else ranked_candidate.role_tier
            )
            try:
                observation = ContactObservation(
                    supplier_ref=run.supplier_ref,
                    provider_person_id=enriched.provider_person_id,
                    provider_organization_id=enriched.provider_organization_id,
                    first_name=enriched.first_name,
                    last_name=enriched.last_name,
                    display_name=enriched.display_name,
                    title=current_title,
                    normalized_title=normalized_title,
                    role_profile_version=profile.profile_version,
                    role_tier=role_tier,
                    business_email=enriched.business_email,
                    provider_email_status=enriched.provider_email_status,
                    provider_observed_at=enriched.provider_observed_at,
                    email_observed_at=enriched.provider_observed_at,
                    source_fingerprint=enriched.source_fingerprint,
                )
            except ValidationError:
                counters["candidates_rejected"] = int(counters["candidates_rejected"]) + 1
                continue
            try:
                contact, finished = self._commit_success(run, observation, counters)
            except (OpportunityConcurrencyConflict, sa.exc.SQLAlchemyError, RuntimeError) as exc:
                finished = self._finish_persistence_failure(run, exc, counters)
                return ContactDiscoveryServiceResult(
                    decision=decision, run=finished, provider_called=True
                )
            return ContactDiscoveryServiceResult(
                decision=decision,
                run=finished,
                contact=contact,
                provider_called=True,
            )

        return self._complete_without_contact(
            run, decision, ContactRunStatus.NO_VERIFIED_CONTACT, counters
        )

    def _commit_success(self, run, observation, counters):
        with self._engine.begin() as connection:
            current = self._acquisition.get_opportunity_in_transaction(
                connection, run.acquisition_opportunity_id, for_update=True
            )
            self._require_post_policy(current, run)
            upserted = self._contacts.upsert_contact_in_transaction(connection, observation)
            persisted = upserted.contact
            if not (
                persisted.supplier_ref == current.supplier_ref
                and persisted.verification_state == "PROVIDER_VERIFIED"
                and persisted.verification_provider == "apollo"
                and persisted.provider_email_status == "verified"
                and persisted.business_email
            ):
                raise RuntimeError("persisted contact is not attachable")
            selected = self._acquisition.append_in_transaction(
                connection,
                current.acquisition_opportunity_id,
                event_type=EventType.CONTACT_SELECTED,
                expected_version=run.expected_post_policy_version,
                idempotency_key=f"contact_selected:{run.contact_discovery_run_id}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-contact-discovery",
                payload={
                    "contact_ref": persisted.contact_ref,
                    "supplier_ref": run.supplier_ref,
                },
                correlation_id=run.correlation_id,
            )
            transitioned = self._acquisition.append_in_transaction(
                connection,
                current.acquisition_opportunity_id,
                event_type=EventType.STATE_TRANSITIONED,
                expected_version=selected.projection.stream_version,
                idempotency_key=f"contact_enriching:{run.contact_discovery_run_id}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-contact-discovery",
                payload={"target_state": AcquisitionState.ENRICHING.value},
                correlation_id=run.correlation_id,
            )
            self._acquisition.append_in_transaction(
                connection,
                current.acquisition_opportunity_id,
                event_type=EventType.NEXT_ACTION_SET,
                expected_version=transitioned.projection.stream_version,
                idempotency_key=f"contact_next_action:{run.contact_discovery_run_id}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-contact-discovery",
                payload={"next_action": "enrich_company"},
                correlation_id=run.correlation_id,
            )
            finished = self._contacts.finish_run_in_transaction(
                connection,
                run.contact_discovery_run_id,
                status=ContactRunStatus.SUCCESS,
                completed_at=self._now(),
                selected_contact_ref=persisted.contact_ref,
                **counters,
            )
        return persisted, finished

    def _complete_without_contact(self, run, decision, status, counters):
        try:
            with self._engine.begin() as connection:
                current = self._acquisition.get_opportunity_in_transaction(
                    connection, run.acquisition_opportunity_id, for_update=True
                )
                self._require_post_policy(current, run)
                self._acquisition.append_in_transaction(
                    connection,
                    current.acquisition_opportunity_id,
                    event_type=EventType.NEXT_ACTION_SET,
                    expected_version=run.expected_post_policy_version,
                    idempotency_key=f"contact_human_review:{run.contact_discovery_run_id}",
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-contact-discovery",
                    reason_codes=(status.value.lower(),),
                    payload={"next_action": "request_human_review"},
                    correlation_id=run.correlation_id,
                )
                finished = self._contacts.finish_run_in_transaction(
                    connection,
                    run.contact_discovery_run_id,
                    status=status,
                    completed_at=self._now(),
                    **counters,
                )
        except (OpportunityConcurrencyConflict, sa.exc.SQLAlchemyError, RuntimeError) as exc:
            finished = self._finish_persistence_failure(run, exc, counters)
        return ContactDiscoveryServiceResult(decision=decision, run=finished, provider_called=True)

    def _finish_failed(self, run, error, *, counters=None):
        values = counters or {
            "people_search_requests": 1,
            "provider_total_entries": None,
            "search_results_returned": 0,
            "search_results_truncated": False,
            "candidates_eligible": 0,
            "candidates_rejected": 0,
            "enrichment_attempts": 0,
            "attempted_contact_refs": (),
        }
        return self._contacts.finish_run(
            run.contact_discovery_run_id,
            status=ContactRunStatus.FAILED,
            completed_at=self._now(),
            error_category=error.category,
            error_detail=error.detail,
            retry_after=error.retry_after,
            **values,
        )

    def _finish_persistence_failure(self, run, error, counters):
        category = (
            "opportunity_concurrency_conflict"
            if isinstance(error, (OpportunityConcurrencyConflict, ContactDiscoveryNotActionable))
            else "persistence_error"
        )
        return self._contacts.finish_run(
            run.contact_discovery_run_id,
            status=ContactRunStatus.FAILED,
            completed_at=self._now(),
            error_category=category,
            error_detail=type(error).__name__,
            **counters,
        )

    @staticmethod
    def _require_actionable(opportunity) -> None:
        if not (
            opportunity.state is AcquisitionState.DISCOVERED
            and opportunity.supplier_ref is not None
            and opportunity.contact_ref is None
            and opportunity.next_action == "find_decision_makers"
        ):
            raise ContactDiscoveryNotActionable(opportunity.acquisition_opportunity_id)

    def _profile_upgrade_candidate(self, opportunity) -> bool:
        return bool(
            self._profile_upgrade_requeue is not None
            and opportunity.state is AcquisitionState.DISCOVERED
            and opportunity.supplier_ref is not None
            and opportunity.contact_ref is None
            and opportunity.next_action == "request_human_review"
        )

    def _requeue_profile_upgrade(
        self,
        opportunity,
        profile,
        *,
        authorize,
        correlation_id: str,
    ):
        if not self._profile_upgrade_candidate(opportunity):
            return opportunity
        assert self._profile_upgrade_requeue is not None
        source_version, target_version = self._profile_upgrade_requeue
        if profile.profile_version != target_version or authorize is None:
            return opportunity
        authorize()
        with self._engine.begin() as connection:
            current = self._acquisition.get_opportunity_in_transaction(
                connection,
                opportunity.acquisition_opportunity_id,
                for_update=True,
            )
            if not self._profile_upgrade_candidate(current):
                return current
            latest_run = self._contacts.get_latest_run_for_opportunity_in_transaction(
                connection,
                current.acquisition_opportunity_id,
            )
            try:
                previous_profile = DecisionMakerSearchProfile.model_validate(
                    latest_run.search_profile if latest_run is not None else {}
                )
            except ValidationError:
                return current
            previous_profile_material = previous_profile.model_dump(mode="json")
            previous_profile_material.pop("profile_fingerprint")
            if latest_run is None or not (
                latest_run.status is ContactRunStatus.CONTACT_SEARCH_TOO_BROAD
                and latest_run.completed_at is not None
                and latest_run.selected_contact_ref is None
                and latest_run.supplier_ref == current.supplier_ref == profile.supplier_ref
                and latest_run.search_profile_version == source_version
                and previous_profile.profile_version == source_version
                and previous_profile.acquisition_opportunity_id
                == current.acquisition_opportunity_id
                and previous_profile.supplier_ref == current.supplier_ref
                and previous_profile.provider_organization_id
                == profile.provider_organization_id
                and latest_run.search_profile_fingerprint
                == previous_profile.profile_fingerprint
                == _fingerprint(previous_profile_material)
            ):
                return current
            last_event = self._acquisition.get_last_event_in_transaction(
                connection,
                current.acquisition_opportunity_id,
            )
            if last_event.event_id != current.last_event_id:
                raise OpportunityConcurrencyConflict(
                    current.acquisition_opportunity_id
                )
            if not (
                last_event.event_type is EventType.NEXT_ACTION_SET
                and last_event.idempotency_key
                == f"contact_human_review:{latest_run.contact_discovery_run_id}"
                and last_event.actor_type is ActorType.SYSTEM
                and last_event.actor_ref == "kivou-contact-discovery"
                and last_event.correlation_id == latest_run.correlation_id
                and last_event.reason_codes
                == (ContactRunStatus.CONTACT_SEARCH_TOO_BROAD.value.lower(),)
                and last_event.payload == {"next_action": "request_human_review"}
            ):
                return current
            requeue_fingerprint = _fingerprint(
                {
                    "kind": "contact-search-profile-upgrade-requeue-v1",
                    "opportunity_id": current.acquisition_opportunity_id,
                    "previous_run_id": latest_run.contact_discovery_run_id,
                    "source_profile_version": source_version,
                    "target_profile_fingerprint": profile.profile_fingerprint,
                }
            )
            mutation = self._acquisition.append_in_transaction(
                connection,
                current.acquisition_opportunity_id,
                event_type=EventType.NEXT_ACTION_SET,
                expected_version=current.stream_version,
                idempotency_key=f"contact_profile_requeue:{requeue_fingerprint}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-contact-discovery",
                reason_codes=("contact_search_profile_upgraded",),
                evidence_refs=(latest_run.contact_discovery_run_id,),
                payload={"next_action": "find_decision_makers"},
                correlation_id=correlation_id,
                causation_id=last_event.event_id,
            )
            if mutation.projection.next_action == "find_decision_makers":
                return mutation.projection
            raise OpportunityConcurrencyConflict(
                current.acquisition_opportunity_id
            )

    @classmethod
    def _require_post_policy(cls, opportunity, run) -> None:
        cls._require_actionable(opportunity)
        if (
            opportunity.stream_version != run.expected_post_policy_version
            or opportunity.supplier_ref != run.supplier_ref
        ):
            raise OpportunityConcurrencyConflict(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _expected_target(opportunity_id: str) -> str:
        return f"acquisition-opportunity:{opportunity_id}"

    def _require_existing_run_binding(
        self, run, *, opportunity_id: str, authorization: ContactAuthorizationInput
    ) -> None:
        with self._engine.connect() as connection:
            evaluation = self._policy_store.evaluation_row(connection, authorization.evaluation_id)
        if evaluation is None or not (
            run.acquisition_opportunity_id == opportunity_id
            and evaluation["acquisition_opportunity_id"] == opportunity_id
            and evaluation["request_id"] == authorization.request_id
            and evaluation["command"] == "find_decision_makers"
            and evaluation["target_ref"] == self._expected_target(opportunity_id)
            and evaluation["action_fingerprint"] == run.provider_request_fingerprint
        ):
            raise ContactRunIdentityConflict(authorization.evaluation_id)

    @staticmethod
    def _policy_request(
        authorization,
        *,
        opportunity_id,
        expected_version,
        arguments,
        action_fingerprint,
    ) -> PolicyRequest:
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="find_decision_makers",
            target_ref=ContactDiscoveryService._expected_target(opportunity_id),
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            qa_signal_ref=authorization.qa_signal_ref,
            canonical_arguments=arguments,
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

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("contact discovery clock must be timezone-aware")
        return value
