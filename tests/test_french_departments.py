"""Le département français se lit dans le code postal ; son nom vient d'une table."""

from signals.feed.french_departments import (
    DEPARTMENTS,
    department_from_postal_code,
    department_label,
    location_subdivision,
)


def test_metropolitan_postal_codes_give_a_two_digit_department():
    assert department_from_postal_code("92350") == "92"
    assert department_from_postal_code("06150") == "06"


def test_corsica_is_split_at_20200():
    assert department_from_postal_code("20000") == "2A"
    assert department_from_postal_code("20167") == "2A"
    assert department_from_postal_code("20200") == "2B"
    assert department_from_postal_code("20600") == "2B"


def test_overseas_postal_codes_give_a_three_digit_department():
    assert department_from_postal_code("97133") == "971"
    assert department_from_postal_code("97400") == "974"


def test_anything_else_is_not_a_department():
    assert department_from_postal_code(None) is None
    assert department_from_postal_code("1234") is None
    assert department_from_postal_code("CH-1000") is None
    assert department_from_postal_code("99999") is None


def test_the_label_needs_the_iso_prefix():
    assert department_label("FR-92") == "Hauts-de-Seine"
    assert department_label("FR-2A") == "Corse-du-Sud"
    assert department_label("FR-971") == "Guadeloupe"
    assert department_label("92") is None
    assert department_label("CH-VD") is None
    assert department_label(None) is None


def test_the_label_accepts_official_french_nuts3_codes():
    assert department_label("FRL05") == "Var"
    assert department_label("FR106") == "Seine-Saint-Denis"
    assert department_label("FRB05") == "Loir-et-Cher"


def test_the_table_covers_the_hundred_and_one_departments():
    assert len(DEPARTMENTS) == 101


def test_the_published_subdivision_wins_over_the_derived_one():
    assert location_subdivision({"country": "FR", "subdivision_code": "FR-75", "postal_code": "92350"}) == "FR-75"
    assert location_subdivision({"country": "FR", "postal_code": "92350"}) == "FR-92"
    assert location_subdivision({"country": "CH", "postal_code": "1000"}) is None
    assert location_subdivision(None) is None
