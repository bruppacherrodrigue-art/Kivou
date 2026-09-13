"""Process-local host lock for enrichment commands."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class InstanceAlreadyRunning(RuntimeError):
    """The same host already owns the requested enrichment lock."""


@contextmanager
def exclusive_instance_lock(path: str | Path) -> Iterator[None]:
    """Hold one non-blocking exclusive lock for the context lifetime."""

    descriptor = os.open(Path(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise InstanceAlreadyRunning(str(path)) from error
        yield
    finally:
        os.close(descriptor)


__all__ = ["InstanceAlreadyRunning", "exclusive_instance_lock"]
