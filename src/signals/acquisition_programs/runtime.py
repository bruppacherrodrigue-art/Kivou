"""Program-scoped SHADOW orchestration over Kivou's event and suppression stores."""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import EventType
from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.mail_provider import normalize_domain
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.campaigns.instantly import ShadowInstantlyProvider
from signals.compliance.milomail_rules import (
    MilomailPolicyDecision,
    MilomailPolicyInput,
    evaluate_milomail,
)
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    SuppressionIdentityUnavailable,
)
from signals.persistence.schema import acquisition_program, acquisition_program_eligibility
from signals.prospection_actions.suppression import EmailSuppressionChecker


class MilomailShadowRuntime:
    def __init__(
        self,
        engine: Engine,
        acquisition: AcquisitionStore,
        suppression_keyring: SuppressionIdentityKeyring,
        instantly_provider: object,
    ) -> None:
        self._engine = engine
        self._acquisition = acquisition
        self._suppression = EmailSuppressionChecker(
            suppression_keyring,
            scope=MILOMAIL_SUPPRESSION_SCOPE,
        )
        self._instantly = ShadowInstantlyProvider(instantly_provider)

    def evaluate(
        self,
        *,
        program_id: str,
        opportunity_id: str,
        email: str,
        policy_input: MilomailPolicyInput,
    ) -> MilomailPolicyDecision:
        if policy_input.program.campaign_mode != "SHADOW":
            raise ValueError("Milo Mail runtime is locked to SHADOW")
        try:
            recipient_domain = normalize_domain(
                validate_email(email, check_deliverability=False).domain
            )
        except EmailNotValidError as error:
            raise ValueError("recipient email is invalid") from error
        if recipient_domain != policy_input.provider.domain:
            raise ValueError("recipient/provider domain evidence mismatch")
        with self._engine.begin() as connection:
            program = (
                connection.execute(
                    sa.select(acquisition_program).where(
                        acquisition_program.c.program_id == program_id
                    )
                )
                .mappings()
                .one()
            )
            if program["program_key"] != "milomail" or (
                program["config_snapshot"] != policy_input.program.model_dump(mode="json")
            ):
                raise ValueError("program identity or configuration mismatch")
            existing = (
                connection.execute(
                    sa.select(acquisition_program_eligibility).where(
                        acquisition_program_eligibility.c.program_id == program_id,
                        acquisition_program_eligibility.c.acquisition_opportunity_id
                        == opportunity_id,
                        acquisition_program_eligibility.c.evaluated_at == policy_input.assessed_at,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return MilomailPolicyDecision(
                    decision=existing["decision"],
                    reason_codes=tuple(existing["reason_codes"]),
                    policy_country=existing["policy_country"],
                    policy_version=existing["policy_version"],
                    score_version=existing["score_version"],
                    evidence_ids=tuple(existing["evidence_ids"]),
                    decided_at=policy_input.assessed_at,
                )
            try:
                suppressed = self._suppression.is_suppressed(
                    connection,
                    email=email,
                    at=policy_input.assessed_at,
                )
                safe = True
            except SuppressionIdentityUnavailable:
                suppressed, safe = False, False
            assessed = policy_input.model_copy(
                update={
                    "suppressed": policy_input.suppressed or suppressed,
                    "suppression_coverage_safe": safe and policy_input.suppression_coverage_safe,
                }
            )
            decision = evaluate_milomail(assessed)
            current = self._acquisition.get_opportunity_in_transaction(
                connection,
                opportunity_id,
                for_update=True,
            )
            event_key = hashlib.sha256(
                f"milomail-policy-v1\0{program_id}\0{opportunity_id}\0{decision.decided_at.isoformat()}".encode()
            ).hexdigest()
            self._acquisition.append_in_transaction(
                connection,
                opportunity_id,
                event_type=EventType.POLICY_EVALUATED,
                expected_version=current.stream_version,
                idempotency_key=event_key,
                payload={
                    "program_id": program_id,
                    "decision": decision.decision,
                    "fit_score": assessed.fit.total,
                    "score_version": assessed.fit.score_version,
                },
                reason_codes=decision.reason_codes,
                evidence_refs=decision.evidence_ids,
                policy_version=decision.policy_version,
                occurred_at=decision.decided_at,
            )
            AcquisitionProgramStore.record_eligibility_in_transaction(
                connection,
                program_id=program_id,
                opportunity_id=opportunity_id,
                provider=assessed.provider,
                capacity=assessed.capacity,
                fit=assessed.fit,
                decision=decision,
                collection_source_url=assessed.collection_source_url,
                collected_at=assessed.collected_at,
            )
            return decision

    def export_preview(self, _decision: MilomailPolicyDecision) -> str:
        """Explicit command boundary: SHADOW cannot create or export a lead."""
        return "BLOCKED_SHADOW"


__all__ = ["MilomailShadowRuntime"]
