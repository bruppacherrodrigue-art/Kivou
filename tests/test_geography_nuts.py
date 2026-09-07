from __future__ import annotations

import pytest
from test_matching_engine import _cu, _icp
from test_qa_attribution import NOW, issue
from test_qa_attribution import prepared_qa as recipe_fixture

from signals.accounts.icp_input import TargetIcpInput
from signals.domain import french_departments as geo
from signals.matching.engine import MatchingEngine
from signals.matching.icp import Territory

prepared_qa = recipe_fixture


def place(code, *, scheme="NUTS", country="FR"):
    return {"country": country, "subdivision_code": code, "subdivision_scheme": scheme}


def test_nuts3_becomes_its_iso_department():
    assert geo.location_subdivision(place("FRJ23")) == "FR-31"
    assert TargetIcpInput(territory_subdivisions=("FRJ23",)).territory_subdivisions == ("FR-31",)


@pytest.mark.parametrize("region,departments", [
    ("FRJ2", {"09", "12", "31", "32", "46", "65", "81", "82"}),
    ("FRJ", {"09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"}),
])
def test_regional_nuts_preserves_all_departments(region, departments):
    expected = {f"FR-{code}" for code in departments}
    actual = TargetIcpInput(territory_subdivisions=(region,)).territory_subdivisions
    assert set(actual) == expected
    assert geo.location_subdivision(place(region)) == region
    for department in expected:
        assert geo.location_matches_subdivision(place(region), department)
        assert geo.location_matches_subdivision(place(department, scheme="ISO-3166-2"), region)
    assert not geo.location_matches_subdivision(place(region), "FR-38")


@pytest.mark.parametrize("code,target,expected", [
    ("FRJ23", "FR-31", True), ("FRJ23", "FR-38", False),
    ("FRJ2", "FR-31", True), ("FRJ2", "FR-82", True),
    ("FRJ2", "FR-34", False), ("FRJ", "FR-34", True),
])
def test_materialization_matching_uses_geographic_coverage(code, target, expected):
    cu = _cu(country="FR")
    location = cu.geography.place_of_performance.model_copy(update={
        "subdivision_code": code, "subdivision_scheme": "NUTS",
    })
    cu = cu.model_copy(update={"geography": cu.geography.model_copy(update={
        "place_of_performance": location,
    })})
    profile = _icp(territories=(Territory(
        country="FR", subdivision_code=target, subdivision_scheme="ISO-3166-2",
    ),))
    result, state = MatchingEngine._geography_filter(cu, profile)
    assert result.passed is expected
    assert state == ("match" if expected else "mismatch")


def test_unknown_codes_country_and_conflicting_schemes_remain_rejected():
    with pytest.raises(ValueError):
        TargetIcpInput(territory_subdivisions=("FRZZ",))
    assert not geo.location_matches_subdivision(place("FRJ23", country="CH"), "FR-31")
    assert not geo.location_matches_subdivision(place("FRJ23", scheme="ISO-3166-2"), "FR-31")
    assert not geo.location_matches_subdivision(None, "FR-31")


def test_landing_and_both_feed_filters_share_the_same_coverage(prepared_qa):
    import sqlalchemy as sa

    from signals.accounts.schema import account_landing_signal, target_icp
    from signals.feed.query import feed_page, history_page

    engine, client, opportunity = prepared_qa
    response = client.get(f"/a/{issue(opportunity, engine=engine)}", follow_redirects=False)
    assert response.headers["location"].startswith("/app/signals/")
    with engine.connect() as connection:
        landing = connection.execute(sa.select(account_landing_signal)).mappings().one()
        profile = connection.execute(sa.select(target_icp.c.customer_input)).scalar_one()
        assert profile["territory_subdivisions"] == ["FR-31"]
        for query in (feed_page, history_page):
            def keys(zone, query=query):
                page = query(connection, account_id=landing["account_id"],
                             as_of=NOW.date(), subdivision_code=zone,
                             **({"freshness": "all"} if query is feed_page else {}))
                return {item.signal.signal_key for item in page.items}
            assert landing["signal_key"] in keys("FR-31")
            assert keys("FR-31") == keys("FRJ23") == keys("FRJ2")
            assert not keys("FR-38")
