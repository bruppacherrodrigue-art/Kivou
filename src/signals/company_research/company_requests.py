"""Durable exact-company requests, sharing the deployed enrichment pipeline."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from signals.client_value.capabilities import usable_phone
from signals.client_value.directory import directory_company
from signals.companies.schema import company_directory_enrichment_job as jobs
from signals.engagement import analytics
from signals.engagement.schema import product_event
from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import supplier_directory
from signals.supplier_directory.store import FRESHNESS, SupplierDirectoryStore
from signals.supplier_discovery.families import default_supplier_family_for_naf

COOLDOWN = dt.timedelta(hours=1)
# Longer than the systemd hard runtime bound (20 minutes), including cleanup.
LEASE = dt.timedelta(minutes=30)
MAX_ATTEMPTS = 3
MAX_PENDING_REQUESTS = 100
MAX_ACCOUNT_PENDING_REQUESTS = 5
_ACTIVE = {"queued", "running", "budget_wait"}
_FIELDS = ("website", "phone", "email")


class CompanyEnrichmentQueueFull(RuntimeError):
    """Concurrent work admission, unrelated to a plan's paid contact quota."""


def _pending():
    return sa.or_(
        jobs.c.status.in_(tuple(_ACTIVE)),
        sa.and_(jobs.c.status == "failed", jobs.c.attempt_count < MAX_ATTEMPTS),
    )


def _aware(value):
    return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value


def _validate(siren, now):
    if not re.fullmatch(r"\d{9}", siren) or now.tzinfo is None:
        raise ValueError("an exact SIREN and aware clock are required")


def _directory(connection, siren):
    return (
        connection.execute(sa.select(supplier_directory).where(supplier_directory.c.siren == siren))
        .mappings()
        .one_or_none()
    )


def _public_fields(connection, siren):
    projected = (
        directory_company(
            connection,
            siren=siren,
            legal_name=None,
            department=None,
            include_public_contact=True,
        )
        or {}
    )
    return {
        key: value
        for key, value in {
            "website": projected.get("website_url"),
            "phone": usable_phone(projected.get("phone")),
            "email": projected.get("published_email"),
        }.items()
        if value
    }


def _row(connection, siren):
    return connection.execute(sa.select(jobs).where(jobs.c.siren == siren)).mappings().one_or_none()


def _stale_fields(directory, fields, now):
    timestamps = {
        "website": "domain_observed_at",
        "phone": "phone_observed_at",
        "email": "email_observed_at",
    }
    stale = []
    for field in fields:
        observed = _aware(directory[timestamps[field]]) if directory else None
        if observed is None or not dt.timedelta(0) <= now - observed <= FRESHNESS:
            stale.append(field)
    return sorted(stale)


def enrichment_view(connection, *, siren: str | None, now: dt.datetime) -> dict:
    if siren is None or not re.fullmatch(r"\d{9}", siren):
        return {
            "state": "identity_unavailable",
            "can_refresh": False,
            "missing_fields": list(_FIELDS),
            "added_fields": [],
        }
    _validate(siren, now)
    directory = _directory(connection, siren)
    row = _row(connection, siren)
    observed = _aware(directory["enrichment_observed_at"]) if directory else None
    suppressed = directory is not None and directory["suppressed_at"] is not None
    fields = {} if suppressed else _public_fields(connection, siren)
    missing = sorted(set(_FIELDS) - fields.keys())
    stale = _stale_fields(directory, fields, now)
    fresh = observed is not None and now - observed <= FRESHNESS
    state = "ready" if fresh and not missing and not stale else "available"
    retry = None
    can_refresh = not suppressed and state != "ready"
    if row is not None:
        state = row["status"]
        retry = _aware(row["retry_after"])
        if state == "failed" and row["attempt_count"] < MAX_ATTEMPTS and retry is not None:
            state = "queued"
        if state in {"ready", "partial"} and not fresh:
            state = "available"
        elif state in {"ready", "partial"} and not missing and not stale:
            # A later winner/mirror pass may complete a previously partial profile.
            state = "ready"
        elif state == "ready" and (missing or stale):
            state = "partial"
        cooldown = _aware(row["finished_at"] or row["queued_at"]) + COOLDOWN
        can_refresh = (
            not suppressed and state not in _ACTIVE and state != "ready" and now >= cooldown
        )
        if state not in _ACTIVE and not can_refresh and state != "ready":
            retry = max(cooldown, retry) if retry else cooldown
    result = {
        "state": "failed" if suppressed else state,
        "can_refresh": can_refresh,
        "missing_fields": missing,
        "stale_fields": stale,
        "added_fields": list(row["added_fields"] or []) if row else [],
    }
    if observed:
        result["observed_at"] = observed.isoformat()
    if retry:
        result["retry_after"] = retry.isoformat()
    if row:
        result["job_id"] = row["job_id"]
        for public, stored in (
            ("requested_at", "queued_at"),
            ("started_at", "started_at"),
            ("finished_at", "finished_at"),
        ):
            if row[stored] is not None:
                result[public] = _aware(row[stored]).isoformat()
        if row["outcome"]:
            result["outcome"] = row["outcome"]
    return result


