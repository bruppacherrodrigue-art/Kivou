from __future__ import annotations

import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parents[1]
SHARDER = ROOT / "ops/bin/kivou-pytest-shard.sh"


def test_pytest_shards_are_disjoint_and_cover_the_collection(tmp_path: pathlib.Path) -> None:
    collected = tmp_path / "collected.txt"
    collected.write_text("\n".join(f"tests/test_{index}.py::test_case" for index in range(11)), encoding="utf-8")
    selected: list[set[str]] = []

    for shard in range(4):
        log = tmp_path / f"shard-{shard}.txt"
        runner = tmp_path / f"runner-{shard}.sh"
        runner.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$KIVOU_SHARD_LOG"\n',
            encoding="utf-8",
        )
        runner.chmod(0o755)
        result = subprocess.run(
            [str(SHARDER), str(shard), "4"],
            cwd=ROOT,
            env={
                **os.environ,
                "KIVOU_PYTEST_COLLECTION_FILE": str(collected),
                "KIVOU_PYTEST_RUNNER": str(runner),
                "KIVOU_SHARD_LOG": str(log),
            },
            check=False,
        )
        assert result.returncode == 0
        selected.append(set(log.read_text(encoding="utf-8").splitlines()) - {"-q"})

    assert set.union(*selected) == set(collected.read_text(encoding="utf-8").splitlines())
    assert sum(len(shard) for shard in selected) == 11
    assert max(map(len, selected)) - min(map(len, selected)) <= 1
