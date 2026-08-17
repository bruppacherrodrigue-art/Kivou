"""SPEC-008 §7, §30, §46 — TargetICP : ce que le client déclare vouloir recevoir.

Le modèle est déclaratif et déterministe : il ne devine pas l'offre du client,
il ne consulte aucun texte libre pour décider, et il ignore tout ce qui relève
de l'Acquisition Engine (Apollo, contacts, campagnes). Cette frontière est
structurelle — un champ de campagne ne peut pas exister ici.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.matching import (
    MATCH_POLICY_VERSION,
    TargetICP,
    Territory,
    ValueThreshold,
)


def _icp(**overrides) -> TargetICP:
    data = {
        "icp_id": "icp-staffing-romandie",
        "name": "Agence d'intérim BTP — Suisse romande",
        "offer_summary": "Mise à disposition de personnel qualifié pour chantiers.",
        "primary_need_categories": ("workforce_capacity",),
        "secondary_need_categories": ("specialist_subcontracting",),
        "geography_basis": "place_of_performance",
        "geography_policy": "required",
        "territories": (Territory(country="CH"),),
        "included_contract_types": ("construction",),
        "excluded_contract_types": ("it_digital",),
        "included_sectors": (),
        "excluded_sectors": ("defence_security",),
        "value_thresholds": (ValueThreshold(currency="CHF", minimum_amount=250_000),),
        "unknown_value_policy": "allow_with_penalty",
        "maximum_signal_age_days": 90,
        "preferred_timings": ("immediate", "near_term"),
        "source_modes_allowed": ("metadata_fallback",),
    }
    data.update(overrides)
    return TargetICP(**data)


class TestTargetICPInvariants:
    def test_a_well_formed_icp_is_accepted(self) -> None:
        icp = _icp()
        assert icp.icp_id == "icp-staffing-romandie"
        assert icp.primary_need_categories == ("workforce_capacity",)

    def test_at_least_one_primary_need_category_is_required(self) -> None:
        with pytest.raises(ValidationError):
            _icp(primary_need_categories=())

    def test_primary_and_secondary_categories_must_be_disjoint(self) -> None:
        with pytest.raises(ValidationError):
            _icp(
                primary_need_categories=("workforce_capacity",),
                secondary_need_categories=("workforce_capacity",),
            )

    def test_included_and_excluded_contract_types_must_be_disjoint(self) -> None:
        with pytest.raises(ValidationError):
            _icp(
                included_contract_types=("construction",),
                excluded_contract_types=("construction",),
            )

    def test_included_and_excluded_sectors_must_be_disjoint(self) -> None:
        with pytest.raises(ValidationError):
            _icp(included_sectors=("healthcare",), excluded_sectors=("healthcare",))

    def test_required_geography_demands_at_least_one_territory(self) -> None:
        with pytest.raises(ValidationError):
            _icp(geography_policy="required", territories=())

    def test_ignored_geography_may_have_no_territory(self) -> None:
        icp = _icp(geography_policy="ignored", territories=(), geography_basis="ignore")
        assert icp.territories == ()

    def test_only_one_threshold_per_currency(self) -> None:
        with pytest.raises(ValidationError):
            _icp(
                value_thresholds=(
                    ValueThreshold(currency="CHF", minimum_amount=100_000),
                    ValueThreshold(currency="CHF", minimum_amount=250_000),
                )
            )

    def test_a_threshold_minimum_may_not_exceed_its_maximum(self) -> None:
        with pytest.raises(ValidationError):
            ValueThreshold(currency="EUR", minimum_amount=500_000, maximum_amount=100_000)

    def test_the_maximum_signal_age_must_be_positive_and_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _icp(maximum_signal_age_days=0)
        with pytest.raises(ValidationError):
            _icp(maximum_signal_age_days=4000)

    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _icp(campaign_id="camp-42")

    def test_several_icps_may_coexist_without_any_quota(self) -> None:
        """§48 — aucun plan, aucun quota, aucun paywall dans SPEC-008."""
        icps = tuple(_icp(icp_id=f"icp-{index}") for index in range(12))
        assert len({icp.icp_id for icp in icps}) == 12


class TestTerritory:
    def test_a_country_alone_is_a_valid_territory(self) -> None:
        assert Territory(country="CH").country == "CH"

    def test_a_subdivision_requires_its_scheme(self) -> None:
        """Sans schéma, « VD » ne veut rien dire de comparable."""
        with pytest.raises(ValidationError):
            Territory(country="CH", subdivision_code="VD")

    def test_a_subdivision_with_its_scheme_is_accepted(self) -> None:
        territory = Territory(country="CH", subdivision_code="VD", subdivision_scheme="ISO-3166-2")
        assert territory.subdivision_code == "VD"


class TestClientAcquisitionBoundary:
    """§2 et §46 — le produit client ne connaît pas l'Acquisition Engine."""

    FORBIDDEN = (
        "apollo",
        "instantly",
        "campaign",
        "mailbox",
        "email_sequence",
        "reply_rate",
        "outbound",
        "prospect",
        "acquisitiondashboard",
    )

    def test_the_matching_package_never_imports_an_acquisition_module(self) -> None:
        """Les imports, pas la prose : un commentaire qui explique l'exclusion
        est légitime, un import ne l'est jamais."""
        import ast
        import pathlib

        for path in pathlib.Path("src/signals/matching").glob("*.py"):
            tree = ast.parse(path.read_text())
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported += [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
                    imported += [alias.name for alias in node.names]
            for name in imported:
                lowered = name.casefold()
                for token in self.FORBIDDEN:
                    assert token not in lowered, f"{path.name} importe « {name} »"

    def test_no_acquisition_identifier_exists_in_the_matching_code(self) -> None:
        """Aucun nom de variable, de classe, de fonction ou d'attribut du
        vocabulaire d'acquisition — les docstrings sont exclues du scan."""
        import ast
        import pathlib

        for path in pathlib.Path("src/signals/matching").glob("*.py"):
            tree = ast.parse(path.read_text())
            # Les docstrings — de module, de classe, de fonction, et les
            # commentaires de champ Pydantic (chaîne isolée après une
            # affectation) — expliquent l'exclusion : elles ne la violent pas.
            prose: set[int] = set()
            for scope in ast.walk(tree):
                body = getattr(scope, "body", None)
                if not isinstance(body, list):
                    continue
                for statement in body:
                    if (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.value.value, str)
                    ):
                        prose.add(id(statement.value))

            identifiers: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    identifiers.append(node.id)
                elif isinstance(node, ast.Attribute):
                    identifiers.append(node.attr)
                elif isinstance(node, ast.arg):
                    identifiers.append(node.arg)
                elif isinstance(node, ast.ClassDef | ast.FunctionDef):
                    identifiers.append(node.name)
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    # Une chaîne littérale porteuse de sens (valeur d'enum, nom
                    # de champ) compte ; la prose explicative, non.
                    and id(node) not in prose
                ):
                    identifiers.append(node.value)
            for identifier in identifiers:
                lowered = str(identifier).casefold()
                for token in self.FORBIDDEN:
                    assert token not in lowered, f"{path.name} référence « {identifier} »"

    def test_no_acquisition_field_exists_on_the_icp(self) -> None:
        fields = " ".join(TargetICP.model_fields).casefold()
        for token in self.FORBIDDEN + ("contact", "decision_maker"):
            assert token not in fields

    def test_the_policy_version_is_declared(self) -> None:
        assert MATCH_POLICY_VERSION == "icp-match-v0.1"
