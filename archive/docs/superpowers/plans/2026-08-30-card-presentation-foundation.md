# Card Intelligence × QA Signals Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline, tenant-scoped, versioned Card Intelligence publication boundary, expose factual presentations to unlocked signal GETs without provider calls or N+1 reads, and version the complete staging rollout procedure.

**Architecture:** A strict `PresentationInput` is rendered or generated outside GETs, checked by deterministic validators, decided by QA Signals, and persisted as an immutable attempt. Only `PASS/FULL` or `FALLBACK/FACTUAL_FALLBACK` rows cross the read boundary. Feed reads are batched; detail reads can pin the immutable artifact selected by the feed.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core 2, Alembic, FastAPI, pytest, PostgreSQL/SQLite migration tests, Bash runbooks.

---

## Audited base and branch

- The initial audited `origin/main` was
  `a1ffc5021f1d981059f4e9017d295683a389605b`. Immediately before product code,
  it was revalidated first at `9b73cc370ef6657e0a53a9fb53fde1d226500fc9`
  again at `c568cede29cfcca2b729ce487c0d68f166197c6b`, and finally at
  `5e0e7e29df8db75089e51bce845343c1f88c565e`. The #115/#116 delta adds and
  connects an isolated Founder Console. The later #128 delta adds isolated
  production runtime contracts and typed ingestion failure diagnostics; it
  does not modify Card Intelligence, Signals/company persistence, or the
  migration chain. CI run `33331502374` executed non-empty backend and frontend
  jobs successfully, including tests, visual regression, builds, typecheck and
  lint. The clean implementation branch starts at `5e0e7e2`, whose migration
  head remains `0027_signal_notes`.
- Immediately before implementation, fetch `origin/main`. If it advanced,
  inspect the complete delta and create a new clean foundation branch from the
  new SHA; port the reviewed documentation and implementation commits normally.
  Do not rebase or force-push a published branch.
- The implementation branch is
  `feat/119-card-presentation-foundation-v5`. It replaces draft #123 without
  cherry-picking its commits.
- `CONTRIBUTING.md` prohibits history rewriting and force-push. Every push in
  this plan is a normal fast-forward push.

## File map

**Create:**

- `src/signals/card_intelligence/__init__.py` — public package boundary.
- `src/signals/card_intelligence/__main__.py` — CLI entry point.
- `src/signals/card_intelligence/contracts.py` — closed inputs, claims, payloads and public envelope.
- `src/signals/card_intelligence/protocol.py` — generator protocol only; no live registry.
- `src/signals/card_intelligence/input.py` — account-owned source-fact assembly.
- `src/signals/card_intelligence/fallback.py` — deterministic factual renderer.
- `src/signals/card_intelligence/validation.py` — semantic and evidence gates.
- `src/signals/card_intelligence/store.py` — immutable attempts, publication and batch/pinned reads.
- `src/signals/card_intelligence/service.py` — offline orchestration.
- `src/signals/card_intelligence/backfill.py` — bounded factual backfill.
- `src/signals/card_intelligence/cli.py` — explicit one-page CLI.
- `src/signals/qa_signals/__init__.py` — QA package boundary.
- `src/signals/qa_signals/contracts.py` — decision-only QA contract.
- `src/signals/qa_signals/protocol.py` — QA protocol with no rewrite surface.
- `src/signals/persistence/migrations/versions/0028_card_presentation.py` — one additive table.
- `tests/test_card_intelligence_contracts.py`
- `tests/test_card_intelligence_validation.py`
- `tests/test_card_intelligence_service.py`
- `tests/test_card_presentation_migration.py`
- `tests/test_card_presentation_store.py`
- `tests/test_card_presentation_api.py`
- `tests/test_card_intelligence_backfill.py`
- `tests/test_card_presentation_runbook.py`
- `docs/runbooks/11-staging-card-presentation-rollout.md`

**Modify:**

- `tests/test_billing_paywall.py` — remove the random opaque-ID false positive while strengthening the teaser surface assertion.
- `src/signals/persistence/schema.py` — declare the new table only.
- `src/signals/api/routes_signals.py` — one batch read for feed and optional pinned detail read.
- `src/signals/feed/view.py` — attach a supplied presentation; never generate one.
- the 21 migration tests returned by `rg -l '0027_signal_notes' tests` — advance only their expected current head.
- `ops/README.md` — link the new versioned rollout runbook.

## Task 1: Stabilize the existing locked-teaser confidentiality test

**Files:**

- Modify: `tests/test_billing_paywall.py:1-20,265-285`

- [ ] **Step 1: Replace the substring-over-opaque-ID assertion**

```python
import json


def test_a_locked_teaser_never_names_the_company(alice, engine):
    item = locked_item(alice, engine)
    assert set(item) == {
        "signal_id",
        "target_icp_id",
        "locked",
        "unlock_required",
        "event",
        "context",
        "headline",
    }
    assert item["locked"] is True
    visible = json.dumps(
        {key: value for key, value in item.items() if key not in {"signal_id", "target_icp_id"}},
        ensure_ascii=False,
    )
    for forbidden in ("company", "winner", "Egli", "GmbH", "SA "):
        assert forbidden not in visible, forbidden
```

