from signals.feed.location import normalized_city


def test_city_removes_cedex_and_normalizes_all_caps() -> None:
    assert normalized_city("NICE CEDEX 3") == "Nice"
    assert normalized_city("  Saint-Étienne  ") == "Saint-Étienne"
    assert normalized_city("FR") is None
