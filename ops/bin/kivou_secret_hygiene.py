#!/usr/bin/env python3
"""Rotate and audit the four staging secrets without exposing their values."""

from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import pathlib
import secrets
import stat
import sys
import tempfile
import urllib.parse
import warnings

SECRET_NAMES = (
    "KIVOU_DATABASE_URL",
    "SMTP_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)
_SECRET_NAME_SET = frozenset(SECRET_NAMES)
_PROVIDER_SECRET_NAMES = SECRET_NAMES[1:]
_PROTECTED_MODE = 0o600


class _SafeFailure(Exception):
    code = "invalid_input"


class _InvalidInput(_SafeFailure):
    """An intentionally detail-free input failure."""


class _DatabaseUpdateFailed(_SafeFailure):
    code = "database_update_failed"


class _DatabaseStateUnknown(_SafeFailure):
    code = "database_state_unknown"


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


def _parse_values(
    text: str,
    *,
    require_complete: bool,
    allow_empty: bool = False,
) -> dict[str, str]:
    if not text:
        if allow_empty:
            return {}
        raise _InvalidInput
    if "\x00" in text:
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


def _serialize_values(values: dict[str, str]) -> str:
    return "".join(
        f"{name}={values[name]}\n" for name in SECRET_NAMES if name in values
    )


def _read_secret_from_tty(name: str) -> str:
    descriptor = -1
    try:
        descriptor = os.open(
            "/dev/tty",
            os.O_RDWR | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        if not os.isatty(descriptor):
            raise _InvalidInput
    except OSError:
        raise _InvalidInput from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(f"{name}: ")
    except Exception:  # noqa: BLE001 - error text could contain the entered value
        raise _InvalidInput from None
    return value


def _validate_provider_secret(name: str, value: str) -> None:
    if name not in _PROVIDER_SECRET_NAMES:
        raise _InvalidInput
    if (
        not value
        or not value.strip()
        or any(character in value for character in "\x00\r\n")
    ):
        raise _InvalidInput
    if name == "STRIPE_SECRET_KEY" and not value.startswith("sk_test_"):
        raise _InvalidInput
    if name == "STRIPE_WEBHOOK_SECRET" and not value.startswith("whsec_"):
        raise _InvalidInput


def _extract_database_url(environment_text: str) -> str:
    database_url: str | None = None
    for line in environment_text.splitlines():
        name, separator, value = line.partition("=")
        if separator and name == "KIVOU_DATABASE_URL":
            if database_url is not None or not value or not value.strip():
                raise _InvalidInput
            database_url = value
    if database_url is None:
        raise _InvalidInput
    return database_url


def _postgres_urls(old_url: str, new_password: str) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(old_url)
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise _InvalidInput
        if parsed.username != "kivou_app" or parsed.password is None or parsed.hostname is None:
            raise _InvalidInput
        if parsed.fragment or "@" not in parsed.netloc:
            raise _InvalidInput
        raw_userinfo, raw_hostinfo = parsed.netloc.rsplit("@", 1)
        raw_username = raw_userinfo.split(":", 1)[0]
        candidate_netloc = (
            f"{raw_username}:{urllib.parse.quote(new_password, safe='')}@{raw_hostinfo}"
        )
        candidate_url = urllib.parse.urlunsplit(
            parsed._replace(netloc=candidate_netloc)
        )
        connection_url = urllib.parse.urlunsplit(parsed._replace(scheme="postgresql"))
    except (TypeError, ValueError):
        raise _InvalidInput from None
    return candidate_url, connection_url


def _generate_postgres_password() -> str:
    return secrets.token_urlsafe(48)


def _connect_postgres(url: str, *, autocommit: bool) -> object:
    psycopg = importlib.import_module("psycopg")
    return psycopg.connect(url, autocommit=autocommit)


def _close_without_error(resource: object | None) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:  # noqa: BLE001 - close errors may contain connection secrets
        return


def _alter_postgres_role(connection_url: str, new_password: str) -> None:
    connection: object | None = None
    try:
        try:
            connection = _connect_postgres(connection_url, autocommit=True)
        except Exception:  # noqa: BLE001 - driver errors may contain the old URL
            raise _DatabaseUpdateFailed from None

        try:
            password_protocol = connection.pgconn
            change_password = password_protocol.change_password
        except (AttributeError, TypeError):
            raise _DatabaseUpdateFailed from None

        try:
            change_password(b"kivou_app", new_password.encode("utf-8"))
        except Exception:  # noqa: BLE001 - protocol errors may contain credentials
            raise _DatabaseStateUnknown from None
    finally:
        _close_without_error(connection)


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


def _set_secret(name: str, values_file: pathlib.Path) -> int:
    values_text, metadata = _read_protected_file(values_file)
    values = _parse_values(values_text, require_complete=False, allow_empty=True)
    value = _read_secret_from_tty(name)
    _validate_provider_secret(name, value)
    if value in values.values():
        raise _InvalidInput
    values[name] = value
    _atomic_replace(values_file, _serialize_values(values), metadata)
    _emit_counters(
        {
            "secret_values_present": len(values),
            "secret_values_stored": 1,
        }
    )
    return 0


def _rotate_postgres_password(
    old_env_file: pathlib.Path,
    values_file: pathlib.Path,
) -> int:
    old_environment_text, old_metadata = _read_protected_file(old_env_file)
    values_text, values_metadata = _read_protected_file(values_file)
    if (old_metadata.st_dev, old_metadata.st_ino) == (
        values_metadata.st_dev,
        values_metadata.st_ino,
    ):
        raise _InvalidInput

    old_url = _extract_database_url(old_environment_text)
    values = _parse_values(values_text, require_complete=False, allow_empty=True)
    new_password = _generate_postgres_password()
    if (
        not new_password
        or not new_password.strip()
        or any(character in new_password for character in "\x00\r\n")
        or new_password in values.values()
    ):
        raise _InvalidInput
    candidate_url, connection_url = _postgres_urls(old_url, new_password)
    values["KIVOU_DATABASE_URL"] = candidate_url
    _atomic_replace(values_file, _serialize_values(values), values_metadata)

    try:
        _alter_postgres_role(connection_url, new_password)
    except _DatabaseUpdateFailed:
        _atomic_replace(values_file, values_text, values_metadata)
        raise

    _emit_counters(
        {
            "database_password_rotated": 1,
            "secret_values_present": len(values),
        }
    )
    return 0


def _audit_journal(values_files: list[pathlib.Path]) -> int:
    secret_values: list[str] = []
    seen_values: set[str] = set()
    for values_file in values_files:
        values_text, _metadata = _read_protected_file(values_file)
        for value in _parse_values(values_text, require_complete=True).values():
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

    set_secret_parser = subcommands.add_parser("set-secret")
    set_secret_parser.add_argument("name", choices=_PROVIDER_SECRET_NAMES)
    set_secret_parser.add_argument("--values-file", required=True, type=pathlib.Path)

    rotate_postgres_parser = subcommands.add_parser("rotate-postgres-password")
    rotate_postgres_parser.add_argument(
        "--old-env-file",
        required=True,
        type=pathlib.Path,
    )
    rotate_postgres_parser.add_argument(
        "--values-file",
        required=True,
        type=pathlib.Path,
    )

    audit_parser = subcommands.add_parser("audit-journal")
    audit_parser.add_argument("values_files", nargs="+", type=pathlib.Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "replace-env":
            return _replace_env(arguments.values_file, arguments.target)
        if arguments.command == "set-secret":
            return _set_secret(arguments.name, arguments.values_file)
        if arguments.command == "rotate-postgres-password":
            return _rotate_postgres_password(
                arguments.old_env_file,
                arguments.values_file,
            )
        return _audit_journal(arguments.values_files)
    except _SafeFailure as error:
        sys.stderr.write(f"error={error.code}\n")
        return 2
    except Exception:  # noqa: BLE001 - fail closed without rendering exception content
        # The error is deliberately opaque: exception messages may embed file content.
        sys.stderr.write("error=invalid_input\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
