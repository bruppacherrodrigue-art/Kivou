"""Authoritative, offline orchestration for deterministic personalization."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from signals.acquisition.contracts import AcquisitionState, ActorType, Decision, EventType
from signals.acquisition.store import AcquisitionStore
from signals.company_research.contracts import PREBUILD_VERSION, SIZE_BAND_VERSION
from signals.company_research.store import CompanyResearchStore
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.decision_engine.contracts import DecisionAuthorizationInput
from signals.decision_engine.input import (
    build_acquisition_decision_input,
    build_public_decision_context,
)
from signals.decision_engine.policy import DECISION_POLICY_V1, semantic_fingerprint
from signals.decision_engine.service import _legacy_budget_usage_candidates, _publication_date
from signals.decision_engine.store import DecisionEvaluationStore
from signals.needs import NeedGraphEngine
from signals.persistence.schema import acquisition_decision_evaluation, acquisition_event
from signals.personalization.catalog import (
    CATALOG_VERSION,
    LANGUAGE_POLICY_VERSION,
    SUPPORTED_LANGUAGES,
    TEMPLATE_VERSION,
    CatalogMessage,
    PersonalizationLanguageUnsupported,
    render_catalog_message,
)
from signals.personalization.contracts import (
    ClaimMapEntry,
    PersonalizationArtifactWrite,
    PersonalizationDisposition,
    PersonalizationInput,
)
from signals.personalization.grounding import (
    PersonalizationDecisionNoLongerEligible,
    PersonalizationGroundingInsufficient,
    require_current_send,
)
from signals.personalization.store import (
    PersonalizationArtifactIdempotencyConflict,
    PersonalizationStore,
    personalization_artifact_id,
)
from signals.personalization.validator import (
    PersonalizationValidationError,
    require_safe_awardee,
    safe_first_name,
    validate_catalog_message,
)
from signals.policy.contracts import BudgetUsage, EvidenceReadiness, PolicyRequest
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_from_row
from signals.recency import assess_recency
from signals.recency.claim import claim_for
from signals.supplier_discovery.seed import (
    AcquisitionSeedNotFound,
    resolve_public_acquisition_context_in_transaction,
)
from signals.supplier_discovery.store import SupplierDiscoveryStore
from signals.understanding import ContractUnderstandingEngine

_PERSONALIZATION_EVIDENCE = (
    "ACQUISITION_DECISION",
    "PUBLIC_EVIDENCE",
    "VERIFIED_CONTACT",
    "ACQUISITION_PROSPECT_PREBUILD",
    "PERSONALIZATION_INPUT",
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class PersonalizationNotActionable(ValueError):
    """The opportunity is not the exact SEND/prepare_campaign input."""


class PersonalizationBindingConflict(ValueError):
    """A current durable supplier/contact/profile binding is unsafe."""


class PersonalizationEvaluationRequiresFreshAttempt(RuntimeError):
    """A policy audit exists but its personalization artifact does not."""


class PersonalizationInputChanged(RuntimeError):
    """The final revalidation found a material change after policy audit."""


def _canonical(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _action_fingerprint(
    *, opportunity_id: str, supplier_ref: str, contact_ref: str, proposal_fingerprint: str
) -> str:
    return semantic_fingerprint(
        {
            "kind": "personalization-policy-action-v1",
            "command": "prepare_campaign",
            "acquisition_opportunity_id": opportunity_id,
            "supplier_ref": supplier_ref,
            "contact_ref": contact_ref,
            "proposal_fingerprint": proposal_fingerprint,
        }
    )


class PersonalizationService:
    """Render a one-language artifact only after fresh local eligibility proof."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], dt.datetime] = _utc_now,
        policy_gateway: PolicyGateway | None = None,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._acquisition = AcquisitionStore(engine)
        self._companies = CompanyResearchStore(engine)
        self._contacts = ContactDiscoveryStore(engine)
        self._suppliers = SupplierDiscoveryStore(engine)
        self._decisions = DecisionEvaluationStore(engine)
        self._artifacts = PersonalizationStore(engine)
        self._policy_store = PolicyStore(engine)
        self._policy = policy_gateway or PolicyGateway(engine, acquisition_store=self._acquisition)

    def personalize(
        self,
        opportunity_id: str,
        language: str,
        authorization: DecisionAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ):
        if language not in SUPPORTED_LANGUAGES:
            raise PersonalizationLanguageUnsupported(language)
        # Idempotency is intentionally before the clock: a completed result is history.
        existing = self._artifacts.get_by_policy(authorization.evaluation_id)
        if existing is not None:
            self._require_existing(existing, opportunity_id, language, authorization)
            return existing
        with self._engine.connect() as connection:
            if self._policy_store.evaluation_row(connection, authorization.evaluation_id):
                raise PersonalizationEvaluationRequiresFreshAttempt(authorization.evaluation_id)

        captured_at = self._now()
        as_of_date = captured_at.date()
        values = self._build_values(self._load(opportunity_id), language, as_of_date)
        request = self._request(
            authorization, values, expected_version=values["opportunity"].stream_version
        )
        decision = self._policy.evaluate_and_record(
            request, evaluated_at=captured_at, budget_usage=budget_usage
        )
        expected = values["opportunity"].stream_version + 1
        if not decision.executable:
            return self._commit_blocked(values, decision, captured_at)
        return self._commit_ready(
            opportunity_id,
            language,
            values,
            decision,
            expected,
            as_of_date,
            captured_at,
            authorization,
        )

    def _load(self, opportunity_id: str):
        with self._engine.connect() as connection:
            current = self._acquisition.get_opportunity_in_transaction(
                connection, opportunity_id, for_update=False
            )
            return self._load_in_transaction(connection, opportunity_id, current=current)

    def _load_in_transaction(self, connection: Connection, opportunity_id: str, *, current):
        self._require_actionable(current)
        assert current.supplier_ref is not None
        assert current.contact_ref is not None
        decision_row = (
            connection.execute(
                sa.select(acquisition_decision_evaluation)
                .where(
                    acquisition_decision_evaluation.c.acquisition_opportunity_id
                    == opportunity_id,
                    acquisition_decision_evaluation.c.disposition == "RECORDED",
                    acquisition_decision_evaluation.c.proposed_decision == "SEND",
                )
                .order_by(acquisition_decision_evaluation.c.created_at.desc())
            )
            .mappings()
            .first()
        )
        if decision_row is None:
            raise PersonalizationNotActionable(opportunity_id)
        try:
            profile = self._companies.get_profile_in_transaction(connection, opportunity_id)
            supplier = self._suppliers.get_supplier_in_transaction(
                connection, current.supplier_ref
            )
            contact = self._contacts.get_contact_in_transaction(connection, current.contact_ref)
        except sa.exc.NoResultFound as error:
            raise PersonalizationBindingConflict(opportunity_id) from error
        self._require_bindings(current, supplier, contact, profile)
        try:
            public = resolve_public_acquisition_context_in_transaction(
                connection, self._key(current.signal_ref)
            )
        except AcquisitionSeedNotFound as error:
            raise PersonalizationBindingConflict(current.signal_ref) from error
        return current, supplier, contact, profile, public, decision_row

    @staticmethod
    def _require_actionable(opportunity) -> None:
        if not (
            opportunity.state is AcquisitionState.SEND
            and opportunity.decision is Decision.SEND
            and opportunity.next_action == "prepare_campaign"
            and opportunity.supplier_ref
            and opportunity.contact_ref
        ):
            raise PersonalizationNotActionable(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _require_bindings(opportunity, supplier, contact, profile) -> None:
        if profile.prebuild_version != PREBUILD_VERSION or profile.size_band_version != SIZE_BAND_VERSION:
            raise PersonalizationBindingConflict(opportunity.acquisition_opportunity_id)
        if not (
            profile.acquisition_opportunity_id == opportunity.acquisition_opportunity_id
            and profile.signal_ref == opportunity.signal_ref
            and profile.supplier_ref == opportunity.supplier_ref == supplier.supplier_ref
            and profile.contact_ref == opportunity.contact_ref == contact.contact_ref
            and contact.supplier_ref == supplier.supplier_ref
            and contact.verification_state == "PROVIDER_VERIFIED"
            and contact.verification_provider == "apollo"
            and contact.provider_email_status == "verified"
        ):
            raise PersonalizationBindingConflict(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _key(signal_ref: str) -> str:
        prefix = "procurement-opportunity:"
        if not signal_ref.startswith(prefix) or not signal_ref[len(prefix) :]:
            raise PersonalizationBindingConflict(signal_ref)
        return signal_ref[len(prefix) :]

    @staticmethod
    def _decision_input(opportunity, supplier, contact, profile, public, as_of_date):
        public_context = build_public_decision_context(
            opportunity_key=public.opportunity_key,
            representative_award_key=public.representative_award_key,
            source_event_key=public.event.ref().key(),
            award_date=public.award.award_date,
            contract_notification_date=public.award.contract_notification_date,
            publication_date=_publication_date(public.event.published_at),
            public_evidence_refs=public.public_evidence_refs,
        )
        return build_acquisition_decision_input(
            acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
            signal_ref=opportunity.signal_ref,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact.contact_ref,
            company_prebuild_version=profile.prebuild_version,
            company_prebuild_fingerprint=profile.prebuild_fingerprint,
            size_band_version=profile.size_band_version,
            profile_supplier_identity_status=profile.supplier_identity_status,
            current_supplier_identity_status=supplier.identity_status,
            profile_contact_role_profile_version=profile.contact_role_profile_version,
            profile_contact_role_tier=profile.contact_role_tier,
            current_contact_role_profile_version=contact.role_profile_version,
            current_contact_role_tier=contact.role_tier,
            current_contact_verification_state=contact.verification_state,
            current_contact_verification_provider=contact.verification_provider,
            current_contact_provider_email_status=contact.provider_email_status,
            research_completeness=profile.research_completeness,
            research_gaps=tuple(gap.value for gap in profile.research_gaps),
            size_band=profile.size_band,
            public_context=public_context,
            as_of_date=as_of_date,
            policy_config=DECISION_POLICY_V1,
        )

    def _build_values(self, loaded, language: str, as_of_date: dt.date) -> dict[str, object]:
        opportunity, supplier, contact, profile, public, decision_row = loaded
        decision_input = self._decision_input(
            opportunity, supplier, contact, profile, public, as_of_date
        )
        # The frozen decision evaluator owns 60/3650-day, timing, and identity semantics.
        require_current_send(decision_input)
        understanding = ContractUnderstandingEngine().understand(public.award, public.event)
        needs = NeedGraphEngine().derive(understanding)
        if not needs.needs:
            raise PersonalizationGroundingInsufficient(opportunity.acquisition_opportunity_id)
        need = needs.needs[0]
        awardees = public.award.awardee_organizations()
        if not awardees or not awardees[0].legal_name.strip():
            raise PersonalizationGroundingInsufficient(opportunity.acquisition_opportunity_id)
        awardee = require_safe_awardee(awardees[0].legal_name)
        recency = assess_recency(
            award_date=public.award.award_date,
            contract_notification_date=public.award.contract_notification_date,
            publication_date=_publication_date(public.event.published_at),
            as_of=as_of_date,
        )
        first_name = safe_first_name(contact.first_name)
        message = render_catalog_message(
            language=language,
            awardee=awardee,
            public_event_sentence=claim_for(recency, company=awardee, lang=language),
            need_category=need.category,
            first_name=first_name,
        )
        validate_catalog_message(message)
        selected_need_fingerprint = semantic_fingerprint(
            {
                "kind": "personalization-selected-need-v1",
                "need_engine_version": needs.engine_version,
                "category": need.category,
                "evidence_refs": [item.model_dump(mode="json") for item in need.evidence_refs],
            }
        )
        # This domain-separated value protects the rendered first name without storing it.
        contact_personalization_fingerprint = semantic_fingerprint(
            {
                "kind": "contact-personalization-v1",
                "contact_ref": contact.contact_ref,
                "contact_source_fingerprint": contact.source_fingerprint,
                "safe_first_name": first_name,
            }
        )
        input_values = {
            "acquisition_opportunity_id": opportunity.acquisition_opportunity_id,
            "signal_ref": opportunity.signal_ref,
            "supplier_ref": supplier.supplier_ref,
            "contact_ref": contact.contact_ref,
            "decision_evaluation_id": decision_row["decision_evaluation_id"],
            "historical_decision_input_fingerprint": decision_row["decision_input_fingerprint"],
            "representative_award_key": public.representative_award_key,
            "source_event_key": public.event.ref().key(),
            "public_evidence_refs": public.public_evidence_refs,
            "recency_basis": decision_input.recency_basis.value,
            "recency_date": decision_input.recency_date,
            "decision_policy_config_fingerprint": decision_input.decision_policy_config_fingerprint,
            "company_prebuild_fingerprint": profile.prebuild_fingerprint,
            "public_context_fingerprint": decision_input.public_context_fingerprint,
            "eligibility_fingerprint": decision_input.decision_input_fingerprint,
            "as_of_date": as_of_date,
            "need_engine_version": needs.engine_version,
            "selected_need_fingerprint": selected_need_fingerprint,
            "selected_need_category": need.category,
            "selected_need_confidence": need.confidence,
            "language": language,
            "salutation_mode": "FIRST_NAME" if first_name else "NEUTRAL",
            "contact_personalization_fingerprint": contact_personalization_fingerprint,
            "template_version": TEMPLATE_VERSION,
            "catalog_version": CATALOG_VERSION,
            "language_policy_version": LANGUAGE_POLICY_VERSION,
        }
        input_fingerprint = semantic_fingerprint(
            {"kind": "personalization-input-v1", **input_values}
        )
        personalization_input = PersonalizationInput(
            **input_values, personalization_input_fingerprint=input_fingerprint
        )
        input_snapshot = personalization_input.model_dump(mode="json")
        claim_map = (
            ClaimMapEntry(
                claim_id="PUBLIC_EVENT",
                kind="PUBLIC_FACT",
                evidence_refs=public.public_evidence_refs,
            ),
            ClaimMapEntry(
                claim_id="PLAUSIBLE_NEED",
                kind="KIVOU_INFERENCE",
                evidence_refs=(
                    f"need-graph:{needs.engine_version}:{selected_need_fingerprint}",
                    *public.public_evidence_refs,
                ),
            ),
            ClaimMapEntry(claim_id="KIVOU_CTA", kind="KIVOU_PRODUCT_COPY"),
        )
        proposal_fingerprint = semantic_fingerprint(
            {
                "kind": "personalization-proposal-v1",
                "input_fingerprint": input_fingerprint,
                "language": language,
                "message": message.__dict__,
                "claim_map": [claim.model_dump(mode="json") for claim in claim_map],
                "template_version": TEMPLATE_VERSION,
                "catalog_version": CATALOG_VERSION,
            }
        )
        return {
            "opportunity": opportunity,
            "supplier": supplier,
            "contact": contact,
            "profile": profile,
            "public": public,
            "decision_row": decision_row,
            "decision_input": decision_input,
            "message": message,
            "needs": needs,
            "input_snapshot": input_snapshot,
            "personalization_input": personalization_input,
            "input_fingerprint": input_fingerprint,
            "selected_need_fingerprint": selected_need_fingerprint,
            "claim_map": claim_map,
            "proposal_fingerprint": proposal_fingerprint,
            "action_fingerprint": _action_fingerprint(
                opportunity_id=opportunity.acquisition_opportunity_id,
                supplier_ref=supplier.supplier_ref,
                contact_ref=contact.contact_ref,
                proposal_fingerprint=proposal_fingerprint,
            ),
        }

    @staticmethod
    def _internal_evidence(authorization: DecisionAuthorizationInput) -> EvidenceReadiness:
        """The caller may attest readiness, but cannot select the claim vocabulary."""
        evidence = authorization.evidence
        return EvidenceReadiness(
            status=evidence.status,
            claims=_PERSONALIZATION_EVIDENCE,
            assessment_version=evidence.assessment_version,
            observed_at=evidence.observed_at,
            valid_until=evidence.valid_until,
        )

    def _request(self, authorization, values, *, expected_version: int) -> PolicyRequest:
        opportunity = values["opportunity"]
        supplier = values["supplier"]
        contact = values["contact"]
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="prepare_campaign",
            target_ref=f"acquisition-opportunity:{opportunity.acquisition_opportunity_id}",
            acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            canonical_arguments=_canonical(
                {
                    "personalization_input_fingerprint": values["input_fingerprint"],
                    "personalization_proposal_fingerprint": values["proposal_fingerprint"],
                    "supplier_ref": supplier.supplier_ref,
                    "contact_ref": contact.contact_ref,
                }
            ),
            action_fingerprint=values["action_fingerprint"],
            scope=authorization.scope,
            proposed_cost=Decimal("0"),
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=("PERSONALIZATION_PREPARED",),
            evidence_refs=tuple(
                dict.fromkeys(
                    ref for item in values["claim_map"] for ref in item.evidence_refs
                )
            ),
            evidence=self._internal_evidence(authorization),
            compliance=authorization.compliance,
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
            approval_grants=authorization.approval_grants,
            supervisor_plan_id=authorization.supervisor_plan_id,
            supervisor_action_index=authorization.supervisor_action_index,
            supervisor_version=authorization.supervisor_version,
            skill_version=authorization.skill_version,
        )

    def _write(self, values, decision, disposition, created_at, event_id=None):
        message: CatalogMessage = values["message"]
        return PersonalizationArtifactWrite(
            personalization_artifact_id=personalization_artifact_id(decision.evaluation_id),
            acquisition_opportunity_id=values["opportunity"].acquisition_opportunity_id,
            supplier_ref=values["supplier"].supplier_ref,
            contact_ref=values["contact"].contact_ref,
            policy_evaluation_id=decision.evaluation_id,
            decision_evaluation_id=values["decision_row"]["decision_evaluation_id"],
            language=message.language,
            input_fingerprint=values["input_fingerprint"],
            eligibility_fingerprint=values["decision_input"].decision_input_fingerprint,
            need_engine_version=values["needs"].engine_version,
            selected_need_fingerprint=values["selected_need_fingerprint"],
            template_version=TEMPLATE_VERSION,
            catalog_version=CATALOG_VERSION,
            language_policy_version=LANGUAGE_POLICY_VERSION,
            proposal_fingerprint=values["proposal_fingerprint"],
            policy_action_fingerprint=values["action_fingerprint"],
            artifact_fingerprint=semantic_fingerprint(
                {
                    "kind": "personalization-artifact-v1",
                    "proposal_fingerprint": values["proposal_fingerprint"],
                    "disposition": disposition.value,
                }
            ),
            input_snapshot=values["input_snapshot"],
            claim_map=values["claim_map"],
            disposition=disposition,
            policy_status=decision.status.value,
            policy_counterfactual_status=(
                decision.counterfactual_status.value if decision.counterfactual_status else None
            ),
            subject=message.subject if disposition is PersonalizationDisposition.READY else None,
            greeting=message.greeting if disposition is PersonalizationDisposition.READY else None,
            body=message.body if disposition is PersonalizationDisposition.READY else None,
            cta=message.cta if disposition is PersonalizationDisposition.READY else None,
            recorded_event_id=event_id,
            created_at=created_at,
        )

    def _commit_blocked(self, values, decision, created_at):
        with self._engine.begin() as connection:
            return self._artifacts.append_in_transaction(
                connection,
                self._write(
                    values,
                    decision,
                    PersonalizationDisposition.POLICY_BLOCKED,
                    created_at,
                ),
            )

    def _commit_ready(
        self,
        opportunity_id,
        language,
        values,
        decision,
        expected,
        as_of_date,
        captured_at,
        authorization,
    ):
        try:
            with self._engine.begin() as connection:
                current = self._acquisition.get_opportunity_in_transaction(
                    connection, opportunity_id, for_update=True
                )
                if current.stream_version != expected:
                    raise PersonalizationInputChanged(opportunity_id)
                try:
                    rebuilt = self._build_values(
                        self._load_in_transaction(
                            connection, opportunity_id, current=current
                        ),
                        language,
                        as_of_date,
                    )
                except (
                    PersonalizationBindingConflict,
                    PersonalizationGroundingInsufficient,
                    PersonalizationNotActionable,
                    PersonalizationDecisionNoLongerEligible,
                    PersonalizationValidationError,
                ) as error:
                    raise PersonalizationInputChanged(opportunity_id) from error
                if (
                    rebuilt["input_fingerprint"] != values["input_fingerprint"]
                    or rebuilt["proposal_fingerprint"] != values["proposal_fingerprint"]
                    or rebuilt["action_fingerprint"] != values["action_fingerprint"]
                ):
                    raise PersonalizationInputChanged(opportunity_id)
                mutation = self._acquisition.append_in_transaction(
                    connection,
                    opportunity_id,
                    event_type=EventType.NEXT_ACTION_SET,
                    expected_version=expected,
                    idempotency_key=f"personalization_next_action:{decision.evaluation_id}",
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-personalization",
                    payload={"next_action": "assess_campaign_compliance"},
                    causation_id=decision.evaluation_id,
                    occurred_at=captured_at,
                )
                return self._artifacts.append_in_transaction(
                    connection,
                    self._write(
                        rebuilt,
                        decision,
                        PersonalizationDisposition.READY,
                        captured_at,
                        mutation.event.event_id,
                    ),
                )
        except PersonalizationInputChanged:
            # A race that completed the same durable evaluation is an exact replay,
            # not a second event. Any other state change remains a typed conflict.
            existing = self._artifacts.get_by_policy(decision.evaluation_id)
            if existing is not None:
                self._require_existing(existing, opportunity_id, language, authorization)
                return existing
            raise

    def _require_existing(self, existing, opportunity_id, language, authorization) -> None:
        if existing["acquisition_opportunity_id"] != opportunity_id or existing["language"] != language:
            raise PersonalizationArtifactIdempotencyConflict(authorization.evaluation_id)
        with self._engine.connect() as connection:
            row = self._policy_store.evaluation_row(connection, authorization.evaluation_id)
            policy_event = (
                connection.execute(
                    sa.select(acquisition_event.c.stream_sequence).where(
                        acquisition_event.c.acquisition_opportunity_id == opportunity_id,
                        acquisition_event.c.idempotency_key
                        == f"policy_evaluation:{authorization.evaluation_id}",
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or policy_event is None or row["request_id"] != authorization.request_id:
            raise PersonalizationArtifactIdempotencyConflict(authorization.evaluation_id)
        existing_decision = decision_from_row(row)
        control = self._policy_store.get_control(existing_decision.policy_snapshot_id)
        historical_cost_used = control.daily_cost_cap - existing_decision.cost_remaining
        historical_volume_used = control.daily_volume_cap - existing_decision.volume_remaining
        if historical_cost_used < 0 or historical_volume_used < 0:
            raise PersonalizationArtifactIdempotencyConflict(authorization.evaluation_id)
        historical_budget = BudgetUsage(
            cost_used=historical_cost_used, volume_used=historical_volume_used
        )
        request = self._replay_request(
            authorization,
            existing,
            expected_version=policy_event["stream_sequence"] - 1,
        )
        matches = row["semantic_fingerprint"] == self._policy.semantic_fingerprint(
            request,
            evaluated_at=existing_decision.evaluated_at,
            budget_usage=historical_budget,
            policy_snapshot_id=existing_decision.policy_snapshot_id,
        )
        if not matches:
            matches = any(
                row["semantic_fingerprint"]
                == self._policy.semantic_fingerprint(
                    request,
                    evaluated_at=existing_decision.evaluated_at,
                    budget_usage=candidate,
                    policy_snapshot_id=existing_decision.policy_snapshot_id,
                    legacy_decimal_encoding=True,
                )
                for candidate in _legacy_budget_usage_candidates(
                    historical_cost_used, historical_volume_used
                )
            )
        if not matches:
            raise PersonalizationArtifactIdempotencyConflict(authorization.evaluation_id)

    def _replay_request(self, authorization, existing, *, expected_version: int) -> PolicyRequest:
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="prepare_campaign",
            target_ref=f"acquisition-opportunity:{existing['acquisition_opportunity_id']}",
            acquisition_opportunity_id=existing["acquisition_opportunity_id"],
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            canonical_arguments=_canonical(
                {
                    "personalization_input_fingerprint": existing["input_fingerprint"],
                    "personalization_proposal_fingerprint": existing["proposal_fingerprint"],
                    "supplier_ref": existing["supplier_ref"],
                    "contact_ref": existing["contact_ref"],
                }
            ),
            action_fingerprint=existing["policy_action_fingerprint"],
            scope=authorization.scope,
            proposed_cost=Decimal("0"),
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=("PERSONALIZATION_PREPARED",),
            evidence_refs=tuple(
                dict.fromkeys(
                    ref for item in existing["claim_map"] for ref in item["evidence_refs"]
                )
            ),
            evidence=self._internal_evidence(authorization),
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
            raise ValueError("personalization clock must be timezone-aware")
        return value.astimezone(dt.UTC)


__all__ = [
    "PersonalizationBindingConflict",
    "PersonalizationEvaluationRequiresFreshAttempt",
    "PersonalizationInputChanged",
    "PersonalizationNotActionable",
    "PersonalizationService",
]
