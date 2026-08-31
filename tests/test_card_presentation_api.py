from __future__ import annotations

import ast
import datetime as dt
import pathlib
from collections.abc import Iterator, Mapping

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    Clock,
    account_of,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    signed_up,
)
from fastapi.testclient import TestClient

from signals.api import routes_signals
from signals.card_intelligence import fallback as fallback_renderer
from signals.card_intelligence import service as card_service
from signals.card_intelligence.contracts import PublishedCardPresentation
from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import publish_factual_fallback
from signals.card_intelligence.store import (
    published_for_signals as load_published_for_signals,
)
from signals.persistence.schema import card_presentation_artifact


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path):
    return make_engine(tmp_path)


@pytest.fixture
def app(engine, clock: Clock):
    return make_app(engine, clock)


@pytest.fixture
def alice(app) -> TestClient:
    return signed_up(app)


def _seed_paid(engine, client: TestClient, *, count: int) -> list[str]:
    target_icp_id = icp_of(client)
    pay(engine, client, plan="scale")
    return seed(engine, target_icp_id, count=count)


def _publish(
    engine,
    client: TestClient,
    signal_key: str,
    *,
    language: str = "fr",
    at: dt.datetime = NOW,
) -> PublishedCardPresentation:
    """Offline ARRANGE only: publish the deterministic server fallback."""

    account_id = account_of(client)
    with engine.begin() as connection:
        source = build_presentation_input(
            connection,
            account_id=account_id,
            signal_key=signal_key,
            language=language,
        )
        publish_factual_fallback(connection, source=source, now=at)
        current = load_published_for_signals(
            connection,
            account_id=account_id,
            bindings={
                signal_key: (source.signal_revision, source.target_icp_revision),
            },
            language=language,
        ).get(signal_key)
    assert current is not None
    return current


def _feed(client: TestClient, **params) -> dict:
    response = client.get("/signals", params={"freshness": "all", **params})
    assert response.status_code == 200, response.text
    return response.json()


