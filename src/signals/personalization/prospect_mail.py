"""Single prospect mail renderer shared by every acquisition mode."""

from __future__ import annotations

import datetime as dt
import html
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RenderedProspectMail:
    subject: str
    text: str
    html: str
    word_count: int
    contract_status: str
    contract_failure: str | None


@dataclass(frozen=True)
class FamilyMailCopy:
    subject_label: str
    footer_label: str
    sentence: str


@dataclass(frozen=True)
class WorkTerm:
    key: str
    rendered: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class ProspectMailCatalog:
    families: dict[str, FamilyMailCopy]
    work_terms: tuple[WorkTerm, ...]


_MONTHS = (
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_URL_PATTERN = re.compile(r"https?://[^\s<>]+")
_TECHNICAL_PATTERN = re.compile(
    r"(?:\bLOT\b|\bCPV\b|\b\d{8}(?:-\d)?\b|\b\d{2}[A-Z]\d{4,}\b)",
    re.IGNORECASE,
)
_BODY_TECHNICAL_PATTERN = re.compile(
    r"(?:\bLOT\b|\bCPV\b|\b\d{8}(?:-\d)?\b|\b\d{2}[A-Z]\d{4,}\b)"
)
_FOOTER_SEPARATOR = "\n\n—\n"


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "ops/config/prospect-mail.yaml"


@lru_cache(maxsize=1)
def load_prospect_mail_catalog(path: Path | None = None) -> ProspectMailCatalog:
    source = _catalog_path() if path is None else path
    try:
        raw: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("prospect mail catalog unavailable") from exc
    if not isinstance(raw, dict) or raw.get("version") != "prospect-mail-v1":
        raise ValueError("prospect mail catalog version is invalid")
    raw_families = raw.get("families")
    raw_terms = raw.get("work_terms")
    if not isinstance(raw_families, dict) or not isinstance(raw_terms, list):
        raise TypeError("prospect mail catalog structure is invalid")
    families: dict[str, FamilyMailCopy] = {}
    for key, value in raw_families.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise TypeError("prospect mail family is invalid")
        try:
            copy = FamilyMailCopy(
                subject_label=str(value["subject_label"]).strip(),
                footer_label=str(value["footer_label"]).strip(),
                sentence=str(value["sentence"]).strip(),
            )
        except KeyError as exc:
            raise ValueError(f"prospect mail family is incomplete: {key}") from exc
        if not copy.subject_label or not copy.footer_label or not copy.sentence.endswith("."):
            raise ValueError(f"prospect mail family is invalid: {key}")
        families[key] = copy
    terms: list[WorkTerm] = []
    for value in raw_terms:
        if not isinstance(value, dict):
            raise TypeError("prospect mail work term is invalid")
        try:
            term = WorkTerm(
                key=str(value["key"]).strip(),
                rendered=str(value["rendered"]).strip(),
                terms=tuple(str(item).strip() for item in value["terms"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("prospect mail work term is incomplete") from exc
        if not term.key or not term.rendered or not all(term.terms):
            raise ValueError(f"prospect mail work term is invalid: {term.key}")
        terms.append(term)
    return ProspectMailCatalog(families=families, work_terms=tuple(terms))


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _normal_case(value: str) -> str:
    return " ".join(part.title() for part in value.split())


def normalize_director_name(value: object) -> str | None:
    raw = re.sub(r"\([^)]*\)", " ", str(value or ""))
    raw = re.sub(r"\b(?:M(?:ONSIEUR)?|MME|MADAME)\.?\b", " ", raw, flags=re.IGNORECASE)
    parts = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ'’-]+", raw)
    if len(parts) < 2:
        return None
    return _normal_case(f"{parts[0]} {parts[-1]}")


def _work_description(raw_subject: str, catalog: ProspectMailCatalog) -> str:
    folded = _fold(raw_subject)
    matches: list[tuple[int, str, str]] = []
    for work_term in catalog.work_terms:
        positions = [folded.find(_fold(term)) for term in work_term.terms]
        found = [position for position in positions if position >= 0]
        if found:
            matches.append((min(found), work_term.key, work_term.rendered))
    unique: list[str] = []
    seen: set[str] = set()
    for _position, key, rendered in sorted(matches):
        if key not in seen:
            unique.append(rendered)
            seen.add(key)
    if not unique:
        return "les travaux prévus"
    if len(unique) == 1:
        return unique[0]
    return ", ".join(unique[:-1]) + f" et {unique[-1]}"


def _amount(minor_units: int, currency: str) -> str:
    major = Decimal(minor_units) / Decimal(100)
    suffix = "€" if currency.casefold() == "eur" else currency.upper()
    if major >= Decimal(1_000_000):
        millions = (major / Decimal(1_000_000)).quantize(Decimal("0.1"), ROUND_HALF_UP)
        value = format(millions, "f").rstrip("0").rstrip(".").replace(".", ",")
        return f"{value} M{suffix}"
    thousands = (major / Decimal(1_000)).quantize(Decimal("1"), ROUND_HALF_UP)
    return f"{int(thousands)} k{suffix}"


def _date(value: object) -> str:
    if isinstance(value, dt.datetime):
        value = value.date()
    if not isinstance(value, dt.date):
        raise TypeError("signal decision date must be a date")
    return f"{value.day} {_MONTHS[value.month]}"


def _linked(url: str, label: str) -> str:
    escaped = html.escape(url, quote=True)
    return f'<a href="{escaped}">{html.escape(label)}</a>'


def _render_html(
    *,
    greeting: str,
    signal_sentence: str,
    family_sentence: str,
    attribution_url: str,
    footer_reason: str,
    unsubscribe_url: str,
) -> str:
    return "".join(
        (
            f"<p>{html.escape(greeting)}</p>",
            f"<p>{html.escape(signal_sentence)}</p>",
            f"<p>{html.escape(family_sentence)}</p>",
            (
                "<p>Si ça vous intéresse, le détail du marché est ici : "
                f"{_linked(attribution_url, 'Voir le marché')}</p>"
            ),
            "<p>Bien à vous,<br>Rodrigue Bruppacher<br>Kivou</p>",
            (
                f"<p>—<br>{html.escape(footer_reason)} Source : registres publics et avis "
                "d'attribution officiel.<br>"
                f"{_linked(unsubscribe_url, 'Ne plus recevoir')}</p>"
            ),
        )
    )


def render_prospect_mail(row: dict[str, object]) -> RenderedProspectMail:
    catalog = load_prospect_mail_catalog()
    family_key = str(row["family_key"])
    try:
        family = catalog.families[family_key]
    except KeyError as exc:
        raise ValueError(f"prospect mail family is unknown: {family_key}") from exc
    director_name = normalize_director_name(row.get("director_name"))
    greeting = f"Bonjour {director_name}," if director_name else "Bonjour,"
    holder = str(row.get("signal_holder") or "").strip()
    city = _normal_case(str(row.get("signal_city") or "").strip()) or None
    department = str(row.get("signal_department") or "").strip()
    place = f"à {city}" if city else f"en {department}"
    amount = _amount(int(row["signal_amount_minor_units"]), str(row["signal_currency"]))
    date = _date(row["signal_decision_date"])
    work = _work_description(str(row["signal_subject"]), catalog)
    if holder and city:
        subject = f"{holder} vient de gagner un chantier {family.subject_label} à {city}"
    elif holder:
        subject = f"{holder} vient de gagner un chantier {family.subject_label} en {department}"
    else:
        subject = (
            f"{amount} de {family.subject_label} en {department} : "
            "le titulaire va sous-traiter"
        )
    signal_sentence = (
        f"{holder or 'Le titulaire'} vient d'être retenu pour {work} {place} — {amount}, "
        f"attribué le {date}."
    )
    attribution_url = str(row["attribution_url"])
    unsubscribe_url = str(row["unsubscribe_url"])
    footer_reason = (
        "Vous recevez ce message parce que votre entreprise est référencée en "
        f"{family.footer_label} en {department}."
    )
    body = "\n\n".join(
        (
            greeting,
            signal_sentence,
            family.sentence,
            f"Si ça vous intéresse, le détail du marché est ici : {attribution_url}",
            "Bien à vous,\nRodrigue Bruppacher\nKivou",
        )
    )
    footer = (
        f"{footer_reason} Source : registres publics et avis d'attribution officiel.\n"
        f"Ne plus recevoir : {unsubscribe_url}"
    )
    text = f"{body}{_FOOTER_SEPARATOR}{footer}"
    word_count = len(body.split())
    candidate = RenderedProspectMail(
        subject=subject,
        text=text,
        html=_render_html(
            greeting=greeting,
            signal_sentence=signal_sentence,
            family_sentence=family.sentence,
            attribution_url=attribution_url,
            footer_reason=footer_reason,
            unsubscribe_url=unsubscribe_url,
        ),
        word_count=word_count,
        contract_status="passed",
        contract_failure=None,
    )
    failure = validate_prospect_mail(
        candidate,
        raw_subject=str(row["signal_subject"]),
        director_name=director_name,
    )
    if failure is None:
        return candidate
    return RenderedProspectMail(
        subject=candidate.subject,
        text=candidate.text,
        html=candidate.html,
        word_count=candidate.word_count,
        contract_status="failed",
        contract_failure=failure,
    )


def validate_prospect_mail(
    mail: RenderedProspectMail,
    *,
    raw_subject: str,
    director_name: str | None,
) -> str | None:
    body = mail.text.partition(_FOOTER_SEPARATOR)[0]
    folded_subject = _fold(mail.subject)
    if folded_subject == _fold(raw_subject):
        return "subject_matches_signal_title"
    if _TECHNICAL_PATTERN.search(mail.subject):
        return "subject_contains_technical_identifier"
    retired_fragments = (
        "autour " + "de",
        "L'" + "équipe Kivou",
        "L’" + "équipe Kivou",
        "Vous fournissez " + "ou réalisez",
    )
    if _BODY_TECHNICAL_PATTERN.search(body) or any(
        fragment.casefold() in body.casefold() for fragment in retired_fragments
    ):
        return "body_contains_forbidden_fragment"
    greeting = body.partition("\n\n")[0]
    if director_name:
        if (
            greeting != f"Bonjour {director_name},"
            or "(" in director_name
            or ")" in director_name
            or len(director_name.split()) > 2
            or director_name != _normal_case(director_name)
        ):
            return "director_name_invalid"
    elif greeting != "Bonjour,":
        return "director_name_invalid"
    if "\n\nBien à vous,\nRodrigue Bruppacher\nKivou" not in body:
        return "signature_invalid"
    urls = _URL_PATTERN.findall(mail.text)
    if len(urls) != 2:
        return "url_count_invalid"
    if any(mail.html.count(f'href="{html.escape(url, quote=True)}"') != 1 for url in urls):
        return "html_link_count_invalid"
    if ">Voir le marché</a>" not in mail.html or ">Ne plus recevoir</a>" not in mail.html:
        return "html_link_label_invalid"
    actual_word_count = len(body.split())
    if actual_word_count != mail.word_count or actual_word_count > 90:
        return "body_word_limit_exceeded"
    return None


__all__ = [
    "FamilyMailCopy",
    "ProspectMailCatalog",
    "RenderedProspectMail",
    "WorkTerm",
    "load_prospect_mail_catalog",
    "normalize_director_name",
    "render_prospect_mail",
    "validate_prospect_mail",
]
