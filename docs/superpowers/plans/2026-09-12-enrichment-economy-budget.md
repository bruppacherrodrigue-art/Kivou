# Economic Company Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect every configured OpenRouter usage with a persistent Europe/Zurich daily budget, reduce company-enrichment prompts below 4,000 input tokens, preserve every per-company judgment call, and benchmark the three approved economic models before any production enrichment pass.

**Architecture:** A small `model_runtime` package owns usage names, environment routes, reservations, reconciliation, and append-only call history. Existing provider adapters call this gateway but retain their domain response schemas. Company research builds a bounded evidence packet, calls the economic judge, and invokes Sonnet only for invalid JSON or confidence below 0.8; operational read models expose the persisted counters.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, Pydantic, httpx, Playwright, PostgreSQL/SQLite tests, FastAPI founder API, React/TypeScript/Vitest.

---

## File map

- `src/signals/model_runtime/config.py`: closed usage list; batch-scoped model and cap loading from environment.
- `src/signals/model_runtime/budget.py`: atomic reserve/reconcile/fail operations and graceful exhaustion exception.
- `src/signals/model_runtime/openrouter.py`: one metered OpenRouter JSON call gateway.
- `src/signals/persistence/migrations/versions/0058_model_call_budget.py`: persistent daily counters and call journal.
- `src/signals/persistence/schema.py`: SQLAlchemy declarations for those tables.
- `src/signals/company_research/evidence.py`: reduced HTML/directory extraction and page limits.
- `src/signals/company_research/providers.py`: judge/arbiter prompt and routes.
- `src/signals/company_research/enrichment.py`: one optional second fetch and historical judgment linkage.
- `src/signals/company_research/replay.py`: one environment snapshot per lot and graceful budget stop.
- `src/signals/company_research/benchmark.py`: fixed 30-company comparison, masked DeepSeek directors, ratio and projection report.
- `src/signals/documents/openrouter.py`, `src/signals/documents/providers.py`, `src/signals/supervisor/hermes_bridge.py`, `src/signals/contact_discovery/providers.py`: route existing calls through named usage metering.
- `src/signals/founder_api/read_models.py`, `frontend/founder/src/types.ts`, `frontend/founder/src/FounderApp.tsx`: System budget visibility and directory batch cost.
- `docs/reports/2026-09-12-enrichment-economique/`: benchmark, token, staging and production evidence generated only after code gates pass.

### Task 1: Persist daily budgets and immutable call history

**Files:**
- Create: `src/signals/persistence/migrations/versions/0058_model_call_budget.py`
- Modify: `src/signals/persistence/schema.py`
- Create: `tests/test_model_call_budget_migration.py`
- Modify: `tests/test_persistence_schema.py`

- [ ] **Step 1: Write migration tests that require the two tables, constraints, indexes, and supplier link**

