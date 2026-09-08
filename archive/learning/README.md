# Learning archive

This directory contains the experimental learning loop, Hermes helpers,
metrics, stores, and their historical tests. The production runtime does not
import this package and Hermes is not an active timer, so the code is retained
outside `src` rather than shipped as dormant application surface.

The former modules are under `source/` and the tests are under `tests/`.
Database migrations remain active and are not archived; they describe the
schema history independently of this experiment.

To study or reproduce the experiment, use an isolated checkout and run the
archived tests explicitly. Do not import this directory from acquisition,
alerts, or any systemd unit without a new architecture decision and a new
operational owner.