- [ ] **Step 2: Run the focused privacy tests**

Run: `uv run pytest -q tests/test_billing_paywall.py -k 'locked_teaser'`

Expected: all selected tests pass even when an opaque ID happens to contain `AG`.

- [ ] **Step 3: Commit the baseline repair**

```bash
git add tests/test_billing_paywall.py
git commit -m "test(signals): remove opaque-id teaser flake"
```

## Task 2: Define strict Card Intelligence and QA contracts

**Files:**

- Create: `src/signals/card_intelligence/contracts.py`
- Create: `src/signals/card_intelligence/protocol.py`
- Create: `src/signals/qa_signals/contracts.py`
- Create: `src/signals/qa_signals/protocol.py`
- Create: `tests/test_card_intelligence_contracts.py`

- [ ] **Step 1: Write contract tests that fail closed**

```python
import pytest
from pydantic import ValidationError

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationVariant,
)
from signals.qa_signals.contracts import QaDecision, QaStatus


def test_every_claim_requires_evidence_including_recommendations():
    for kind in ClaimKind:
        with pytest.raises(ValidationError, match="evidence_refs"):
            PresentationClaim(claim_id="CLAIM", kind=kind, text="Texte", evidence_refs=())


def test_every_public_prose_field_is_bound_to_an_evidenced_claim():
    payload = valid_full_payload().model_copy(update={"timing": "Appeler demain"})
    with pytest.raises(ValidationError, match="timing.*claim"):
        CardPresentationPayload.model_validate(payload.model_dump())


def test_fallback_rejects_every_commercial_conclusion():
    with pytest.raises(ValidationError, match="FACTUAL_FALLBACK"):
        CardPresentationPayload(
            variant=PresentationVariant.FACTUAL_FALLBACK,
            headline="Attribution publiée",
            award_summary="Entreprise attributaire publiée.",
            commercial_importance="Urgent",
            claims=(
                PresentationClaim(
                    claim_id="FACT_AWARDEE",
                    kind=ClaimKind.FACT,
                    text="Entreprise attributaire publiée.",
                    evidence_refs=("source:awardee",),
                ),
            ),
        )


def test_qa_decision_has_no_content_rewrite_field():
    decision = QaDecision(status=QaStatus.PASS, reasons=("grounded",))
    assert set(decision.model_dump()) == {"status", "reasons"}
    with pytest.raises(ValidationError):
        QaDecision(status=QaStatus.PASS, reasons=("grounded",), payload={"headline": "rewrite"})
```

- [ ] **Step 2: Run the contract tests and confirm RED**

Run: `uv run pytest -q tests/test_card_intelligence_contracts.py`

Expected: collection fails because the new packages do not exist.

- [ ] **Step 3: Implement the closed contracts**

Use this public shape and preserve these validators exactly:

```python
class PresentationClaim(Contract):
    claim_id: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
    kind: ClaimKind
    text: Annotated[str, StringConstraints(min_length=1, max_length=420)]
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)
    confidence: Literal["high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def inference_requires_confidence(self):
        if self.kind is ClaimKind.INFERENCE and self.confidence is None:
            raise ValueError("INFERENCE claim requires confidence")
        if self.kind is not ClaimKind.INFERENCE and self.confidence is not None:
            raise ValueError("only INFERENCE claims carry confidence")
        return self


class TargetRole(Contract):
    role: BoundedCommercialText
    rationale: BoundedCommercialText
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)


class PresentationUnknown(Contract):
    text: BoundedUnknown
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)


class CardPresentationPayload(Contract):
    schema_version: Literal["card-presentation-v1"] = "card-presentation-v1"
    variant: PresentationVariant
    headline: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    award_summary: Annotated[str, StringConstraints(min_length=1, max_length=420)]
    commercial_importance: BoundedCommercialText | None = None
    fit_reason: BoundedCommercialText | None = None
    timing: BoundedActionText | None = None
    recommended_action: BoundedActionText | None = None
    target_roles: tuple[TargetRole, ...] = Field(default=(), max_length=6)
    fit_need_categories: tuple[StableRef, ...] = Field(default=(), max_length=8)
    unknowns: tuple[PresentationUnknown, ...] = Field(default=(), max_length=8)
    claims: tuple[PresentationClaim, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def closed_variant_and_unique_claims(self):
        commercial = (
            self.commercial_importance,
            self.fit_reason,
            self.timing,
            self.recommended_action,
        )
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim_id values must be unique")
        if self.variant is PresentationVariant.FULL:
            if any(value is None for value in commercial):
                raise ValueError("FULL requires every commercial field")
            if not self.target_roles or not self.fit_need_categories:
                raise ValueError("FULL requires roles and matched needs")
        elif any(value is not None for value in commercial) or self.target_roles or self.fit_need_categories:
            raise ValueError("FACTUAL_FALLBACK cannot carry commercial conclusions")
        elif any(claim.kind is not ClaimKind.FACT for claim in self.claims):
            raise ValueError("FACTUAL_FALLBACK contains FACT claims only")
        claim_texts = {claim.text for claim in self.claims}
        named_prose = {
            "headline": self.headline,
            "award_summary": self.award_summary,
            "commercial_importance": self.commercial_importance,
            "fit_reason": self.fit_reason,
            "timing": self.timing,
            "recommended_action": self.recommended_action,
        }
        for field, text in named_prose.items():
            if text is not None and text not in claim_texts:
                raise ValueError(f"{field} requires an exact evidenced claim")
        return self


class PublishedCardPresentation(Contract):
    artifact_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    version: Annotated[int, Field(gt=0)]
    status: Literal["PASS", "FALLBACK"]
    schema_version: Literal["card-presentation-v1"]
    published_at: dt.datetime
    content: CardPresentationPayload

    @model_validator(mode="after")
    def exact_public_pair(self):
        expected = {
            "PASS": PresentationVariant.FULL,
            "FALLBACK": PresentationVariant.FACTUAL_FALLBACK,
        }[self.status]
        if self.content.variant is not expected:
            raise ValueError("invalid published status/variant pair")
        if self.schema_version != self.content.schema_version:
            raise ValueError("envelope/content schema mismatch")
        if self.published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")
        return self
```

