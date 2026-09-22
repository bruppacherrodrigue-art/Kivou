from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).parents[1]


def test_ci_routes_changes_and_keeps_one_decision_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "git diff --name-only" in workflow
    assert "frontend/*) frontend=true" in workflow
    assert "if [[ \"$EVENT_NAME\" == push ]]" in workflow
    assert "backend_shards=[0,1,2,3]" in workflow
    assert "[[ \"$milomail_only\" == true ]] && shards='[0]'" in workflow
    assert "matrix:\n        shard: ${{ fromJSON(needs.changes.outputs.backend_shards) }}" in workflow
    assert "ops/bin/kivou-pytest-shard.sh" in workflow
    assert "tests/test_milomail_*.py" in workflow
    assert "name: CI décisionnelle" in workflow
    assert "needs: [changes, backend, frontend]" in workflow
