from __future__ import annotations

import ast
import pathlib


def test_personalization_has_no_external_or_customer_runtime_boundary() -> None:
    package = pathlib.Path("src/signals/personalization")
    imports: set[str] = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.lower())

    forbidden = (
        "apollo",
        "instantly",
        "smtplib",
        "openrouter",
        "target_icp",
        "matchingengine",
        "stripe",
        "crawler",
        "requests.",
        "httpx.",
    )
    assert not {term for term in forbidden if any(term in item for item in imports)}
