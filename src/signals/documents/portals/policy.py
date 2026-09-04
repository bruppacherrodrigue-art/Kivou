"""Politique d'accès réversible, relue à chaque décision."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

PolicyStatus = Literal["portal_blocked", "cgu_restricted"]


@dataclass(frozen=True)
class PortalPolicyDecision:
    status: PolicyStatus
    reason: str


_DEFAULTS: dict[str, PortalPolicyDecision] = {
    "marches-publics.info": PortalPolicyDecision("portal_blocked", "captcha"),
    "marches-securises.fr": PortalPolicyDecision("cgu_restricted", "cgu_automation"),
    "achatpublic.com": PortalPolicyDecision("portal_blocked", "robots_disallowed"),
}


class PortalPolicy:
    """Retourne un refus revu ou `None` quand le retrait est autorisé.

    Le fichier facultatif a la forme
    ``{"hosts": {"achatpublic.com": {"enabled": true}}}``. Il est relu à
    chaque appel pour qu'une autorisation prenne effet sans redéploiement. Un
    fichier absent ou invalide conserve les décisions sûres par défaut.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def _overrides(self) -> dict[str, object]:
        if self.path is None:
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        hosts = payload.get("hosts") if isinstance(payload, dict) else None
        return hosts if isinstance(hosts, dict) else {}

    def decision(self, url: str) -> PortalPolicyDecision | None:
        host = (urlparse(url).hostname or "").casefold()
        overrides = self._overrides()
        for suffix, default in _DEFAULTS.items():
            if host == suffix or host.endswith(f".{suffix}"):
                override = overrides.get(suffix)
                if isinstance(override, dict) and override.get("enabled") is True:
                    return None
                return default
        return None