Define `SourceFacts`, `PresentationInput`, `GenerationResponse`,
`PublishedCardPresentation`, `QaStatus`, `QaDecision`, `CardGenerator` and
`QaSignals` in the same task. `SourceFacts` carries a closed evidence catalog;
every claim, target role and unknown reference must resolve into that catalog.
`QaDecision` must not accept a payload.

- [ ] **Step 4: Run contracts and static checks**

Run: `uv run pytest -q tests/test_card_intelligence_contracts.py && uv run ruff check src/signals/card_intelligence src/signals/qa_signals tests/test_card_intelligence_contracts.py`

Expected: PASS.

- [ ] **Step 5: Commit contracts**

```bash
git add src/signals/card_intelligence src/signals/qa_signals tests/test_card_intelligence_contracts.py
git commit -m "feat(signals): define card presentation contracts"
```

## Task 3: Build tenant-owned inputs and deterministic factual fallbacks

**Files:**

- Create: `src/signals/card_intelligence/input.py`
- Create: `src/signals/card_intelligence/fallback.py`
- Create: `tests/test_card_intelligence_validation.py`

- [ ] **Step 1: Add failing fallback and source-binding cases**

The test table must include FR and EN, missing buyer, long actors, bounded
evidence and a raw administrative title that may not appear in the result:

```python
def test_fallback_never_reuses_the_administrative_title(source):
    source = source.model_copy(
        update={
            "facts": source.facts.model_copy(
                update={"award_title": "FOURNITURE LOT 7 ACCORD-CADRE ADMINISTRATIF"}
            )
        }
    )
    payload = factual_fallback(source)
    rendered = payload.model_dump_json()
    assert payload.variant is PresentationVariant.FACTUAL_FALLBACK
    assert "FOURNITURE LOT 7" not in rendered
    assert all(claim.kind is ClaimKind.FACT for claim in payload.claims)
    assert all(claim.evidence_refs for claim in payload.claims)


def test_english_fallback_discloses_missing_buyer_without_commercial_claims(source):
    source = source.model_copy(
        update={
            "language": "en",
            "facts": source.facts.model_copy(update={"buyer_name": None}),
        }
    )
    payload = factual_fallback(source)
    assert "buyer is not published" in payload.award_summary.lower()
    assert payload.commercial_importance is None
    assert payload.target_roles == ()
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest -q tests/test_card_intelligence_validation.py -k 'fallback'`

Expected: import failure for `factual_fallback`.

- [ ] **Step 3: Implement exact actor, date and evidence assembly**

`build_presentation_input()` must load the active ICP by account and exact
revision, then copy only structured facts. The fallback renderer must use
bounded actor labels and typed dates:

```python
def factual_fallback(source: PresentationInput) -> CardPresentationPayload:
    winner = actor_label(source.facts.winner_name)
    buyer = actor_label(source.facts.buyer_name) if source.facts.buyer_name else None
    actor_sentence = (
        f"{buyer} est identifié comme acheteur et {winner} comme entreprise attributaire."
        if buyer and source.language == "fr"
        else f"{buyer} is identified as the buyer and {winner} as the awarded company."
        if buyer
        else f"Entreprise attributaire : {winner}. Acheteur non publié."
        if source.language == "fr"
        else f"Awarded company: {winner}. The buyer is not published."
    )
    evidence = tuple(dict.fromkeys(source.facts.evidence_refs))[:16]
    headline = (
        f"Attribution publiée pour {winner}"
        if source.language == "fr"
        else f"Published award for {winner}"
    )
    return CardPresentationPayload(
        variant=PresentationVariant.FACTUAL_FALLBACK,
        headline=headline,
        award_summary=bounded(actor_sentence, 420),
        unknowns=missing_fact_labels(source),
        claims=(
            PresentationClaim(
                claim_id="FACT_HEADLINE",
                kind=ClaimKind.FACT,
                text=headline,
                evidence_refs=evidence,
            ),
            PresentationClaim(
                claim_id="FACT_AWARD_CONTEXT",
                kind=ClaimKind.FACT,
                text=bounded(actor_sentence, 420),
                evidence_refs=evidence,
            ),
        ),
    )
```

