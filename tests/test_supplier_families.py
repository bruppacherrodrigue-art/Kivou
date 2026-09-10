from __future__ import annotations

from signals.supplier_discovery.families import (
    department_and_neighbours,
    department_from_subdivision,
    families_for_signal,
    load_supplier_family_catalog,
)


def test_catalog_covers_six_verticals_with_bounded_readable_families() -> None:
    catalog = load_supplier_family_catalog()
    assert set(catalog) == {
        "general_building",
        "interior_finishing",
        "technical_installation",
        "roadworks_civil",
        "earthworks_demolition",
        "special_civil",
    }
    for families in catalog.values():
        assert 3 <= len(families) <= 5
        assert all(f.label_fr and f.apollo_tags and f.priority > 0 for f in families)
    naf_codes = {code for families in catalog.values() for f in families for code in f.naf_codes}
    assert {
        "43.99C", "23.63Z", "43.91A", "43.91B", "43.32A", "43.32B", "43.29A",
        "43.21A", "43.22A", "43.22B", "43.31Z", "43.33Z", "43.34Z", "43.12A",
        "43.12B", "42.11Z",
    } <= naf_codes


def test_gross_oeuvre_maps_to_precise_supplier_families() -> None:
    catalog = load_supplier_family_catalog()
    names = {family.key for family in catalog["general_building"]}
    assert {"ready_mix_concrete", "reinforcement_steel", "formwork", "scaffolding"} <= names


def test_family_queries_are_derived_from_signal_cpv_and_object() -> None:
    families = families_for_signal(
        "general_building", cpv_codes=("45262300",), object_text="Lot 3 : Gros œuvre"
    )
    assert {family.key for family in families} == {
        "ready_mix_concrete",
        "reinforcement_steel",
        "formwork",
    }
    assert all("construction" not in tag for family in families for tag in family.apollo_tags)


def test_aura_search_uses_signal_department_and_adjacent_departments() -> None:
    assert department_and_neighbours("69") == ("69", "01", "38", "42", "71")


def test_nuts_subdivisions_resolve_to_the_signal_department() -> None:
    assert department_from_subdivision("FRK26") == "69"
    assert department_from_subdivision("FRB05") == "41"
    assert department_from_subdivision("FR-45") == "45"
    assert department_from_subdivision("FRB") is None
