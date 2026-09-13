"""One validated consultation scope across today's feed and private prospection."""

from decimal import Decimal

import pytest
import sqlalchemy as sa
from engagement_helpers import Clock, icp_of, make_app, make_engine, pay, seed, signed_up

from signals.client_value.prospecting import follow_company
from signals.engagement import company
from signals.persistence.schema import contract_award, materialized_signal, supplier_directory


@pytest.fixture
def prepared(tmp_path):
    engine = make_engine(tmp_path)
    app = make_app(engine, Clock())
    client = signed_up(app)
    pay(engine, client, plan="pro")
    first = icp_of(client, "Première")
    second = icp_of(client, "Seconde")
    first_keys = seed(engine, first, count=2)
    second_keys = seed(engine, second, count=2, offset=2)
    return client, app, engine, first, second, first_keys, second_keys


@pytest.mark.parametrize("path", ["/dashboard", "/signals", "/companies"])
def test_foreign_target_is_not_found_on_all_surfaces(prepared, path):
    client, app, _, *_ = prepared
    foreign = icp_of(signed_up(app, "foreign-scope@example.com"))
    response = client.get(path, params={"target_icp_id": foreign})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "target_icp_not_found"


def test_three_surfaces_return_same_selected_profile_scope_without_mutating_it(prepared):
    client, _, _, first, _, first_keys, _ = prepared
    before = client.get("/target-icps")
    params = {"target_icp_id": first, "min_amount": "1000.01", "amount_currency": "CHF"}
    results = [client.get(path, params=params) for path in ("/dashboard", "/signals", "/companies")]
    assert all(result.status_code == 200 for result in results), [result.text for result in results]
    scopes = [result.json()["scope"] for result in results]
    assert scopes[0] == scopes[1] == scopes[2]
    assert scopes[0]["target_icp_id"] == first
    assert scopes[0]["min_amount"] == "1000.01"
    assert scopes[0]["amount_currency"] == "CHF"
    assert {item["signal_id"] for item in results[1].json()["items"]} <= set(first_keys)
    assert client.get("/target-icps").json() == before.json()


@pytest.mark.parametrize("path", ["/dashboard", "/signals", "/companies"])
def test_scope_rejects_authority_and_offers_not_in_profile(prepared, path):
    client, _, _, first, *_ = prepared
    assert client.get(path, params={"account_id": "acc_foreign"}).status_code == 422
    response = client.get(
        path, params={"target_icp_id": first, "offer_category": "workforce_capacity"}
    )
    assert response.status_code == 422


def test_history_cursor_cannot_be_reused_for_another_profile(prepared):
    client, _, _, first, second, *_ = prepared
    first_page = client.get(
        "/signals", params={"view": "history", "target_icp_id": first, "limit": 1}
    )
    assert first_page.status_code == 200
    cursor = first_page.json()["page"]["next_cursor"]
    assert cursor
    reused = client.get(
        "/signals", params={"view": "history", "target_icp_id": second, "cursor": cursor}
    )
    assert reused.status_code == 422


