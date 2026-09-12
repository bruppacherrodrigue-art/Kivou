from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import httpx
from alembic import command

from signals.company_research.enrichment import (
    CompanyEnrichmentDecision,
    CompanyEnrichmentInput,
    CompanyEnrichmentProviderResult,
    CompanyEnrichmentService,
    CompanyWebCollector,
)
from signals.company_research.providers import OpenRouterCompanyEnrichmentProvider
from signals.persistence.database import alembic_config, create_database_engine
from signals.supplier_directory.store import SupplierDirectoryStore

NOW = dt.datetime(2026, 9, 12, 8, tzinfo=dt.UTC)


def _identity(**updates: object) -> CompanyEnrichmentInput:
    values: dict[str, object] = {
        "siren": "481153435",
        "legal_name": "ALYA BATIMENT",
        "city": "GUEREINS",
        "department": "01",
        "naf_code": "43.99C",
        "naf_label": "Travaux de maçonnerie générale et gros œuvre de bâtiment",
        "employees": 19,
        "directors_raw": (
            {"name": "MOSBAH BENZAOUI", "title": "Gérant", "entity_type": "personne physique"},
        ),
    }
    values.update(updates)
    return CompanyEnrichmentInput.model_validate(values)


def _decision(**updates: object) -> CompanyEnrichmentDecision:
    values: dict[str, object] = {
        "website": "alyabat.fr",
        "website_confidence": 0.98,
        "email": "alya.batiment@hotmail.fr",
        "email_confidence": 0.97,
        "email_is_placeholder": False,
        "family": "subcontracted_structural_work",
        "family_confidence": 0.94,
        "director_display_name": "Mosbah Benzaoui",
        "phone": "06 68 07 39 63",
        "notes": "site alyabat.fr trouvé via verif.com, adresse publiée page contact",
    }
    values.update(updates)
    return CompanyEnrichmentDecision.model_validate(values)


def test_collector_runs_one_exact_serper_query_and_collects_bounded_pages() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.host == "google.serper.dev":
            payload = json.loads(request.content)
            assert payload == {"q": "ALYA BATIMENT GUEREINS", "gl": "fr", "hl": "fr", "num": 10}
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "ALYA BATIMENT - Verif",
                            "link": "https://www.verif.com/societe/ALYA-BATIMENT-481153435/",
                            "snippet": "Site internet : alyabat.fr",
                        },
                        {
                            "title": "ALYA Bâtiment",
                            "link": "https://alyabat.fr/",
                            "snippet": "Maçonnerie à Guéreins",
                        },
                    ]
                },
            )
        pages = {
            ("www.verif.com", "/societe/ALYA-BATIMENT-481153435/"): (
                "<title>Fiche ALYA</title><p>Site internet alyabat.fr</p>"
            ),
            ("alyabat.fr", "/"): (
                "<title>ALYA Bâtiment</title><p>Maçonnerie et gros œuvre.</p>"
            ),
            ("alyabat.fr", "/contact"): (
                "<title>Contact</title><p>alya.batiment@hotmail.fr</p>"
            ),
            ("alyabat.fr", "/mentions-legales"): (
                "<title>Mentions légales</title><p>SIREN 481 153 435</p>"
            ),
        }
        body = pages.get((request.url.host, request.url.path))
        return (
            httpx.Response(200, headers={"content-type": "text/html"}, text=body)
            if body is not None
            else httpx.Response(404)
        )

    collector = CompanyWebCollector(
        serper_api_key="serper-test",
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )

    evidence = collector.collect(_identity())

    assert evidence.query == "ALYA BATIMENT GUEREINS"
    assert len(evidence.results) == 2
    assert evidence.results[0].is_directory is True
    assert evidence.results[0].page is not None
    assert evidence.results[1].is_directory is False
    assert {page.url for page in evidence.candidate_pages} == {
        "https://alyabat.fr/",
        "https://alyabat.fr/contact",
        "https://alyabat.fr/mentions-legales",
    }
    assert all(len(page.text) <= 3000 for page in evidence.candidate_pages)
    assert sum(1 for method, url in seen if method == "POST" and "serper" in url) == 1


