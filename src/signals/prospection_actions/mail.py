"""Single final assisted-prospection mail template."""

from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class RenderedProspectMail:
    subject: str
    text: str
    html: str
    word_count: int


def _amount(minor_units: int, currency: str) -> str:
    amount = minor_units / 100
    suffix = "€" if currency.casefold() == "eur" else "CHF"
    if amount.is_integer():
        rendered = f"{int(amount):,}".replace(",", " ")
    else:
        rendered = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{rendered} {suffix}"


def _family_question(label: str) -> str:
    normalized = label.strip()
    prefixes = ("du ", "de la ", "de l'", "des ")
    complement = normalized if normalized.casefold().startswith(prefixes) else f"de {normalized}"
    return f"Vous fournissez ou réalisez {complement} ?"


def render_assisted_mail(row: dict[str, object]) -> RenderedProspectMail:
    """Render the exact text and HTML sent by the provider; no UI assembly remains."""

    director_name = str(row.get("director_name") or "").strip()
    greeting = f"Bonjour {director_name}," if director_name else "Bonjour,"
    decision_date = row["signal_decision_date"]
    date_text = decision_date.strftime("%d/%m/%Y")
    family_question = _family_question(str(row["family_label"]))
    for_you = (
        f"Pour vous : ce signal peut créer un besoin en "
        f"{str(row['family_label']).casefold()} autour de {row['signal_location']}."
    )
    paragraphs = (
        greeting,
        family_question,
        (
            f"{row['signal_holder']} vient de gagner « {row['signal_subject']} » "
            f"({_amount(int(row['signal_amount_minor_units']), str(row['signal_currency']))}, "
            f"{row['signal_location']}, {date_text})."
        ),
        for_you,
        f"Ouvrir le signal : {row['attribution_url']}",
        "Bien cordialement,\nL’équipe Kivou",
        f"Source des données : registres publics et {row['signal_source_url']}",
        f"Se désinscrire : {row['unsubscribe_url']}",
    )
    text = "\n\n".join(paragraphs)
    word_count = len(text.split())
    if word_count > 120:
        raise ValueError("assisted prospect mail exceeds 120 words")
    html_body = "".join(
        f"<p>{html.escape(paragraph).replace(chr(10), '<br>')}</p>" for paragraph in paragraphs
    )
    return RenderedProspectMail(
        subject=str(row["signal_subject"]),
        text=text,
        html=html_body,
        word_count=word_count,
    )


__all__ = ["RenderedProspectMail", "render_assisted_mail"]