Do not use `award_title` in the fallback renderer.

- [ ] **Step 4: Run fallback/input tests**

Run: `uv run pytest -q tests/test_card_intelligence_validation.py -k 'fallback or input'`

Expected: PASS.

- [ ] **Step 5: Commit input and fallback**

```bash
git add src/signals/card_intelligence/input.py src/signals/card_intelligence/fallback.py tests/test_card_intelligence_validation.py
git commit -m "feat(signals): render grounded factual fallbacks"
```

## Task 4: Implement deterministic semantic validation

**Files:**

- Create: `src/signals/card_intelligence/validation.py`
- Modify: `tests/test_card_intelligence_validation.py`

- [ ] **Step 1: Add the complete adversarial matrix**

Use parameterized rows so each bypass has a stable test ID:

```python
@pytest.mark.parametrize(
    ("claim", "expected_error"),
    (
        ("La société Acheteur SA a attribué le marché à Ville de Sion le 12 août 2026.", "actor_role_inversion"),
        ("Marché attribué le 15 août 2026.", "award_date_unbound"),
        ("Marché attribué le 15 août 26.", "award_date_unbound"),
        ("Awarded on August 15, 2026.", "award_date_unbound"),
        ("Attribution du 15/08/2026 confirmée.", "award_date_unbound"),
        ("Besoin urgent de personnel pour livrer les matériaux.", "materials_staffing_mismatch"),
    ),
)
def test_adversarial_claims_fail_closed(source_without_award_date, full_payload, claim, expected_error):
    payload = full_payload.model_copy(
        update={
            "award_summary": claim,
            "claims": (
                full_payload.claims[0].model_copy(update={"text": claim}),
            ),
        }
    )
    result = validate_payload(payload, source_without_award_date)
    assert expected_error in result.errors
```

Add explicit passing controls for amounts `250 000`, postcode `1200`, legal
name `Personnel Matériaux SA`, exact FR/EN dates bound to the correct source
field, and a materials claim that mentions materials but not staffing.

- [ ] **Step 2: Run validation tests and confirm RED**

Run: `uv run pytest -q tests/test_card_intelligence_validation.py -k 'adversarial or localized or collision'`

Expected: failures because `validate_payload` is absent or accepts the cases.

- [ ] **Step 3: Implement composable validators**

The public entry point must collect, not rewrite, errors:

```python
@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_payload(payload: CardPresentationPayload, source: PresentationInput) -> ValidationResult:
    text = "\n".join(
        value
        for value in (
            payload.headline,
            payload.award_summary,
            payload.commercial_importance,
            payload.fit_reason,
            payload.timing,
            payload.recommended_action,
            *(claim.text for claim in payload.claims),
        )
        if value
    )
    errors = {
        *_validate_evidence(payload, source),
        *_validate_actor_roles(text, source),
        *_validate_dates(text, source),
        *_validate_fit(payload, source),
        *_validate_certainty(text, source),
        *_validate_administrative_copy(text, source),
    }
    return ValidationResult(tuple(sorted(errors)))
```

Date parsing must normalize accents and recognize ISO, `dd/mm/yyyy`,
`dd-mm-yyyy`, two-digit years and FR/EN month names. It must ignore isolated
amounts, project numbers and postcodes unless an award/date lexeme binds them.
Actor comparison must use exact normalized labels and reject ambiguous
truncation collisions.

- [ ] **Step 4: Run every validation test**

Run: `uv run pytest -q tests/test_card_intelligence_validation.py`

Expected: PASS.

- [ ] **Step 5: Commit validators**

```bash
git add src/signals/card_intelligence/validation.py tests/test_card_intelligence_validation.py
git commit -m "feat(signals): validate card claims deterministically"
```

## Task 5: Add the additive 0028 schema and migration

**Files:**

- Modify: `src/signals/persistence/schema.py`
- Create: `src/signals/persistence/migrations/versions/0028_card_presentation.py`
- Create: `tests/test_card_presentation_migration.py`
- Modify: every test returned by `rg -l '0027_signal_notes' tests`

- [ ] **Step 1: Write migration shape and round-trip tests**

```python
PREVIOUS = "0027_signal_notes"
HEAD = "0028_card_presentation"


def test_card_presentation_migration_is_one_additive_table(tmp_path):
    engine = _engine(tmp_path, "card-presentation.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())
    command.upgrade(config, HEAD)
    assert set(sa.inspect(engine).get_table_names()) - before == {"card_presentation_artifact"}
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]


def test_fallback_metadata_cannot_claim_a_provider(tmp_path):
    engine = _engine(tmp_path, "constraints.db")
    command.upgrade(alembic_config(engine), HEAD)
    with engine.begin() as connection, pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.insert(card_presentation_artifact).values(
            **artifact_values(
                qa_status="FALLBACK",
                provider="hermes",
                model_id="forbidden",
                prompt_version="forbidden",
            )
        ))
```

- [ ] **Step 2: Run migration tests and confirm RED**

Run: `uv run pytest -q tests/test_card_presentation_migration.py`

