#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 2 ]] || { printf 'usage: %s SHARD TOTAL\n' "$0" >&2; exit 64; }
shard=$1
total=$2
[[ "$shard" =~ ^[0-9]+$ && "$total" =~ ^[1-9][0-9]*$ && "$shard" -lt "$total" ]] \
  || { printf 'invalid shard\n' >&2; exit 64; }

collection=$(mktemp)
trap 'rm -f "$collection"' EXIT
if [[ -n "${KIVOU_PYTEST_COLLECTION_FILE:-}" ]]; then
  cp "$KIVOU_PYTEST_COLLECTION_FILE" "$collection"
else
  uv run pytest --collect-only -q | sed -n '/::/p' > "$collection"
fi

selected=()
index=0
while IFS= read -r node || [[ -n "$node" ]]; do
  [[ -n "$node" ]] || continue
  if (( index % total == shard )); then selected+=("$node"); fi
  ((index += 1))
done < "$collection"
[[ ${#selected[@]} -gt 0 ]] || { printf 'empty shard %s/%s\n' "$shard" "$total" >&2; exit 1; }

if [[ -n "${KIVOU_PYTEST_RUNNER:-}" ]]; then
  "$KIVOU_PYTEST_RUNNER" -q "${selected[@]}"
else
  uv run pytest -q "${selected[@]}"
fi
