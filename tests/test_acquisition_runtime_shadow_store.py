import datetime as dt

import pytest
import sqlalchemy as sa

from signals.acquisition_runtime.shadow_store import (
    latest_shadow_mails,
    mask_email,
    write_shadow_mail,
)
from signals.persistence.schema import acquisition_runtime_cycle, acquisition_shadow_mail


@pytest.fixture
def engine():
    return sa.create_engine("sqlite:///:memory:")


def test_shadow_mail_is_masked_and_one_per_procedure_day(engine):
    acquisition_runtime_cycle.create(engine)
    acquisition_shadow_mail.create(engine)
    now = dt.datetime(2026, 9, 9, 10, tzinfo=dt.UTC)
    with engine.begin() as connection:
        connection.execute(acquisition_runtime_cycle.insert().values(
            cycle_ref="cycle-1", opportunity_key="opportunity-1",
            config_fingerprint="a" * 64, status="SUCCEEDED",
            spent_cost=0, started_at=now, updated_at=now, completed_at=now,
        ))
    kwargs = {
        "cycle_ref": "cycle-1", "opportunity_key": "opportunity-1",
        "procedure_award_key": "award-1", "supplier_ref": None, "contact_ref": None,
        "company_name": "Entreprise", "contact_role": "Dirigeant", "email": "alice@example.com",
        "signal_snapshot": {"object": "Toiture"}, "subject": "Toiture", "body": "Texte",
        "apollo_query": {"keywords": ["couverture"]}, "created_at": now,
    }
    assert write_shadow_mail(engine, **kwargs)
    assert write_shadow_mail(engine, **kwargs) is None
    assert mask_email("alice@example.com") == "a***@example.com"
    rows = latest_shadow_mails(engine)
    assert len(rows) == 1
    assert rows[0].masked_email == "a***@example.com"
