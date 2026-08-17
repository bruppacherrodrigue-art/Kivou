"""Ouverture d'archives — une archive téléchargée est une entrée hostile.

Trois attaques classiques, trois garde-fous, chacun testé sur une archive
forgée :

- **path traversal** : une entrée nommée `../../etc/passwd` ne doit jamais
  décider d'un chemin d'écriture. Rien n'est écrit sur disque ici, mais un
  chemin remontant est refusé pour qu'aucun appelant ne puisse s'y fier ;
- **bombe zip** : quelques kilo-octets qui se déploient en gigaoctets. La somme
  décompressée est plafonnée, et le plafond est vérifié **avant** de lire ;
- **récursion** : le dossier portugais réel contient un ZIP dans un ZIP. La
  profondeur est bornée.

Aucun fichier n'est exécuté. Les exécutables sont listés — c'est un fait du
dossier — mais jamais ouverts.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO

# Extensions jamais ouvertes, quelle que soit leur place dans l'archive.
EXECUTABLE_SUFFIXES = (
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".scr",
    ".sh",
    ".ps1",
    ".vbs",
    ".js",
    ".jar",
    ".app",
    ".bin",
    ".apk",
)


@dataclass(frozen=True)
class ArchiveLimits:
    """Plafonds explicites. Une archive ne doit jamais pouvoir épuiser la machine."""

    max_entries: int = 500
    max_entry_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_depth: int = 2


@dataclass
class ArchiveEntry:
    """Une entrée d'archive, avec la raison éventuelle de son rejet."""

    path: str
    size: int
    depth: int = 0
    content: bytes | None = None
    rejected: str | None = None

    @property
    def accepted(self) -> bool:
        return self.rejected is None


@dataclass
class ArchiveReading:
    entries: list[ArchiveEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> list[ArchiveEntry]:
        return [entry for entry in self.entries if entry.accepted]


def _is_traversal(name: str) -> bool:
    """Un chemin absolu ou remontant n'est jamais légitime dans une archive."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return True
    return any(part == ".." for part in normalized.split("/"))


def _is_executable(name: str) -> bool:
    return name.lower().endswith(EXECUTABLE_SUFFIXES)


def read_archive(
    data: bytes, *, limits: ArchiveLimits | None = None, depth: int = 0
) -> ArchiveReading:
    """Liste et lit une archive ZIP dans les limites données.

    Rien n'est écrit sur disque, rien n'est exécuté, et l'expansion totale est
    plafonnée avant lecture.
    """
    limits = limits or ArchiveLimits()
    reading = ArchiveReading()
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        reading.warnings.append(f"archive illisible : {exc}")
        return reading

    total = 0
    for index, info in enumerate(archive.infolist()):
        if index >= limits.max_entries:
            reading.warnings.append(f"archive tronquée : plus de {limits.max_entries} entrées")
            break
        if info.is_dir():
            continue

        entry = ArchiveEntry(path=info.filename, size=info.file_size, depth=depth)
        if _is_traversal(info.filename):
            entry.rejected = "chemin remontant ou absolu"
        elif _is_executable(info.filename):
            entry.rejected = "exécutable : listé, jamais ouvert"
        elif info.file_size > limits.max_entry_bytes:
            entry.rejected = f"entrée de {info.file_size} octets au-delà de la limite"
        elif total + info.file_size > limits.max_total_bytes:
            entry.rejected = "expansion totale de l'archive au-delà de la limite"
            reading.warnings.append("expansion totale plafonnée : archive partiellement lue")
            reading.entries.append(entry)
            break
        else:
            try:
                entry.content = archive.read(info)
            except Exception as exc:  # noqa: BLE001 — une entrée illisible ne casse pas le reste
                entry.rejected = f"lecture impossible : {exc}"
            else:
                total += len(entry.content)

        reading.entries.append(entry)

    return reading


def expand(data: bytes, *, limits: ArchiveLimits | None = None, depth: int = 0) -> ArchiveReading:
    """Lit une archive et descend dans les archives imbriquées, jusqu'à la limite.

    Le dossier portugais réel contient `espd-request.zip` : la descente est utile,
    mais bornée — une archive qui se contient elle-même ne doit pas tourner.
    """
    limits = limits or ArchiveLimits()
    reading = read_archive(data, limits=limits, depth=depth)
    if depth + 1 >= limits.max_depth:
        nested = [e for e in reading.accepted if e.path.lower().endswith(".zip")]
        if nested:
            reading.warnings.append(
                f"profondeur maximale {limits.max_depth} atteinte : "
                f"{len(nested)} archive(s) imbriquée(s) non ouverte(s)"
            )
        return reading

    for entry in list(reading.accepted):
        if not entry.path.lower().endswith(".zip") or entry.content is None:
            continue
        inner = expand(entry.content, limits=limits, depth=depth + 1)
        for child in inner.entries:
            child.path = f"{entry.path}!/{child.path}"
            reading.entries.append(child)
        reading.warnings.extend(inner.warnings)
    return reading
