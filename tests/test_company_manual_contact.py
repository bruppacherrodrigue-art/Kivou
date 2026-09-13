import pytest
from pydantic import ValidationError
from test_company_entity_aliases import NOW, A
from test_company_entity_aliases import db as db  # noqa: PLC0414 — pytest fixture re-export

from signals.client_value.user_contacts import (
    ContactConflict,
    ManualContactWrite,
    delete_contact,
    get_contact,
    put_contact,
)


def test_contact_is_private_revisioned_and_deletion_cannot_resurrect_it(db):
    with db.begin() as connection:
        payload = ManualContactWrite(
            name="  Alice  ", role="Achats", email="alice@example.com", expected_revision=0
        )
        first = put_contact(
            connection, account_id="account_a", company_key=A, payload=payload, now=NOW
        )
        assert first["contact"]["name"] == "Alice"
        assert first["contact"]["source"] == "user"
        assert first["revision"] == 1
        assert get_contact(connection, account_id="account_b", company_key=A)["contact"] is None
        with pytest.raises(ContactConflict):
            put_contact(connection, account_id="account_a", company_key=A, payload=payload, now=NOW)
        deleted = delete_contact(
            connection, account_id="account_a", company_key=A, expected_revision=1, now=NOW
        )
        assert deleted["contact"] is None and deleted["revision"] == 2
        with pytest.raises(ContactConflict):
            put_contact(connection, account_id="account_a", company_key=A, payload=payload, now=NOW)


@pytest.mark.parametrize(
    "values",
    [
        {"name": "Alice"},
        {"name": "", "phone": "0493123456"},
        {"name": "Alice", "email": "invalid"},
        {"name": "Alice", "phone": "04 93"},
        {"name": "x" * 121, "phone": "0493123456"},
        {"name": "Alice", "email": "alice@example.com", "account_id": "account_b"},
        {"name": "Alice", "email": "alice@example.com", "expected_revision": True},
    ],
)
def test_invalid_manual_contacts_are_rejected(values):
    with pytest.raises(ValidationError):
        ManualContactWrite.model_validate({"expected_revision": 0, **values})
