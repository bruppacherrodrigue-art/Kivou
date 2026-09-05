from __future__ import annotations

import re

_CEDEX = re.compile(r"\s+CEDEX(?:\s+\d+)?$", re.IGNORECASE)


def normalized_city(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    city = " ".join(value.split()).strip()
    if not city:
        return None
    if re.fullmatch(r"[A-Za-z]{2}", city):
        return None
    city = _CEDEX.sub("", city).strip()
    return city.title() if city.isupper() else city