def request_enrichment(
    connection,
    *,
    siren: str,
    now: dt.datetime,
    account_id: str | None = None,
) -> dict:
    """Only persist a click; shared jobs never reserve decision-maker quota."""
    _validate(siren, now)
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": "company-enrichment-admission"},
        )
    elif connection.dialect.name == "sqlite":
        # Begin a real write transaction before counting; no row is changed.
        connection.execute(sa.update(jobs).where(sa.false()).values(updated_at=now))
    before = enrichment_view(connection, siren=siren, now=now)
    if not before["can_refresh"]:
        return {**before, "queued": False}
    pending = connection.scalar(sa.select(sa.func.count()).select_from(jobs).where(_pending()))
    if pending >= MAX_PENDING_REQUESTS:
        raise CompanyEnrichmentQueueFull("global_pending_limit")
    if account_id is not None:
        owned = sa.exists(
            sa.select(sa.literal(1))
            .select_from(product_event)
            .where(
                product_event.c.account_id == account_id,
                product_event.c.event_type == "company_enrichment_requested",
                product_event.c.properties["job_id"].as_string() == jobs.c.job_id,
            )
        )
        account_pending = connection.scalar(
            sa.select(sa.func.count()).select_from(jobs).where(_pending(), owned)
        )
        if account_pending >= MAX_ACCOUNT_PENDING_REQUESTS:
            raise CompanyEnrichmentQueueFull("account_pending_limit")
    directory = _directory(connection, siren)
    values = {
        "siren": siren,
        "job_id": uuid.uuid4().hex,
        "status": "queued",
        "attempt_count": 0,
        "queued_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "claimed_by": None,
        "lease_id": None,
        "lease_expires_at": None,
        "retry_after": None,
        "error_code": None,
        "outcome": None,
        "added_fields": [],
        "baseline_fields": _public_fields(connection, siren),
        "previous_observed_at": directory["enrichment_observed_at"] if directory else None,
    }
    previous = _row(connection, siren)
    if previous:
        changed = (
            connection.execute(
                sa.update(jobs)
                .where(
                    jobs.c.siren == siren,
                    jobs.c.job_id == previous["job_id"],
                    jobs.c.status.not_in(tuple(_ACTIVE)),
                )
                .values(**values)
            ).rowcount
            == 1
        )
    else:
        insert_if_absent(connection, jobs, values)
        changed = _row(connection, siren)["job_id"] == values["job_id"]
    if changed and account_id is not None:
        analytics.record(
            connection,
            account_id=account_id,
            event_type="company_enrichment_requested",
            occurred_at=now,
            properties={"job_id": values["job_id"], "siren": siren},
        )
    return {**enrichment_view(connection, siren=siren, now=now), "queued": changed}


@dataclass(frozen=True)
class CompanyRequestBatch:
    processed: int = 0
    completed: int = 0
    cached: int = 0
    failed: int = 0
    cost_usd: Decimal = Decimal("0")
    budget_usage: str | None = None


def _claim(engine, *, now, worker_ref, limit):
    due = sa.and_(
        jobs.c.attempt_count < MAX_ATTEMPTS,
        sa.or_(
            sa.and_(
                jobs.c.status.in_(("queued", "failed", "budget_wait")),
                sa.or_(jobs.c.retry_after.is_(None), jobs.c.retry_after <= now),
            ),
            sa.and_(jobs.c.status == "running", jobs.c.lease_expires_at <= now),
        ),
    )
    with engine.begin() as connection:
        # A third crashed attempt must become a visible terminal failure.
        connection.execute(
            sa.update(jobs)
            .where(
                jobs.c.status == "running",
                jobs.c.lease_expires_at <= now,
                jobs.c.attempt_count >= MAX_ATTEMPTS,
            )
            .values(
                status="failed",
                error_code="worker_interrupted",
                finished_at=now,
                updated_at=now,
                lease_id=None,
                lease_expires_at=None,
            )
        )
        statement = sa.select(jobs).where(due).order_by(jobs.c.queued_at, jobs.c.siren).limit(limit)
        if connection.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        rows = connection.execute(statement).mappings().all()
        claimed = []
        for row in rows:
            lease_id = uuid.uuid4().hex
            values = {
                "status": "running",
                "attempt_count": row["attempt_count"] + 1,
                "claimed_by": worker_ref,
                "lease_id": lease_id,
                "lease_expires_at": now + LEASE,
                "started_at": now,
                "finished_at": None,
                "updated_at": now,
                "error_code": None,
            }
            if (
                connection.execute(
                    sa.update(jobs)
                    .where(
                        jobs.c.siren == row["siren"],
                        jobs.c.job_id == row["job_id"],
                        due,
                    )
                    .values(**values)
                ).rowcount
                == 1
            ):
                claimed.append({**row, **values})
        return claimed


