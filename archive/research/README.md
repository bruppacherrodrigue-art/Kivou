# Research archive

This directory contains the completed signal research corpus and benchmark
material that is not part of the production package. It is retained for audit,
reproduction, and historical comparison only.

The former Python modules are under `source/`; their tests and fixtures are
under `tests/`. `spec009c/` contains the protected benchmark files moved from
the working tree before cleanup. Nothing in this directory is importable by
the application or collected by CI.

To reproduce an old study, create an isolated checkout at the recorded
commit, add this directory explicitly to `PYTHONPATH`, and run only the test
files under `tests/`. Do not add the archive to the application package or
production deployment. New production behavior belongs under `src/signals` and
must have an active owner and architecture test.
