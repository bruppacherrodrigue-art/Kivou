from __future__ import annotations

import inspect

import signals.company_research.apollo as apollo_module
import signals.company_research.prebuild as prebuild_module
import signals.company_research.profile as profile_module
import signals.company_research.service as service_module
import signals.company_research.store as store_module
from signals.acquisition.contracts import EventType


def test_company_research_has_no_customer_private_dependencies() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (
            apollo_module,
            prebuild_module,
            profile_module,
            service_module,
            store_module,
        )
    )
    for forbidden in (
        "signals.accounts",
        "signals.billing",
        "signals.matching",
        "TargetICP",
        "materialized_signal",
        "customer_feedback",
        "entitlement",
    ):
        assert forbidden not in source


def test_company_research_has_no_outbound_or_research_executor_path() -> None:
    source = "\n".join(inspect.getsource(module) for module in (apollo_module, service_module))
    for forbidden in (
        "/organizations/enrich",
        "mixed_companies/search",
        "mixed_people",
        "people/match",
        "instantly",
        "smtp",
        "send_email",
        "web_crawler",
        "import openai",
        "from openai",
        "hermes",
    ):
        assert forbidden not in source.casefold()


def test_company_profile_store_does_not_select_or_persist_contact_pii() -> None:
    source = inspect.getsource(store_module.CompanyResearchStore)
    assert "business_email" not in source
    assert "first_name" not in source
    assert "last_name" not in source
    assert "linkedin" not in source.casefold()


def test_company_research_adds_no_acquisition_event_type() -> None:
    names = {event.value for event in EventType}
    assert "COMPANY_RESEARCHED" not in names
    assert "PROFILE_CREATED" not in names
    assert "COMPANY_ENRICHED" not in names
