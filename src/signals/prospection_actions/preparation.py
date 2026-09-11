"""Build a bounded Founder review queue from reusable supplier-directory facts."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    prospect_target,
    prospect_target_history,
    supplier_directory,
)
from signals.prospection_actions.mail import render_assisted_mail
from signals.prospection_actions.service import ProspectLinkIssuer, _history_id
from signals.supplier_discovery.families import department_and_neighbours

DAILY_PENDING_CAP = 25
DAILY_SIGNAL_CAP = 5
CONTACT_COOLDOWN = dt.timedelta(days=90)


class AssistedSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    opportunity_key: str = Field(min_length=1, max_length=256)
    acquisition_opportunity_id: str = Field(min_length=1, max_length=64)
    procedure_key: str = Field(min_length=1, max_length=256)
    holder: str = Field(min_length=1, max_length=512)
    subject: str = Field(min_length=1, max_length=998)
    amount_minor_units: int = Field(ge=5_000_000)
    currency: str = Field(pattern=r"^(eur|chf)$")
    location: str = Field(min_length=1, max_length=512)
    department: str = Field(pattern=r"^(?:\d{2,3}|2[AB])$")
    decision_date: dt.date
    source_url: str = Field(min_length=8, max_length=2048)
    vertical: str = Field(min_length=1, max_length=100)
    families: tuple[tuple[str, str], ...] = Field(min_length=1, max_length=5)


@dataclass(frozen=True)
class PreparationResult:
    prepared: int
    status: str
    target_ids: tuple[str, ...] = ()
    reason: str | None = None
    directory_candidates: int = 0
    enrichment_required: bool = False


def _director(row: dict[str, object]) -> tuple[str | None, str | None]:
    directors = row.get("directors") or ()
    for director in directors:
        if not isinstance(director, dict) or not director.get("name"):
            continue
        if str(director.get("entity_type") or "personne physique") != "personne physique":
            continue
        return str(director["name"]), str(director.get("title") or "Dirigeant")
    return None, None


class ProspectPreparationService:
    def __init__(
        self,
        engine: Engine,
        *,
        link_issuer: ProspectLinkIssuer,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._link_issuer = link_issuer
        self._clock = clock

    def prepare(self, signal: AssistedSignal, *, cycle_ref: str) -> PreparationResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("preparation clock must be timezone-aware")
        day_start = dt.datetime.combine(now.astimezone(dt.UTC).date(), dt.time(), tzinfo=dt.UTC)
        day_end = day_start + dt.timedelta(days=1)
        family_order = {key: index for index, (key, _label) in enumerate(signal.families)}
        family_labels = dict(signal.families)
        departments = set(department_and_neighbours(signal.department))
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
                    {"scope": f"assisted-prospection:{day_start.date().isoformat()}"},
                )
            daily = tuple(
                connection.execute(
                    sa.select(
                        prospect_target.c.opportunity_key,
                        prospect_target.c.procedure_award_key,
                    ).where(
                        prospect_target.c.created_at >= day_start,
                        prospect_target.c.created_at < day_end,
                    )
                )
            )
            if any(row.procedure_award_key == signal.procedure_key for row in daily):
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
                        prospect_target.c.sent_at.is_not(None),
                        prospect_target.c.sent_at > cutoff,
                    )
                ).scalars()
            )
            directory_rows = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(supplier_directory).where(
                        supplier_directory.c.department.in_(departments),
                        supplier_directory.c.employees >= 10,
                        supplier_directory.c.professional_email.is_not(None),
                        supplier_directory.c.email_verification_status == "mx_verified",
                        supplier_directory.c.domain_validation_method.is_not(None),
                        supplier_directory.c.reverification_required_at.is_(None),
                        supplier_directory.c.suppressed_at.is_(None),
                    ).order_by(
                        supplier_directory.c.employees.desc(),
                        supplier_directory.c.siren,
                    )
                ).mappings()
            )
            eligible: list[tuple[dict[str, object], str]] = []
            for row in directory_rows:
                if row["siren"] in recently_contacted:
                    continue
                matches = sorted(
                    set(row.get("family_keys") or ()).intersection(family_order),
                    key=family_order.__getitem__,
                )
                review = set(row.get("family_review_keys") or ())
                family_key = next((key for key in matches if key not in review), None)
                if family_key is None:
                    continue
                duplicate = connection.scalar(
                    sa.select(sa.literal(1)).where(
                        prospect_target.c.opportunity_key == signal.opportunity_key,
                        prospect_target.c.email_address == row["professional_email"],
                    ).limit(1)
                )
                if duplicate:
                    continue
                eligible.append((row, family_key))
                if len(eligible) >= remaining:
                    break

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
                rendered = render_assisted_mail(values)
                values.update(
                    mail_subject=rendered.subject,
                    mail_text=rendered.text,
                    mail_html=rendered.html,
                    mail_word_count=rendered.word_count,
                )
                connection.execute(sa.insert(prospect_target).values(**values))
                connection.execute(
                    sa.insert(prospect_target_history).values(
                        history_id=_history_id(target_id, 1, "prepared"),
                        target_id=target_id,
                        event_type="prepared",
                        actor="acquisition-runtime",
                        previous_values={},
                        new_values={"status": "pending_review"},
                        created_at=now,
                    )
                )
                target_ids.append(target_id)
        return PreparationResult(
            prepared=len(target_ids),
            status="pending_review",
            target_ids=tuple(target_ids),
            directory_candidates=len(directory_rows),
            enrichment_required=len(target_ids) < remaining,
        )


__all__ = [
    "AssistedSignal",
    "PreparationResult",
    "ProspectPreparationService",
]
