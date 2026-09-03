"""Subdivisions FR/CH : départements français (réexportés) et cantons suisses."""

from __future__ import annotations

from signals.domain.french_departments import DEPARTMENTS
from signals.domain.subdivisions import FRENCH_DEPARTMENTS, SWISS_CANTONS, subdivision_label


def test_french_departments_are_reexported_without_duplication():
    assert FRENCH_DEPARTMENTS is DEPARTMENTS


def test_the_twenty_six_cantons_are_all_present():
    assert len(SWISS_CANTONS) == 26
    assert SWISS_CANTONS["VD"] == "Vaud"
    assert SWISS_CANTONS["ZH"] == "Zurich"
    assert SWISS_CANTONS["GE"] == "Genève"


def test_a_swiss_subdivision_renders_its_canton_label():
    assert subdivision_label("CH-VD") == "Vaud"


def test_a_french_subdivision_renders_its_department_label():
    assert subdivision_label("FR-92") == "Hauts-de-Seine"


def test_an_unknown_scheme_renders_nothing():
    assert subdivision_label("XX-1") is None
    assert subdivision_label(None) is None
