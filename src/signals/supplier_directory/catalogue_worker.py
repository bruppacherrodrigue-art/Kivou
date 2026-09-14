"""Scheduled, least-data HTTPS catalogue transfer into isolated staging only."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os

import httpx
import sqlalchemy as sa

from signals.persistence.database import create_database_engine
from signals.supplier_directory.catalogue_mirror import apply_snapshot
from signals.supplier_directory.catalogue_publication import MAX_SNAPSHOT_BYTES, CatalogueSnapshot

SOURCE_URL = "https://kivou.eu/api/internal/company-catalogue"


@dataclasses.dataclass(frozen=True)
class MirrorConfiguration:
    environment: str
    database_url: str = dataclasses.field(repr=False)
    token: str = dataclasses.field(repr=False)

    def __post_init__(self):
        try:
            url = sa.make_url(self.database_url)
        except (ValueError, sa.exc.ArgumentError) as error:
            raise ValueError("catalogue staging configuration invalid") from error
        if (
            self.environment != "STAGING"
            or url.get_backend_name() != "postgresql"
            or url.database != "kivou_staging"
            or url.query
            or not 32 <= len(self.token) <= 256
            or not self.token.isascii()
            or any(character.isspace() for character in self.token)
        ):
            raise ValueError("catalogue staging configuration invalid")

    @classmethod
    def from_environment(cls) -> MirrorConfiguration:
        return cls(
            environment=os.environ.get("KIVOU_ACQUISITION_ENVIRONMENT", ""),
            database_url=os.environ.get("KIVOU_DATABASE_URL", ""),
            token=os.environ.get("KIVOU_CATALOGUE_PUBLICATION_TOKEN", ""),
        )


def download_snapshot(client: httpx.Client, *, token: str) -> CatalogueSnapshot:
    try:
        with client.stream(
            "GET", SOURCE_URL, headers={"Authorization": f"Bearer {token}"}, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                raise ValueError("catalogue transport failed")
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_SNAPSHOT_BYTES:
                    raise ValueError("catalogue body size exceeded")
                body.extend(chunk)
    except httpx.HTTPError as error:
        raise ValueError("catalogue transport failed") from error
    try:
        return CatalogueSnapshot.model_validate_json(bytes(body))
    except ValueError as error:
        raise ValueError("catalogue payload invalid") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the validated staging mirror")
    args = parser.parse_args(argv)
    engine = None
    try:
        config = MirrorConfiguration.from_environment()
        engine = create_database_engine(config.database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            if connection.scalar(sa.text("SELECT current_database()")) != "kivou_staging":
                raise ValueError("catalogue database must be staging")
        with httpx.Client(
            timeout=httpx.Timeout(30.0, connect=5.0), trust_env=False, follow_redirects=False
        ) as client:
            snapshot = download_snapshot(client, token=config.token)
        if args.apply:
            with engine.begin() as connection:
                connection.execute(sa.text("SET LOCAL statement_timeout = '60000ms'"))
                result = apply_snapshot(
                    connection,
                    snapshot,
                    destination_environment=config.environment,
                    now=dt.datetime.now(dt.UTC),
                )
        else:
            result = {"source_total": snapshot.total}
        print(
            json.dumps(
                {"status": "applied" if args.apply else "validated", **result}, sort_keys=True
            )
        )
        return 0
    except (ValueError, OSError, sa.exc.SQLAlchemyError):
        # No URL, bearer, raw response or database exception enters systemd's journal.
        print(json.dumps({"status": "failed", "code": "catalogue_mirror_failed"}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