def test_openrouter_provider_uses_sonnet_strict_json_max_tokens_and_reports_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "anthropic/claude-sonnet-4.6"
        assert payload["max_tokens"] == 1000
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["usage"] == {"include": True}
        prompt = json.loads(payload["messages"][0]["content"])
        assert prompt["instruction"].startswith("Voici une entreprise française")
        assert prompt["company"]["siren"] == "481153435"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _decision().model_dump_json()}}],
                "usage": {"prompt_tokens": 321, "completion_tokens": 87, "cost": 0.0042},
            },
        )

    provider = OpenRouterCompanyEnrichmentProvider(
        api_key="openrouter-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    evidence = CompanyWebCollector.empty_evidence(_identity())

    result = provider.enrich(_identity(), evidence)

    assert result.decision == _decision()
    assert result.cost_usd == Decimal("0.0042")
    assert result.input_tokens == 321
    assert result.output_tokens == 87


def test_service_applies_thresholds_mx_placeholder_and_persists_one_model_decision(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'directory.db'}")
    command.upgrade(alembic_config(engine), "head")
    store = SupplierDirectoryStore(engine, clock=lambda: NOW)
    store.upsert_identity(
        siren="481153435",
        legal_name="ALYA BATIMENT",
        naf_code="43.99C",
        family_key="subcontracted_structural_work",
        department="01",
        city="GUEREINS",
        employees=19,
        observed_at=NOW,
        naf_label="Travaux de maçonnerie générale et gros œuvre de bâtiment",
    )

    class Collector:
        calls = 0

        def collect(self, identity):
            self.calls += 1
            return CompanyWebCollector.evidence_for_test(
                identity,
                domain="alyabat.fr",
                contact_text="Contact : alya.batiment@hotmail.fr",
            )

    class Provider:
        calls = 0

        def enrich(self, identity, evidence):
            self.calls += 1
            return CompanyEnrichmentProviderResult(
                decision=_decision(),
                model="anthropic/claude-sonnet-4.6",
                cost_usd=Decimal("0.0042"),
                input_tokens=321,
                output_tokens=87,
            )

    collector = Collector()
    provider = Provider()
    service = CompanyEnrichmentService(
        directory=store,
        collector=collector,
        provider=provider,
        mx_verifier=lambda email: email == "alya.batiment@hotmail.fr",
        clock=lambda: NOW,
    )

    first = service.enrich("481153435", directors_raw=_identity().directors_raw)
    second = service.enrich("481153435", directors_raw=_identity().directors_raw)
    record = store.get("481153435")

    assert first.cached is False
    assert second.cached is True
    assert collector.calls == provider.calls == 1
    assert record is not None
    assert record.domain == "alyabat.fr"
    assert record.domain_source == "model"
    assert record.domain_validation_method == "model"
    assert record.domain_confidence == Decimal("0.980")
    assert record.professional_email == "alya.batiment@hotmail.fr"
    assert record.email_source == "model"
    assert record.email_confidence == Decimal("0.970")
    assert record.family_keys == ("subcontracted_structural_work",)
    assert record.family_source == "model"
    assert record.family_confidence == Decimal("0.940")
    assert record.family_confirmation_status == "confirmed"
    assert record.director_display_name == "Mosbah Benzaoui"
    assert record.phone == "06 68 07 39 63"
    assert record.enrichment_notes == _decision().notes
    assert record.enrichment_cost_usd == Decimal("0.004200")
    assert record.enrichment_observed_at == NOW


def test_service_clears_low_confidence_and_placeholder_fields_and_falls_back_to_naf(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'directory.db'}")
    command.upgrade(alembic_config(engine), "head")
    store = SupplierDirectoryStore(engine, clock=lambda: NOW)
    store.upsert_identity(
        siren="950009944",
        legal_name="ENTREPRISE ALAIN LE NY",
        naf_code="43.91A",
        family_key="timber_carpentry",
        department="69",
        city="DARDILLY",
        employees=99,
        observed_at=NOW,
        naf_label="Travaux de charpente",
    )

    class Provider:
        def enrich(self, identity, evidence):
            return CompanyEnrichmentProviderResult(
                decision=_decision(
                    website="leny-alain.fr",
                    website_confidence=0.79,
                    email="jean.dupont@gmail.com",
                    email_confidence=0.99,
                    email_is_placeholder=False,
                    family="reinforcement_steel",
                    family_confidence=0.69,
                    director_display_name="Adil El Mansouri",
                    phone=None,
                ),
                model="anthropic/claude-sonnet-4.6",
                cost_usd=Decimal("0.003"),
                input_tokens=200,
                output_tokens=70,
            )

    evidence = CompanyWebCollector.evidence_for_test(
        _identity(
            siren="950009944",
            legal_name="ENTREPRISE ALAIN LE NY",
            city="DARDILLY",
            department="69",
            naf_code="43.91A",
            naf_label="Travaux de charpente",
            employees=99,
            directors_raw=(
                {"name": "ADIL EL MANSOURI", "title": "Président de SAS"},
            ),
        ),
        domain="leny-alain.fr",
        contact_text="jean.dupont@gmail.com",
    )

    class Collector:
        def collect(self, identity):
            return evidence

    result = CompanyEnrichmentService(
        directory=store,
        collector=Collector(),
        provider=Provider(),
        mx_verifier=lambda _email: True,
        clock=lambda: NOW,
    ).enrich(
        "950009944",
        directors_raw=({"name": "ADIL EL MANSOURI", "title": "Président de SAS"},),
        force=True,
    )
    record = store.get("950009944")

    assert result.reverification_required is True
    assert record is not None
    assert record.domain is None
    assert record.professional_email is None
    assert record.family_keys == ("timber_carpentry",)
    assert record.family_source == "naf"
    assert record.family_confirmation_status == "unconfirmed"
    assert record.director_display_name == "Adil El Mansouri"
    assert record.reverification_reason == "model_confidence_below_threshold"
