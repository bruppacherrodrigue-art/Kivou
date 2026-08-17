"""Du binaire au texte localisé — et rien d'autre.

Le moteur d'intelligence ne touche jamais un binaire : il reçoit des blocs de
texte déjà situés. C'est cette séparation qui permet à une preuve de dire
« page 4 » ou « feuille Popis!B12 » plutôt que « document.pdf ».

Formats traités parce qu'ils ont été **réellement rencontrés** dans les deux
dossiers du spike : PDF, DOCX, XLSX, ZIP, XML, plus HTML et texte brut. Tout le
reste est marqué `unsupported` — écrire un parseur pour un format jamais vu
serait du code sans preuve d'utilité.

DOCX et XLSX sont lus avec la bibliothèque standard : ce sont des archives ZIP
contenant du XML, et deux dépendances de plus ne se justifient pas pour en
extraire du texte.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from defusedxml import ElementTree as DefusedET

from signals.understanding.text import plain_text

ExtractionMethod = Literal[
    "pdf_text", "docx_paragraph", "xlsx_cell", "html_text", "plain_text", "xml_text"
]

# Limite de texte extrait par document : un cahier des charges utile tient très
# largement dedans, une bombe de texte non.
MAX_TEXT_CHARS = 4_000_000

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@dataclass(frozen=True)
class TextBlock:
    """Un morceau de texte ET sa localisation dans le document.

    `locator` est ce qui rendra une preuve vérifiable par un humain :
    « page 4 », « paragraphe 137 », « Popis del!B12 ».
    """

    locator: str
    text: str
    method: ExtractionMethod
    page: int | None = None


@dataclass
class ExtractionResult:
    blocks: tuple[TextBlock, ...] = ()
    media_type: str | None = None
    supported: bool = True
    encrypted: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def text_length(self) -> int:
        return sum(len(block.text) for block in self.blocks)


def _zip_entries(data: bytes) -> frozenset[str]:
    """Les noms d'entrées d'une archive, sans jamais rien décompresser."""
    try:
        return frozenset(zipfile.ZipFile(BytesIO(data)).namelist())
    except (zipfile.BadZipFile, OSError):
        return frozenset()


def sniff_media_type(name: str | None, data: bytes) -> str:
    """Le format réel, d'après les octets d'abord et le nom ensuite."""
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:4] == b"PK\x03\x04":
        # Le contenu de l'archive tranche avant le nom : un DOCX transmis sans
        # nom de fichier resterait sinon un simple ZIP, et son texte serait perdu.
        inside = _zip_entries(data)
        if "word/document.xml" in inside:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if "xl/workbook.xml" in inside:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        lowered = (name or "").lower()
        if lowered.endswith(".docx"):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if lowered.endswith(".xlsx"):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    head = data[:512].lstrip()
    if head[:5].lower() == b"<html" or b"<!doctype html" in head[:64].lower():
        return "text/html"
    if head[:5] == b"<?xml":
        return "application/xml"
    lowered = (name or "").lower()
    for suffix, media in (
        (".pdf", "application/pdf"),
        (".html", "text/html"),
        (".htm", "text/html"),
        (".xml", "application/xml"),
        (".txt", "text/plain"),
        (".csv", "text/plain"),
    ):
        if lowered.endswith(suffix):
            return media
    return "application/octet-stream"


def extract_text(data: bytes, *, name: str | None = None) -> ExtractionResult:
    """Extrait des blocs de texte localisés, ou dit pourquoi il n'y arrive pas."""
    media = sniff_media_type(name, data)
    if media == "application/pdf":
        return _pdf(data, media)
    if media.endswith("wordprocessingml.document"):
        return _docx(data, media)
    if media.endswith("spreadsheetml.sheet"):
        return _xlsx(data, media)
    if media in ("text/html",):
        return _html(data, media)
    if media in ("application/xml",):
        return _xml(data, media)
    if media == "text/plain":
        return _plain(data, media)
    return ExtractionResult(media_type=media, supported=False)


# ─── PDF ────────────────────────────────────────────────────────────────────────


def _pdf(data: bytes, media: str) -> ExtractionResult:
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — un PDF cassé n'est pas une exception métier
        return ExtractionResult(media_type=media, supported=False, warnings=(str(exc),))
    if reader.is_encrypted:
        return ExtractionResult(media_type=media, encrypted=True)

    blocks: list[TextBlock] = []
    page_warnings: list[str] = []
    total = 0
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:  # noqa: BLE001 — une page illisible n'invalide pas les autres
            page_warnings.append(f"page {index} illisible : {exc}")
            continue
        if not text:
            continue  # page sans texte : aucun bloc, donc aucune exigence possible
        total += len(text)
        if total > MAX_TEXT_CHARS:
            return ExtractionResult(
                blocks=tuple(blocks),
                media_type=media,
                warnings=("texte tronqué : limite d'extraction atteinte",),
            )
        blocks.append(TextBlock(locator=f"page {index}", text=text, method="pdf_text", page=index))

    warnings: tuple[str, ...] = tuple(page_warnings)
    if not blocks and len(reader.pages):
        # Un PDF de pages sans couche texte : c'est un scan. On le dit, on
        # n'invente pas de contenu et on ne lance pas d'OCR par défaut.
        warnings = (*warnings, "OCR_REQUIRED_NOT_IMPLEMENTED : aucune couche texte exploitable")
    return ExtractionResult(blocks=tuple(blocks), media_type=media, warnings=warnings)