def _finish(engine, row, now, **values):
    with engine.begin() as connection:
        return (
            connection.execute(
                sa.update(jobs)
                .where(
                    jobs.c.siren == row["siren"],
                    jobs.c.job_id == row["job_id"],
                    jobs.c.lease_id == row["lease_id"],
                    jobs.c.status == "running",
                )
                .values(updated_at=now, lease_id=None, lease_expires_at=None, **values)
            ).rowcount
            == 1
        )


def _next_budget_day(now):
    zone = ZoneInfo("Europe/Zurich")
    tomorrow = now.astimezone(zone).date() + dt.timedelta(days=1)
    return dt.datetime.combine(tomorrow, dt.time(), tzinfo=zone).astimezone(dt.UTC)


def run_company_enrichment_requests(
    engine,
    *,
    now,
    worker_ref,
    identity_source,
    enrichment_service,
    limit=5,
    clock=None,
) -> CompanyRequestBatch:
    """Process only explicit requests, with no winner age/watermark dependency."""
    if now.tzinfo is None or not 1 <= limit <= 25 or not re.fullmatch(r"[\w.:-]{1,64}", worker_ref):
        raise ValueError("invalid bounded company-request worker arguments")
    processed = completed = failed = cached = 0
    cost = Decimal("0")
    budget_usage = None
    current_time = clock or (lambda: now)
    directory = SupplierDirectoryStore(engine, clock=current_time)
    # Claim one at a time so unprocessed rows are never stranded when budget ends.
    for _ in range(limit):
        claims = _claim(engine, now=current_time(), worker_ref=worker_ref, limit=1)
        if not claims:
            break
        row = claims[0]
        processed += 1
        try:
            before = directory.get(row["siren"])
            if before is not None and before.suppressed_at is not None:
                raise ValueError("suppressed")
            # Another worker may have supplied a durable result since the click.
            satisfied = (
                before is not None
                and before.enrichment_observed_at is not None
                and before.enrichment_observed_at >= _aware(row["queued_at"])
            )
            if satisfied:
                cached += 1
            else:
                identity = identity_source(row["siren"])
                if identity is None or identity.siren != row["siren"]:
                    raise ValueError("unresolved_exact_identity")
                directory.upsert_identity(
                    siren=identity.siren,
                    legal_name=identity.legal_name,
                    naf_code=identity.naf_code,
                    family_key=default_supplier_family_for_naf(identity.naf_code) or "",
                    department=identity.department,
                    city=identity.city,
                    employees=identity.employees,
                    observed_at=current_time(),
                    naf_label=identity.naf_label,
                    preserve_known_fields=True,
                )
                result = enrichment_service.enrich(
                    identity.siren,
                    directors_raw=identity.directors_raw,
                    force=True,
                )
                cost += result.cost_usd
                cached += int(result.cached)
            after = directory.get(row["siren"])
            if (
                after is None
                or after.suppressed_at is not None
                or after.enrichment_observed_at is None
                or after.enrichment_observed_at < _aware(row["queued_at"])
            ):
                raise ValueError("result_not_persisted")
            with engine.connect() as connection:
                fields = _public_fields(connection, row["siren"])
            added = sorted(set(fields) - set(row["baseline_fields"]))
            changed = any(
                value != row["baseline_fields"].get(field) for field, value in fields.items()
            )
            finished = current_time()
            completed += int(
                _finish(
                    engine,
                    row,
                    finished,
                    status="ready"
                    if set(_FIELDS) <= fields.keys()
                    and not _stale_fields(after.model_dump(), fields, finished)
                    else "partial",
                    finished_at=finished,
                    retry_after=None,
                    added_fields=added,
                    outcome="enriched" if changed else "no_change",
                )
            )
        except DailyModelBudgetExhausted as error:
            finished = current_time()
            _finish(
                engine,
                row,
                finished,
                status="budget_wait",
                retry_after=_next_budget_day(finished),
                attempt_count=max(0, row["attempt_count"] - 1),
                error_code="daily_budget_reached",
            )
            budget_usage = error.usage
            break
        except Exception:  # noqa: BLE001 - isolate one bounded company/provider failure
            finished = current_time()
            _finish(
                engine,
                row,
                finished,
                status="failed",
                finished_at=finished,
                retry_after=finished + dt.timedelta(minutes=10),
                error_code="company_enrichment_failed",
            )
            failed += 1
    return CompanyRequestBatch(processed, completed, cached, failed, cost, budget_usage)