def test_currency_and_customer_offer_filter_before_counts_and_pagination(prepared):
    client, _, engine, first, _, keys, _ = prepared
    with engine.begin() as connection:
        for key, currency, amount, needs in (
            (keys[0], "CHF", "1000000", ["materials_or_components"]),
            (keys[1], "EUR", "2000000", ["workforce_capacity"]),
        ):
            reference = connection.scalar(
                sa.select(materialized_signal.c.materialization_award_key).where(
                    materialized_signal.c.signal_key == key
                )
            )
            connection.execute(
                sa.update(contract_award)
                .where(contract_award.c.award_key == reference)
                .values(amount=Decimal(amount), currency=currency)
            )
            connection.execute(
                sa.update(materialized_signal)
                .where(materialized_signal.c.signal_key == key)
                .values(icp_matched_needs=needs)
            )
    response = client.get(
        "/signals",
        params={
            "target_icp_id": first,
            "amount_currency": "CHF",
            "min_amount": "1000",
            "offer_category": "materials_and_components",
            "limit": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert [item["signal_id"] for item in response.json()["items"]] == [keys[0]]
    assert sum(response.json()["counts"].values()) == 1
    assert response.json()["page"]["has_more"] is False


@pytest.mark.parametrize("view", ["recent", "history"])
def test_amount_sort_is_stable_across_three_pages_without_mixing_currencies(prepared, view):
    client, _, engine, first, _, keys, _ = prepared
    keys += seed(engine, first, count=2, offset=4)
    assignments = [("EUR", "100"), ("CHF", "2"), ("CHF", "3"), (None, None)]
    with engine.begin() as connection:
        for key, (currency, amount) in zip(keys, assignments, strict=True):
            reference = connection.scalar(
                sa.select(materialized_signal.c.materialization_award_key).where(
                    materialized_signal.c.signal_key == key
                )
            )
            connection.execute(
                sa.update(contract_award)
                .where(contract_award.c.award_key == reference)
                .values(amount=Decimal(amount) if amount else None, currency=currency)
            )
    seen = []
    cursor = None
    for index in range(4):
        params = {"view": view, "target_icp_id": first, "sort": "amount", "limit": 1}
        if view == "history" and cursor:
            params["cursor"] = cursor
        elif view == "recent":
            params["offset"] = index
        response = client.get("/signals", params=params)
        assert response.status_code == 200, response.text
        payload = response.json()
        seen += [item["signal_id"] for item in payload["items"]]
        assert payload["counts_available"] is (view == "recent" or index == 0)
        cursor = payload["page"].get("next_cursor")
    assert seen == [keys[2], keys[1], keys[0], keys[3]]


def test_followed_company_survives_missing_profiles_and_counts_are_global(prepared):
    _, app, engine, *_ = prepared
    client = signed_up(app, "manual-prospect@example.com")
    account = client.get("/me").json()["account_id"]
    now = Clock().now
    with engine.begin() as connection:
        for siren, name, state in (
            ("552100554", "Alpha", "contacted"),
            ("356000000", "Beta", "replied"),
        ):
            key = f"cmp_directory_{siren}"
            connection.execute(
                sa.insert(supplier_directory).values(
                    siren=siren,
                    legal_name=name,
                    legal_name_observed_at=now,
                    family_keys=[],
                    families_observed_at=now,
                    directors=[],
                    created_at=now,
                    updated_at=now,
                )
            )
            follow_company(connection, account_id=account, company_key=key, now=now)
            company.set_contact(
                connection, account_id=account, company_key=key, status=state, now=now
            )
    response = client.get("/companies", params={"contact_status": "contacted", "limit": 1})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["name"] for item in payload["items"]] == ["Alpha"]
    assert payload["items"][0]["tracked"] is True
    assert payload["counts"] == {"to_contact": 0, "contacted": 1, "replied": 1}
    assert payload["total"] == 2


def test_week_saved_reads_reversible_workflow_not_historical_relevance(prepared):
    client, _, _, first, _, keys, _ = prepared
    saved = client.put(
        f"/signals/{keys[0]}/status", json={"status": "saved", "expected_revision": 0}
    )
    assert saved.status_code == 200
    assert client.get("/dashboard", params={"target_icp_id": first}).json()["week"]["saved"] == 1
    client.put(
        f"/signals/{keys[0]}/status",
        json={"status": "new", "expected_revision": saved.json()["revision"]},
    )
    assert client.get("/dashboard", params={"target_icp_id": first}).json()["week"]["saved"] == 0


def test_week_replied_ignores_preserved_historical_alias_copies(prepared):
    from signals.client_value.company_identity import register_alias, resolve_subject
    from signals.dashboard.service import _week_activity_counts

    client, _, engine, *_ = prepared
    account = client.get("/me").json()["account_id"]
    now = Clock().now
    with engine.begin() as connection:
        alias = "cmp_historical_alias"
        register_alias(connection, company_key=alias, siren="552100554", now=now)
        company.set_contact(
            connection, account_id=account, company_key=alias, status="replied", now=now
        )
        subject = resolve_subject(connection, account_id=account, company_key=alias, now=now)
        assert subject.private_subject_key != alias
        assert _week_activity_counts(connection, account_id=account, now=now)["replied"] == 1
        company.set_contact(
            connection,
            account_id=account,
            company_key=subject.private_subject_key,
            status="to_contact",
            now=now,
        )
        assert _week_activity_counts(connection, account_id=account, now=now)["replied"] == 0


@pytest.mark.parametrize("path", ["/dashboard", "/signals", "/companies"])
def test_consultation_filters_are_plan_gated_even_with_no_results(prepared, path):
    _, app, *_ = prepared
    client = signed_up(app, "discovery-scope@example.com")
    first = icp_of(client)
    response = client.get(
        path, params={"target_icp_id": first, "offer_category": "materials_and_components"}
    )
    assert response.status_code == 403, response.text


def test_text_query_matches_beyond_an_unfiltered_third_page(prepared):
    client, _, engine, first, _, keys, _ = prepared
    keys += seed(engine, first, count=3, offset=4)
    ordered = client.get("/signals", params={"target_icp_id": first, "limit": 50}).json()["items"]
    target = ordered[-1]["signal_id"]
    with engine.begin() as connection:
        reference = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == target
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == reference)
            .values(title="Needle consultation unique")
        )
    response = client.get(
        "/signals", params={"target_icp_id": first, "limit": 1, "q": "Needle consultation"}
    )
    assert response.status_code == 200, response.text
    assert [item["signal_id"] for item in response.json()["items"]] == [target]
    assert sum(response.json()["counts"].values()) == 1


def test_known_signal_link_keeps_access_when_return_view_filters_differ(prepared):
    client, _, _, _, second, keys, _ = prepared
    response = client.get(
        f"/signals/{keys[0]}",
        params={"target_icp_id": second, "min_amount": "999999999999", "amount_currency": "CHF"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["signal_id"] == keys[0]
    assert response.json()["outside_consultation_scope"] is True
    assert response.json()["scope"]["target_icp_id"] == second