Expected: missing revision/table.

- [ ] **Step 3: Declare the table and migration**

The migration must create only `card_presentation_artifact`. Declare these
columns in both `schema.py` and the migration: `artifact_id` (64-hex primary
key), `account_id`, `signal_key`, `signal_revision`, `target_icp_id`,
`target_icp_revision`, `artifact_kind`, `language`, `version`,
`input_fingerprint`, `payload`, `payload_variant`, `qa_status`, `qa_reasons`,
`generator_version`, `prompt_version`, `model_id`, `provider`, `qa_model_id`,
`qa_provider`, `created_at`, `published_at` and `superseded_at`. Provider,
model and prompt columns are nullable; `generator_version` is non-null. Add
foreign keys to `account.account_id`, `materialized_signal.signal_key` and
`target_icp.target_icp_id`, positive-version, language, enum, timestamp-order
and 64-hex checks in addition to:

```python
sa.CheckConstraint(
    "published_at IS NULL OR "
    "(qa_status = 'PASS' AND payload_variant = 'FULL') OR "
    "(qa_status = 'FALLBACK' AND payload_variant = 'FACTUAL_FALLBACK')",
    name="ck_card_presentation_publishable_pair",
),
sa.CheckConstraint(
    "qa_status <> 'FALLBACK' OR "
    "(provider IS NULL AND model_id IS NULL AND prompt_version IS NULL "
    "AND qa_provider IS NULL AND qa_model_id IS NULL)",
    name="ck_card_presentation_fallback_offline",
),
```

Store `payload_variant` as a separate nullable column so the database can
enforce the published pair without parsing JSON. The active partial unique
index key is `(account_id, signal_key, target_icp_id, artifact_kind, language)`.

- [ ] **Step 4: Advance expected migration heads mechanically**

Replace only expected-current-head literals from `0027_signal_notes` to
`0028_card_presentation`. Keep `PREVIOUS = "0027_signal_notes"` in the new
migration test and in tests specifically exercising migration 0027.

Run: `rg -n 'CURRENT_HEAD = "0027_signal_notes"|current_revision\(engine\) == "0027_signal_notes"' tests`

Expected: no stale current-head assertion; historical `PREVIOUS` references remain.

- [ ] **Step 5: Run the migration suite**

Run: `uv run pytest -q tests/test_*migration*.py tests/test_policy_persistence.py tests/test_billing_entitlements.py`

Expected: PASS with one Alembic head.

- [ ] **Step 6: Commit the migration**

```bash
git add src/signals/persistence/schema.py src/signals/persistence/migrations/versions/0028_card_presentation.py tests
git commit -m "feat(signals): persist versioned card presentations"
```

## Task 6: Implement immutable attempts and fail-closed publication

**Files:**

- Create: `src/signals/card_intelligence/store.py`
- Create: `tests/test_card_presentation_store.py`

- [ ] **Step 1: Write store tests for publication boundaries**

Cover valid replacement, invalid attempt preserving the old publication,
tenant/revision isolation, malformed JSON, inactive ICP, invalidated signal,
status/variant mismatch, monotonic versions, pinned superseded reads and two
active rows rejected by the database.

```python
def test_invalid_attempt_cannot_supersede_current(connection, source, fallback):
    first = append_attempt(
        connection,
        source=source,
        payload=fallback,
        qa_status=QaStatus.FALLBACK,
        metadata=factual_metadata(),
        publish=True,
    )
    with pytest.raises(PresentationPublicationConflict):
        append_attempt(
            connection,
            source=source,
            payload=fallback.model_copy(update={"variant": PresentationVariant.FULL}),
            qa_status=QaStatus.PASS,
            metadata=factual_metadata(),
            publish=True,
        )
    current = published_for_signals(
        connection,
        account_id=source.account_id,
        bindings={source.signal_key: (source.signal_revision, source.target_icp_revision)},
        language=source.language,
    )
    assert current[source.signal_key].artifact_id == first["artifact_id"]
```

- [ ] **Step 2: Confirm store tests are RED**

Run: `uv run pytest -q tests/test_card_presentation_store.py`

Expected: import failures.

- [ ] **Step 3: Implement transaction and read APIs**

Use these signatures consistently:

```python
def append_attempt(
    connection: Connection,
    *,
    source: PresentationInput,
    payload: CardPresentationPayload | None,
    qa_status: QaStatus,
    qa_reasons: Sequence[str],
    metadata: AttemptMetadata,
    created_at: dt.datetime,
    publish: bool,
) -> Mapping[str, object]: ...


def published_for_signals(
    connection: Connection,
    *,
    account_id: str,
    bindings: Mapping[str, tuple[int, int]],
    language: Literal["fr", "en"],
) -> dict[str, PublishedCardPresentation]: ...


def published_artifact_for_signal(
    connection: Connection,
    *,
    account_id: str,
    signal_key: str,
    binding: tuple[int, int],
    language: Literal["fr", "en"],
    artifact_id: str,
) -> PublishedCardPresentation | None: ...
```

