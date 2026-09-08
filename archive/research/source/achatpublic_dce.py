"""SPIKE — retrait anonyme du DCE sur Achatpublic, pour constituer un corpus.

Implémentation minimale de recherche, **pas** un adaptateur de production.

Le diagnostic navigateur a établi le parcours public exact : la fiche de
consultation expose un identifiant de DCE, et le chemin « Souhaitez-vous vous
identifier ? → Non » poste ce même formulaire avec les trois champs de contact
**vides**. Le serveur accepte et sert l'archive.

    GET  /sdm/ent/gen/ent_detail.do?PCSLID=…      → cookie anonyme + dceId
    POST /sdm/ent2/gen/telechargerDCE.action?…    → ZIP du DCE

Ce que ce module ne fait jamais :

- aucun login, aucun compte, aucun mot de passe ;
- aucun CAPTCHA — il n'y en a pas sur ce chemin, il garde le formulaire de
  connexion ;
- **aucune identité inventée** : les champs de contact partent vides, comme le
  fait l'interface publique quand on répond « Non ».

Une leçon coûteuse est encodée ici : une consultation **close** ne propose plus
son DCE. Viser les appels d'offres ouverts n'est pas une préférence, c'est la
condition pour que quoi que ce soit soit téléchargeable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BASE = "https://www.achatpublic.com"
DETAIL_URL = f"{BASE}/sdm/ent/gen/ent_detail.do"
DOWNLOAD_URL = f"{BASE}/sdm/ent2/gen/telechargerDCE.action"
USER_AGENT = "Kivou-research-spike/0.1 (donnees publiques marches publics)"

# Les trois champs du formulaire de contact. Envoyés VIDES : c'est exactement ce
# que fait `dowloadWithoutAuth()` dans la page publique.
EMPTY_IDENTITY = {"nomEntiteContact": "", "nomPointContact": "", "mailPointContact": ""}

_PCSLID = re.compile(r"PCSLID=([A-Za-z0-9_\-]+)")
# Le DCE n'apparaît pas dans un champ de formulaire mais dans l'identifiant du
# bloc de détail que le JavaScript alimente : `<div id="detailsDce_383958044">`.
_DCE_ID = re.compile(r"detailsDce_(\d+)")


def pcslid_from_url(url: str) -> str | None:
    """L'identifiant de consultation porté par l'URL publiée par BOAMP."""
    match = _PCSLID.search(url or "")
    return match.group(1) if match else None


def dce_id_from_page(html: str) -> str | None:
    """L'identifiant du DCE, lu dans la page — jamais deviné ni incrémenté."""
    match = _DCE_ID.search(html or "")
    return match.group(1) if match else None


def detail_url(pcslid: str) -> str:
    return f"{DETAIL_URL}?PCSLID={pcslid}"


def download_request(pcslid: str, dce_id: str, *, cycle: str = "0") -> tuple[str, dict[str, str]]:
    """L'URL et le corps du retrait anonyme, tels que la page publique les émet."""
    url = f"{DOWNLOAD_URL}?PCSLID={pcslid}&cycNum={cycle}"
    body = {"PCSLID": pcslid, "cycNum": cycle, "dceId": dce_id, **EMPTY_IDENTITY}
    return url, body


def is_zip(payload: bytes) -> bool:
    return payload[:4] == b"PK\x03\x04"


@dataclass
class DceAttempt:
    """Ce qu'une tentative de retrait a donné, étape par étape."""

    pcslid: str
    detail_status: int | None = None
    dce_id: str | None = None
    download_status: int | None = None
    content_type: str | None = None
    filename: str | None = None
    byte_size: int = 0
    sha256: str | None = None
    is_archive: bool = False
    members: list[str] = field(default_factory=list)
    blocker: str = ""

    @property
    def succeeded(self) -> bool:
        return self.byte_size > 0 and self.download_status == 200

    def as_dict(self) -> dict[str, object]:
        data = self.__dict__.copy()
        data["succeeded"] = self.succeeded
        return data
