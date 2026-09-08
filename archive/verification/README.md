# Verification archive

This directory contains the completed document-verification implementation,
provider experiments, fixtures, and contract tests. It is preserved to make
the original campaign and its evidence reproducible, but it is no longer part
of the runtime verification path.

The former modules are under `source/` and their tests are under `tests/`.
They are intentionally outside the Python package and pytest discovery. The
active application keeps the persisted evidence and migration history needed
by current signal decisions.

To inspect this material, use an isolated checkout and run a selected archived
test explicitly. Do not import it from `src/signals`, add it to `pyproject`, or
ship it in a release. Any replacement verifier must be implemented in the
active package with an explicit provenance and publication-policy contract.
