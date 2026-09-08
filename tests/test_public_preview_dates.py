"""Attribution/publication dates on independent, chronological synthetic notices."""

import datetime as dt
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from feed_helpers import BOAMP_AGING, boamp_award
from test_qa_attribution import NOW, SECRET, issue

from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.domain.awards import ContractAward
from signals.domain.events import Provenance, PublicEvent
from signals.domain.values import Location, Money
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence import create_database_engine, migrate_to_latest
from signals.persistence.schema import opportunity_representation


@contextmanager
def public_date_context(
    tmp_path, *, award_age_days=None, notification_age_days=None, publication_age_days=2,
):
    """Ingest a distinct synthetic notice; archived source facts stay untouched."""
    published_on = NOW.date() - dt.timedelta(days=publication_age_days)
    awarded_on = (NOW.date() - dt.timedelta(days=award_age_days)
                  if award_age_days is not None else None)
    notified_on = (NOW.date() - dt.timedelta(days=notification_age_days)
                   if notification_age_days is not None else None)
    assert published_on <= NOW.date()
    assert awarded_on is None or awarded_on <= published_on
    assert notified_on is None or notified_on <= published_on
    assert awarded_on is None or notified_on is None or awarded_on <= notified_on

    # Reuse only canonical party/CPV structures, never archived chronology or identity.
    template_event, template_awards = boamp_award(BOAMP_AGING)
    template_award = template_awards[0]
    event = PublicEvent(
        provenance=Provenance(
            source_system="manual", source_country="FR",
            source_notice_id="synthetic-public-preview-dates", retrieved_at=NOW,
        ),
        event_type="award_notice", published_at=published_on,
        procedure_buyers=template_event.procedure_buyers,
    )
    award = ContractAward(
        event_ref=event.ref(), source_award_id="synthetic-public-preview-award",
        title="Construction synthetique de bureaux", cpv_main=template_award.cpv_main,
        value=Money(amount=Decimal("125000"), currency="EUR"),
        awardee_parties=template_award.awardee_parties,
        place_of_performance=Location(country="FR", locality="Ville de recette"),
        award_date=awarded_on, contract_notification_date=notified_on,
    )
    engine = create_database_engine(f"sqlite:///{tmp_path / 'public-dates.db'}")
    try:
        migrate_to_latest(engine)
        IngestionPipeline(engine).process(
            AcquiredPublication(event, (award,)), as_of=NOW.date(), persisted_at=NOW,
        )
        with engine.connect() as connection:
            opportunity = connection.execute(
                sa.select(opportunity_representation.c.opportunity_key)
            ).scalar_one()
        config = ApiConfig(
            cookie_secure=True, attribution_hmac_key=SECRET,
            attribution_hmac_key_version="test-v1", public_app_url="https://kivou.test",
            allowed_origin="https://kivou.test",
        )
        with TestClient(create_app(engine, config, now_override=lambda: NOW),
                        base_url="https://kivou.test") as client:
            yield SimpleNamespace(
                engine=engine, client=client, event=event, award=award,
                token=issue(opportunity, engine=engine),
            )
    finally:
        engine.dispose()


def preview(context):
    return context.client.post(
        "/auth/attribution/preview", headers={"Origin": "https://kivou.test"},
        json={"token": context.token},
    )


def test_public_preview_uses_notification_when_award_date_is_missing(tmp_path):
    with public_date_context(tmp_path, notification_age_days=4) as context:
        assert context.award.award_date is None
        assert context.award.contract_notification_date < context.event.published_at
        response = preview(context)
        assert response.status_code == 200
        signal = response.json()["signal"]
        assert signal["date"] == context.award.contract_notification_date.isoformat()
        assert signal["date_label"] == "Attribué le"


@pytest.mark.parametrize("notification_age_days", [None, 4], ids=["award-only", "both-dates"])
def test_public_preview_preserves_award_date_precedence(tmp_path, notification_age_days):
    with public_date_context(
        tmp_path, award_age_days=6, notification_age_days=notification_age_days,
    ) as context:
        response = preview(context)
        assert response.status_code == 200
        signal = response.json()["signal"]
        assert signal["date"] == context.award.award_date.isoformat()
        assert signal["date_label"] == "Attribué le"


@pytest.mark.parametrize("age_days", [2, 30, 31])
def test_publication_only_preview_respects_the_30_day_boundary(tmp_path, age_days):
    with public_date_context(tmp_path, publication_age_days=age_days) as context:
        assert context.award.award_date is None
        assert context.award.contract_notification_date is None
        response = preview(context)
        if age_days == 31:
            assert response.status_code == 400
            return
        assert response.status_code == 200
        signal = response.json()["signal"]
        assert signal["date"] == context.event.published_at.isoformat()
        assert signal["date_label"] == "Publié le"
