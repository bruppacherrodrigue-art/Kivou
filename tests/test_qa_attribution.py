from __future__ import annotations

import datetime as dt
import importlib.util
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from feed_helpers import BOAMP_AGING, BOAMP_PUBLICATION_ONLY, MATERIALIZED_AT, boamp_award

from signals.accounts import service as accounts
from signals.accounts.schema import account, account_landing_signal, auth_user, target_icp
from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.conversion.token import AttributionTokenKeyring
from signals.engagement import analytics
from signals.engagement.schema import product_event, signal_feedback
from signals.founder_api.read_models import FounderReadService
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.sources import AcquiredPublication
from signals.persistence import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    opportunity_representation,
)

NOW = MATERIALIZED_AT + dt.timedelta(hours=1)
SECRET = b"synthetic-qa-attribution-test-secret"


def qa_module():
    assert importlib.util.find_spec("signals.conversion.qa_token") is not None, (
        "A campaign-free, signed QA token runtime is required"
    )
    from signals.conversion import qa_token

    return qa_token


def keyring():
    return AttributionTokenKeyring(current_key_version="test-v1", keys={"test-v1": SECRET})


def issue(opportunity_key="opp_test", **overrides):
    data = {
        "opportunity_key": opportunity_key, "wedge": "construction", "country": "FR",
        "sector": "bardage metallique", "need": "materials_or_components",
        "issued_at": NOW, "expires_at": NOW + dt.timedelta(days=7),
    }
    data.update(overrides)
    qa = qa_module()
    return qa.issue(qa.QaTokenPayload(**data), keyring=keyring())


def test_signed_recipe_token_without_campaign_or_member():
    raw = issue()
    payload = qa_module().verify(raw, keyring=keyring(), at=NOW)
    assert payload.qa is True
    assert payload.sector == "bardage metallique"
    assert "member_ref" not in payload.model_dump()
    assert "campaign_ref" not in payload.model_dump()
    assert raw.startswith("kqa1.")


@pytest.mark.parametrize("offset", [-1, 7 * 86400])
def test_recipe_rejects_future_and_expired_token(offset):
    raw = issue()
    with pytest.raises(ValueError):
        qa_module().verify(raw, keyring=keyring(), at=NOW + dt.timedelta(seconds=offset))


def test_recipe_rejects_tampering_and_other_keys():
    raw = issue()
    parts = raw.split(".")
    parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
    with pytest.raises(ValueError):
        qa_module().verify(".".join(parts), keyring=keyring(), at=NOW)
    wrong = AttributionTokenKeyring(current_key_version="test-v1", keys={"test-v1": b"x" * 32})
    with pytest.raises(ValueError):
        qa_module().verify(raw, keyring=wrong, at=NOW)


def test_recipe_rejects_unknown_fields_and_excessive_ttl():
    qa = qa_module()
    with pytest.raises(ValueError):
        issue(expires_at=NOW + dt.timedelta(days=8))
    with pytest.raises(ValueError):
        issue(campaign_ref="must-not-be-accepted")
    with pytest.raises(ValueError):
        issue(qa=False)
    with pytest.raises(ValueError):
        qa.QaTokenPayload.model_validate({})


def test_cli_refuses_absent_key_before_database_or_send(monkeypatch, capsys):
    qa_module()
    from signals.conversion.mint_token import main

    monkeypatch.delenv("KIVOU_ATTRIBUTION_HMAC_KEY", raising=False)
    monkeypatch.delenv("KIVOU_ATTRIBUTION_HMAC_KEY_VERSION", raising=False)
    assert main([
        "--opportunity", "opp_test", "--wedge", "construction", "--country", "FR",
        "--sector", "bardage", "--need", "materials_or_components", "--ttl", "7d",
    ]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "KIVOU_ATTRIBUTION_HMAC_KEY" in output.err


@pytest.fixture
def prepared_qa(tmp_path):
    qa_module()
    engine = create_database_engine(f"sqlite:///{tmp_path / 'qa.db'}")
    migrate_to_latest(engine)
    # This published notice supplies a real execution location in France.
    # Keep its facts unchanged; a buyer's country is not an execution location.
    event, awards = boamp_award(BOAMP_AGING)
    IngestionPipeline(engine).process(
        AcquiredPublication(event, awards), as_of=NOW.date(), persisted_at=NOW,
    )
    with engine.connect() as connection:
        opportunity_key = connection.scalar(sa.select(opportunity_representation.c.opportunity_key))
    config = ApiConfig(
        cookie_secure=True, attribution_hmac_key=SECRET,
        attribution_hmac_key_version="test-v1", public_app_url="https://kivou.test",
    )
    client = TestClient(
        create_app(engine, config, now_override=lambda: NOW), base_url="https://kivou.test",
    )
    yield engine, client, opportunity_key
    engine.dispose()


def test_mint_is_read_only_and_logs_no_secret(prepared_qa, capsys):
    from signals.conversion.mint_token import mint_url

    engine, _, opportunity = prepared_qa
    with engine.connect() as connection:
        before = connection.scalar(sa.select(sa.func.count()).select_from(account))
    url = mint_url(
        engine=engine, keyring=keyring(), origin="https://kivou.test",
        opportunity=opportunity, wedge="construction", country="FR",
        sector="bardage metallique", need="materials_or_components", ttl="7d", now=NOW,
    )
    assert url.startswith("https://kivou.test/a/kqa1.")
    output = capsys.readouterr()
    assert '"qa": true' in output.err
    assert url not in output.err
    assert SECRET.decode() not in output.err
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(account)) == before
        assert connection.scalar(sa.select(sa.func.count()).select_from(account_landing_signal)) == 0
    with pytest.raises(ValueError):
        mint_url(
            engine=engine, keyring=keyring(), origin="https://kivou.test",
            opportunity="opp_missing", wedge="construction", country="FR",
            sector="bardage", need="materials_or_components", ttl="7d", now=NOW,
        )