# ─── DOCX ───────────────────────────────────────────────────────────────────────


def _docx(data: bytes, media: str) -> ExtractionResult:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
        document = archive.read("word/document.xml")
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(media_type=media, supported=False, warnings=(str(exc),))

    root = DefusedET.fromstring(document)
    blocks: list[TextBlock] = []
    total = 0
    for index, paragraph in enumerate(root.iter(f"{WORD_NS}p"), start=1):
        text = "".join(node.text or "" for node in paragraph.iter(f"{WORD_NS}t")).strip()
        if not text:
            continue
        total += len(text)
        if total > MAX_TEXT_CHARS:
            break
        blocks.append(TextBlock(locator=f"paragraphe {index}", text=text, method="docx_paragraph"))
    return ExtractionResult(blocks=tuple(blocks), media_type=media)


# ─── XLSX ───────────────────────────────────────────────────────────────────────


def _xlsx(data: bytes, media: str) -> ExtractionResult:
    """Feuille par feuille, cellule par cellule — jamais un classeur concaténé.

    Un bordereau de quantités n'a de sens qu'avec sa cellule : « 120 » seul ne
    prouve rien, « Popis del!B12 = 120 » est vérifiable.
    """
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(media_type=media, supported=False, warnings=(str(exc),))

    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        root = DefusedET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in root.iter(f"{SHEET_NS}si"):
            shared.append("".join(node.text or "" for node in item.iter(f"{SHEET_NS}t")))

    names = _sheet_names(archive)
    blocks: list[TextBlock] = []
    total = 0
    for position, member in enumerate(
        sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet")), start=1
    ):
        sheet_name = names.get(position, f"feuille {position}")
        root = DefusedET.fromstring(archive.read(member))
        for cell in root.iter(f"{SHEET_NS}c"):
            reference = cell.get("r") or "?"
            value_node = cell.find(f"{SHEET_NS}v")
            if value_node is None or value_node.text is None:
                continue
            raw = value_node.text
            if cell.get("t") == "s":
                try:
                    raw = shared[int(raw)]
                except (ValueError, IndexError):
                    continue
            text = raw.strip()
            if not text:
                continue
            total += len(text)
            if total > MAX_TEXT_CHARS:
                return ExtractionResult(
                    blocks=tuple(blocks),
                    media_type=media,
                    warnings=("texte tronqué : limite d'extraction atteinte",),
                )
            blocks.append(
                TextBlock(locator=f"{sheet_name}!{reference}", text=text, method="xlsx_cell")
            )
    return ExtractionResult(blocks=tuple(blocks), media_type=media)


def _sheet_names(archive: zipfile.ZipFile) -> dict[int, str]:
    if "xl/workbook.xml" not in archive.namelist():
        return {}
    root = DefusedET.fromstring(archive.read("xl/workbook.xml"))
    return {
        index: (sheet.get("name") or f"feuille {index}")
        for index, sheet in enumerate(root.iter(f"{SHEET_NS}sheet"), start=1)
    }


# ─── HTML, XML, texte ───────────────────────────────────────────────────────────


def _html(data: bytes, media: str) -> ExtractionResult:
    text = plain_text(data.decode("utf-8", errors="replace")) or ""
    blocks = tuple(
        TextBlock(locator=f"bloc {index}", text=line, method="html_text")
        for index, line in enumerate(text.split("\n"), start=1)
        if line.strip()
    )
    return ExtractionResult(blocks=blocks, media_type=media)


def _xml(data: bytes, media: str) -> ExtractionResult:
    try:
        root = DefusedET.fromstring(data)
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(media_type=media, supported=False, warnings=(str(exc),))
    blocks: list[TextBlock] = []
    for index, node in enumerate(root.iter(), start=1):
        text = (node.text or "").strip()
        if text:
            tag = node.tag.split("}")[-1]
            blocks.append(TextBlock(locator=f"{tag}[{index}]", text=text, method="xml_text"))
    return ExtractionResult(blocks=tuple(blocks), media_type=media)


def _plain(data: bytes, media: str) -> ExtractionResult:
    text = data.decode("utf-8", errors="replace")
    blocks = tuple(
        TextBlock(locator=f"ligne {index}", text=line.strip(), method="plain_text")
        for index, line in enumerate(text.split("\n"), start=1)
        if line.strip()
    )
    return ExtractionResult(blocks=blocks, media_type=media)
