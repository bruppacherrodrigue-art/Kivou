"""Atomic multi-family preparation of the assisted Founder review queue."""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_runtime.catalog_selection import CatalogFamilyInventory
from signals.client_value.directory import published_email_evidence
from signals.decision_engine.policy import semantic_fingerprint
from signals.domain.french_departments import DEPARTMENTS
from signals.persistence.schema import (
    acquisition_runtime_cycle,
    prospect_target,
    prospect_target_history,
    supplier_directory,
)
from signals.personalization.prospect_mail import RenderedProspectMail, render_prospect_mail
from signals.prospection_actions.preparation import (
    CONTACT_COOLDOWN,
    DAILY_PENDING_CAP,
    AssistedSignal,
    _director,
)
from signals.prospection_actions.service import ProspectLinkIssuer, _history_id
from signals.supplier_discovery.families import department_and_neighbours

_ACTIVE_STATUSES = ("pending_review", "approved")
_ATTRIBUTION_URL = re.compile(r"https://[^\s\"'<>]+/a/[^\s\"'<>]+")


@dataclass(frozen=True)
class CatalogFamilyResult:
    family_key: str
    eligible: int
    queued: int
    refused_by_reason: Mapping[str, int]
    deferred_global_cap: int
    opportunity_keys: tuple[str, ...]
    zero_reason: str | None


@dataclass(frozen=True)
class CatalogPreparationResult:
    prepared: int
    active_before: int
    active_after: int
    cycle_ref: str | None
    target_ids: tuple[str, ...]
    families: tuple[CatalogFamilyResult, ...]


@dataclass(frozen=True)
class _Candidate:
    family_key: str
    signal: AssistedSignal
    directory: dict[str, object]
    target_id: str


@dataclass
class _FamilyWork:
    family_key: str
    inventory: CatalogFamilyInventory
    pools: list[tuple[AssistedSignal, tuple[_Candidate, ...]]] = field(default_factory=list)
    refused: Counter[str] = field(default_factory=Counter)
    eligible: int = 0
    queued: list[_Candidate] = field(default_factory=list)
    deferred: int = 0
    site_in_geo: int = 0
    qualification_error: bool = False


