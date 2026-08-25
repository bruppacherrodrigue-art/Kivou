#!/usr/bin/env python3
"""Rotate and audit the four staging secrets without exposing their values."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import sys
import tempfile

SECRET_NAMES = (
    "KIVOU_DATABASE_URL",
    "SMTP_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)
_SECRET_NAME_SET = frozenset(SECRET_NAMES)
_PROTECTED_MODE = 0o600


class _InvalidInput(Exception):
    """An intentionally detail-free input failure."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "error=invalid_arguments\n")


def _read_protected_file(path: pathlib.Path) -> tuple[str, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise _InvalidInput
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise _InvalidInput
        if stat.S_IMODE(metadata.st_mode) != _PROTECTED_MODE:
            raise _InvalidInput
        with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as stream:
            descriptor = -1
            return stream.read(), metadata
    except _InvalidInput:
        raise
    except (OSError, UnicodeError):
        raise _InvalidInput from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parse_values(text: str, *, require_complete: bool) -> dict[str, str]:
    if not text or "\x00" in text:
        raise _InvalidInput

    values: dict[str, str] = {}
    seen_values: set[str] = set()
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if not separator or name not in _SECRET_NAME_SET:
            raise _InvalidInput
        if name in values or not value or not value.strip() or value in seen_values:
            raise _InvalidInput
        if "\n" in value or "\r" in value:
            raise _InvalidInput
        values[name] = value
        seen_values.add(value)

    if not values or (require_complete and set(values) != _SECRET_NAME_SET):
        raise _InvalidInput
    return values


def _rewrite_target(target_text: str, replacements: dict[str, str]) -> tuple[str, int]:
    lines = target_text.splitlines(keepends=True)
    replaced: set[str] = set()
    rewritten: list[str] = []

    for line in lines:
        if line.endswith("\r\n"):
            content, ending = line[:-2], "\r\n"
        elif line.endswith(("\n", "\r")):
            content, ending = line[:-1], line[-1]
        else:
            content, ending = line, ""

        name, separator, _current_value = content.partition("=")
        if separator and name in _SECRET_NAME_SET:
            if name in replaced:
                raise _InvalidInput
            rewritten.append(f"{name}={replacements[name]}{ending}")
            replaced.add(name)
        else:
            rewritten.append(line)

    if replaced != _SECRET_NAME_SET:
        raise _InvalidInput
    return "".join(rewritten), len(lines)


def _atomic_replace(
    target: pathlib.Path,
    replacement_text: str,
    metadata: os.stat_result,
) -> None:
    descriptor = -1
    temporary_path: pathlib.Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            dir=target.parent,
        )
        temporary_path = pathlib.Path(temporary_name)
        os.fchown(descriptor, metadata.st_uid, metadata.st_gid)
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            descriptor = -1
            stream.write(replacement_text)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary_path, target)
        temporary_path = None

        directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        directory_flags |= getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(target.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except _InvalidInput:
        raise
    except OSError:
        raise _InvalidInput from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _emit_counters(counters: dict[str, int]) -> None:
    json.dump(counters, sys.stdout, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")


def _replace_env(values_file: pathlib.Path, target: pathlib.Path) -> int:
    values_text, _values_metadata = _read_protected_file(values_file)
    replacements = _parse_values(values_text, require_complete=True)
    target_text, target_metadata = _read_protected_file(target)
    replacement_text, line_count = _rewrite_target(target_text, replacements)
    _atomic_replace(target, replacement_text, target_metadata)
    _emit_counters(
        {
            "secret_values_replaced": len(replacements),
            "target_lines_written": line_count,
        }
    )
    return 0


def _audit_journal(values_files: list[pathlib.Path]) -> int:
    secret_values: list[str] = []
    seen_values: set[str] = set()
    for values_file in values_files:
        values_text, _metadata = _read_protected_file(values_file)
        for value in _parse_values(values_text, require_complete=False).values():
            if value in seen_values:
                raise _InvalidInput
            seen_values.add(value)
            secret_values.append(value)

    matching_lines = 0
    matching_occurrences = 0
    for line in sys.stdin:
        occurrences = sum(line.count(value) for value in secret_values)
        if occurrences:
            matching_lines += 1
            matching_occurrences += occurrences

    _emit_counters(
        {
            "secret_values_checked": len(secret_values),
            "matching_lines": matching_lines,
            "matching_occurrences": matching_occurrences,
        }
    )
    return 1 if matching_occurrences else 0


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_SafeArgumentParser,
    )

    replace_parser = subcommands.add_parser("replace-env")
    replace_parser.add_argument("--values-file", required=True, type=pathlib.Path)
    replace_parser.add_argument("--target", required=True, type=pathlib.Path)

    audit_parser = subcommands.add_parser("audit-journal")
    audit_parser.add_argument("values_files", nargs="+", type=pathlib.Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "replace-env":
            return _replace_env(arguments.values_file, arguments.target)
        return _audit_journal(arguments.values_files)
    except Exception:  # noqa: BLE001 - fail closed without rendering exception content
        # The error is deliberately opaque: exception messages may embed file content.
        sys.stderr.write("error=invalid_input\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
