"""Pure, non-networking extraction of the prospect's current response."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser

from pydantic import BaseModel, ConfigDict

MAX_CLASSIFIER_INPUT_BYTES = 16_384


class ResponseContentUnavailable(ValueError):
    """Content cannot be exposed safely to deterministic rules or a classifier."""


class NormalizedResponseContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    subject: str
    current_response: str
    source: str


class _TextExtractor(HTMLParser):
    _BLOCKS = frozenset(
        {"address", "article", "blockquote", "br", "div", "footer", "header", "li", "p", "tr"}
    )
    _IGNORED = frozenset({"script", "style", "svg", "template", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._IGNORED:
            self._ignored_depth += 1
        elif tag in self._BLOCKS and not self._ignored_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._BLOCKS and not self._ignored_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


_QUOTED_BOUNDARY = re.compile(
    r"^(?:on\s.+\swrote:|le\s.+\sa\s(?:é|e)crit\s?:|from:\s|de\s?:\s)",
    re.IGNORECASE,
)
_SPACE = re.compile(r"[^\S\n]+")


def _plain_html(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception as exc:  # HTMLParser should fail closed without reflecting input.
        raise ResponseContentUnavailable("response HTML extraction failed") from exc
    return html.unescape("".join(parser.parts))


def _canonical(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    value = _SPACE.sub(" ", value)
    lines: list[str] = []
    for raw_line in value.split("\n"):
        line = raw_line.strip()
        if line.startswith(">"):
            continue
        if _QUOTED_BOUNDARY.match(line):
            break
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(line)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def normalize_response_content(
    *, subject: str | None, body_text: str | None, body_html: str | None
) -> NormalizedResponseContent:
    raw: str
    source: str
    if body_text is not None and body_text.strip():
        raw = body_text
        source = "TEXT"
    elif body_html is not None and body_html.strip():
        raw = _plain_html(body_html)
        source = "HTML"
    else:
        raise ResponseContentUnavailable("response content is unavailable")
    current = _canonical(raw)
    if not current:
        raise ResponseContentUnavailable("response content is unavailable")
    if len(current.encode("utf-8")) > MAX_CLASSIFIER_INPUT_BYTES:
        raise ResponseContentUnavailable("response content exceeds the safe boundary")
    return NormalizedResponseContent(
        subject=_canonical(subject or ""),
        current_response=current,
        source=source,
    )


__all__ = [
    "MAX_CLASSIFIER_INPUT_BYTES",
    "NormalizedResponseContent",
    "ResponseContentUnavailable",
    "normalize_response_content",
]
