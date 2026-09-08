"""Cache déterministe des vérifications (SPEC-009A §11).

Ne jamais repayer une vérification identique. La clé englobe tout ce qui peut
changer la réponse — la vue, l'ICP, le prompt, le schéma, le modèle — si bien
qu'un changement de l'un d'eux invalide le cache sans intervention.

Contraintes tenues : portable (un seul fichier JSON, chemin configurable), sans
secret (aucune clé d'API, aucun en-tête n'y entre), borné (plafond d'entrées
explicite), désactivable, et compatible VPS puisqu'il ne suppose aucun service.
Toujours pas de base de données (§56 de SPEC-009).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import threading
from typing import Any

from signals.verification.model import CommercialVerification

ENV_CACHE = "KIVOU_VERIFIER_CACHE"
ENV_CACHE_DISABLED = "KIVOU_VERIFIER_CACHE_DISABLED"

DEFAULT_MAX_ENTRIES = 5000


def cache_key(
    *,
    snapshot_hash: str,
    icp_hash: str,
    prompt_version: str,
    schema_version: str,
    model_id: str,
) -> str:
    """L'identité d'une vérification (§11) — tout ce qui la ferait changer."""
    material = f"{snapshot_hash}|{icp_hash}|{prompt_version}|{schema_version}|{model_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def icp_hash(target_icp: dict[str, Any]) -> str:
    """Empreinte stable de l'ICP structuré tel qu'il est montré au modèle."""
    payload = json.dumps(target_icp, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class VerificationCache:
    """Un cache fichier, borné et sans secret. Désactivable par variable d'environnement."""

    def __init__(
        self,
        path: pathlib.Path | None = None,
        *,
        enabled: bool | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        configured = os.environ.get(ENV_CACHE)
        self.path = (
            path or pathlib.Path(configured or ".kivou-cache/verifier_cache.json").expanduser()
        )
        if enabled is None:
            enabled = os.environ.get(ENV_CACHE_DISABLED, "").strip().lower() not in (
                "1",
                "true",
                "yes",
            )
        self.enabled = enabled
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0
        self.skipped_full = 0
        self.flushes = 0
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        # Le cache est lu et écrit depuis plusieurs threads de vérification, et
        # il est vidé en cours de route : sans verrou, une écriture partielle
        # pourrait être relue comme un cache corrompu.
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.enabled or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Un cache illisible est un cache vide : il n'a aucune autorité sur
            # le résultat, il ne doit donc jamais faire échouer une course.
            return
        entries = payload.get("entries")
        if isinstance(entries, dict):
            self._entries = entries

    def get(self, key: str) -> CommercialVerification | None:
        if not self.enabled:
            return None
        self._load()
        raw = self._entries.get(key)
        if raw is None:
            self.misses += 1
            return None
        try:
            verification = CommercialVerification.model_validate(raw)
        except ValueError:
            # Une entrée qui ne valide plus est une entrée d'un contrat antérieur.
            self.misses += 1
            return None
        self.hits += 1
        return verification

    def put(self, key: str, verification: CommercialVerification) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._load()
            if key not in self._entries and len(self._entries) >= self.max_entries:
                self.skipped_full += 1
                return
            self._entries[key] = verification.model_dump(mode="json")

    def flush(self) -> None:
        """Écrit le cache sur disque, de façon atomique.

        Appelée périodiquement pendant une course, pas seulement à la fin : §10
        exige de pouvoir redémarrer après une interruption, et un cache vidé
        uniquement en sortie ferait repayer l'intégralité d'une course coupée.

        L'écriture passe par un fichier temporaire puis un `replace` : une
        course tuée en plein `write_text` laisserait sinon un JSON tronqué,
        c'est-à-dire un cache perdu.
        """
        if not self.enabled:
            return
        with self._lock:
            self._load()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps({"entries": self._entries}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            temporary.replace(self.path)
            self.flushes += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "skipped_full": self.skipped_full,
            "flushes": self.flushes,
            "max_entries": self.max_entries,
        }
