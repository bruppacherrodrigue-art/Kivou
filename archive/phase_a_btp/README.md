# Phase A BTP archive

This directory contains the completed Phase A BTP demonstration code, sample
JSON, and its tests. The demonstration is not a production route, worker, or
ingestion source, so it has been removed from the active package.

The former modules and demonstration data are under `source/`; the historical
tests are under `tests/`. They are not imported by the application and are not
collected by CI.

To reproduce the demonstration, use an isolated checkout and invoke its test
files explicitly. Do not restore it into `src/signals` or connect it to a
timer. Production changes must use an active API or runtime boundary and a
reviewed test contract.
