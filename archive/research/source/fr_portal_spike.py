"""MICRO-SPIKE — PLACE et Achatpublic donnent-ils un DCE public sans compte ?

Le spike France précédent a classé 22 URLs de profil acheteur en `external` et
conclu à 0 % d'accès documentaire. Ce module vérifie si ce verdict venait de la
plateforme ou de notre fetcher, qui s'arrête à la première page HTML.

Ce qu'il fait : ouvrir la page publique en HTTP, lire ce qu'elle propose, et
nommer précisément l'obstacle. Ce qu'il ne fait **jamais** :

- aucun login, aucun compte, aucun mot de passe ;
- aucun contournement de CAPTCHA ;
- aucune réutilisation de session humaine ;
- **aucune soumission de formulaire d'identité**. Le chemin « anonyme »
  d'Achatpublic exige raison sociale, nom et email : le remplir automatiquement
  reviendrait à déclarer une fausse identité à une plateforme publique. Le spike
  mesure que la porte existe, il ne la franchit pas avec de faux papiers.

Les seuls cookies utilisés sont ceux que la session HTTP crée elle-même.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

USER_AGENT = "Kivou-research-spike/0.1 (mesure accessibilite publique; donnees marches publics)"

Platform = Literal["place", "achatpublic", "other"]


@dataclass
class ConsultationProbe:
    """Ce qu'une consultation publique a réellement laissé voir."""

    url: str
    platform: Platform
    http_status: int | None = None
    page_bytes: int = 0
    anonymous_cookies: list[str] = field(default_factory=list)
    consultation_page_found: bool = False
    public_without_login: bool = False
    documents_section_detected: bool = False
    anonymous_download_option_detected: bool = False
    identity_form_required: bool = False
    identity_fields: list[str] = field(default_factory=list)
    captcha_present: bool = False
    captcha_on_login_path_only: bool = False
    results_rendered_server_side: bool = False
    browser_required: bool = False
    download_attempted: bool = False
    document_download_success: bool = False
    blocker: str = ""

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def platform_of(url: str) -> Platform:
    lowered = url.lower()
    if "marches-publics.gouv.fr" in lowered:
        return "place"
    if "achatpublic.com" in lowered:
        return "achatpublic"
    return "other"


_DCE_MARKERS = re.compile(
    r"\bDCE\b|dossier de consultation|pi[eè]ces de la consultation", re.IGNORECASE
)
_ANON_MARKERS = re.compile(
    r"t[ée]l[ée]charger.{0,40}anonyme|anonyme.{0,40}t[ée]l[ée]charg", re.IGNORECASE
)
_CAPTCHA = re.compile(r"captcha|capcha", re.IGNORECASE)
_LOGIN_CAPTCHA = re.compile(r"loginForm__cap[ct]haWrapp|textCaptchaDiv", re.IGNORECASE)
_EMPTY_RESULT_BLOCK = re.compile(
    r"<!--\s*Debut Bloc de Resultat\s*-->\s*<!--\s*Fin Bloc de Resultat\s*-->", re.IGNORECASE
)
_IDENTITY_FIELDS = ("nomEntiteContact", "nomPointContact", "mailPointContact")


def analyse(url: str, status: int, body: str, cookies: list[str]) -> ConsultationProbe:
    """Lit une page publique et nomme l'obstacle, sans rien soumettre."""
    probe = ConsultationProbe(url=url, platform=platform_of(url))
    probe.http_status = status
    probe.page_bytes = len(body)
    probe.anonymous_cookies = cookies
    probe.consultation_page_found = status == 200 and len(body) > 2000
    # Une page servie sans identifiant est publique ; la présence d'un
    # formulaire de connexion dans l'en-tête ne la rend pas privée.
    probe.public_without_login = probe.consultation_page_found

    probe.documents_section_detected = bool(_DCE_MARKERS.search(body))
    probe.anonymous_download_option_detected = bool(_ANON_MARKERS.search(body))
    probe.captcha_present = bool(_CAPTCHA.search(body))
    probe.captcha_on_login_path_only = probe.captcha_present and bool(_LOGIN_CAPTCHA.search(body))

    present = [name for name in _IDENTITY_FIELDS if name in body]
    probe.identity_fields = present
    probe.identity_form_required = len(present) >= 2

    # Bloc de résultat vide = contenu injecté par JavaScript.
    probe.results_rendered_server_side = not bool(_EMPTY_RESULT_BLOCK.search(body))
    if not probe.results_rendered_server_side:
        probe.browser_required = True
        probe.blocker = "contenu injecté en JavaScript : la page HTML ne porte aucune consultation"
    elif probe.identity_form_required:
        probe.blocker = (
            "formulaire d'identité obligatoire (raison sociale, contact, email) — "
            "non soumis : le remplir automatiquement serait une fausse déclaration"
        )
    elif not probe.documents_section_detected:
        probe.blocker = "aucune section documentaire annoncée sur la page publique"
    return probe
