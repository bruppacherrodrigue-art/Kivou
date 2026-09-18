"""Build a bounded Founder review queue from reusable supplier-directory facts."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import Engine

from signals.client_value.directory import published_email_evidence
from signals.companies.schema import winner_enrichment_job
from signals.domain.french_departments import DEPARTMENTS
from signals.persistence.schema import (
    materialized_signal,
    prospect_target,
    prospect_target_history,
    supplier_directory,
)
from signals.personalization.prospect_mail import RenderedProspectMail, render_prospect_mail
from signals.prospection_actions.day import prospection_day, prospection_day_bounds
from signals.prospection_actions.service import ProspectLinkIssuer, _history_id
from signals.supplier_directory.email_quality import is_placeholder_email
from signals.supplier_discovery.families import (
    department_and_neighbours,
    load_supplier_family_catalog,
)

DAILY_PENDING_CAP = 25
DAILY_SIGNAL_CAP = 5
CONTACT_COOLDOWN = dt.timedelta(days=30)
SMALL_SIGNAL_LIMIT = 5
LARGE_SIGNAL_LIMIT = 8
SMALL_SIGNAL_MAX_MINOR_UNITS = 10_000_000


class AssistedSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    opportunity_key: str = Field(min_length=1, max_length=256)
    acquisition_opportunity_id: str = Field(min_length=1, max_length=64)
    procedure_key: str = Field(min_length=1, max_length=256)
    holder: str = Field(min_length=1, max_length=512)
    holder_siren: str | None = Field(default=None, pattern=r"^\d{9}$")
    holder_family_required: bool = False
    target_holder_family: bool = False
    subject: str = Field(min_length=1, max_length=998)
    amount_minor_units: int = Field(ge=5_000_000)
    currency: str = Field(pattern=r"^(eur|chf)$")
    location: str = Field(min_length=1, max_length=512)
    city: str | None = Field(default=None, min_length=1, max_length=512)
    department: str = Field(pattern=r"^(?:\d{2,3}|2[AB])$")
    decision_date: dt.date
    source_url: str = Field(min_length=8, max_length=2048)
    vertical: str = Field(min_length=1, max_length=100)
    families: tuple[tuple[str, str], ...] = Field(min_length=1, max_length=5)

    @field_validator("holder")
    @classmethod
    def holder_is_a_named_company(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) in {9, 14} and not re.sub(r"[\d\s.-]", "", value):
            raise ValueError("holder must be a named company")
        return value


@dataclass(frozen=True)
class PreparationResult:
    prepared: int
    status: str
    target_ids: tuple[str, ...] = ()
    reason: str | None = None
    directory_candidates: int = 0
    enrichment_required: bool = False


def _director(row: dict[str, object]) -> tuple[str | None, str | None]:
    selected = str(row.get("director_display_name") or "").strip()
    if selected:
        return selected, str(row.get("email_contact_title") or "Dirigeant")
    return None, None


class ProspectPreparationService:
    def __init__(
        self,
        engine: Engine,
        *,
        link_issuer: ProspectLinkIssuer,
        mail_renderer: Callable[[dict[str, object]], RenderedProspectMail] = render_prospect_mail,
        site_email_only: bool = False,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._link_issuer = link_issuer
        self._mail_renderer = mail_renderer
        self._site_email_only = site_email_only
        self._clock = clock

    def prepare(self, signal: AssistedSignal, *, cycle_ref: str) -> PreparationResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("preparation clock must be timezone-aware")
        observed_on = prospection_day(now)
        if not observed_on - dt.timedelta(days=30) <= signal.decision_date <= observed_on:
            return PreparationResult(
                prepared=0,
                status="pending_review",
                reason="SIGNAL_OUTSIDE_ATTRIBUTION_WINDOW",
            )
        day_start, day_end = prospection_day_bounds(now)
        family_order = {key: index for index, (key, _label) in enumerate(signal.families)}
        family_labels = dict(signal.families)
        catalog_by_key = {
            family.key: family
            for families in load_supplier_family_catalog().values()
            for family in families
        }
        departments = set(department_and_neighbours(signal.department))
        department_order = {
            department: index
            for index, department in enumerate(department_and_neighbours(signal.department))
        }
        signal_limit = (
            SMALL_SIGNAL_LIMIT
            if signal.amount_minor_units <= SMALL_SIGNAL_MAX_MINOR_UNITS
            else LARGE_SIGNAL_LIMIT
        )
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
                    {"scope": f"assisted-prospection:{day_start.date().isoformat()}"},
                )
            active_rows = tuple(
                connection.execute(
                    sa.select(
                        prospect_target.c.target_id,
                        prospect_target.c.siren,
                        prospect_target.c.created_at,
                        prospect_target.c.status,
                    )
                    .where(prospect_target.c.status.in_(("pending_review", "approved")))
                    .order_by(
                        prospect_target.c.siren,
                        prospect_target.c.created_at,
                        prospect_target.c.target_id,
                    )
                ).mappings()
            )
            kept_sirens: set[str] = set()
            for row in active_rows:
                siren = str(row["siren"])
                if siren not in kept_sirens:
                    kept_sirens.add(siren)
                    continue
                target_id = str(row["target_id"])
                connection.execute(
                    sa.update(prospect_target)
                    .where(prospect_target.c.target_id == target_id)
                    .values(
                        status="rejected",
                        rejection_reason="other",
                        rejection_comment="duplicate_siren_targeting_rule",
                        rejected_at=now,
                        rejected_by="acquisition-runtime",
                        updated_at=now,
                    )
                )
                connection.execute(
                    sa.insert(prospect_target_history).values(
                        history_id=_history_id(target_id, 2, "rejected-duplicate-siren"),
                        target_id=target_id,
                        event_type="rejected_duplicate_siren",
                        actor="acquisition-runtime",
                        previous_values={"status": row["status"]},
                        new_values={
                            "status": "rejected",
                            "rejection_reason": "other",
                            "rejection_comment": "duplicate_siren_targeting_rule",
                        },
                        created_at=now,
                    )
                )
            daily = tuple(
                connection.execute(
                    sa.select(
                        prospect_target.c.opportunity_key,
                        prospect_target.c.procedure_award_key,
                        prospect_target.c.cycle_ref,
                    ).where(
                        prospect_target.c.created_at >= day_start,
                        prospect_target.c.created_at < day_end,
                        prospect_target.c.status.in_(("pending_review", "approved")),
                    )
                )
            )
            if any(
                row.procedure_award_key == signal.procedure_key and row.cycle_ref != cycle_ref
                for row in daily
            ):
                return PreparationResult(
                    prepared=0,
                    status="pending_review",
                    reason="PROCEDURE_ALREADY_PREPARED_TODAY",
                )
            distinct_signals = {row.opportunity_key for row in daily}
            if signal.opportunity_key not in distinct_signals and len(distinct_signals) >= 5:
                return PreparationResult(
                    prepared=0,
                    status="pending_review",
                    reason="DAILY_SIGNAL_CAP_REACHED",
                )
            remaining = DAILY_PENDING_CAP - len(daily)
            if remaining <= 0:
                return PreparationResult(
                    prepared=0,
                    status="pending_review",
                    reason="DAILY_PENDING_CAP_REACHED",
                )
            cutoff = now - CONTACT_COOLDOWN
            recently_contacted = set(
                connection.execute(
                    sa.select(prospect_target.c.siren).where(
                        prospect_target.c.instantly_accepted_at.is_not(None),
                        prospect_target.c.instantly_accepted_at > cutoff,
                    )
                ).scalars()
            )
            queued_sirens = set(
                connection.execute(
                    sa.select(prospect_target.c.siren).where(
                        prospect_target.c.status.in_(("pending_review", "approved"))
                    )
                ).scalars()
            )
            historically_rejected_sirens = set(
                connection.execute(
                    sa.select(prospect_target.c.siren).where(
                        prospect_target.c.status == "rejected"
                    )
                ).scalars()
            )
            historical_target_ids = set(
                connection.execute(sa.select(prospect_target.c.target_id)).scalars()
            )
            holder_family_keys: set[str] = set()
            if signal.holder_family_required:
                holder_row = connection.execute(
                    sa.select(
                        supplier_directory.c.family_keys,
                        supplier_directory.c.family_confirmation_status,
                    ).where(supplier_directory.c.siren == signal.holder_siren)
                ).first()
                holder_family_keys = set(
                    (holder_row[0] or ()) if holder_row and holder_row[1] == "confirmed" else ()
                )
                if not holder_family_keys:
                    # Do not silently target a supplier from the holder's own
                    # trade while its enrichment is incomplete. Requeue the
                    # corresponding winner job at the head of the worker queue.
                    signal_keys = sa.select(materialized_signal.c.signal_key).where(
                        materialized_signal.c.opportunity_key == signal.opportunity_key
                    )
                    connection.execute(
                        sa.update(winner_enrichment_job)
                        .where(winner_enrichment_job.c.signal_key.in_(signal_keys))
                        .values(
                            status="pending",
                            attempt_count=0,
                            error_code=None,
                            claimed_by=None,
                            queued_at=now,
                            started_at=None,
                            finished_at=None,
                            updated_at=now,
                        )
                    )
                    return PreparationResult(
                        prepared=0,
                        status="pending_review",
                        reason="HOLDER_FAMILY_ENRICHMENT_REQUIRED",
                    )
            directory_rows = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(supplier_directory)
                    .where(
                        supplier_directory.c.department.in_(departments),
                        supplier_directory.c.employees >= 10,
                        supplier_directory.c.professional_email.is_not(None),
                        supplier_directory.c.email_verification_status == "mx_verified",
                        supplier_directory.c.domain_validation_method.is_not(None),
                        supplier_directory.c.family_confirmation_status == "confirmed",
                        supplier_directory.c.reverification_required_at.is_(None),
                        supplier_directory.c.suppressed_at.is_(None),
                    )
                    .order_by(
                        supplier_directory.c.employees.desc(),
                        supplier_directory.c.siren,
                    )
                ).mappings()
            )
            eligible: list[tuple[dict[str, object], str]] = []
            for row in directory_rows:
                if self._site_email_only:
                    site_email = published_email_evidence(row)
                    if site_email is None:
                        continue
                    row.update(
                        professional_email=site_email[0],
                        email_source="site",
                        email_evidence_url=site_email[1],
                    )
                if is_placeholder_email(row["professional_email"]):
                    connection.execute(
                        sa.update(supplier_directory)
                        .where(supplier_directory.c.siren == row["siren"])
                        .values(
                            email_verification_status="mx_failed",
                            reverification_required_at=now,
                            reverification_reason="placeholder_email",
                            updated_at=now,
                        )
                    )
                    continue
                if row["siren"] in recently_contacted:
                    continue
                if row["siren"] in queued_sirens:
                    continue
                if row["siren"] in historically_rejected_sirens:
                    continue
                email = str(row["professional_email"]).casefold()
                target_id = str(
                    uuid5(NAMESPACE_URL, f"kivou:prospect:{signal.opportunity_key}:{email}")
                )
                if target_id in historical_target_ids:
                    continue
                matches = sorted(
                    (
                        key
                        for key in set(row.get("family_keys") or ()).intersection(family_order)
                        if key in catalog_by_key
                    ),
                    key=family_order.__getitem__,
                )
                review = set(row.get("family_review_keys") or ())
                family_key = next((key for key in matches if key not in review), None)
                if family_key is None:
                    continue
                if (
                    not signal.target_holder_family
                    and holder_family_keys
                    and set(row.get("family_keys") or ()).intersection(holder_family_keys)
                ):
                    continue
                eligible.append((row, family_key))

            eligible.sort(
                key=lambda item: (
                    0 if _director(item[0])[0] else 1,
                    department_order.get(str(item[0]["department"]), len(department_order)),
                    str(item[0]["siren"]),
                )
            )
            eligible = eligible[: min(remaining, signal_limit)]

            target_ids: list[str] = []
            for directory, family_key in eligible:
                email = str(directory["professional_email"]).casefold()
                target_id = str(
                    uuid5(NAMESPACE_URL, f"kivou:prospect:{signal.opportunity_key}:{email}")
                )
                director_name, director_title = _director(directory)
                values: dict[str, object] = {
                    "target_id": target_id,
                    "version": 1,
                    "cycle_ref": cycle_ref,
                    "opportunity_key": signal.opportunity_key,
                    "procedure_award_key": signal.procedure_key,
                    "acquisition_opportunity_id": signal.acquisition_opportunity_id,
                    "siren": directory["siren"],
                    "company_name": directory["legal_name"],
                    "company_city": directory["city"],
                    "company_employees": directory["employees"],
                    "vertical": signal.vertical,
                    "family_key": family_key,
                    "family_label": family_labels[family_key],
                    "director_name": director_name,
                    "director_title": director_title,
                    "director_source": "registry" if director_name else None,
                    "email_address": email,
                    "email_source": directory["email_source"],
                    "email_verification_status": "mx_verified",
                    "email_evidence_url": directory.get("email_evidence_url"),
                    "signal_holder": signal.holder,
                    "signal_subject": signal.subject,
                    "signal_amount_minor_units": signal.amount_minor_units,
                    "signal_currency": signal.currency,
                    "signal_location": signal.location,
                    "signal_department": DEPARTMENTS.get(signal.department, signal.department),
                    "signal_decision_date": signal.decision_date,
                    "signal_source_url": signal.source_url,
                    "unsubscribe_url": "https://kivou.eu/unsubscribe/pending",
                    "status": "pending_review",
                    "delivery_status": "not_sent",
                    "created_at": now,
                    "updated_at": now,
                }
                link = self._link_issuer.issue(row=values, email=email, at=now)
                values.update(
                    attribution_url=link.url,
                    attribution_member_ref=link.member_ref,
                    attribution_payload=link.payload,
                    attribution_token_fingerprint=link.token_fingerprint,
                    unsubscribe_url=(link.unsubscribe_url or values["unsubscribe_url"]),
                )
                rendered = self._mail_renderer({**values, "signal_city": signal.city})
                values.update(
                    mail_subject=rendered.subject,
                    mail_text=rendered.text,
                    mail_html=rendered.html,
                    mail_word_count=rendered.word_count,
                    mail_contract_status=rendered.contract_status,
                    mail_contract_failure=rendered.contract_failure,
                )
                connection.execute(sa.insert(prospect_target).values(**values))
                connection.execute(
                    sa.insert(prospect_target_history).values(
                        history_id=_history_id(target_id, 1, "prepared"),
                        target_id=target_id,
                        event_type="prepared",
                        actor="acquisition-runtime",
                        previous_values={},
                        new_values={
                            "status": "pending_review",
                            "mail_contract_status": rendered.contract_status,
                            "mail_contract_failure": rendered.contract_failure,
                        },
                        created_at=now,
                    )
                )
                target_ids.append(target_id)
        return PreparationResult(
            prepared=len(target_ids),
            status="pending_review",
            target_ids=tuple(target_ids),
            directory_candidates=len(directory_rows),
            enrichment_required=len(target_ids) < min(remaining, signal_limit),
        )


__all__ = [
    "AssistedSignal",
    "PreparationResult",
    "ProspectPreparationService",
]