Lock the current materialized signal with `with_for_update`, validate before
superseding, and catch integrity conflicts as `PresentationPublicationConflict`.
The pinned reader may return a superseded but previously published immutable
artifact only while tenant, signal and ICP revisions remain current.

Inside that row lock, compute `version = max(existing versions) + 1`. Derive
`artifact_id` as SHA-256 over canonical JSON containing the account/signal/ICP
bindings, language, version, input fingerprint, payload hash, QA decision and
non-secret generator metadata. For publication, mark the prior active row
superseded and insert the new published row in the same transaction; any insert
or validation failure rolls the prior-row update back. Never update an
artifact’s payload, decision, metadata or original publication timestamp.

- [ ] **Step 4: Run store tests**

Run: `uv run pytest -q tests/test_card_presentation_store.py`

Expected: PASS, including PostgreSQL SQL compilation containing `FOR UPDATE`.

- [ ] **Step 5: Commit the store**

```bash
git add src/signals/card_intelligence/store.py tests/test_card_presentation_store.py
git commit -m "feat(signals): publish card artifacts atomically"
```

## Task 7: Orchestrate private candidates and factual-only publication

**Files:**

- Create: `src/signals/card_intelligence/service.py`
- Create: `tests/test_card_intelligence_service.py`

- [ ] **Step 1: Write service transition tests**

```python
def test_qa_pass_cannot_override_invalid_copy(connection, source, writer, qa):
    writer.responses = [GenerationResponse(payload=materials_to_staffing_payload(source))]
    qa.decisions = [QaDecision(status=QaStatus.PASS, reasons=("model_said_pass",))]
    result = run_offline_candidate_pipeline(
        connection,
        source=source,
        generator=writer,
        qa=qa,
        now=NOW,
    )
    assert result.published.status is QaStatus.FALLBACK
    assert result.published.content.variant is PresentationVariant.FACTUAL_FALLBACK


def test_qa_pass_is_private_and_can_never_activate_full(connection, source, writer, qa):
    candidate = valid_full_payload(source)
    writer.responses = [GenerationResponse(payload=candidate)]
    qa.decisions = [QaDecision(status=QaStatus.PASS, reasons=("grounded",))]
    result = run_offline_candidate_pipeline(
        connection,
        source=source,
        generator=writer,
        qa=qa,
        now=NOW,
    )
    attempts = stored_attempts(connection)
    assert attempts[-2]["qa_status"] == "PASS"
    assert attempts[-2]["published_at"] is None
    assert result["qa_status"] == "FALLBACK"
    assert result["payload"]["variant"] == "FACTUAL_FALLBACK"
    assert qa.seen_payloads == [candidate]
```

Also cover one regeneration before a private QA decision, generation failure
to fallback, ambiguous actor collision to review, `REVIEW` stored but not
published, and a generator-supplied fallback that QA cannot promote to PASS.
QA returns only a decision and never a replacement payload.

- [ ] **Step 2: Confirm service tests are RED**

Run: `uv run pytest -q tests/test_card_intelligence_service.py`

Expected: missing orchestration.

- [ ] **Step 3: Implement the finite state machine**

Allow one regeneration only. Deterministic validators run before QA; only a
semantically valid `FULL` candidate whose sole remaining refusal is
`full_variant_not_authorized` may reach the provider-neutral QA protocol. QA
receives the immutable candidate and input, returns only a decision, and is
never allowed to mutate the payload.

All generator and QA outcomes remain private attempts. In particular, a QA
`PASS/FULL` attempt is recorded with `published_at = NULL`; it can never cross
the read boundary. The function then publishes the exact deterministic
`FACTUAL_FALLBACK`, revalidating it at `append_attempt()`. Generation or QA
errors use the same factual path. Published fallback metadata must use
`generator_version="factual-fallback-v1"`, a deterministic QA policy version,
and null provider, model, prompt and QA-provider fields. No application route,
worker, provider implementation, environment credential or Hermes default is
introduced. Provider-returned reasons are untrusted: private and factual
attempts persist only closed service-owned reason codes. The public factual
publisher exposes no caller-controlled reason parameter.

- [ ] **Step 4: Run service tests**

Run: `uv run pytest -q tests/test_card_intelligence_service.py`

Expected: PASS.

- [ ] **Step 5: Commit orchestration**

```bash
git add src/signals/card_intelligence/service.py tests/test_card_intelligence_service.py
git commit -m "feat(signals): gate card generation through QA"
```

## Task 8: Expose presentations in one batch and pin detail artifacts

**Files:**

- Modify: `src/signals/api/routes_signals.py`
- Modify: `src/signals/feed/view.py`
- Create: `tests/test_card_presentation_api.py`

- [ ] **Step 1: Write API privacy, batching and pinning tests**

