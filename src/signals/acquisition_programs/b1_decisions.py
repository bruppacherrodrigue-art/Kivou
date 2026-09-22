"""Append-only Milo Mail B1 decisions and private, versioned France lead view."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.activity_evidence import (
    WebsiteIdentityProof,
    activity_input_from_b0,
    evaluate_activity_evidence,
)
from signals.acquisition_programs.census_b0 import program_role
from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderEvidence,
    ProviderConfidence,
)
from signals.acquisition_programs.qualification import (
    FitSignals,
    ProfessionalEvidenceInput,
    classify_recipient,
    score_fit,
)
from signals.compliance.milomail_rules import (
    MILOMAIL_PURPOSE,
    POLICY_VERSION_V2,
    MilomailPolicyInput,
    evaluate_b0_activity_replay,
)
from signals.persistence.schema import (
    acquisition_census_b0_entry,
    acquisition_census_b1_decision,
    acquisition_census_b1_entry,
    acquisition_census_b1_ready_lead,
    acquisition_census_candidate,
)

_PERSON_SOURCE = "https://api.apollo.io/api/v1/people/match"


def _json_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def _segment(sector: str) -> str:
    return {
        "digital_or_creative_agency": "France — Agences",
        "consulting": "France — Conseil",
        "recruiting_agency": "France — Recrutement",
    }.get(sector, "France — Autre")


class B1DecisionStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def replay_b0(self, *, census_id: str, config: AcquisitionProgramConfig,
                  at: dt.datetime, is_suppressed: Callable[[str], bool],
                  website_proofs: dict[str, WebsiteIdentityProof] | None = None) -> dict:
        if config.policy_version != POLICY_VERSION_V2 or config.program_key != "milomail":
            raise ValueError("B1 replay requires Milo Mail ruleset v2")
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(
                acquisition_census_b0_entry.c.candidate_id,
                acquisition_census_b0_entry.c.result,
                acquisition_census_b0_entry.c.stratum,
                acquisition_census_candidate.c.snapshot,
                acquisition_census_candidate.c.provider_evidence,
                acquisition_census_candidate.c.primary_domain,
                acquisition_census_candidate.c.sector,
            ).join(acquisition_census_candidate,
                   acquisition_census_candidate.c.candidate_id ==
                   acquisition_census_b0_entry.c.candidate_id).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_b0_entry.c.status == "COMPLETE",
            )).mappings().all()
        if len(rows) != 200 or len({row["candidate_id"] for row in rows}) != 200:
            raise ValueError("B1 replay requires exactly 200 completed B0 companies")
        return self._replay_rows(rows, config=config, at=at,
                                 is_suppressed=is_suppressed,
                                 website_proofs=website_proofs,
                                 source="B0_PERSISTED")

    def replay_b1(self, *, plan_id: str, config: AcquisitionProgramConfig,
                  at: dt.datetime, is_suppressed: Callable[[str], bool],
                  website_proofs: dict[str, WebsiteIdentityProof] | None = None) -> dict:
        """Re-evaluate only completed B1 checkpoints; never make provider calls."""
        if config.policy_version != POLICY_VERSION_V2 or config.program_key != "milomail":
            raise ValueError("B1 replay requires Milo Mail ruleset v2")
        with self.engine.connect() as connection:
            rows = connection.execute(sa.select(
                acquisition_census_b1_entry.c.candidate_id,
                acquisition_census_b1_entry.c.result,
                acquisition_census_b1_entry.c.stratum,
                acquisition_census_candidate.c.snapshot,
                acquisition_census_candidate.c.provider_evidence,
                acquisition_census_candidate.c.primary_domain,
                acquisition_census_candidate.c.sector,
            ).join(acquisition_census_candidate,
                   acquisition_census_candidate.c.candidate_id ==
                   acquisition_census_b1_entry.c.candidate_id).where(
                acquisition_census_b1_entry.c.plan_id == plan_id,
                acquisition_census_b1_entry.c.status == "COMPLETE",
            )).mappings().all()
        return self._replay_rows(rows, config=config, at=at,
                                 is_suppressed=is_suppressed,
                                 website_proofs=website_proofs,
                                 source="B1_PERSISTED")

    def _replay_rows(self, rows, *, config: AcquisitionProgramConfig,
                     at: dt.datetime, is_suppressed: Callable[[str], bool],
                     website_proofs: dict[str, WebsiteIdentityProof] | None,
                     source: str) -> dict:
        counts: Counter[str] = Counter()
        activities: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        for row in rows:
            result = row["result"] or {}
            candidate = row["snapshot"]
            prior = result.get("decision") or "NO_SEND"
            decision = prior
            activity_status = "ACTIVITY_UNKNOWN"
            reason_codes = list(result.get("reason_codes") or [result.get("classification") or "B0_EXCLUDED"])
            evidence: dict = {"source": source, "prior_decision": prior}
            verified = bool(result.get("verified_email") and isinstance(result.get("email"), str))
            suppressed = bool(verified and is_suppressed(result["email"]))
            if verified and isinstance(result.get("person"), dict) and isinstance(row["provider_evidence"], dict):
                person = result["person"]
                raw_provider = row["provider_evidence"]
                provider = MailProviderEvidence(
                    domain=row["primary_domain"], provider=MailProvider.GOOGLE_WORKSPACE,
                    confidence=ProviderConfidence.CONFIRMED,
                    mx_records=tuple(raw_provider["mx_records"]),
                    source=raw_provider["source"],
                    observed_at=dt.datetime.fromisoformat(raw_provider["observed_at"]),
                    expires_at=dt.datetime.fromisoformat(raw_provider["expires_at"]),
                    detector_version=raw_provider["detector_version"],
                )
                role = program_role(person.get("title"), config)
                activity_input = activity_input_from_b0(
                    result, candidate, role=role,
                    website_proof=(website_proofs or {}).get(row["candidate_id"]),
                )
                activity = evaluate_activity_evidence(
                    activity_input, provider=provider,
                    allowed_roles=config.target_roles, at=at,
                )
                observed_at = dt.datetime.fromisoformat(person["provider_observed_at"])
                capacity = classify_recipient(ProfessionalEvidenceInput(
                    email=result["email"], company_domain=row["primary_domain"],
                    company_id=candidate["provider_organization_id"],
                    company_active=activity.status in {
                        "OFFICIAL_ACTIVE", "OPERATIONALLY_ACTIVE",
                    }, role=role, email_verified=True,
                    professional_source_url=_PERSON_SOURCE,
                    professional_source_type="APOLLO_PEOPLE_ENRICHMENT",
                    professional_evidence_observed_at=observed_at,
                ), config=config, at=at)
                sector = row["sector"]
                size_band = row["stratum"].get("size_band", "1-10")
                count_range = tuple(int(piece) for piece in size_band.split("-"))
                fit = score_fit(FitSignals(
                    provider=provider.provider,
                    provider_confirmed=provider.provider == MailProvider.GOOGLE_WORKSPACE,
                    sector=sector, role=role,
                    employee_count_range=count_range,
                    operational_decision_maker=role is not None,
                ), config=config)
                policy = MilomailPolicyInput(
                    acquisition_purpose=MILOMAIL_PURPOSE, program=config,
                    country=candidate.get("country_code"), sector=sector,
                    employee_count_range=count_range,
                    business_relevance_confirmed=sector in config.target_sectors,
                    provider=provider, capacity=capacity, fit=fit,
                    email_verified=True, collection_source_url=_PERSON_SOURCE,
                    collected_at=observed_at,
                    suppressed=suppressed,
                    suppression_coverage_safe=True,
                    evidence_ids=(f"apollo-person:{person['source_fingerprint']}",),
                    assessed_at=at,
                )
                replay = evaluate_b0_activity_replay(
                    result, candidate, policy_input=policy,
                    website_proof=(website_proofs or {}).get(row["candidate_id"]),
                )
                decision = ("SEND_THEORETICAL" if replay.policy.decision == "SEND"
                            else replay.policy.decision)
                activity_status = ("ACTIVITY_UNKNOWN" if replay.activity.status == "UNKNOWN"
                                   else replay.activity.status)
                reason_codes = list(replay.policy.reason_codes)
                evidence = {"source": source, "activity_version": replay.activity.version,
                            "evidence_ids": list(replay.activity.evidence_ids),
                            "fit_score": fit.total, "score_version": fit.score_version,
                            "provider_detector_version": provider.detector_version}
                self._upsert_private_lead(
                    candidate_id=row["candidate_id"], result=result,
                    candidate=candidate, sector=sector, role=person.get("title") or "",
                    decision=decision, reasons=reason_codes,
                    provider=provider, suppressed=suppressed, at=at,
                    size_band=size_band,
                )
            elif suppressed:
                decision, reason_codes = "NO_SEND", ["SUPPRESSION_MATCH"]
            decision_id = _json_hash((row["candidate_id"], POLICY_VERSION_V2, at.isoformat(),
                                      decision, reason_codes, evidence))
            with self.engine.begin() as connection:
                if not connection.scalar(sa.select(sa.func.count()).select_from(
                    acquisition_census_b1_decision).where(
                    acquisition_census_b1_decision.c.decision_id == decision_id,
                )):
                    connection.execute(sa.insert(acquisition_census_b1_decision).values(
                        decision_id=decision_id, candidate_id=row["candidate_id"],
                        ruleset_version=POLICY_VERSION_V2, prior_decision=prior,
                        decision=decision, activity_status=activity_status,
                        reason_codes=reason_codes, evidence=evidence,
                        decided_at=at,
                    ))
            counts[decision] += 1
            activities[activity_status] += 1
            reasons.update(reason_codes)
        return {"replayed": len(rows), "decisions": dict(counts),
                "activity": dict(activities), "reason_codes": dict(reasons),
                "apollo_calls": 0, "instantly_mutations": 0, "emails_sent": 0}

    def _upsert_private_lead(self, *, candidate_id: str, result: dict,
                             candidate: dict, sector: str, role: str,
                             decision: str, reasons: list[str],
                             provider: MailProviderEvidence, suppressed: bool,
                             size_band: str, at: dt.datetime) -> None:
        table = acquisition_census_b1_ready_lead
        person = result["person"]
        name = person.get("first_name") if isinstance(person, dict) else None
        values = {
            "candidate_id": candidate_id, "program_key": "milomail",
            "first_name": name, "role": role,
            "company_name": candidate.get("display_name"),
            "company_domain": candidate["primary_domain"],
            "professional_email": result["email"],
            "sector": sector, "size_band": size_band, "country": "FR",
            "locale": "fr-FR", "segment": _segment(sector),
            "provider_evidence": {
                "mx_records": list(provider.mx_records), "source": provider.source,
                "observed_at": provider.observed_at.isoformat(),
                "expires_at": provider.expires_at.isoformat(),
                "detector_version": provider.detector_version,
            },
            "ruleset_version": POLICY_VERSION_V2,
            "decision": "READY_THEORETICAL" if decision == "SEND_THEORETICAL" else decision,
            "primary_reason": reasons[0] if reasons else None,
            "verified_at": at, "suppressed": suppressed,
        }
        with self.engine.begin() as connection:
            existing = connection.scalar(sa.select(table.c.candidate_id).where(
                table.c.candidate_id == candidate_id,
            ))
            if existing:
                connection.execute(sa.update(table).where(
                    table.c.candidate_id == candidate_id,
                ).values(**{key: value for key, value in values.items() if key != "candidate_id"}))
            else:
                connection.execute(sa.insert(table).values(**values))
