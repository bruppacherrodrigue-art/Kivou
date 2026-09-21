"""Synthetic Apollo → research → contact → DNS → score → policy proof."""

import datetime as dt

import httpx
import pytest
import sqlalchemy as sa
from test_milomail_policy import NOW, ready_input

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.config import runtime_flags
from signals.acquisition_programs.mail_provider import MailProviderDetector
from signals.acquisition_programs.pipeline import (
    ActiveCompanyEvidence,
    ProgramDiscoveryPipeline,
    ProgramOperationalContext,
    _match_role,
)
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.persistence.database import migrate_to_latest
from signals.persistence.schema import acquisition_program_eligibility
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient


class DNS:
    def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
        assert domain == "agence.fr"
        return ("smtp.google.com",)


class ForbiddenProvider:
    def __getattr__(self, name):
        raise AssertionError(f"Instantly called in SHADOW: {name}")


def test_synthetic_pipeline_records_theoretical_send_without_instantly() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v1/mixed_companies/search":
            return httpx.Response(
                200,
                json={
                    "organizations": [
                        {
                            "id": "org-1",
                            "name": "Agence Exemple",
                            "primary_domain": "agence.fr",
                            "website_url": "https://agence.fr",
                            "country": "France",
                            "industry": "Marketing",
                        }
                    ],
                    "pagination": {"page": 1, "per_page": 25, "total_entries": 1, "total_pages": 1},
                },
            )
        if request.url.path == "/api/v1/organizations/org-1":
            return httpx.Response(
                200,
                json={
                    "organization": {
                        "id": "org-1",
                        "name": "Agence Exemple",
                        "primary_domain": "agence.fr",
                        "website_url": "https://agence.fr",
                        "country": "France",
                        "industry": "Marketing",
                        "estimated_num_employees": 5,
                        "keywords": ["agence digitale"],
                    }
                },
            )
        if request.url.path == "/api/v1/mixed_people/api_search":
            return httpx.Response(
                200,
                json={
                    "total_entries": 1,
                    "people": [
                        {"id": "person-1", "title": "Founder", "has_email": True},
                    ],
                },
            )
        if request.url.path == "/api/v1/people/match":
            return httpx.Response(
                200,
                json={
                    "person": {
                        "id": "person-1",
                        "organization_id": "org-1",
                        "title": "Founder",
                        "email": "founder@agence.fr",
                        "email_status": "verified",
                    }
                },
            )
        raise AssertionError(f"unexpected Apollo endpoint: {request.url.path}")

    client = httpx.Client(transport=httpx.MockTransport(handle))
    config = ready_input().program.model_copy(update={"enabled": True})
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    shadow = MilomailShadowRuntime(
        engine,
        acquisition,
        SuppressionIdentityKeyring(current_key_version="v1", keys={"v1": b"test-secret-key"}),
        ForbiddenProvider(),
    )
    operations = ProgramOperationalContext(
        sender_identity_ready=True,
        opt_out_ready=True,
        privacy_notice_ready=True,
        source_notice_ready=True,
        sender_domain="outbound.milomail.example",
        sender_healthy=True,
        spf_ready=True,
        dkim_ready=True,
        dmarc_ready=True,
        warmup_ready=True,
        landing_active=True,
        landing_french=True,
        daily_remaining=10,
        monthly_remaining=100,
        cost_remaining_chf="10",
    )
    pipeline = ProgramDiscoveryPipeline(
        engine,
        config=config,
        flags=runtime_flags(
            {
                "MILOMAIL_ACQUISITION_ENABLED": "true",
                "MILOMAIL_CAMPAIGN_MODE": "SHADOW",
            }
        ),
        organizations=ApolloOrganizationSearchClient(api_key="test", client=client),
        companies=ApolloCompanyResearchClient(api_key="test", client=client, clock=lambda: NOW),
        contacts=ApolloContactDiscoveryClient(api_key="test", client=client),
        mail_provider=MailProviderDetector(DNS()),
        company_activity=lambda _: ActiveCompanyEvidence(
            status="ACTIVE",
            source_url="https://registre.example/org-1",
            source_type="PUBLIC_COMPANY_REGISTRY",
            observed_at=NOW,
            evidence_id="registry:org-1",
        ),
        acquisition=acquisition,
        shadow=shadow,
        operations=operations,
    )
    result = pipeline.run(program_id=program_id, observed_at=NOW)
    assert len(result) == 1
    assert result[0].decision.decision == "SEND"
    assert result[0].decision.score_version == config.score_version
    assert seen == [
        "/api/v1/mixed_companies/search",
        "/api/v1/organizations/org-1",
        "/api/v1/mixed_people/api_search",
        "/api/v1/people/match",
    ]
    with engine.connect() as connection:
        row = connection.execute(sa.select(acquisition_program_eligibility)).mappings().one()
    assert row["supplier_ref"] and row["contact_ref"]
    assert row["wedge_key"] == "digital_or_creative_agency"
    assert row["decision"] == "SEND"
    assert shadow.export_preview(result[0].decision) == "BLOCKED_SHADOW"
    refreshed = pipeline.run(program_id=program_id, observed_at=NOW + dt.timedelta(hours=1))
    assert refreshed[0].opportunity_id == result[0].opportunity_id
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_program_eligibility)) == 2