```python
def test_feed_and_detail_use_the_exact_pinned_artifact(alice, engine, published):
    feed = alice.get("/signals").json()
    item = next(item for item in feed["items"] if not item["locked"])
    artifact = item["presentation"]
    publish_newer_artifact(engine, signal_id=item["signal_id"], language=feed["language"])
    detail = alice.get(
        f"/signals/{item['signal_id']}",
        params={"presentation_artifact_id": artifact["artifact_id"]},
    ).json()
    assert detail["presentation"]["artifact_id"] == artifact["artifact_id"]
    assert detail["presentation"]["version"] == artifact["version"]


def test_locked_teaser_omits_presentation_and_is_excluded_from_bindings(
    alice, monkeypatch
):
    observed_bindings: list[frozenset[str]] = []
    original = published_for_signals

    def recording_reader(connection, *, account_id, bindings, language):
        observed_bindings.append(frozenset(bindings))
        return original(
            connection,
            account_id=account_id,
            bindings=bindings,
            language=language,
        )

    monkeypatch.setattr(
        "signals.api.routes_signals.published_for_signals", recording_reader
    )
    body = alice.get("/signals").json()
    locked = [item for item in body["items"] if item["locked"]]
    assert locked
    assert all("presentation" not in item for item in locked)
    locked_ids = {item["signal_id"] for item in locked}
    assert all(bindings.isdisjoint(locked_ids) for bindings in observed_bindings)
```

Instrument the connection to assert one `card_presentation_artifact` SELECT
for an unlocked feed page and zero generator/QA/provider calls for feed and
detail GETs.

- [ ] **Step 2: Run API tests and confirm RED**

Run: `uv run pytest -q tests/test_card_presentation_api.py`

Expected: no `presentation` key and unsupported query parameter behavior.

- [ ] **Step 3: Add batch and pinned reads to routes**

In `list_signals`, build bindings only for unlocked items, call
`published_for_signals()` once, and pass each result into `view.feed_item()`.
In `get_signal`, accept:

```python
presentation_artifact_id: str | None = Query(
    default=None,
    min_length=64,
    max_length=64,
    pattern=r"^[0-9a-f]{64}$",
)
```

Read no presentation until ownership and unlock checks have passed. Use the
pinned reader when an ID is supplied and the current batch reader otherwise.

Update view functions as follows:

```python
def feed_item(
    item: FeedSignal,
    *,
    lang: str,
    presentation: PublishedCardPresentation | None = None,
) -> dict[str, Any]:
    card = _base_feed_item(item, lang=lang)
    card["presentation"] = (
        None if presentation is None else presentation.model_dump(mode="json")
    )
    return card
```

Locked paywall functions remain unchanged, guaranteeing the key is absent.

- [ ] **Step 4: Run API and existing signal tests**

Run: `uv run pytest -q tests/test_card_presentation_api.py tests/test_billing_paywall.py tests/test_signal_notes.py`

Expected: PASS.

- [ ] **Step 5: Commit API integration**

```bash
git add src/signals/api/routes_signals.py src/signals/feed/view.py tests/test_card_presentation_api.py
git commit -m "feat(signals): expose published card artifacts on GET"
```

## Task 9: Add a bounded factual backfill CLI

**Files:**

- Create: `src/signals/card_intelligence/backfill.py`
- Create: `src/signals/card_intelligence/cli.py`
- Create: `src/signals/card_intelligence/__main__.py`
- Create: `tests/test_card_intelligence_backfill.py`

- [ ] **Step 1: Write bounded-progress and savepoint tests**

```python
def test_backfill_never_processes_more_than_fifty(engine, qa_account):
    result = backfill_factual_presentations(
        engine,
        account_id=qa_account,
        as_of=DAY,
        language="fr",
        limit=50,
        offset=0,
        now=NOW,
    )
    assert result.scanned <= 50
    assert result.published <= 50


def test_malformed_current_artifact_is_repaired_not_marked_unchanged(engine, source):
    corrupt_current_payload(engine, source)
    result = run_one_backfill_page(engine, source.account_id, language=source.language)
    assert result.published == 1
    assert result.unchanged == 0
```

Also test reaching the 51st raw candidate with explicit offset, scan-cap
termination, per-item savepoint preservation, CLI nonzero on any failure, and
no automatic offset loop.

- [ ] **Step 2: Confirm backfill tests are RED**

Run: `uv run pytest -q tests/test_card_intelligence_backfill.py`

Expected: imports fail.

- [ ] **Step 3: Implement one bounded page only**

Use `MAX_BACKFILL_ITEMS = 50`. The function must accept explicit `limit` and
`offset`, return `next_offset`, and never call itself or loop over offsets.
Inside each item savepoint, skip only when fingerprint matches and the current
row parses as a valid public `FALLBACK/FACTUAL_FALLBACK` envelope.

The CLI command is exactly:

```text
python -m signals.card_intelligence backfill-fallbacks \
  --account-id "$KIVOU_CARD_QA_ACCOUNT_ID" \
  --as-of "$KIVOU_BACKFILL_AS_OF" \
  --language fr \
  --limit 50 \
  --offset 0
```

It prints counts and `next_offset`, never credentials, content, source facts or
account metadata.

- [ ] **Step 4: Run backfill tests**

Run: `uv run pytest -q tests/test_card_intelligence_backfill.py`

Expected: PASS.

- [ ] **Step 5: Commit backfill**

```bash
git add src/signals/card_intelligence/backfill.py src/signals/card_intelligence/cli.py src/signals/card_intelligence/__main__.py tests/test_card_intelligence_backfill.py
git commit -m "feat(signals): backfill factual card artifacts safely"
```