def _detail(client: TestClient, signal_key: str, *, artifact_id: str | None = None) -> dict:
    params = {} if artifact_id is None else {"presentation_artifact_id": artifact_id}
    response = client.get(f"/signals/{signal_key}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _all_mapping_keys(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _all_mapping_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_mapping_keys(child)


def _explode(*_args, **_kwargs):
    raise AssertionError("offline Card Intelligence surface called during GET")


def test_feed_exposes_the_published_contract_and_null_when_no_artifact(
    alice: TestClient,
    engine,
) -> None:
    published_key, absent_key = _seed_paid(engine, alice, count=2)
    published = _publish(engine, alice, published_key)

    items = {item["signal_id"]: item for item in _feed(alice, limit=50)["items"]}

    assert items[published_key]["presentation"] == published.model_dump(mode="json")
    assert items[absent_key]["presentation"] is None
    assert items[published_key]["locked"] is False


def test_unlocked_detail_reads_the_current_published_contract(
    alice: TestClient,
    engine,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    published = _publish(engine, alice, signal_key)

    detail = _detail(alice, signal_key)

    assert detail["presentation"] == published.model_dump(mode="json")
    assert detail["locked"] is False


def test_pinned_detail_keeps_the_exact_feed_artifact_after_a_new_publication(
    alice: TestClient,
    engine,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    first = _publish(engine, alice, signal_key)
    feed_first = next(
        item for item in _feed(alice)["items"] if item["signal_id"] == signal_key
    )["presentation"]

    second = _publish(engine, alice, signal_key, at=NOW + dt.timedelta(minutes=1))
    pinned = _detail(alice, signal_key, artifact_id=first.artifact_id)["presentation"]
    current = _detail(alice, signal_key)["presentation"]

    assert feed_first == first.model_dump(mode="json")
    assert pinned == feed_first
    assert pinned["artifact_id"] == first.artifact_id
    assert pinned["version"] == 1
    assert current == second.model_dump(mode="json")
    assert current["artifact_id"] != pinned["artifact_id"]
    assert current["version"] == 2


def test_unknown_pin_returns_null_without_falling_back_to_current(
    alice: TestClient,
    engine,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    current = _publish(engine, alice, signal_key)

    detail = _detail(alice, signal_key, artifact_id="f" * 64)

    assert detail["presentation"] is None
    assert current.artifact_id != "f" * 64


def test_locked_feed_item_is_excluded_from_bindings_and_has_no_presentation_key(
    alice: TestClient,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_icp_id = icp_of(alice)
    signal_keys = seed(engine, target_icp_id, count=4)
    initial = _feed(alice, limit=50)["items"]
    locked_key = next(item["signal_id"] for item in initial if item["locked"])
    unlocked_keys = {
        item["signal_id"] for item in initial if item["locked"] is False
    }
    _publish(engine, alice, locked_key)
    calls: list[dict[str, tuple[int, int]]] = []

    def recorded_reader(connection, *, account_id, bindings, language):
        calls.append(dict(bindings))
        return load_published_for_signals(
            connection,
            account_id=account_id,
            bindings=bindings,
            language=language,
        )

    monkeypatch.setattr(
        routes_signals,
        "published_for_signals",
        recorded_reader,
        raising=False,
    )

    items = {item["signal_id"]: item for item in _feed(alice, limit=50)["items"]}

    assert set(items) == set(signal_keys)
    assert len(calls) == 1
    assert set(calls[0]) == unlocked_keys
    assert locked_key not in calls[0]
    assert "presentation" not in items[locked_key]
    assert all("presentation" in items[key] for key in unlocked_keys)


def test_locked_only_page_calls_one_empty_batch_without_artifact_sql(
    alice: TestClient,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_icp_id = icp_of(alice)
    seed(engine, target_icp_id, count=4)
    initial = _feed(alice, limit=50)["items"]
    locked_key = next(item["signal_id"] for item in initial if item["locked"])
    locked_offset = next(
        index for index, item in enumerate(initial) if item["signal_id"] == locked_key
    )
    calls: list[dict[str, tuple[int, int]]] = []
    artifact_selects: list[str] = []

    def recorded_reader(connection, *, account_id, bindings, language):
        calls.append(dict(bindings))
        return load_published_for_signals(
            connection,
            account_id=account_id,
            bindings=bindings,
            language=language,
        )

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = statement.lower().lstrip()
        if normalized.startswith("select") and "card_presentation_artifact" in normalized:
            artifact_selects.append(statement)

    monkeypatch.setattr(
        routes_signals,
        "published_for_signals",
        recorded_reader,
        raising=False,
    )
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        body = _feed(alice, limit=1, offset=locked_offset)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)

    assert len(body["items"]) == 1
    assert body["items"][0]["signal_id"] == locked_key
    assert body["items"][0]["locked"] is True
    assert "presentation" not in body["items"][0]
    assert calls == [{}]
    assert artifact_selects == []


def test_locked_detail_never_calls_a_reader_even_with_an_existing_pinned_artifact(
    alice: TestClient,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_icp_id = icp_of(alice)
    seed(engine, target_icp_id, count=4)
    locked = next(item for item in _feed(alice, limit=50)["items"] if item["locked"])
    published = _publish(engine, alice, locked["signal_id"])
    monkeypatch.setattr(
        routes_signals,
        "published_for_signals",
        _explode,
        raising=False,
    )
    monkeypatch.setattr(
        routes_signals,
        "published_artifact_for_signal",
        _explode,
        raising=False,
    )

    detail = _detail(alice, locked["signal_id"], artifact_id=published.artifact_id)

    assert detail["locked"] is True
    assert "presentation" not in detail


def test_foreign_and_missing_detail_never_call_a_presentation_reader(
    app,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice = signed_up(app, "alice-card-api@example.com")
    bob = signed_up(app, "bob-card-api@example.com")
    signal_key = _seed_paid(engine, alice, count=1)[0]
    _publish(engine, alice, signal_key)
    monkeypatch.setattr(
        routes_signals,
        "published_for_signals",
        _explode,
        raising=False,
    )
    monkeypatch.setattr(
        routes_signals,
        "published_artifact_for_signal",
        _explode,
        raising=False,
    )

    foreign = bob.get(
        f"/signals/{signal_key}",
        params={"presentation_artifact_id": "a" * 64},
    )
    missing = bob.get(
        f"/signals/{'0' * 64}",
        params={"presentation_artifact_id": "a" * 64},
    )

    assert foreign.status_code == 404
    assert missing.status_code == 404


@pytest.mark.parametrize("invalid_pin", ("a" * 63, "A" * 64, "g" * 64, "not-a-digest"))
def test_invalid_pin_is_rejected_before_any_reader(
    alice: TestClient,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    invalid_pin: str,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    monkeypatch.setattr(
        routes_signals,
        "published_for_signals",
        _explode,
        raising=False,
    )
    monkeypatch.setattr(
        routes_signals,
        "published_artifact_for_signal",
        _explode,
        raising=False,
    )

    response = alice.get(
        f"/signals/{signal_key}",
        params={"presentation_artifact_id": invalid_pin},
    )

    assert response.status_code == 422


def test_multi_item_feed_uses_one_batch_reader_and_one_artifact_select(
    alice: TestClient,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_keys = _seed_paid(engine, alice, count=4)
    # Two fixture notices have a complete, unambiguous factual fallback.  The
    # other two deliberately stay without an artifact; batching must cover both
    # states without turning fixture ambiguity into made-up copy.
    for index, signal_key in enumerate(signal_keys[:2]):
        _publish(engine, alice, signal_key, at=NOW + dt.timedelta(seconds=index))
    calls: list[dict[str, tuple[int, int]]] = []
    artifact_selects: list[str] = []

    def recorded_reader(connection, *, account_id, bindings, language):
        calls.append(dict(bindings))
        return load_published_for_signals(
            connection,
            account_id=account_id,
            bindings=bindings,
            language=language,
        )

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = statement.lower().lstrip()
        if normalized.startswith("select") and "card_presentation_artifact" in normalized:
            artifact_selects.append(statement)

    monkeypatch.setattr(
        routes_signals,
        "published_for_signals",
        recorded_reader,
        raising=False,
    )
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        items = _feed(alice, limit=50)["items"]
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)

    assert {item["signal_id"] for item in items} == set(signal_keys)
    by_key = {item["signal_id"]: item for item in items}
    assert all(by_key[key]["presentation"] is not None for key in signal_keys[:2])
    assert all(by_key[key]["presentation"] is None for key in signal_keys[2:])
    assert len(calls) == 1
    assert set(calls[0]) == set(signal_keys)
    assert len(artifact_selects) == 1


def test_account_language_selects_only_the_matching_artifact_stream(
    alice: TestClient,
    engine,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    french = _publish(engine, alice, signal_key, language="fr")
    assert _detail(alice, signal_key)["presentation"] == french.model_dump(mode="json")

    switched = alice.patch("/me", json={"locale": "en"})
    assert switched.status_code == 200, switched.text
    assert _detail(alice, signal_key)["presentation"] is None

    english = _publish(
        engine,
        alice,
        signal_key,
        language="en",
        at=NOW + dt.timedelta(minutes=1),
    )
    assert _detail(alice, signal_key)["presentation"] == english.model_dump(mode="json")
    assert english.content.headline != french.content.headline

    switched_back = alice.patch("/me", json={"locale": "fr"})
    assert switched_back.status_code == 200, switched_back.text
    assert _detail(alice, signal_key)["presentation"] == french.model_dump(mode="json")


def test_corrupt_persisted_json_is_returned_as_null_and_never_repaired(
    alice: TestClient,
    engine,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    published = _publish(engine, alice, signal_key)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE card_presentation_artifact SET payload = ? WHERE artifact_id = ?",
            ("{malformed", published.artifact_id),
        )

    feed_item = next(
        item for item in _feed(alice)["items"] if item["signal_id"] == signal_key
    )
    detail = _detail(alice, signal_key)

    assert feed_item["presentation"] is None
    assert detail["presentation"] is None
    with engine.connect() as connection:
        persisted = connection.scalar(
            sa.select(sa.cast(card_presentation_artifact.c.payload, sa.Text)).where(
                card_presentation_artifact.c.artifact_id == published.artifact_id
            )
        )
    assert persisted == "{malformed"


def test_gets_never_call_generation_qa_or_fallback_publication_surfaces(
    alice: TestClient,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    published = _publish(engine, alice, signal_key)
    monkeypatch.setattr(card_service, "publish_factual_fallback", _explode)
    monkeypatch.setattr(card_service, "run_offline_candidate_pipeline", _explode)
    monkeypatch.setattr(fallback_renderer, "factual_fallback", _explode)

    feed_item = next(
        item for item in _feed(alice)["items"] if item["signal_id"] == signal_key
    )
    detail = _detail(alice, signal_key)

    assert feed_item["presentation"] == published.model_dump(mode="json")
    assert detail["presentation"] == feed_item["presentation"]


_ALLOWED_CARD_INTELLIGENCE_IMPORTS = {
    "signals.card_intelligence.contracts.PublishedCardPresentation",
    "signals.card_intelligence.store.published_artifact_for_signal",
    "signals.card_intelligence.store.published_for_signals",
}


def _assert_static_card_intelligence_imports_are_read_only(
    source: str,
    *,
    require_complete_boundary: bool = False,
) -> None:
    """Check static imports only; dynamic import calls are outside this invariant."""

    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports are outside the allowed static boundary"
            module = node.module or ""
            imported.update(f"{module}.{alias.name}" for alias in node.names)

    card_intelligence_boundary_imports = {
        name
        for name in imported
        if name == "signals"
        or name == "signals.card_intelligence"
        or name.startswith("signals.card_intelligence.")
    }
    if require_complete_boundary:
        assert card_intelligence_boundary_imports == _ALLOWED_CARD_INTELLIGENCE_IMPORTS
    else:
        assert card_intelligence_boundary_imports <= _ALLOWED_CARD_INTELLIGENCE_IMPORTS
    forbidden_tokens = ("fallback", "protocol", "provider", "hermes", "worker", ".qa")
    assert all(
        not any(token in name.casefold() for token in forbidden_tokens)
        for name in imported
    )


def test_signal_get_routes_import_only_card_intelligence_read_contracts() -> None:
    route_path = pathlib.Path(routes_signals.__file__)
    _assert_static_card_intelligence_imports_are_read_only(
        route_path.read_text(encoding="utf-8"),
        require_complete_boundary=True,
    )


@pytest.mark.parametrize(
    "source",
    (
        "from signals import card_intelligence",
        "import signals.card_intelligence as ci",
        "import signals as root",
        "from ..card_intelligence import service",
    ),
)
def test_static_import_guard_rejects_parent_bare_and_relative_signal_imports(
    source: str,
) -> None:
    with pytest.raises(AssertionError):
        _assert_static_card_intelligence_imports_are_read_only(source)


def test_static_import_guard_accepts_only_the_three_read_imports() -> None:
    source = """
from signals.card_intelligence.contracts import PublishedCardPresentation
from signals.card_intelligence.store import (
    published_artifact_for_signal,
    published_for_signals,
)
"""
    _assert_static_card_intelligence_imports_are_read_only(
        source,
        require_complete_boundary=True,
    )


def test_public_response_contains_only_the_published_contract_not_private_qa_metadata(
    alice: TestClient,
    engine,
) -> None:
    signal_key = _seed_paid(engine, alice, count=1)[0]
    _publish(engine, alice, signal_key)

    presentation = _detail(alice, signal_key)["presentation"]

    assert set(presentation) == {
        "artifact_id",
        "version",
        "status",
        "schema_version",
        "published_at",
        "content",
    }
    assert {
        "qa_status",
        "qa_reasons",
        "qa_policy_version",
        "generator_version",
        "prompt_version",
        "model_id",
        "provider",
        "qa_model_id",
        "qa_provider",
    }.isdisjoint(_all_mapping_keys(presentation))
