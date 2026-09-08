"""Shared match-band ordering, independent of API and dashboard imports."""

_BAND_RANK: dict[str, int] = {"strong": 3, "promising": 2, "weak": 1}


def match_band_rank(band: str | None) -> int:
    return _BAND_RANK.get(band, 0)
