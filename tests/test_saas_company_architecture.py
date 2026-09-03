from __future__ import annotations

import ast
from pathlib import Path

import pytest

from signals.companies.contracts import CompanyProfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "signals" / "companies"


def test_company_boundary_has_no_provider_or_acquisition_dependency() -> None:
    forbidden_imports = (
        "signals.acquisition",
        "signals.campaigns",
        "signals.contact_discovery",
        "signals.company_research",
        "signals.personalization",
        "signals.supplier_discovery",
    )
    forbidden_text = (
        "apollo",
        "acquisitioncompanyprofile",
        "acquisitionprospectprebuild",
        "contact_ref",
        "supplier_ref",
        "acquisition_opportunity_id",
        "business_email",
        "direct_phone",
    )

    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        lowered = source.lower()
        assert not any(term in lowered for term in forbidden_text), path
        tree = ast.parse(source)
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for imported in imports
            for forbidden in forbidden_imports
        ), path


def test_browser_contract_exposes_no_internal_or_person_fields() -> None:
    schema = repr(CompanyProfile.model_json_schema()).lower()
    # PR1 §4 — le suivi commercial du compte est le SEUL « contact* » légitime
    # de ce contrat. Le nom du champ, son titre humanisé par pydantic et le
    # vocabulaire fermé du statut (`to_contact`/`contacted`/`replied`)
    # contiennent tous la sous-chaîne « contact » ; on les retire un par un
    # avant le test plutôt que d'affaiblir le terme interdit lui-même.
    # `signals` se déclare comme un tableau d'objets non typés
    # (`dict[str, Any]`) : ce garde-fou ne voit donc PAS l'intérieur des
    # cartes qu'il contient — elles restent gouvernées par `view.feed_item`.
    for allowed in (
        "contact_status",
        "contacted_at",
        "contact status",
        "contacted at",
        "to_contact",
        "contacted",
    ):
        schema = schema.replace(allowed, "")

    for forbidden in (
        "provider_id",
        "score",
        "policy",
        "verdict",
        "contact",
        "person",
        "email",
        "phone",
        "raw_payload",
    ):
        assert forbidden not in schema


@pytest.mark.xfail(
    strict=True,
    reason="companies/france.py utilise encore un client HTTP ; dette héritée hors PR3",
)
def test_company_boundary_has_no_http_client_or_new_entitlement() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PACKAGE.glob("*.py"))
    ).lower()

    for forbidden in ("httpx", "requests", "urllib.request", "new_entitlement"):
        assert forbidden not in source