def test_qa_landing_is_replayable_and_has_no_commercial_attribution(prepared_qa):
    engine, client, opportunity = prepared_qa
    raw = issue(opportunity)
    first = client.get(f"/a/{raw}", follow_redirects=False)
    second = client.get(f"/a/{raw}", follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert first.headers["location"].startswith("/app/signals/")
    assert first.headers["location"] == second.headers["location"]
    assert first.headers["cache-control"] == "no-store"
    assert not any(c.startswith("kivou_attribution=") and "Max-Age=0" not in c
                   for c in first.headers.get_list("set-cookie"))
    with engine.connect() as connection:
        landing = connection.execute(sa.select(account_landing_signal)).mappings().one()
        assert landing["qa"] is True
        assert landing["opportunity_key"] == opportunity
        assert connection.scalar(sa.select(sa.func.count()).select_from(account)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(target_icp)) == 1
        for table in (acquisition_campaign, acquisition_campaign_member,
                      acquisition_conversion_event, acquisition_conversion_journey):
            assert connection.scalar(sa.select(sa.func.count()).select_from(table)) == 0
        events = connection.execute(sa.select(product_event)).mappings().all()
        assert len(events) == 2
        assert all(e["properties"]["qa"] is True for e in events)
        assert [e["properties"]["replayed"] for e in events] == [False, True]


def test_qa_link_cannot_reopen_a_confirmed_identity(prepared_qa):
    engine, client, opportunity = prepared_qa
    raw = issue(opportunity)
    first = client.get(f"/a/{raw}", follow_redirects=False)
    assert first.status_code == 303
    assert first.headers["location"].startswith("/app/signals/")
    with engine.begin() as connection:
        connection.execute(sa.update(auth_user).values(email_normalized="confirmed@example.invalid"))
    response = client.get(f"/a/{raw}", follow_redirects=False)
    assert response.headers["location"] == "/signup?attribution=expired"


def test_qa_activity_is_excluded_from_product_and_founder_metrics(prepared_qa):
    engine, client, opportunity = prepared_qa
    client.get(f"/a/{issue(opportunity)}", follow_redirects=False)
    with engine.begin() as connection:
        landing = connection.execute(sa.select(account_landing_signal)).mappings().one()
        analytics.record(connection, account_id=landing["account_id"],
                         event_type="signal_contacted", occurred_at=NOW,
                         signal_key=landing["signal_key"])
        connection.execute(sa.insert(signal_feedback).values(
            account_id=landing["account_id"], signal_key=landing["signal_key"],
            relevance="not_relevant", reason_code="wrong_need", contacted_at=NOW,
            created_at=NOW, updated_at=NOW,
        ))
        ordinary = accounts.sign_up(
            connection, email="ordinary@example.invalid", password="synthetic-password-long",
            company_name="Ordinary", locale="fr", now=NOW, session_ttl=dt.timedelta(days=1),
        )
        analytics.record(connection, account_id=ordinary.account_id,
                         event_type="signal_contacted", occurred_at=NOW, signal_key="ordinary")
        connection.execute(sa.insert(signal_feedback).values(
            account_id=ordinary.account_id, signal_key="ordinary", relevance="relevant",
            contacted_at=NOW, created_at=NOW, updated_at=NOW,
        ))
    with engine.connect() as connection:
        assert analytics.north_star(connection, as_of=NOW + dt.timedelta(seconds=1)) == 1
        event = connection.execute(sa.select(product_event.c.properties).where(
            product_event.c.account_id == landing["account_id"],
            product_event.c.event_type == "signal_contacted",
        )).scalar_one()
        assert event["qa"] is True
    quality = FounderReadService(engine)._quality(
        now=NOW + dt.timedelta(seconds=1),
        business=SimpleNamespace(data_quality=SimpleNamespace(
            unresolved_sector_count=0, unknown_mrr_journey_count=0,
        )),
    )
    assert quality.feedback_updated_in_window_count == 1
    assert quality.contacted_in_window_count == 1
    assert quality.not_relevant_feedback_updated_in_window_count == 0
    assert quality.negative_reason_counts == ()


def test_missing_execution_location_still_refuses_country_claim(prepared_qa):
    from signals.conversion.mint_token import mint_url
    from signals.persistence.schema import contract_award

    engine, client, _ = prepared_qa
    event, awards = boamp_award(BOAMP_PUBLICATION_ONLY)
    IngestionPipeline(engine).process(
        AcquiredPublication(event, awards), as_of=NOW.date(), persisted_at=NOW,
    )
    with engine.connect() as connection:
        opportunity = connection.scalar(sa.select(opportunity_representation.c.opportunity_key)
            .join(contract_award,
                  opportunity_representation.c.award_key == contract_award.c.award_key)
            .where(contract_award.c.place_country.is_(None)))
    assert opportunity is not None
    with pytest.raises(ValueError, match="requested country"):
        mint_url(
            engine=engine, keyring=keyring(), origin="https://kivou.test",
            opportunity=opportunity, wedge="construction", country="FR",
            sector="bardage", need="materials_or_components", ttl="7d", now=NOW,
        )
    response = client.get(f"/a/{issue(opportunity)}", follow_redirects=False)
    assert response.headers["location"] == "/signup?attribution=expired"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(account)) == 0
