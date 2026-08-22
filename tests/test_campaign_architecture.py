from __future__ import annotations

import ast
import json
from pathlib import Path

import sqlalchemy as sa
from test_campaign_service import _approved, _assisted, _deployment, _prepared, _service

from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.campaigns.contracts import CampaignDeploymentConfig, PacingPolicy
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_event,
    acquisition_provider_event,
    acquisition_provider_operation,
    policy_evaluation,
)
from signals.policy.contracts import BudgetUsage

FORBIDDEN_IMPORT_PREFIXES = (
    "signals.company_research.apollo",
    "signals.contact_discovery.apollo",
    "signals.billing",
    "signals.crawler",
    "signals.matching",
    "signals.target_icp",
    "openai",
    "stripe",
    "smtplib",
)


def test_campaign_package_has_no_forbidden_runtime_dependencies() -> None:
    package = Path("src/signals/campaigns")
    violations: list[str] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = (node.module,)
            for name in names:
                if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(f"{path}:{node.lineno}:{name}")
    assert violations == []


def test_default_composition_is_inert_and_fail_closed(tmp_path) -> None:
    engine, _, _, _ = _prepared(tmp_path)
    deployment = CampaignDeploymentConfig()

    create_app(engine, ApiConfig())

    assert deployment.mailbox_catalog.usable_entries == ()
    assert deployment.transport_contract_proof == "UNVERIFIED"
    assert deployment.webhook_entitlement == "UNVERIFIED"
    assert deployment.response_ingress_capability == "NONE"
    assert PacingPolicy().autonomous_live_cap == 0


def test_generic_campaign_audit_is_pii_minimized(tmp_path) -> None:
    engine, opportunity_id, artifact, _assessment = _prepared(tmp_path)
    _assisted(engine)
    service = _service(engine, _deployment())
    authorization = _approved(service, engine, opportunity_id)
    service.schedule(opportunity_id, authorization, budget_usage=BudgetUsage())

    forbidden = (
        "buyer@example.test",
        artifact["subject"],
        artifact["body"],
        artifact["greeting"],
        artifact["cta"],
        "approved_by_actor_ref",
        "campaign-test-key",
    )
    with engine.connect() as connection:
        rows = []
        for table in (
            acquisition_campaign,
            acquisition_campaign_member,
            acquisition_provider_operation,
            acquisition_provider_event,
        ):
            rows.extend(dict(row) for row in connection.execute(sa.select(table)).mappings())
        campaign_events = connection.execute(
            sa.select(acquisition_event).where(
                acquisition_event.c.actor_ref == "kivou-campaign-factory"
            )
        ).mappings().all()
        policy = connection.execute(
            sa.select(policy_evaluation).where(
                policy_evaluation.c.evaluation_id == authorization.evaluation_id
            )
        ).mappings().one()
    serialized = json.dumps(
        [*rows, *(dict(row) for row in campaign_events), dict(policy)],
        default=str,
        sort_keys=True,
    )
    assert all(value not in serialized for value in forbidden)


def test_offline_eval_fixture_is_synthetic_and_versioned() -> None:
    corpus = json.loads(Path("tests/fixtures/campaign_factory_eval_v1.json").read_text())
    assert corpus["version"] == "campaign-factory-eval-v1"
    assert len(corpus["cases"]) >= 20
    serialized = json.dumps(corpus)
    assert "@example.invalid" in serialized
    assert "instantly.ai" not in serialized.lower()
