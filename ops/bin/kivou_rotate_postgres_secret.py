#!/usr/bin/env python3
"""Rotate the staging PostgreSQL role secret without exposing its value."""

from __future__ import annotations

import argparse
import pathlib
import secrets
import sys
import urllib.parse

import kivou_secret_hygiene as hygiene
import psycopg

_ROLE_NAME = "kivou_app"
_DATABASE_PATH = "/kivou_staging"
_LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_ALLOWED_SSL_MODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)


class _SafeFailure(Exception):
    code = "invalid_input"


class _DatabaseUpdateFailed(_SafeFailure):
    code = "database_update_failed"


class _DatabaseStateUnknown(_SafeFailure):
    code = "database_state_unknown"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "error=invalid_arguments\n")


def _extract_database_url(environment_text: str) -> str:
    database_url: str | None = None
    for line in environment_text.splitlines():
        name, separator, value = line.partition("=")
        if separator and name == "KIVOU_DATABASE_URL":
            if database_url is not None or not value or not value.strip():
                raise hygiene._InvalidInput
            database_url = value
    if database_url is None:
        raise hygiene._InvalidInput
    return database_url


def _postgres_urls(old_url: str, new_password: str) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(old_url)
        connection_options = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise hygiene._InvalidInput
        if (
            parsed.username != _ROLE_NAME
            or parsed.password is None
            or parsed.hostname not in _LOCAL_DATABASE_HOSTS
            or parsed.path != _DATABASE_PATH
            or parsed.port not in (None, 5432)
        ):
            raise hygiene._InvalidInput
        if connection_options and (
            len(connection_options) != 1
            or connection_options[0][0] != "sslmode"
            or connection_options[0][1] not in _ALLOWED_SSL_MODES
        ):
            raise hygiene._InvalidInput
        if parsed.fragment or "@" not in parsed.netloc:
            raise hygiene._InvalidInput
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
        raise hygiene._InvalidInput from None
    return candidate_url, connection_url


def _generate_postgres_password() -> str:
    return secrets.token_urlsafe(48)


def _connect_postgres(url: str, *, autocommit: bool) -> object:
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
            change_password(_ROLE_NAME.encode("ascii"), new_password.encode("utf-8"))
        except Exception:  # noqa: BLE001 - protocol errors may contain credentials
            raise _DatabaseStateUnknown from None
    finally:
        _close_without_error(connection)


def _rotate_postgres_password(
    old_env_file: pathlib.Path,
    values_file: pathlib.Path,
) -> int:
    old_environment_text, old_metadata = hygiene._read_protected_file(old_env_file)
    values_text, values_metadata = hygiene._read_protected_file(values_file)
    if (old_metadata.st_dev, old_metadata.st_ino) == (
        values_metadata.st_dev,
        values_metadata.st_ino,
    ):
        raise hygiene._InvalidInput

    old_url = _extract_database_url(old_environment_text)
    values = hygiene._parse_values(
        values_text,
        require_complete=False,
        allow_empty=True,
    )
    hygiene._validate_new_values(values)
    new_password = _generate_postgres_password()
    if (
        not new_password
        or not new_password.strip()
        or any(character in new_password for character in "\x00\r\n")
        or new_password in values.values()
    ):
        raise hygiene._InvalidInput
    candidate_url, connection_url = _postgres_urls(old_url, new_password)
    values["KIVOU_DATABASE_URL"] = candidate_url
    hygiene._atomic_replace(
        values_file,
        hygiene._serialize_values(values),
        values_metadata,
    )

    try:
        _alter_postgres_role(connection_url, new_password)
    except _DatabaseUpdateFailed:
        hygiene._atomic_replace(values_file, values_text, values_metadata)
        raise

    hygiene._emit_counters(
        {
            "database_password_rotated": 1,
            "secret_values_present": len(values),
        }
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--old-env-file", required=True, type=pathlib.Path)
    parser.add_argument("--values-file", required=True, type=pathlib.Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        return _rotate_postgres_password(
            arguments.old_env_file,
            arguments.values_file,
        )
    except _SafeFailure as error:
        sys.stderr.write(f"error={error.code}\n")
        return 2
    except hygiene._SafeFailure as error:
        sys.stderr.write(f"error={error.code}\n")
        return 2
    except Exception:  # noqa: BLE001 - exception messages may contain credentials
        sys.stderr.write("error=invalid_input\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
