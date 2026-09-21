"""Auditable authorization and read-only checks before paid Apollo census calls."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.engine import Connection, Engine

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusLimits
from signals.acquisition_programs.official_company import MATCHER_VERSION, OfficialSourceConfig
from signals.compliance.milomail_rules import MILOMAIL_PURPOSE, POLICY_VERSION
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    SuppressionIdentityUnavailable,
)
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.database import alembic_config
from signals.persistence.schema import (
    acquisition_census_call,
    acquisition_census_partition,
    acquisition_census_permit,
    acquisition_census_run,
    acquisition_contact_suppression,
    acquisition_program,
)

HEAD = "0073_milomail_a0_prepaid"
APOLLO_ORG_SEARCH_PRICING_URL = "https://docs.apollo.io/reference/organization-search"


def database_revisions(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        if not sa.inspect(connection).has_table("alembic_version"):
            return ()
        return tuple(sorted(connection.execute(sa.text(
            "SELECT version_num FROM alembic_version"
        )).scalars()))


def migration_ready(engine: Engine) -> bool:
    return (database_revisions(engine) == (HEAD,) and
            ScriptDirectory.from_config(alembic_config(engine)).get_heads() == [HEAD])


def database_identity(engine: Engine) -> tuple[str, str, str]:
    """Logical identity and redacted host fingerprint; never expose URL credentials."""
    url = engine.url
    host = url.host or "local"
    name = url.database or ""
    if not name:
        raise ValueError("database name is missing")
    if engine.dialect.name == "sqlite" and name != ":memory:" and not Path(name).exists():
        raise ValueError("preflight cannot create a missing SQLite database")
    host_hash = hashlib.sha256(f"{host}:{url.port or 0}".encode()).hexdigest()[:16]
    return f"{url.get_backend_name()}:{host_hash}:{name}", host_hash, name


class DatabaseAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    database_id: str = Field(min_length=8, max_length=128)
    environment: Literal["test", "staging", "authorized-census"]
    issued_by_reference: str = Field(min_length=3, max_length=128)
    expires_at: dt.datetime

    @model_validator(mode="after")
    def expiration_is_aware(self) -> DatabaseAuthorization:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("database authorization expiration must be timezone-aware")
        return self

    def check_identity(self, engine: Engine, *, at: dt.datetime) -> None:
        if self.expires_at <= at or self.database_id != database_identity(engine)[0]:
            raise ValueError("database authorization expired or identity changed")
        declared = (
            os.environ.get("KIVOU_ENVIRONMENT", "").casefold(),
            os.environ.get("KIVOU_ACQUISITION_ENVIRONMENT", "").casefold(),
            os.environ.get("KIVOU_FOUNDER_ENVIRONMENT", "").casefold(),
        )
        production_marker = re.compile(r"(^|[-_.])(?:prod|production|live)(?:$|[-_.])")
        logical_name = engine.url.database or ""
        host = engine.url.host or ""
        if (any(production_marker.search(value) for value in (*declared, logical_name.casefold(),
                                                               host.casefold()))):
            raise ValueError("production environment or database is forbidden")
        if self.environment == "test":
            if engine.dialect.name != "sqlite":
                raise ValueError("test authorization requires a disposable SQLite database")
        elif (engine.dialect.name != "postgresql" or
              os.environ.get("KIVOU_ACQUISITION_ENVIRONMENT", "").upper() != "STAGING"):
            raise ValueError("real census database requires explicit STAGING identity")

    def check(self, engine: Engine, *, at: dt.datetime) -> None:
        self.check_identity(engine, at=at)
        if not migration_ready(engine):
            raise ValueError("authorized database is not at the reviewed migration head")


class ApolloCreditPricing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    currency: Literal["CHF"]
    price_per_credit: Decimal | None = Field(default=None, gt=0)
    billing_basis: Literal["PRICED", "PREPAID_SHARED_POOL"] = "PRICED"
    max_incremental_charge_chf: Decimal | None = Field(default=None, ge=0)
    auto_top_up_allowed: bool | None = None
    overage_allowed: bool | None = None
    verified_at: dt.datetime
    source_type: Literal["ACCOUNT", "APOLLO_DOCUMENTATION", "OPERATOR_ATTESTATION"]
    source_reference: str = Field(min_length=3, max_length=256)
    plan_name: str = Field(min_length=1, max_length=128)
    verified_by_reference: str = Field(min_length=3, max_length=128)
    org_search_credits: int = Field(ge=1)
    org_enrichment_credits: int = Field(ge=1)
    people_search_credits: int = Field(ge=0)
    person_enrichment_credits_max: int = Field(ge=1)
    # Conservative attested minimum across every operation's credit pool.
    credit_balance: int | None = Field(default=None, ge=0)
    credit_balance_observed_at: dt.datetime | None = None
    rate_limits_per_minute: dict[str, int] = Field(default_factory=dict)
    rate_limit_reference: str | None = None
    credit_pools_by_operation: dict[str, str]

    @model_validator(mode="after")
    def dates_are_aware(self) -> ApolloCreditPricing:
        for value in (self.verified_at, self.credit_balance_observed_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("pricing dates must be timezone-aware")
        return self

    def check(self, limits: CensusLimits, *, at: dt.datetime,
              phase: str | None = None) -> None:
        if self.verified_at > at or at - self.verified_at > dt.timedelta(days=30):
            raise ValueError("Apollo pricing is stale")
        if self.billing_basis == "PREPAID_SHARED_POOL":
            if (phase != "COVERAGE_A0" or self.price_per_credit is not None or
                    self.max_incremental_charge_chf != 0 or
                    self.auto_top_up_allowed is not False or
                    self.overage_allowed is not False):
                raise ValueError("prepaid A0 requires no top-up, overage or incremental charge")
            limits.require_run_authorization(phase="COVERAGE_A0")
        elif self.price_per_credit is None:
            raise ValueError("Apollo unit price is missing")
        else:
            if self.price_per_credit > limits.chf_per_credit_ceiling:
                raise ValueError("Apollo price exceeds configured ceiling")
            if self.price_per_credit * limits.max_apollo_credits > limits.max_cost_chf:
                raise ValueError("Apollo CHF and credit caps are inconsistent")
        if (self.org_search_credits > limits.credits_org_search_page or
                self.org_enrichment_credits > limits.credits_org_enrichment or
                self.people_search_credits > limits.credits_people_search or
                self.person_enrichment_credits_max > limits.credits_person_enrichment_max):
            raise ValueError("configured Apollo credit reservations underestimate charges")
        if self.credit_balance is None or self.credit_balance_observed_at is None:
            raise ValueError("Apollo credit balance is not verified")
        if at - self.credit_balance_observed_at > dt.timedelta(days=1):
            raise ValueError("Apollo credit balance is stale")
        if self.credit_balance < limits.max_apollo_credits:
            raise ValueError("Apollo credit balance below authorization cap")
        required = {"ORG_SEARCH", "ORG_ENRICH", "PEOPLE_SEARCH", "PERSON_ENRICH"}
        if (not required <= set(self.rate_limits_per_minute) or
                any(self.rate_limits_per_minute[key] <= 0 for key in required) or
                not self.rate_limit_reference):
            raise ValueError("Apollo rate limits are not verified for every operation")
        if (set(self.credit_pools_by_operation) != required or
                any(not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", pool)
                    for pool in self.credit_pools_by_operation.values())):
            raise ValueError("Apollo credit pool mapping is not verified")


def account_capacity_ready(account: ApolloAccountState | None,
                           pricing: ApolloCreditPricing | None,
                           limits: CensusLimits) -> bool:
    return bool(
        account and pricing and account.credential_valid and
        account.usage_stats_available and account.rate_stats_available and
        all(account.credit_balances.get(pool, -1) >= limits.max_apollo_credits
            for pool in set(pricing.credit_pools_by_operation.values()))
    )


def configuration_hash(*, census_id: str, limits: CensusLimits,
                       partitions: tuple[dict, ...], pricing: ApolloCreditPricing,
                       source_config: OfficialSourceConfig | None = None) -> str:
    payload = {
        "census_id": census_id,
        "limits": limits.model_dump(mode="json"),
        "partitions": sorted((p["partition_id"], p["filter_signature"]) for p in partitions),
        "pricing": pricing.model_dump(mode="json", exclude={
            "credit_balance", "credit_balance_observed_at",
        }),
        "official_source": (source_config or OfficialSourceConfig()).model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ExecutionPermit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permit_id: str = Field(min_length=8, max_length=64)
    census_id: str = Field(min_length=8, max_length=64)
    program_key: Literal["milomail"] = "milomail"
    phase: Literal["COVERAGE", "COVERAGE_A0", "ENRICHMENT"]
    environment: Literal["test", "staging", "authorized-census"]
    database_id: str = Field(min_length=8, max_length=128)
    country: Literal["FR"] = "FR"
    allowed_partitions: tuple[str, ...] = Field(min_length=1)
    max_pages: int = Field(default=0, ge=0)
    max_candidates: int = Field(default=0, ge=0)
    max_enrichments: int = Field(default=0, ge=0)
    max_credits: int = Field(gt=0)
    max_cost_chf: Decimal = Field(ge=0)
    price_chf_per_credit: Decimal | None = Field(default=None, gt=0)
    billing_basis: Literal["PRICED", "PREPAID_SHARED_POOL"] = "PRICED"
    apollo_secret_ref: str | None = Field(default=None, max_length=80)
    pricing_reference: str = Field(min_length=3, max_length=256)
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_by_reference: str = Field(min_length=3, max_length=128)
    issued_at: dt.datetime
    valid_from: dt.datetime
    expires_at: dt.datetime
    status: Literal["ACTIVE", "REVOKED"] = "ACTIVE"

    @model_validator(mode="after")
    def valid_window_and_caps(self) -> ExecutionPermit:
        if any(value.tzinfo is None or value.utcoffset() is None for value in (
            self.issued_at, self.valid_from, self.expires_at,
        )) or not self.issued_at <= self.valid_from < self.expires_at:
            raise ValueError("permit validity window is invalid")
        if self.phase == "COVERAGE" and (self.max_pages == 0 or self.max_candidates == 0 or
                                          self.max_enrichments != 0):
            raise ValueError("coverage permit must allow pages but no enrichment")
        if self.phase == "ENRICHMENT" and (self.max_enrichments == 0 or self.max_pages != 0):
            raise ValueError("enrichment permit must allow enrichments but no pages")
        if self.phase == "COVERAGE_A0":
            if (self.environment != "staging" or
                    not self.database_id.endswith(":kivou_milomail_census_a0") or
                    self.max_pages != self.max_credits or self.max_credits != 9 or
                    self.max_candidates != 225 or self.max_enrichments != 0 or
                    len(self.allowed_partitions) != 9 or
                    self.max_cost_chf != 0 or self.price_chf_per_credit is not None or
                    self.billing_basis != "PREPAID_SHARED_POOL" or
                    self.apollo_secret_ref != "KIVOU_APOLLO_API_KEY" or
                    self.expires_at - self.issued_at > dt.timedelta(hours=4)):
                raise ValueError("A0 permit must be isolated, short-lived and capped")
        elif (self.billing_basis != "PRICED" or self.price_chf_per_credit is None or
              self.max_credits * self.price_chf_per_credit > self.max_cost_chf or
              self.apollo_secret_ref not in (None, "MILOMAIL_CENSUS_APOLLO_API_KEY")):
            raise ValueError("priced permit terms are inconsistent")
        return self


class PermitStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def issue(self, permit: ExecutionPermit, *, database: DatabaseAuthorization,
              pricing: ApolloCreditPricing, limits: CensusLimits, at: dt.datetime,
              source_config: OfficialSourceConfig | None = None) -> None:
        database.check(self.engine, at=at)
        pricing.check(limits, at=at, phase=permit.phase)
        self.validate_terms(permit, pricing=pricing, limits=limits)
        if permit.database_id != database.database_id or permit.environment != database.environment:
            raise ValueError("permit database or environment mismatch")
        if permit.expires_at > database.expires_at:
            raise ValueError("permit cannot outlive database authorization")
        if permit.issued_at > at or permit.expires_at <= at:
            raise ValueError("permit not currently valid")
        with self.engine.begin() as connection:
            run = connection.execute(sa.select(acquisition_census_run).where(
                acquisition_census_run.c.census_id == permit.census_id,
            )).mappings().one()
            program = connection.execute(sa.select(acquisition_program).where(
                acquisition_program.c.program_id == run["program_id"],
            )).mappings().one()
            if program["program_key"] != "milomail" or program["enabled"] or program["mode"] != "SHADOW":
                raise ValueError("permit requires disabled SHADOW Milo Mail program")
            known = {row[0] for row in connection.execute(sa.select(
                acquisition_census_partition.c.partition_id,
            ).where(acquisition_census_partition.c.census_id == permit.census_id))}
            if not set(permit.allowed_partitions) <= known:
                raise ValueError("permit contains unknown partition")
            partitions = tuple(dict(row) for row in connection.execute(sa.select(
                acquisition_census_partition.c.partition_id,
                acquisition_census_partition.c.filter_signature,
            ).where(acquisition_census_partition.c.census_id == permit.census_id)).mappings())
            if permit.configuration_hash != configuration_hash(
                census_id=permit.census_id, limits=limits, partitions=partitions,
                pricing=pricing, source_config=source_config,
            ):
                raise ValueError("permit configuration hash does not match current plan")
            if not insert_if_absent(connection, acquisition_census_permit,
                                    permit.model_dump(mode="python")):
                previous = connection.execute(sa.select(acquisition_census_permit).where(
                    acquisition_census_permit.c.permit_id == permit.permit_id,
                )).mappings().one()
                normalized = {key: previous[key] for key in ExecutionPermit.model_fields}
                for field in ("issued_at", "valid_from", "expires_at"):
                    normalized[field] = normalized[field].replace(tzinfo=dt.UTC)
                if ExecutionPermit.model_validate(normalized) != permit:
                    raise ValueError("permit identity conflict")

    @staticmethod
    def validate_terms(permit: ExecutionPermit, *, pricing: ApolloCreditPricing,
                       limits: CensusLimits) -> None:
        if (permit.price_chf_per_credit != pricing.price_per_credit or
                permit.billing_basis != pricing.billing_basis or
                permit.pricing_reference != pricing.source_reference):
            raise ValueError("permit price or pricing evidence differs from verified pricing")
        if (permit.max_pages > limits.max_pages or
                permit.max_candidates > limits.max_candidates or
                permit.max_enrichments > limits.max_enrichments or
                permit.max_credits > limits.max_apollo_credits or
                permit.max_cost_chf > limits.max_cost_chf or
                len(permit.allowed_partitions) > limits.max_partitions):
            raise ValueError("permit exceeds configured census limits")
        if (pricing.price_per_credit is not None and
                permit.max_credits * pricing.price_per_credit > permit.max_cost_chf):
            raise ValueError("permit CHF cap understates verified maximum cost")
        if permit.phase == "COVERAGE_A0":
            limits.require_run_authorization(phase="COVERAGE_A0")
            if (permit.allowed_partitions is None or len(permit.allowed_partitions) != 9 or
                    permit.apollo_secret_ref != "KIVOU_APOLLO_API_KEY"):
                raise ValueError("shared pool is only allowed for exact A0")

    def revoke(self, permit_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(sa.update(acquisition_census_permit).where(
                acquisition_census_permit.c.permit_id == permit_id,
            ).values(status="REVOKED"))

    @staticmethod
    def check_call(connection: Connection, *, permit_id: str | None, census_id: str,
                   phase: str, kind: str, partition_id: str | None,
                   credits: int, candidate_slots: int, at: dt.datetime,
                   configuration_hash_value: str, database_id: str,
                   check_capacity: bool = True) -> None:
        if not permit_id:
            raise ValueError("execution permit is mandatory before Apollo calls")
        permit = connection.execute(sa.select(acquisition_census_permit).where(
            acquisition_census_permit.c.permit_id == permit_id,
        ).with_for_update()).mappings().one_or_none()
        if (permit is None or permit["status"] != "ACTIVE" or permit["census_id"] != census_id or
                permit["program_key"] != "milomail" or permit["country"] != "FR" or
                permit["phase"] != phase or permit["database_id"] != database_id or
                permit["configuration_hash"] != configuration_hash_value or
                permit["valid_from"].replace(tzinfo=dt.UTC) > at or
                permit["expires_at"].replace(tzinfo=dt.UTC) <= at or
                (partition_id is not None and partition_id not in permit["allowed_partitions"])):
            raise ValueError("execution permit invalid for this call")
        pages = 1 if kind == "ORG_SEARCH" else 0
        enrichments = 1 if kind in {"ORG_ENRICH", "PERSON_ENRICH"} else 0
        if (phase == "COVERAGE_A0" and kind != "ORG_SEARCH") or (
            phase == "COVERAGE" and kind not in {"ORG_SEARCH", "PEOPLE_SEARCH"}) or (
            phase == "ENRICHMENT" and kind == "ORG_SEARCH"
        ):
            raise ValueError("Apollo operation is outside permit phase")
        if not check_capacity:
            return
        usage = connection.execute(sa.select(
            sa.func.coalesce(sa.func.sum(acquisition_census_call.c.reserved_credits), 0),
            sa.func.coalesce(sa.func.sum(acquisition_census_call.c.candidate_slots), 0),
            sa.func.coalesce(sa.func.sum(sa.case((acquisition_census_call.c.kind == "ORG_SEARCH", 1), else_=0)), 0),
            sa.func.coalesce(sa.func.sum(sa.case((acquisition_census_call.c.kind.in_(("ORG_ENRICH", "PERSON_ENRICH")), 1), else_=0)), 0),
        ).where(acquisition_census_call.c.permit_id == permit_id)).one()
        if (usage[0] + credits > permit["max_credits"] or
                usage[1] + candidate_slots > permit["max_candidates"] or
                usage[2] + pages > permit["max_pages"] or
                usage[3] + enrichments > permit["max_enrichments"] or
                (permit["price_chf_per_credit"] is not None and
                 Decimal(usage[0] + credits) * permit["price_chf_per_credit"] >
                 permit["max_cost_chf"])):
            from signals.acquisition_programs.census import CensusBudgetExceeded

            raise CensusBudgetExceeded("execution permit cap exhausted")


def preflight(engine: Engine, *, census_id: str, limits: CensusLimits,
              database: DatabaseAuthorization | None,
              pricing: ApolloCreditPricing | None, apollo_key_present: bool,
              source_enabled: bool, source_requests: int, source_available: bool,
              suppression_keyring: SuppressionIdentityKeyring | None,
              apollo_account: ApolloAccountState | None,
              at: dt.datetime, permit_id: str | None = None,
              code_sha: str | None = None, app_version: str | None = None,
              source_rate_limit_per_minute: int | None = None,
              source_cache_ttl_days: int | None = None,
              source_config: OfficialSourceConfig | None = None,
              phase: Literal["COVERAGE", "COVERAGE_A0", "ENRICHMENT"] | None = None) -> dict:
    """Read-only assessment; no Apollo, official-source or Instantly request."""
    checks: dict[str, str] = {}
    identity, host_hash, name = database_identity(engine)
    checks["database"] = "MISSING_AUTHORIZATION"
    if database:
        try:
            database.check(engine, at=at)
            checks["database"] = "READY"
        except ValueError:
            checks["database"] = "UNAUTHORIZED_EXPIRED_OR_DIVERGED"
    if phase == "COVERAGE_A0" and (
        database is None or database.environment != "staging" or
        engine.url.database != "kivou_milomail_census_a0"
    ):
        checks["database"] = "A0_REQUIRES_ISOLATED_STAGING_DATABASE"
    revisions = database_revisions(engine)
    revision = revisions[0] if len(revisions) == 1 else None
    checks["migration"] = "READY" if migration_ready(engine) else "MISSING_OR_DIVERGED"
    partitions: tuple[dict, ...] = ()
    with engine.connect() as connection:
        if checks["migration"] == "READY":
            run = connection.execute(sa.select(acquisition_census_run).where(
                acquisition_census_run.c.census_id == census_id,
            )).mappings().one_or_none()
            program = None if run is None else connection.execute(sa.select(acquisition_program).where(
                acquisition_program.c.program_id == run["program_id"],
            )).mappings().one_or_none()
            partitions = tuple(dict(row) for row in connection.execute(sa.select(
                acquisition_census_partition.c.partition_id,
                acquisition_census_partition.c.filter_signature,
                acquisition_census_partition.c.status,
            ).where(acquisition_census_partition.c.census_id == census_id)).mappings())
            pending_calls = connection.scalar(sa.select(sa.func.count()).select_from(
                acquisition_census_call,
            ).where(acquisition_census_call.c.census_id == census_id,
                    acquisition_census_call.c.status != "COMPLETED")) or 0
            reserved = run["credits_reserved"] if run else 0
            try:
                retained_versions = tuple(connection.execute(sa.select(
                    acquisition_contact_suppression.c.identity_key_version,
                ).where(acquisition_contact_suppression.c.scope == MILOMAIL_SUPPRESSION_SCOPE)
                 .distinct()).scalars())
                suppression_accessible = True
            except sa.exc.SQLAlchemyError:
                suppression_accessible = False
                retained_versions = ()
        else:
            run = program = None
            pending_calls = reserved = 0
            suppression_accessible = False
            retained_versions = ()
    count = len(partitions)
    checks["partitions"] = "READY" if count > 0 else "MISSING"
    checks["program"] = "READY" if program and program["program_key"] == "milomail" and not program["enabled"] and program["mode"] == "SHADOW" and program["config_snapshot"]["max_daily_contacts"] == 0 and program["config_snapshot"]["max_monthly_contacts"] == 0 and Decimal(program["config_snapshot"]["max_cost_chf"]) == 0 else "MISSING_OR_UNSAFE"
    checks["policy"] = "READY" if program and program["config_snapshot"]["policy_version"] == POLICY_VERSION else "VERSION_MISMATCH"
    checks["apollo_key"] = "READY" if apollo_key_present else "CREDENTIAL_MISSING"
    checks["apollo_account"] = (
        "READY" if account_capacity_ready(apollo_account, pricing, limits)
        else "NOT_PROBED_OR_CAPACITY_UNKNOWN"
    )
    checks["pricing"] = "MISSING"
    if pricing:
        try:
            pricing.check(limits, at=at, phase=phase)
            checks["pricing"] = "READY"
        except ValueError as error:
            checks["pricing"] = (
                "STALE" if "stale" in str(error) else
                "CREDIT_BALANCE_UNKNOWN" if "balance" in str(error) else
                "RATE_LIMIT_UNKNOWN" if "rate limits" in str(error) else
                "INCOHERENT"
            )
    checks["limits"] = "READY"
    try:
        limits.require_run_authorization(phase=phase)
    except ValueError:
        checks["limits"] = "ZERO_OR_DISABLED"
    checks["official_source"] = (
        "CAP_EXHAUSTED" if run and run["official_requests_reserved"] >= source_requests
        and source_enabled and source_requests > 0
        else "READY" if source_enabled and source_requests > 0 and source_available
        else "CONFIGURED_NOT_PROBED" if source_enabled and source_requests > 0 else "DISABLED"
    )
    scope_constraint = any(
        MILOMAIL_SUPPRESSION_SCOPE in str(row.get("sqltext", ""))
        for row in sa.inspect(engine).get_check_constraints("acquisition_contact_suppression")
    ) if checks["migration"] == "READY" else False
    suppression_ready = bool(suppression_keyring and suppression_accessible and scope_constraint)
    if suppression_ready and suppression_keyring:
        try:
            suppression_keyring.require_versions_covered(retained_versions)
        except SuppressionIdentityUnavailable:
            suppression_ready = False
    checks["suppression"] = "READY" if suppression_ready else "CREDENTIAL_SCOPE_OR_ACCESS_MISSING"
    checks["pending_calls"] = "CLEAR" if pending_calls == 0 else "REVIEW_REQUIRED"
    if phase in {"COVERAGE", "COVERAGE_A0"}:
        checks["postgresql"] = (
            "READY" if engine.dialect.name == "postgresql" else "NON_POSTGRESQL_DATABASE"
        )
        checks["nine_partitions"] = "READY" if count == 9 else "PARTITION_COUNT_MISMATCH"
        checks["official_rate"] = (
            "READY" if source_rate_limit_per_minute is not None and
            source_rate_limit_per_minute <= 60 else "RATE_CAP_ABOVE_60_OR_UNKNOWN"
        )
        checks["no_enrichment"] = (
            "READY" if limits.max_enrichments == 0 else "ENRICHMENT_CAP_NONZERO"
        )
        checks["credit_caps"] = (
            "READY" if limits.max_apollo_credits > 0 and (
                limits.max_cost_chf > 0 or
                (phase == "COVERAGE_A0" and pricing is not None and
                 pricing.billing_basis == "PREPAID_SHARED_POOL"))
            else "ZERO_CREDIT_OR_CHF_CAP"
        )
        # The current organization-search endpoint charges one credit per page.
        checks["operation_cost"] = (
            "READY" if checks["credit_caps"] == "READY" and checks["pricing"] == "READY"
            else "ORG_SEARCH_REQUIRES_CREDIT" if checks["credit_caps"] != "READY"
            else "PRICE_OR_CREDIT_CATEGORY_UNVERIFIED"
        )
    config_digest = configuration_hash(
        census_id=census_id, limits=limits, partitions=partitions, pricing=pricing,
        source_config=source_config,
    ) if pricing and partitions else None
    permit = None
    if permit_id and checks["migration"] == "READY" and config_digest and database:
        with engine.connect() as connection:
            permit = connection.execute(sa.select(acquisition_census_permit).where(
                acquisition_census_permit.c.permit_id == permit_id,
            )).mappings().one_or_none()
    permit_ready = bool(permit and database and permit["status"] == "ACTIVE" and
                        permit["census_id"] == census_id and
                        (phase is None or permit["phase"] == phase) and
                        permit["database_id"] == database.database_id and
                        permit["environment"] == database.environment and
                        permit["configuration_hash"] == config_digest and
                        permit["valid_from"].replace(tzinfo=dt.UTC) <= at <
                        permit["expires_at"].replace(tzinfo=dt.UTC))
    permit_remaining: dict[str, int | str] | None = None
    if permit_ready and permit and pricing:
        try:
            PermitStore.validate_terms(
                ExecutionPermit.model_validate({
                    **dict(permit),
                    **{key: permit[key].replace(tzinfo=dt.UTC) for key in
                       ("issued_at", "valid_from", "expires_at")},
                }), pricing=pricing, limits=limits,
            )
            with engine.connect() as connection:
                calls = connection.execute(sa.select(
                    acquisition_census_call.c.kind,
                    acquisition_census_call.c.reserved_credits,
                    acquisition_census_call.c.candidate_slots,
                ).where(acquisition_census_call.c.permit_id == permit_id)).all()
            used_credits = sum(row.reserved_credits for row in calls)
            remaining_credits = permit["max_credits"] - used_credits
            remaining_pages = permit["max_pages"] - sum(row.kind == "ORG_SEARCH" for row in calls)
            remaining_candidates = permit["max_candidates"] - sum(row.candidate_slots for row in calls)
            remaining_enrichments = permit["max_enrichments"] - sum(
                row.kind in {"ORG_ENRICH", "PERSON_ENRICH"} for row in calls
            )
            remaining_cost = (permit["max_cost_chf"] -
                              Decimal(used_credits) * pricing.price_per_credit
                              if pricing.price_per_credit is not None else Decimal(0))
            permit_remaining = {
                "credits": remaining_credits,
                "pages": remaining_pages,
                "candidates": remaining_candidates,
                "enrichments": remaining_enrichments,
                "cost_chf": str(remaining_cost),
            }
            if (remaining_credits <= 0 or
                    (pricing.price_per_credit is not None and remaining_cost <= 0) or
                    (permit["phase"] in {"COVERAGE", "COVERAGE_A0"} and
                     (remaining_pages <= 0 or remaining_candidates <= 0)) or
                    (permit["phase"] == "ENRICHMENT" and
                     remaining_enrichments <= 0)):
                permit_ready = False
        except ValueError:
            permit_ready = False
    checks["execution_permit"] = "READY" if permit_ready else "NOT_ISSUED_OR_INVALID"
    blockers = [key for key, value in checks.items() if value not in {"READY", "CLEAR"}]
    technical_blockers = [key for key in blockers if key != "execution_permit"]
    categories = {
        "database": "DATABASE_AUTHORIZATION", "migration": "MIGRATION",
        "partitions": "CONFIGURATION", "program": "CONFIGURATION", "policy": "POLICY",
        "apollo_key": "CREDENTIAL", "apollo_account": "EXTERNAL_ACCOUNT",
        "pricing": "PRICING", "limits": "BUDGET_CONFIGURATION",
        "official_source": "EXTERNAL_SOURCE", "suppression": "SUPPRESSION",
        "pending_calls": "RECONCILIATION", "execution_permit": "EXECUTION_AUTHORIZATION",
        "postgresql": "DATABASE_AUTHORIZATION", "nine_partitions": "CONFIGURATION",
        "official_rate": "BUDGET_CONFIGURATION", "no_enrichment": "BUDGET_CONFIGURATION",
        "credit_caps": "BUDGET_CONFIGURATION", "operation_cost": "OPERATION_COST",
    }
    pool_balances = {
        pool: apollo_account.credit_balances.get(pool)
        for pool in sorted(set(pricing.credit_pools_by_operation.values()))
    } if apollo_account and pricing else None
    known_balances = (
        [value for value in pool_balances.values() if value is not None]
        if pool_balances else []
    )
    return {
        "technically_ready": not technical_blockers,
        "execution_authorized": not blockers,
        "checks": checks, "blockers": blockers,
        "blocker_categories": {key: categories[key] for key in blockers},
        "database": {"identity": identity, "host_hash": host_hash, "logical_name": name,
                     "environment": database.environment if database else None,
                     "revision": revision, "all_revisions": revisions},
        "census_id": census_id, "partitions_planned": count,
        "phase": phase,
        "apollo_org_search_pricing_source": APOLLO_ORG_SEARCH_PRICING_URL,
        "run_status": run["status"] if run else None,
        "partitions_complete": sum(row["status"] == "COMPLETE" for row in partitions),
        "partitions_incomplete": sum(row["status"] != "COMPLETE" for row in partitions),
        "code_sha": code_sha, "app_version": app_version,
        "policy_purpose": MILOMAIL_PURPOSE, "policy_version": POLICY_VERSION,
        "matcher_version": MATCHER_VERSION,
        "official_source": {"enabled": source_enabled, "reachable": source_available,
                            "max_requests": source_requests,
                            "rate_limit_per_minute": source_rate_limit_per_minute,
                            "cache_ttl_days": source_cache_ttl_days},
        "apollo_endpoint": "https://api.apollo.io", "apollo_plan": pricing.plan_name if pricing else None,
        "apollo_rate_limits_per_minute": pricing.rate_limits_per_minute if pricing else None,
        "apollo_pricing_source": pricing.source_reference if pricing else None,
        "caps": {"partitions": limits.max_partitions, "pages": limits.max_pages,
                 "candidates": limits.max_candidates, "enrichments": limits.max_enrichments,
                 "credits": limits.max_apollo_credits, "cost_chf": str(limits.max_cost_chf)},
        "credits_available": min(known_balances) if pool_balances and len(
            known_balances
        ) == len(pool_balances) else None,
        "credit_balances_by_pool": pool_balances,
        "worst_cost_chf": str(Decimal(limits.max_apollo_credits) * pricing.price_per_credit)
        if pricing and pricing.price_per_credit is not None else None,
        "max_incremental_charge_chf": str(pricing.max_incremental_charge_chf)
        if pricing and pricing.billing_basis == "PREPAID_SHARED_POOL" else None,
        "allocation_cost_chf": None if pricing and pricing.billing_basis == "PREPAID_SHARED_POOL" else
        (str(Decimal(limits.max_apollo_credits) * pricing.price_per_credit)
         if pricing and pricing.price_per_credit is not None else None),
        "credits_reserved": reserved, "incomplete_calls": pending_calls,
        "configuration_hash": config_digest,
        "permit_remaining": permit_remaining,
        "official_requests_reserved": run["official_requests_reserved"] if run else 0,
        "enrichment_authorized": bool(permit_ready and permit and permit["phase"] == "ENRICHMENT"),
        "contact_enrichment_allowed": False if phase == "COVERAGE" else bool(
            permit_ready and permit and permit["phase"] == "ENRICHMENT"
        ),
        "instantly_mutation_allowed": False,
    }