@pytest.mark.parametrize("title", ["Assistant to CEO", "Former Founder", "cofounder", "CEO advisor"])
def test_target_role_requires_an_unambiguous_current_title(title: str) -> None:
    assert _match_role(title, ready_input().program.role_terms) is None


def test_disabled_pipeline_never_calls_apollo() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    config = ready_input().program

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(name)

    pipeline = ProgramDiscoveryPipeline(
        engine,
        config=config,
        flags=runtime_flags({}),
        organizations=NoCalls(),
        companies=NoCalls(),
        contacts=NoCalls(),
        mail_provider=NoCalls(),
        company_activity=NoCalls(),
        acquisition=NoCalls(),
        shadow=NoCalls(),
        operations=ProgramOperationalContext(),
    )
    assert pipeline.run(program_id="disabled", observed_at=NOW) == ()


def test_provider_allowlist_empty_never_calls_apollo() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    config = ready_input().program.model_copy(update={"enabled": True})

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(name)

    pipeline = ProgramDiscoveryPipeline(
        engine,
        config=config,
        flags=runtime_flags(
            {
                "MILOMAIL_ACQUISITION_ENABLED": "true",
                "MILOMAIL_CAMPAIGN_MODE": "SHADOW",
                "MILOMAIL_ALLOWED_PROVIDERS": "",
            }
        ),
        organizations=NoCalls(),
        companies=NoCalls(),
        contacts=NoCalls(),
        mail_provider=NoCalls(),
        company_activity=NoCalls(),
        acquisition=NoCalls(),
        shadow=NoCalls(),
        operations=ProgramOperationalContext(),
    )
    assert pipeline.run(program_id="disabled", observed_at=NOW) == ()


def test_shadow_pipeline_rejects_real_apollo_transport_before_network() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    live_client = httpx.Client()
    config = ready_input().program.model_copy(update={"enabled": True})

    class NoCalls:
        def __getattr__(self, name):
            raise AssertionError(name)

    pipeline = ProgramDiscoveryPipeline(
        engine,
        config=config,
        flags=runtime_flags(
            {
                "MILOMAIL_ACQUISITION_ENABLED": "true",
                "MILOMAIL_CAMPAIGN_MODE": "SHADOW",
            }
        ),
        organizations=ApolloOrganizationSearchClient(api_key="synthetic", client=live_client),
        companies=ApolloCompanyResearchClient(api_key="synthetic", client=live_client),
        contacts=ApolloContactDiscoveryClient(api_key="synthetic", client=live_client),
        mail_provider=NoCalls(),
        company_activity=NoCalls(),
        acquisition=NoCalls(),
        shadow=NoCalls(),
        operations=ProgramOperationalContext(),
    )
    with pytest.raises(RuntimeError, match="mocked Apollo"):
        pipeline.run(program_id="unused", observed_at=NOW)
    live_client.close()