class AssistedCatalogPreparationService:
    def __init__(
        self,
        engine: Engine,
        *,
        link_issuer: ProspectLinkIssuer,
        mail_renderer: Callable[[dict[str, object]], RenderedProspectMail] = render_prospect_mail,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._link_issuer = link_issuer
        self._mail_renderer = mail_renderer
        self._clock = clock

    def prepare(
        self, inventory: Mapping[str, CatalogFamilyInventory]
    ) -> CatalogPreparationResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("catalog preparation clock must be timezone-aware")
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
                    {"scope": "assisted-catalog-preparation"},
                )
            active_rows = tuple(
                connection.execute(
                    sa.select(prospect_target.c.siren).where(
                        prospect_target.c.status.in_(_ACTIVE_STATUSES)
                    )
                ).scalars()
            )
            active_before = len(active_rows)
            remaining = max(0, DAILY_PENDING_CAP - active_before)
            active_sirens = {str(value) for value in active_rows}
            cutoff = now - CONTACT_COOLDOWN
            recently_contacted = {
                str(value)
                for value in connection.execute(
                    sa.select(prospect_target.c.siren).where(
                        prospect_target.c.instantly_accepted_at.is_not(None),
                        prospect_target.c.instantly_accepted_at > cutoff,
                    )
                ).scalars()
            }
            rejected_sirens = {
                str(value)
                for value in connection.execute(
                    sa.select(prospect_target.c.siren).where(
                        prospect_target.c.status == "rejected"
                    )
                ).scalars()
            }
            historical_target_ids = {
                str(value)
                for value in connection.execute(sa.select(prospect_target.c.target_id)).scalars()
            }
            directory_rows = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(supplier_directory).where(
                        supplier_directory.c.employees >= 10,
                        supplier_directory.c.family_confirmation_status == "confirmed",
                        supplier_directory.c.suppressed_at.is_(None),
                    )
                ).mappings()
            )
            work: list[_FamilyWork] = []
            for family_key, family_inventory in inventory.items():
                try:
                    qualified = self._qualify_family(
                        family_key,
                        family_inventory,
                        directory_rows=directory_rows,
                        active_sirens=active_sirens,
                        recently_contacted=recently_contacted,
                        rejected_sirens=rejected_sirens,
                        historical_target_ids=historical_target_ids,
                    )
                except (KeyError, TypeError, ValueError):
                    qualified = _FamilyWork(
                        family_key=family_key,
                        inventory=family_inventory,
                        qualification_error=True,
                    )
                work.append(qualified)
            selected = self._allocate(work, remaining=remaining, active_sirens=active_sirens)
            cycle_ref = semantic_fingerprint(
                {
                    "kind": "assisted-catalog-cycle-v1",
                    "day": now.astimezone(dt.UTC).date().isoformat(),
                }
            )
            rows = [
                self._render_row(candidate, cycle_ref=cycle_ref, now=now)
                for candidate in selected
            ]
            representative = (
                str(rows[0]["opportunity_key"]) if rows else "assisted-catalog"
            )
            self._persist_cycle(
                connection,
                cycle_ref=cycle_ref,
                opportunity_key=representative,
                now=now,
                prepared=len(rows),
            )
            for values in rows:
                connection.execute(sa.insert(prospect_target).values(**values))
                connection.execute(
                    sa.insert(prospect_target_history).values(
                        history_id=_history_id(str(values["target_id"]), 1, "prepared"),
                        target_id=values["target_id"],
                        event_type="prepared",
                        actor="acquisition-runtime",
                        previous_values={},
                        new_values={
                            "status": "pending_review",
                            "mail_contract_status": values["mail_contract_status"],
                            "mail_contract_failure": values["mail_contract_failure"],
                        },
                        created_at=now,
                    )
                )
            target_ids = tuple(str(row["target_id"]) for row in rows)
            family_results = tuple(self._family_result(item) for item in work)
        return CatalogPreparationResult(
            prepared=len(target_ids),
            active_before=active_before,
            active_after=active_before + len(target_ids),
            cycle_ref=cycle_ref,
            target_ids=target_ids,
            families=family_results,
        )

    def _qualify_family(
        self,
        family_key: str,
        inventory: CatalogFamilyInventory,
        *,
        directory_rows: tuple[dict[str, object], ...],
        active_sirens: set[str],
        recently_contacted: set[str],
        rejected_sirens: set[str],
        historical_target_ids: set[str],
    ) -> _FamilyWork:
        work = _FamilyWork(family_key=family_key, inventory=inventory)
        for notice in inventory.notices:
            signal = notice.signal
            if tuple(key for key, _label in signal.families) != (family_key,):
                work.refused["family_mismatch"] += 1
                continue
            departments = department_and_neighbours(signal.department)
            department_order = {value: index for index, value in enumerate(departments)}
            candidates: list[_Candidate] = []
            for original in directory_rows:
                if family_key not in set(original.get("family_keys") or ()):
                    continue
                if family_key in set(original.get("family_review_keys") or ()):
                    continue
                if str(original.get("department") or "") not in departments:
                    continue
                row = dict(original)
                siren = str(row["siren"])
                if signal.holder_siren is not None and siren == signal.holder_siren:
                    work.refused["holder"] += 1
                    continue
                site_email = published_email_evidence(row)
                if (
                    site_email is None
                    or row.get("email_verification_status") != "mx_verified"
                    or row.get("domain_validation_method") is None
                    or row.get("reverification_required_at") is not None
                ):
                    work.refused["non_site_email"] += 1
                    continue
                work.site_in_geo += 1
                if siren in recently_contacted:
                    work.refused["sent_30j"] += 1
                    continue
                if siren in rejected_sirens:
                    work.refused["rejected_history"] += 1
                    continue
                if siren in active_sirens:
                    work.refused["active_duplicate"] += 1
                    continue
                email, evidence_url = site_email
                target_id = str(
                    uuid5(NAMESPACE_URL, f"kivou:prospect:{signal.opportunity_key}:{email.casefold()}")
                )
                if target_id in historical_target_ids:
                    work.refused["historical_target"] += 1
                    continue
                row.update(
                    professional_email=email.casefold(),
                    email_source="site",
                    email_evidence_url=evidence_url,
                )
                candidates.append(
                    _Candidate(
                        family_key=family_key,
                        signal=signal,
                        directory=row,
                        target_id=target_id,
                    )
                )
            candidates.sort(
                key=lambda item: (
                    0 if _director(item.directory)[0] else 1,
                    department_order.get(
                        str(item.directory.get("department") or ""), len(department_order)
                    ),
                    str(item.directory["siren"]),
                )
            )
            work.eligible += len(candidates)
            work.pools.append((signal, tuple(candidates)))
        work.pools.sort(
            key=lambda item: (
                -len(item[1]),
                -item[0].decision_date.toordinal(),
                item[0].opportunity_key,
            )
        )
        return work

    @staticmethod
    def _allocate(
        work: list[_FamilyWork], *, remaining: int, active_sirens: set[str]
    ) -> list[_Candidate]:
        selected: list[_Candidate] = []
        selected_sirens = set(active_sirens)
        maximum_notice_rank = max((len(item.pools) for item in work), default=0)
        for notice_rank in range(maximum_notice_rank):
            queues: list[tuple[_FamilyWork, deque[_Candidate]]] = [
                (item, deque(item.pools[notice_rank][1]))
                for item in work
                if notice_rank < len(item.pools)
            ]
            while len(selected) < remaining:
                progressed = False
                for item, queue in queues:
                    while queue:
                        candidate = queue.popleft()
                        siren = str(candidate.directory["siren"])
                        if siren in selected_sirens:
                            item.refused["active_duplicate"] += 1
                            continue
                        selected.append(candidate)
                        item.queued.append(candidate)
                        selected_sirens.add(siren)
                        progressed = True
                        break
                    if len(selected) >= remaining:
                        break
                if not progressed:
                    break
            if len(selected) >= remaining:
                break
        if len(selected) >= remaining:
            for item in work:
                deferred_sirens = {
                    str(candidate.directory["siren"])
                    for _signal, candidates in item.pools
                    for candidate in candidates
                    if str(candidate.directory["siren"]) not in selected_sirens
                }
                item.deferred = len(deferred_sirens)
        return selected

    def _render_row(
        self, candidate: _Candidate, *, cycle_ref: str, now: dt.datetime
    ) -> dict[str, object]:
        signal = candidate.signal
        directory = candidate.directory
        email = str(directory["professional_email"]).casefold()
        director_name, director_title = _director(directory)
        labels = dict(signal.families)
        values: dict[str, object] = {
            "target_id": candidate.target_id,
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
            "family_key": candidate.family_key,
            "family_label": labels[candidate.family_key],
            "director_name": director_name,
            "director_title": director_title,
            "director_source": "registry" if director_name else None,
            "email_address": email,
            "email_source": "site",
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
            unsubscribe_url=link.unsubscribe_url or values["unsubscribe_url"],
        )
        rendered = self._mail_renderer({**values, "signal_city": signal.city})
        for content in (rendered.text, rendered.html):
            if set(_ATTRIBUTION_URL.findall(content)) != {link.url}:
                raise ValueError("rendered catalog attribution URL mismatch")
        values.update(
            mail_subject=rendered.subject,
            mail_text=rendered.text,
            mail_html=rendered.html,
            mail_word_count=rendered.word_count,
            mail_contract_status=rendered.contract_status,
            mail_contract_failure=rendered.contract_failure,
        )
        return values

    @staticmethod
    def _persist_cycle(
        connection: sa.Connection,
        *,
        cycle_ref: str,
        opportunity_key: str,
        now: dt.datetime,
        prepared: int,
    ) -> None:
        existing = connection.scalar(
            sa.select(acquisition_runtime_cycle.c.cycle_ref).where(
                acquisition_runtime_cycle.c.cycle_ref == cycle_ref
            )
        )
        reason = "ASSISTED_CATALOG_PENDING_REVIEW" if prepared else "ASSISTED_CATALOG_EMPTY"
        if existing is None:
            connection.execute(
                sa.insert(acquisition_runtime_cycle).values(
                    cycle_ref=cycle_ref,
                    opportunity_key=opportunity_key,
                    config_fingerprint=semantic_fingerprint(
                        {
                            "kind": "assisted-catalog-config-v1",
                            "day": now.astimezone(dt.UTC).date().isoformat(),
                        }
                    ),
                    status="SUPPRESSED",
                    next_stage=None,
                    spent_cost=0,
                    last_reason_code=reason,
                    started_at=now,
                    updated_at=now,
                    completed_at=now,
                )
            )
        else:
            connection.execute(
                sa.update(acquisition_runtime_cycle)
                .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                .values(updated_at=now, completed_at=now, last_reason_code=reason)
            )

    @staticmethod
    def _family_result(work: _FamilyWork) -> CatalogFamilyResult:
        zero_reason = (
            "qualification_error" if work.qualification_error else work.inventory.zero_reason
        )
        if not work.queued and zero_reason is None:
            zero_reason = (
                "no_site_in_geo"
                if work.site_in_geo == 0
                else "all_candidates_excluded"
                if work.eligible == 0
                else None
            )
        return CatalogFamilyResult(
            family_key=work.family_key,
            eligible=work.eligible,
            queued=len(work.queued),
            refused_by_reason=dict(sorted(work.refused.items())),
            deferred_global_cap=work.deferred,
            opportunity_keys=tuple(
                dict.fromkeys(candidate.signal.opportunity_key for candidate in work.queued)
            ),
            zero_reason=zero_reason,
        )


__all__ = [
    "AssistedCatalogPreparationService",
    "CatalogFamilyResult",
    "CatalogPreparationResult",
]
