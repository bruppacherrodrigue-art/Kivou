"""Lecture volontairement bornée des formulaires HTML des portails."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(frozen=True)
class Element:
    tag: str
    attrs: dict[str, str]
    text: str = ""


@dataclass
class Form:
    attrs: dict[str, str]
    inputs: list[dict[str, str]] = field(default_factory=list)


class PortalHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.forms: list[Form] = []
        self._current_form: Form | None = None
        self._open_element: tuple[str, dict[str, str], list[str]] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "form":
            self._current_form = Form(values)
            self.forms.append(self._current_form)
        elif tag == "input" and self._current_form is not None:
            self._current_form.inputs.append(values)
        if tag in {"a", "script", "button"}:
            self._open_element = (tag, values, [])

    def handle_data(self, data: str) -> None:
        if self._open_element is not None:
            self._open_element[2].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._open_element is not None and self._open_element[0] == tag:
            opened, attrs, text = self._open_element
            self.elements.append(Element(opened, attrs, "".join(text).strip()))
            self._open_element = None
        if tag == "form":
            self._current_form = None


def parse_html(value: str) -> PortalHTMLParser:
    parser = PortalHTMLParser()
    parser.feed(value)
    return parser