## Task 10: Version the staging rollout and frontend atomic switch

**Files:**

- Create: `docs/runbooks/11-staging-card-presentation-rollout.md`
- Create: `tests/test_card_presentation_runbook.py`
- Modify: `ops/README.md`

- [ ] **Step 1: Write static runbook contract tests**

```python
def test_card_rollout_requires_exact_main_backup_migration_and_atomic_frontend():
    body = RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "0027_signal_notes",
        "0028_card_presentation",
        "pg_restore --list",
        "sha256sum",
        "frontend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT",
        "mv -Tf",
        "FACTUAL_FALLBACK",
        "--language fr",
        "--language en",
        "provider IS NULL",
        "ne pas exécuter de downgrade",
    ):
        assert required in body
    assert "kivou-production" not in body
```

- [ ] **Step 2: Confirm the runbook test is RED**

Run: `uv run pytest -q tests/test_card_presentation_runbook.py`

Expected: missing file.

- [ ] **Step 3: Write the executable operator sequence**

The runbook must provide exact commands for:

1. final-main SHA and CI verification;
2. current host/SHA/symlink/migration preflight;
3. `kivou-backup.service` start, dump path, size, SHA-256 and
   `pg_restore --list` verification;
4. restore into a uniquely named scratch database and removal after success;
5. immutable backend release preparation from `main`;
6. internal migration API invocation from that release before green runtime;
7. existing `ops/README.md` blue/green backend flow;
8. detached frontend build from the same SHA;
9. immutable frontend directory, tar transfer, temporary symlink and
   `sudo mv -Tf` switch;
10. immediate HTTP rollback of the frontend symlink;
11. separate one-page FR and EN backfills on a server-verified QA account;
12. application-only rollback retaining migration 0028.

Every recursive cleanup command must guard an explicit
`/srv/kivou/releases/.frontend-build-*` or scratch-database name. No production
alias, provider mutation or secret value may appear.

- [ ] **Step 4: Run ops tests**

Run: `uv run pytest -q tests/test_card_presentation_runbook.py tests/test_ops_backup_runtime.py tests/test_ops_api_readiness.py tests/test_ops_nginx_routes.py`

Expected: PASS.

- [ ] **Step 5: Commit the runbook**

```bash
git add docs/runbooks/11-staging-card-presentation-rollout.md tests/test_card_presentation_runbook.py ops/README.md
git commit -m "docs(ops): version card presentation staging rollout"
```

## Task 11: Verify PR 1 locally, visually and on GitHub

**Files:**

- Modify only if evidence requires it: files already listed in Tasks 1–10.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
uv run pytest -q \
  tests/test_card_intelligence_contracts.py \
  tests/test_card_intelligence_validation.py \
  tests/test_card_intelligence_service.py \
  tests/test_card_presentation_migration.py \
  tests/test_card_presentation_store.py \
  tests/test_card_presentation_api.py \
  tests/test_card_intelligence_backfill.py \
  tests/test_card_presentation_runbook.py \
  tests/test_billing_paywall.py
```

Expected: PASS.

- [ ] **Step 2: Run complete local gates**

Run:

```bash
uv run pytest -q
uv run ruff check .
cd frontend
npm test -- --run
npm run test:visual
npm run build
npm run build:founder
npx tsc -b
npm run lint
```

Expected: every command exits 0. Open the generated desktop and mobile
dashboard/signals images with the image viewer and record that PR 1 caused no
visual delta.

- [ ] **Step 3: Audit scope and forbidden coupling**

Run:

```bash
git diff --check origin/main...HEAD
git diff --name-status origin/main...HEAD
rg -n "Hermes|apollo|openrouter|provider_registry|generate_and_publish" \
  src/signals/api src/signals/feed
```

Expected: no whitespace errors; only planned files; no GET-side provider or
generation wiring.

- [ ] **Step 4: Push without force and create the replacement PR**

```bash
git push -u origin feat/119-card-presentation-foundation-v5
gh pr create \
  --repo bruppacherrodrigue-art/Kivou \
  --base main \
  --head feat/119-card-presentation-foundation-v5 \
  --title "feat(signals): found Card Intelligence publication" \
  --body-file /tmp/kivou-pr1-body.md
```

The body must link #119/#127, state that it replaces #123, list test evidence,
declare AI disabled, and document migration/rollback risks. Create the body
file with `apply_patch`, not shell redirection.

- [ ] **Step 5: Require actual GitHub job execution**

Inspect both jobs and their steps with `gh run view --json jobs`. Reject any
job with an empty `steps` list or a conclusion other than `success`. Do not
merge while either job is queued, in progress, cancelled or pre-runner failed.

- [ ] **Step 6: Squash merge and verify the new main**

After both jobs are truly green:

```bash
gh pr merge --squash --delete-branch=false
git fetch origin main
git rev-parse origin/main
gh run list --workflow CI --branch main --commit "$(git rev-parse origin/main)"
```

Verify the squash tree against the reviewed PR tree and wait for both jobs of
the exact `main` SHA. Then close #123 with a comment linking the replacement;
do not delete or rewrite its branch.
