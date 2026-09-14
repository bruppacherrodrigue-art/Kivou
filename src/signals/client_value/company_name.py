"""One customer-facing company-name normalizer, independent from acquisition."""

from __future__ import annotations

import re

_LEGAL_FORMS = re.compile(
    r"\b(?:SASU?|SARL|EURL|SA|SCI|SNC|EI|EIRL|MICRO[- ]?ENTREPRISE|ASSOCIATION)\b",
    re.IGNORECASE,
)
_REGISTRY_MENTION = re.compile(
    r"\s*\((?:RCS|SIREN|RM|registre)[^)]*\)", re.IGNORECASE
)
_PRESERVED_NAME_ACRONYMS = frozenset(
    {"AG", "BV", "GMBH", "INC", "KG", "LLC", "NV", "PLC"}
)


def _normal_case(value: str) -> str:
    return " ".join(
        part.upper() if part.upper() in _PRESERVED_NAME_ACRONYMS else part.title()
        for part in value.split()
    )


def normalize_company_name(value: object) -> str:
    raw = " ".join(str(value or "").replace("–", "-").split()).strip(" ,;:-")
    raw = _REGISTRY_MENTION.sub("", raw)
    abbreviated = re.split(r"\s+EN\s+ABREGE\s+", raw, maxsplit=1, flags=re.IGNORECASE)
    if len(abbreviated) == 2:
        sigle = re.sub(
            r"[^A-Za-z0-9À-ÖØ-öø-ÿ&.-]+", " ", abbreviated[0]
        ).strip()
        name = _normal_case(
            " ".join(_LEGAL_FORMS.sub(" ", abbreviated[1]).split()).strip(" ,;:-")
        )
        return f"{sigle.upper()} ({name})" if sigle and name else (sigle.upper() or name)
    return _normal_case(" ".join(_LEGAL_FORMS.sub(" ", raw).split()).strip(" ,;:-"))


def normalize_holder_name(value: object) -> str:
    raw = " ".join(str(value or "").split()).strip(" ,;:-")
    if re.fullmatch(r"[A-Z][A-Z0-9&.-]{1,15}", raw):
        return raw.upper()
    terminal_sigle = re.search(
        r"(?:\s[-–—]\s|\s+(?i:EN\s+ABREGE)\s+)([A-Z][A-Z0-9&.-]{1,15})$",
        raw,
    )
    if terminal_sigle:
        return terminal_sigle.group(1).upper()
    return normalize_company_name(raw)


__all__ = ["normalize_company_name", "normalize_holder_name"]
