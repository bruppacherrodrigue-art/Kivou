"""The single production-shadow prospecting mail template."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShadowMailInput:
    object: str
    holder: str
    amount: str
    place: str
    date: str
    for_you: str
    attribution_url: str
    source_url: str
    unsubscribe_url: str


@dataclass(frozen=True)
class ShadowMail:
    subject: str
    body: str
    status: str = "SHADOW"


def render_shadow_mail(value: ShadowMailInput) -> ShadowMail:
    body = "\n\n".join(
        (
            f"Signal : {value.object}",
            f"Titulaire : {value.holder}\nMontant : {value.amount}\nLieu : {value.place}\nDate : {value.date}",
            value.for_you,
            f"Ouvrir : {value.attribution_url}",
            "Bien cordialement,\nL’équipe Kivou",
            f"Source des données : {value.source_url}\nLien de désinscription : {value.unsubscribe_url}",
        )
    )
    if len(body.split()) > 120:
        raise ValueError("shadow mail exceeds 120 words")
    return ShadowMail(subject=value.object, body=body)


__all__ = ["ShadowMail", "ShadowMailInput", "render_shadow_mail"]