```python
def test_model_budget_migration_creates_persistent_ledger(tmp_path):
    engine = migrated_engine(tmp_path)
    inspector = sa.inspect(engine)
    assert {"model_daily_budget", "model_call_journal"} <= set(inspector.get_table_names())
    journal = {column["name"] for column in inspector.get_columns("model_call_journal")}
    assert {"usage", "model", "siren", "batch_id", "reserved_usd", "actual_usd",
            "input_tokens", "output_tokens", "status", "called_at"} <= journal
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `uv run pytest tests/test_model_call_budget_migration.py tests/test_persistence_schema.py -q`

Expected: failure because revision `0058_model_call_budget` and table declarations do not exist.

- [ ] **Step 3: Add revision 0058 and matching schema declarations**

```python
model_daily_budget = sa.Table(
    "model_daily_budget", metadata,
    sa.Column("usage_date", sa.Date, primary_key=True),
    sa.Column("usage", sa.String(64), primary_key=True),
    sa.Column("reserved_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
    sa.Column("actual_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
model_call_journal = sa.Table(
    "model_call_journal", metadata,
    sa.Column("call_id", sa.String(36), primary_key=True),
    sa.Column("usage", sa.String(64), nullable=False, index=True),
    sa.Column("model", sa.String(160), nullable=False),
    sa.Column("siren", sa.String(9), nullable=True, index=True),
    sa.Column("batch_id", sa.String(64), nullable=True, index=True),
    sa.Column("reserved_usd", sa.Numeric(14, 8), nullable=False),
    sa.Column("actual_usd", sa.Numeric(14, 8), nullable=True),
    sa.Column("input_tokens", sa.Integer, nullable=True),
    sa.Column("output_tokens", sa.Integer, nullable=True),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
)
```

Add checks for non-negative money/tokens and statuses `reserved`, `succeeded`, `failed`, `rejected_budget`; add a nullable FK from journal `siren` to `supplier_directory.siren` with `ON DELETE SET NULL` so history survives suppression/deletion.

- [ ] **Step 4: Run migration/schema tests GREEN**

Run: `uv run pytest tests/test_model_call_budget_migration.py tests/test_persistence_schema.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/persistence tests/test_model_call_budget_migration.py tests/test_persistence_schema.py
git commit -m "feat(models): persist daily budgets and call history"
```

### Task 2: Load batch-scoped routes and caps

**Files:**
- Create: `src/signals/model_runtime/__init__.py`
- Create: `src/signals/model_runtime/config.py`
- Create: `tests/test_model_runtime_config.py`

- [ ] **Step 1: Write failing tests for defaults, overrides, invalid values, and batch snapshots**

```python
def test_route_snapshot_reads_caps_once_per_batch(monkeypatch):
    monkeypatch.setenv("KIVOU_MODEL_BUDGET_ENRICHMENT_JUDGE_USD", "7.50")
    snapshot = routes_from_environment(batch_id="bench-1")
    monkeypatch.setenv("KIVOU_MODEL_BUDGET_ENRICHMENT_JUDGE_USD", "9")
    assert snapshot.route("enrichment_judge").daily_budget_usd == Decimal("7.50")
    assert routes_from_environment(batch_id="bench-2").route(
        "enrichment_judge"
    ).daily_budget_usd == Decimal("9")
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_model_runtime_config.py -q`

Expected: import failure for `signals.model_runtime.config`.

- [ ] **Step 3: Implement the closed five-use configuration**

```python
MODEL_USAGES = (
    "enrichment_judge", "enrichment_arbiter", "for_you", "hermes",
    "document_classifier",
)
DEFAULT_BUDGETS = {
    "enrichment_judge": Decimal("2"), "enrichment_arbiter": Decimal("1"),
    "for_you": Decimal("1"), "hermes": Decimal("1"),
    "document_classifier": Decimal("1"),
}
MODEL_ENV = {
    usage: f"KIVOU_MODEL_{usage.upper()}" for usage in MODEL_USAGES
}
BUDGET_ENV = {
    usage: f"KIVOU_MODEL_BUDGET_{usage.upper()}_USD" for usage in MODEL_USAGES
}
```

Use approved defaults: Mistral Small for judge until benchmark selection, Sonnet 4.6 for arbiter, and preserve each existing production model as the other usage default. Reject negative, non-finite, and malformed caps at batch startup.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_model_runtime_config.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/model_runtime tests/test_model_runtime_config.py
git commit -m "feat(models): configure routes and batch safety caps"
```

### Task 3: Reserve conservatively and reconcile actual cost

**Files:**
- Create: `src/signals/model_runtime/budget.py`
- Create: `tests/test_model_budget.py`

- [ ] **Step 1: Write concurrency-shaped failing tests**

```python
def test_reservation_stops_before_network_when_cap_would_be_exceeded(store):
    store.reserve(route=route(cap="2"), estimated_usd=Decimal("1.60"), call_id="a")
    with pytest.raises(DailyModelBudgetExhausted) as error:
        store.reserve(route=route(cap="2"), estimated_usd=Decimal("0.41"), call_id="b")
    assert error.value.code == "DAILY_MODEL_BUDGET_EXHAUSTED"

def test_success_replaces_reservation_with_actual_cost(store):
    store.reserve(route=route(cap="2"), estimated_usd=Decimal("0.10"), call_id="a")
    store.succeed(call_id="a", actual_usd=Decimal("0.0004"), input_tokens=900,
                  output_tokens=80)
    assert store.summary("enrichment_judge").actual_usd == Decimal("0.0004")
    assert store.summary("enrichment_judge").reserved_usd == Decimal("0")
```

Also test Europe/Zurich midnight boundaries, failure release, duplicate finalization, and two connections competing for the remaining cap.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_model_budget.py -q`

Expected: missing store and exception.

- [ ] **Step 3: Implement atomic reserve/finalize operations**

```python
class DailyModelBudgetExhausted(RuntimeError):
    code = "DAILY_MODEL_BUDGET_EXHAUSTED"

def reserve(self, *, route, estimated_usd, call_id, siren=None, batch_id=None):
    day = self._clock().astimezone(ZoneInfo("Europe/Zurich")).date()
    with self._engine.begin() as connection:
        row = self._lock_or_create_counter(connection, day, route.usage)
        if row.actual_usd + row.reserved_usd + estimated_usd > route.daily_budget_usd:
            self._insert_rejection(connection, call_id, route, estimated_usd, siren, batch_id)
            raise DailyModelBudgetExhausted(route.usage, route.daily_budget_usd)
        self._reserve(connection, row, estimated_usd)
        self._insert_reservation(connection, call_id, route, estimated_usd, siren, batch_id)
```

PostgreSQL uses `SELECT ... FOR UPDATE`; SQLite tests use a transaction plus a uniqueness retry. `succeed` and `fail` require status `reserved`, release the reservation, and store the terminal result exactly once.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_model_budget.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/model_runtime/budget.py tests/test_model_budget.py
git commit -m "feat(models): enforce persistent daily safety budgets"
```

### Task 4: Meter one OpenRouter gateway call

**Files:**
- Create: `src/signals/model_runtime/openrouter.py`
- Create: `tests/test_model_openrouter_gateway.py`

- [ ] **Step 1: Write failing gateway tests**

```python
def test_gateway_reserves_before_http_and_journals_usage(fake_client, store):
    gateway = OpenRouterGateway(client=fake_client, api_key="key", budgets=store)
    result = gateway.json_call(route=route(), messages=[{"role": "user", "content": "x"}],
                               schema=Schema, siren="123456789", batch_id="bench")
    assert result.input_tokens == 812
    assert store.calls()[0].actual_usd == Decimal("0.00037")
    assert fake_client.events == ["post"]
```

Test budget rejection makes zero HTTP calls, malformed provider output is journalled failed, and response bodies remain bounded.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_model_openrouter_gateway.py -q`

Expected: missing gateway.

- [ ] **Step 3: Implement the gateway and conservative estimate**

```python
estimated_input = max(1, math.ceil(len(serialized_messages.encode("utf-8")) / 3))
reserved_usd = route.reserve_cost(estimated_input, max_tokens)
reservation = budgets.reserve(route=route, estimated_usd=reserved_usd,
                              call_id=str(uuid.uuid4()), siren=siren, batch_id=batch_id)
```

Post the existing strict `response_format`, request provider usage, parse `prompt_tokens`, `completion_tokens`, and `cost`, then reconcile. Keep reservation rates in route configuration and allow the benchmark report to recommend tighter rates when aggregate reserved/actual exceeds 3.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_model_openrouter_gateway.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/model_runtime/openrouter.py tests/test_model_openrouter_gateway.py
git commit -m "feat(models): meter OpenRouter calls by usage"
```

### Task 5: Build reduced evidence under the approved hard limits

**Files:**
- Create: `src/signals/company_research/evidence.py`
- Modify: `src/signals/company_research/enrichment.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/test_company_research_evidence.py`

- [ ] **Step 1: Write failing extraction and page-count tests**

```python
def test_directory_result_exposes_only_three_regex_fields():
    item = reduce_directory_html(URL, HTML_WITH_INSTRUCTIONS_AND_CONTACTS)
    assert item.model_dump() == {
        "website": "https://artisan.fr", "phone": "+33492000000",
        "director": "Adil El Mansouri",
    }

def test_candidate_site_packet_has_at_most_three_pages_and_800_chars_each():
    evidence = collector.collect(identity)
    assert len(evidence.candidate_pages) <= 2
    assert all(len(page.main_text) <= 800 for page in evidence.candidate_pages)
```

Also test navigation/footer/script removal, body fallback, explicit regex emails/phones, ten Serper results containing only title/URL/snippet, directory blacklist, and no raw directory text in serialized evidence.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_company_research_evidence.py -q`

Expected: old 3,000-character fields, rendered directory text, and up to 30 candidate pages violate assertions.

- [ ] **Step 3: Implement rendered reduction and bounded collection**

```python
class ReducedPage(Contract):
    url: str
    title: str = ""
    main_text: str = Field(default="", max_length=800)
    published_emails: tuple[str, ...] = ()
    published_phones: tuple[str, ...] = ()

class DirectoryClues(Contract):
    website: str | None = None
    phone: str | None = None
    director: str | None = None
```

Use Playwright to obtain rendered HTML, retain `<main>` or body after removing `nav`, `footer`, `script`, `style`, `noscript`, and `svg`, normalize whitespace, and truncate to 800 characters. The default packet renders only candidate home and contact; the optional requested URL is the third and final page.

- [ ] **Step 4: Run GREEN and dependency validation**

Run: `uv run pytest tests/test_company_research_evidence.py tests/test_company_enrichment.py -q && uv lock --check`

Expected: all tests pass and lock file is current.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/signals/company_research tests/test_company_research_evidence.py tests/test_company_enrichment.py
git commit -m "feat(enrichment): bound rendered evidence packets"
```

### Task 6: Route judge and Sonnet arbiter, with one optional page request

**Files:**
- Modify: `src/signals/company_research/providers.py`
- Modify: `src/signals/company_research/enrichment.py`
- Modify: `src/signals/company_research/replay.py`
- Modify: `src/signals/acquisition_runtime/execution.py`
- Create: `tests/test_company_enrichment_routing.py`
- Modify: `tests/test_company_enrichment.py`

- [ ] **Step 1: Write failing routing tests**

```python
def test_high_confidence_valid_judge_does_not_call_arbiter(service):
    service.enrich("123456789")
    assert service.judge.calls == 1
    assert service.arbiter.calls == 0

@pytest.mark.parametrize("condition", ["invalid_json", "low_site", "low_email"])
def test_uncertain_judge_calls_sonnet_once(service, condition):
    service.judge.condition = condition
    service.enrich("123456789")
    assert service.arbiter.calls == 1
```

Test that a requested same-site, non-directory URL can be fetched once, that total rendered pages never exceeds three, and that budget exhaustion stops the lot cleanly without marking the company judged.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_company_enrichment_routing.py tests/test_company_enrichment.py -q`

Expected: no separate routes or arbiter behavior.

- [ ] **Step 3: Implement usage-aware provider composition**

```python
judge = OpenRouterCompanyEnrichmentProvider(
    gateway=gateway, route=batch.route("enrichment_judge"), max_tokens=300,
)
arbiter = OpenRouterCompanyEnrichmentProvider(
    gateway=gateway, route=batch.route("enrichment_arbiter"), max_tokens=300,
)
needs_arbiter = invalid_json or decision.website_confidence < Decimal("0.8") \
    or (decision.website is not None and decision.email_confidence < Decimal("0.8"))
```

The prompt sends only family keys plus French names (never descriptions, NAF arrays, or examples). Catch `DailyModelBudgetExhausted` in replay, log its stable code and counters, stop iteration, and return a non-error stopped summary. Load the route snapshot once at replay/acquisition lot composition.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_company_enrichment_routing.py tests/test_company_enrichment.py tests/test_acquisition_runtime_execution.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/company_research src/signals/acquisition_runtime tests/test_company_enrichment.py tests/test_company_enrichment_routing.py
git commit -m "feat(enrichment): route economic judge and Sonnet arbiter"
```

### Task 7: Meter the remaining four named usages

**Files:**
- Modify: `src/signals/documents/openrouter.py`
- Modify: `src/signals/documents/providers.py`
- Modify: `src/signals/supervisor/hermes_bridge.py`
- Modify: `src/signals/contact_discovery/providers.py`
- Modify: relevant composition modules under `src/signals/`
- Modify: `tests/test_document_openrouter.py`
- Modify: `tests/test_acquisition_connectivity_hermes.py`
- Create: `tests/test_model_usage_routing.py`

- [ ] **Step 1: Write failing per-use journal tests**

```python
@pytest.mark.parametrize("adapter,usage", [
    ("for_you", "for_you"), ("hermes", "hermes"),
    ("classifier", "document_classifier"), ("contact", "enrichment_judge"),
])
def test_adapter_uses_expected_route(adapter, usage, composed_runtime):
    composed_runtime.call(adapter)
    assert composed_runtime.journal.one().usage == usage
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_model_usage_routing.py tests/test_document_openrouter.py tests/test_acquisition_connectivity_hermes.py -q`

Expected: adapters call httpx directly and do not create journal rows.

- [ ] **Step 3: Replace direct OpenRouter calls with gateway calls**

```python
gateway.json_call(route=batch.route("document_classifier"), messages=messages,
                  schema=RequirementClassification, batch_id=batch.batch_id)
gateway.text_call(route=batch.route("for_you"), messages=messages,
                  max_tokens=existing_limit, batch_id=batch.batch_id)
gateway.text_call(route=batch.route("hermes"), messages=messages,
                  max_tokens=existing_limit, batch_id=batch.batch_id)
```

Map contact-discovery model extraction to `enrichment_judge`, because it is company enrichment and the public usage list remains exactly five values. Preserve all existing prompts, response schemas, and limits outside the route/model/cost wrapper.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_model_usage_routing.py tests/test_document_openrouter.py tests/test_acquisition_connectivity_hermes.py -q`

Expected: all tests pass and every successful/failing call has one journal entry.

- [ ] **Step 5: Commit**

```bash
git add src/signals/documents src/signals/supervisor src/signals/contact_discovery src/signals/*/composition.py tests
git commit -m "feat(models): route all configured OpenRouter usages"
```

### Task 8: Keep current supplier snapshot plus full judgment history

**Files:**
- Modify: `src/signals/company_research/enrichment.py`
- Modify: `src/signals/supplier_directory/store.py`
- Modify: `tests/test_company_enrichment.py`
- Create: `tests/test_supplier_enrichment_history.py`

- [ ] **Step 1: Write failing no-overwrite-history test**

```python
def test_forced_second_judgment_keeps_both_calls_and_latest_snapshot(service, journal):
    service.enrich("123456789")
    service.enrich("123456789", force=True)
    assert [call.siren for call in journal.calls()] == ["123456789", "123456789"]
    assert service.directory.get("123456789").enrichment_model_id == journal.calls()[-1].model
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_supplier_enrichment_history.py -q`

Expected: existing directory snapshot changes but no durable call linkage exists.

- [ ] **Step 3: Thread call IDs through provider result and snapshot update**

```python
class CompanyEnrichmentProviderResult(EnrichmentContract):
    call_id: str
    decision: CompanyEnrichmentDecision
    model: str
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
```

Add `enrichment_call_id` to `supplier_directory` in revision 0058 and point it at the successful journal row. The snapshot remains convenient current state; journal rows are never deleted or replaced.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_supplier_enrichment_history.py tests/test_company_enrichment.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/company_research src/signals/supplier_directory src/signals/persistence tests/test_supplier_enrichment_history.py tests/test_company_enrichment.py
git commit -m "feat(enrichment): retain every company judgment call"
```

### Task 9: Show daily usage in System and batch cost in Directory

**Files:**
- Modify: `src/signals/founder_api/read_models.py`
- Modify: `tests/founder_api/test_read_models.py`
- Modify: `src/signals/founder_api/prospection.py`
- Modify: `tests/founder_api/test_prospection.py`
- Modify: `frontend/founder/src/types.ts`
- Modify: `frontend/founder/src/FounderApp.tsx`
- Modify: `frontend/founder/src/FounderApp.test.tsx`

- [ ] **Step 1: Write failing backend and frontend visibility tests**

```python
def test_system_summary_exposes_today_model_budgets(read_service):
    row = read_service.summary().system.model_budgets[0]
    assert row.usage == "enrichment_judge"
    assert row.timezone == "Europe/Zurich"
    assert row.cap_usd == Decimal("2")
```

```tsx
expect(screen.getByText("enrichment_judge")).toBeInTheDocument()
expect(screen.getByText("0,42 $US / 2,00 $US")).toBeInTheDocument()
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/founder_api/test_read_models.py tests/founder_api/test_prospection.py -q && npm --prefix frontend/founder test -- --run FounderApp.test.tsx`

Expected: missing API fields and UI labels.

- [ ] **Step 3: Add typed summaries and compact UI tables**

```python
class FounderModelBudget(FounderContract):
    usage: str
    usage_date: dt.date
    timezone: str = "Europe/Zurich"
    actual_usd: Decimal
    reserved_usd: Decimal
    cap_usd: Decimal
    remaining_usd: Decimal
```

Read current caps from a fresh environment snapshot when serving System, combine them with persisted counters, and expose the most recent enrichment `batch_id`, calls, tokens, and cost in the directory summary. Render actual, active reservations, cap, and remaining values.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/founder_api/test_read_models.py tests/founder_api/test_prospection.py -q && npm --prefix frontend/founder test -- --run FounderApp.test.tsx`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/founder_api tests/founder_api frontend/founder/src
git commit -m "feat(founder): display model budgets and enrichment cost"
```

### Task 10: Add the fixed benchmark and active-account queue maintenance tools

**Files:**
- Create: `src/signals/company_research/benchmark.py`
- Create: `tests/fixtures/company_enrichment_benchmark.json`
- Create: `tests/test_company_enrichment_benchmark.py`
- Modify: `src/signals/company_research/replay.py`
- Create: `tests/test_active_winner_enrichment_queue.py`

- [ ] **Step 1: Write failing scoring, masking, projection, and purge tests**

```python
def test_first_eligible_model_wins_with_mistral_priority(results):
    assert choose_model(results, threshold=Decimal("0.95")) == "mistralai/mistral-small"

def test_deepseek_evidence_masks_director_names(case):
    masked = benchmark_input(case, model="deepseek/deepseek-chat")
    assert "Adil El Mansouri" not in masked
    assert "DIR_1" in masked

def test_reservation_ratio_over_three_recommends_recalibration(report):
    report.add_call(reserved="0.003", actual="0.0004")
    assert report.reservation_ratio == Decimal("7.5")
    assert report.requires_reservation_adjustment is True
```

Test field-level site/email/family/name agreement, invalid JSON count, median latency, actual 30-case cost, 20,000-case projection, and deletion only of pending winner jobs whose owner account is not active.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_company_enrichment_benchmark.py tests/test_active_winner_enrichment_queue.py -q`

Expected: benchmark and scoped queue operation do not exist.

- [ ] **Step 3: Implement deterministic benchmark/reporting and dry-run queue projection**

```python
FIELDS = ("website", "email", "family", "director_display_name")
overall = sum(matches[field] for field in FIELDS) / (len(cases) * len(FIELDS))
reservation_ratio = total_reserved / total_actual if total_actual else None
projected_cost_20k = total_actual / completed_calls * Decimal("20000")
```

The CLI defaults to dry-run. `--execute-benchmark` requires all routes/caps and a migrated ledger. Queue cleanup has a separate explicit `--apply-active-account-purge`; it reports counts before mutation and is not invoked during this implementation phase. Store the fixed 30 SIRENs and expected outputs, with the seven supplied manual overrides taking precedence over cached Sonnet truth.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_company_enrichment_benchmark.py tests/test_active_winner_enrichment_queue.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/signals/company_research tests/fixtures/company_enrichment_benchmark.json tests/test_company_enrichment_benchmark.py tests/test_active_winner_enrichment_queue.py
git commit -m "feat(enrichment): add model benchmark and scoped queue tools"
```

### Task 11: Verify, deploy through main, capture, benchmark, and stop before enrichment

**Files:**
- Create: `docs/reports/2026-09-12-enrichment-economique/README.md`
- Create: `docs/reports/2026-09-12-enrichment-economique/*.png`
- Modify: deployment environment documentation/configuration only where repository-managed.

- [ ] **Step 1: Run the complete local quality gates**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src && npm --prefix frontend/founder test -- --run && npm --prefix frontend/founder run typecheck && npm --prefix frontend/founder run lint`

Expected: all commands exit 0.

- [ ] **Step 2: Stage from the feature branch and capture mandatory UI evidence**

Deploy only to staging using the repository deployment procedure. Capture System daily budget rows and Prospection → Annuaire batch-cost area with visible staging identity. Store PNGs in the report directory and record executable SHA, URLs, timestamps, and checks.

- [ ] **Step 3: Merge through reviewed CI, then deploy production from `main` only**

Verify the production deployment SHA equals `origin/main`; apply revision 0058 before enabling any OpenRouter caller. Set the five default cap variables and model variables, restart services so the next lot reads them, then capture production System with Europe/Zurich counters. Do not invoke replay or queue purge.

- [ ] **Step 4: Run only the approved 30-case benchmark under the installed caps**

Run the benchmark command with a unique batch ID. Report, per model, agreement for site/email/family/name, invalid JSON, median latency, actual cost for 30, 20,000 projection, mean input tokens for the last 20 benchmark cases, historical before mean for the matched 20, and aggregate reserved/actual ratio. If ratio exceeds 3, adjust reservation pricing/configuration, rerun its unit tests and the ratio measurement before selecting a model.

- [ ] **Step 5: Select the first model at or above 95%, or retain reduced-input Sonnet**

Apply order Mistral Small, Gemini Flash-Lite, DeepSeek V3; Mistral wins ties. Configure `KIVOU_MODEL_ENRICHMENT_JUDGE` for the selected model at the next service/batch start. Sonnet remains `enrichment_arbiter` below 0.8 or for invalid JSON.

- [ ] **Step 6: Produce the cost projection and stop for Rodrigue’s go**

Calculate separately the 281 unjudged suppliers and holders belonging to active accounts only. Report proposed raised cap, projected judge/arbiter calls, reservation and actual cost ranges, and dry-run inactive queue purge count. Do not run either enrichment pass and do not apply the purge until Rodrigue explicitly approves the projection.

- [ ] **Step 7: Commit evidence and report**

```bash
git add docs/reports/2026-09-12-enrichment-economique
git commit -m "docs(enrichment): report budgeted economic benchmark"
```

## Self-review

- Spec coverage: Tasks 1–4 implement persistent, dynamically batch-scoped caps and per-call accounting; Tasks 5–6 implement reduced evidence and arbitration; Task 7 covers all five declared usages; Task 8 preserves snapshots plus history; Task 9 exposes the ledger; Tasks 10–11 benchmark, project, constrain the active-account queue, and stop before the 281 pass.
- Placeholder scan: no deferred implementation markers or unspecified error-handling steps remain.
- Type consistency: usage names, environment names, `batch_id`, journal fields, `DailyModelBudgetExhausted.code`, and benchmark field names are identical across tasks.
- Safety boundary: no task authorizes the 281-company pass, active-holder pass, mail send, or production deployment from a non-`main` revision.
