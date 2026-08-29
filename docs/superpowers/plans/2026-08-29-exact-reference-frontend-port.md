# Exact Reference Frontend Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public site and authenticated application with direct ports of the two approved reference frontends while retaining Kivou's real APIs, permissions, paywall, Stripe actions, honest states, and staging-only release discipline.

**Architecture:** Keep the current React/Vite SPA, React Router, session provider, and backend contracts. Import the exact reference DOM, class names, CSS, breakpoints, and UI primitives at the pinned source commits; isolate public and dashboard CSS by a route-owned HTML surface attribute; feed the reference components through typed view-model adapters instead of reference demo data. Add only two bounded backend capabilities required by the approved UI: account locale mutation and a private signal-note resource that is deliberately separate from relevance feedback.

**Tech Stack:** React 19, TypeScript, React Router 7, Vite 7, Tailwind CSS 4, Radix UI, Lucide React, Vitest/Testing Library, Playwright/Chromium, FastAPI, Pydantic, SQLAlchemy, Alembic, Pytest, GitHub Actions, nginx/systemd staging releases.

---

## Locked inputs and non-negotiable boundaries

- Public authority: `/tmp/kivou-sites-source-public` at
  `efaa4160f4c3bbbdb01448bf9228772491e614f5`.
- Dashboard authority: `/tmp/kivou-sites-source-dashboard` at
  `05212f2da5197699e6a9bb191556afcb2dcf1bb3`.
- Design contract:
  `docs/superpowers/specs/2026-08-29-exact-reference-frontend-port-design.md`.
- The reference owns visible DOM order, class names, colors, fonts, spacing,
  density, responsive behavior, and component geometry.
- Kivou owns data, session, localization, access, paywall, Stripe actions, and
  loading/error/empty truthfulness.
- Public pages are French only. Connected pages follow `GET /me.locale`, which
  can be changed from Account settings through `PATCH /me`.
- Never ship `Mode démonstration`, `Compte démo`, fixed reference companies,
  fixed reference signals, fixed reference targeting, or fixed reference prices
  as runtime data.
- Never request detail for a locked signal. Never request a company unless an
  accessible signal detail supplied its `company_key`.
- Do not change matching, authentication semantics, entitlements, Stripe
  contracts, Apollo, Instantly, Hermes, or production.
- A note write must not create a relevance judgment. The new note table and
  routes are private engagement storage only and emit no analytical event.

## File map

### Provenance, styling, and test infrastructure

- Create `frontend/reference-source.json`: pinned commits, source paths, and
  normative hashes.
- Create `frontend/scripts/verify-reference-source.mjs`: fail-closed source
  verification before any copy.
- Create `frontend/postcss.config.mjs`: Tailwind compilation followed by CSS
  scoping for only the two reference stylesheets.
- Create `frontend/src/reference/surface/SurfaceBoundary.tsx`: synchronously set
  and restore `data-kivou-surface` on `<html>`.
- Create `frontend/src/reference/router/ReferenceLink.tsx`: React Router adapter
  for the reference's `href`-shaped links.
- Create `frontend/src/reference/public/public-reference.css`: exact public CSS.
- Create `frontend/public/reference/public-favicon.svg`: exact public favicon.
- Create `frontend/src/reference/dashboard/dashboard-reference.css`: exact
  dashboard CSS.
- Create `frontend/public/reference/dashboard-favicon.svg`: exact connected
  favicon.
- Create `frontend/src/reference/dashboard/vendor/shadcn-tailwind-4.13.0.css`:
  exact vendored reference stylesheet and retain its license beside it.
- Create `frontend/src/reference/dashboard/ui/*`: only the exact UI primitives
  imported by the port.
- Modify `frontend/index.html`: remove the legacy no-script redesign and use
  the reference default metadata/favicon.
- Create `frontend/playwright.config.ts`, `frontend/tests/visual/*`, and
  `frontend/tests/visual/reference-goldens/*`: deterministic browser comparison.

### Public presentation

- Modify `frontend/src/layouts/PublicLayout.tsx`: exact `SiteHeader`,
  `SiteFooter`, logo, skip link, and `<Outlet>` composition.
- Replace the visible implementations in `frontend/src/pages/Landing.tsx`,
  `Product.tsx`, `PublicPricing.tsx`, `PublicSignalDemo.tsx`, `Contact.tsx`, and
  `LegalInformation.tsx` with direct reference ports.
- Create `frontend/src/reference/public/PricingResource.tsx`: preserve the exact
  pricing DOM while sourcing prices and availability from `/billing/plans`.

### Connected presentation and adapters

- Modify `frontend/src/layouts/AppShell.tsx`: exact reference sidebar/topbar,
  real account identity, real target profile label, and `<Outlet>`.
- Create `frontend/src/reference/dashboard/models.ts`: presentation-only view
  models matching visible reference slots.
- Create `frontend/src/reference/dashboard/adapters.ts`: pure transformations
  from API contracts to those models; no fetching and no fallback demo data.
- Create `frontend/src/reference/dashboard/resources.ts`: independent resource
  hooks with generation guards and local retry.
- Modify `frontend/src/i18n/fr.ts` and `frontend/src/i18n/en.ts`: connected
  reference copy; French values remain byte-for-byte equal to the source.
- Replace the visible implementations of `Dashboard.tsx`, `SignalsFeed.tsx`,
  `SignalDetail.tsx`, `Companies.tsx`, `CompanyProfile.tsx`, `Icps.tsx`,
  `Settings.tsx`, `Billing.tsx`, and `Notifications.tsx` with the corresponding
  reference compositions fed by those adapters.
- Create `frontend/src/pages/ProfileSettings.tsx` and
  `frontend/src/pages/SecuritySettings.tsx` for the reference account subroutes.
- Adapt `Login.tsx`, `Signup.tsx`, `PasswordReset.tsx`, `Onboarding.tsx`, and
  `Checkout.tsx` to the reference auth/system-state layouts without changing
  their existing actions.

### Backend additions

- Modify `src/signals/accounts/service.py` and
  `src/signals/api/routes_auth.py`: bounded account locale update.
- Create `src/signals/engagement/notes.py`: current private note storage.
- Modify `src/signals/engagement/schema.py`: declare `signal_note`.
- Create `src/signals/api/routes_notes.py` and modify
  `src/signals/api/app.py`: authenticated note routes.
- Create
  `src/signals/persistence/migrations/versions/0027_signal_notes.py`: additive
  note table only.
- Create `tests/test_account_locale.py`, `tests/test_signal_notes.py`, and
  `tests/test_signal_notes_migration.py`.

## Task 1: Lock the source provenance and install only the required toolchain

**Files:**
- Create: `frontend/reference-source.json`
- Create: `frontend/scripts/verify-reference-source.mjs`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Test: `frontend/src/styles/referenceProvenance.test.ts`

- [ ] **Step 1: Write the failing provenance test**

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { SurfaceBoundary } from '../reference/surface/SurfaceBoundary'
import { ReferenceLink } from '../reference/router/ReferenceLink'
import { renderApp } from '../test/harness'

it('pins both approved reference commits and their core hashes', () => {
  const manifest = JSON.parse(
    readFileSync(resolve(process.cwd(), 'reference-source.json'), 'utf8'),
  )
  expect(manifest.public.commit).toBe('efaa4160f4c3bbbdb01448bf9228772491e614f5')
  expect(manifest.dashboard.commit).toBe('05212f2da5197699e6a9bb191556afcb2dcf1bb3')
  expect(manifest.public.files['app/globals.css']).toBe(
    '56f8c96cc3975d9f81882d1ac9eb49c791aefd90d690f6a559c4a96c946bde95',
  )
  expect(manifest.dashboard.files['app/globals.css']).toBe(
    '4f7fb469e4ed2f32a424d4b45cb77e23b016314e0f2a062524f0dc7c090a720d',
  )
})
```

- [ ] **Step 2: Run the test and observe RED**

Run: `cd frontend && npm test -- --run src/styles/referenceProvenance.test.ts`

Expected: FAIL because `reference-source.json` does not exist.

- [ ] **Step 3: Create the manifest and verifier**

`frontend/reference-source.json` must contain exactly these normative core
entries; the verifier also checks that each source tree is clean:

```json
{
  "public": {
    "path": "/tmp/kivou-sites-source-public",
    "commit": "efaa4160f4c3bbbdb01448bf9228772491e614f5",
    "files": {
      "app/globals.css": "56f8c96cc3975d9f81882d1ac9eb49c791aefd90d690f6a559c4a96c946bde95",
      "app/page.tsx": "3c39bfb20716f425d3cb6971191d0c42b242a3560a5be656e2ebba5977762758",
      "components/site-shell.tsx": "e06c282e0001237bd8465bc07e5606a28e068109de36bfb57917464449b2a297",
      "public/favicon.svg": "0d63748a96627ae1508c14f493d04ac8d8cf48d7dc87b429b5746b1697273032"
    }
  },
  "dashboard": {
    "path": "/tmp/kivou-sites-source-dashboard",
    "commit": "05212f2da5197699e6a9bb191556afcb2dcf1bb3",
    "files": {
      "app/globals.css": "4f7fb469e4ed2f32a424d4b45cb77e23b016314e0f2a062524f0dc7c090a720d",
      "components/kivou-dashboard-shell.tsx": "9f14abcdfa10b354f61ad299b445fd223340f013e20715203a6cd0b5f4850dd1",
      "components/overview-page.tsx": "fedc78d0041beb1c77321d24f24e0e41a0ab3b0e153b26036d8d96f337d80423",
      "components/signals-page.tsx": "ddfbfd00ed18373a8d9a3e96d166adf69db13ad59296363bc36065bdddcf6b79",
      "public/favicon.svg": "1540696271c1fae5bb5066346dfaf62fba1c4375548d95c63bec4c24d9205b4c"
    }
  }
}
```

`frontend/scripts/verify-reference-source.mjs`:

```js
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const manifest = JSON.parse(readFileSync(resolve('reference-source.json'), 'utf8'))

for (const [name, source] of Object.entries(manifest)) {
  const head = execFileSync('git', ['-C', source.path, 'rev-parse', 'HEAD'], {
    encoding: 'utf8',
  }).trim()
  if (head !== source.commit) throw new Error(`${name}: HEAD ${head} != ${source.commit}`)
  const dirty = execFileSync('git', ['-C', source.path, 'status', '--porcelain'], {
    encoding: 'utf8',
  }).trim()
  if (dirty) throw new Error(`${name}: source working tree is dirty`)
  for (const [relative, expected] of Object.entries(source.files)) {
    const actual = createHash('sha256')
      .update(readFileSync(resolve(source.path, relative)))
      .digest('hex')
    if (actual !== expected) throw new Error(`${name}/${relative}: hash mismatch`)
  }
}
```

- [ ] **Step 4: Verify both sources**

Run: `cd frontend && node scripts/verify-reference-source.mjs`

Expected: exit 0 and no output. Any mismatch stops the port; do not regenerate a
hash around changed content.

- [ ] **Step 5: Install the exact required packages**

Run:

```bash
cd frontend
npm install --save-exact \
  class-variance-authority@0.7.1 \
  clsx@2.1.1 \
  lucide-react@1.31.0 \
  radix-ui@1.6.7 \
  tailwind-merge@3.6.0
npm install --save-dev --save-exact \
  @playwright/test@1.62.1 \
  @tailwindcss/postcss@4.2.1 \
  postcss@8.5.26 \
  tailwindcss@4.2.1 \
  tw-animate-css@1.4.0
npm test -- --run src/styles/referenceProvenance.test.ts
```

Expected: the focused test passes and `package-lock.json` records exact versions.

- [ ] **Step 6: Commit the provenance/toolchain slice**

```bash
git add frontend/reference-source.json frontend/scripts/verify-reference-source.mjs \
  frontend/package.json frontend/package-lock.json \
  frontend/src/styles/referenceProvenance.test.ts
git commit -m "build(frontend): pin reference source toolchain"
```

## Task 2: Add the bounded account locale mutation

**Files:**
- Create: `tests/test_account_locale.py`
- Modify: `src/signals/accounts/service.py`
- Modify: `src/signals/api/routes_auth.py`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/auth/SessionProvider.tsx`
- Test: `frontend/src/auth/session.test.tsx`

- [ ] **Step 1: Write the failing backend contract tests**

Start `tests/test_account_locale.py` with this complete isolated fixture:

```py
from __future__ import annotations
import datetime as dt
import pytest
from fastapi.testclient import TestClient
from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

ORIGIN = "https://kivou.test"
PASSWORD = "un-mot-de-passe-assez-long"


@pytest.fixture
def engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'locale.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def app(engine):
    def now():
        return dt.datetime(2026, 8, 29, 9, 0, tzinfo=dt.UTC)

    return create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN),
        now_override=now,
    )


@pytest.fixture
def client(app):
    return TestClient(app, headers={"Origin": ORIGIN})


def signup(client):
    response = client.post(
        "/auth/signup",
        json={
            "email": "locale@example.test",
            "password": PASSWORD,
            "company_name": "Locale SA",
            "locale": "fr",
        },
    )
    assert response.status_code == 201
    return response
```

Then add these assertions:

```py
def test_authenticated_account_can_change_its_locale(client):
    signup(client)
    changed = client.patch("/me", json={"locale": "en"})
    assert changed.status_code == 200
    assert changed.json()["locale"] == "en"
    assert client.get("/me").json()["locale"] == "en"


def test_locale_update_rejects_unknown_values_and_fields(client):
    signup(client)
    assert client.patch("/me", json={"locale": "de"}).status_code == 422
    assert client.patch("/me", json={"locale": "en", "account_id": "other"}).status_code == 422
    assert client.get("/me").json()["locale"] == "fr"


def test_locale_update_requires_session_and_same_origin(app):
    from fastapi.testclient import TestClient
    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.patch("/me", json={"locale": "en"}).status_code == 401
    owner = TestClient(app, headers={"Origin": ORIGIN})
    signup(owner)
    assert owner.patch(
        "/me", json={"locale": "en"}, headers={"Origin": "https://attacker.example"}
    ).status_code == 403
```

- [ ] **Step 2: Run the backend tests and observe RED**

Run: `uv run pytest -q tests/test_account_locale.py`

Expected: FAIL with `405 Method Not Allowed` for `PATCH /me`.

- [ ] **Step 3: Add the service and route**

Add to `src/signals/accounts/service.py`:

```py
def update_locale(
    connection: sa.Connection,
    *,
    account_id: str,
    locale: str,
    now: dt.datetime,
) -> None:
    if locale not in SUPPORTED_LOCALES:
        raise UnsupportedLocale(f"locale non prise en charge : {locale}")
    connection.execute(
        sa.update(account)
        .where(account.c.account_id == account_id)
        .values(locale=locale, updated_at=now)
    )
```

Add to `src/signals/api/routes_auth.py`:

```py
class PatchMeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["fr", "en"]


@router.patch("/me")
def patch_me(payload: PatchMeRequest, request: Request) -> MeResponse:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        service.update_locale(
            connection,
            account_id=session.account_id,
            locale=payload.locale,
            now=now,
        )
        user = service.current_user(connection, user_id=session.user_id)
    return _me_response(user, request)
```

- [ ] **Step 4: Verify the backend locale contract**

Run: `uv run pytest -q tests/test_account_locale.py tests/test_accounts_security.py`

Expected: all tests pass.

- [ ] **Step 5: Write the failing frontend session test**

```tsx
function LocaleProbe() {
  const { state, updateLocale } = useSession()
  return (
    <div>
      <span data-testid="locale">
        {state.status === 'authenticated' ? state.me.locale : state.status}
      </span>
      <button onClick={() => void updateLocale('en')}>English</button>
    </div>
  )
}

it('adopts the authoritative PATCH /me response when locale changes', async () => {
  const user = userEvent.setup()
  mockApi({
    'PATCH /me': (request) => {
      expect(request.body).toEqual({ locale: 'en' })
      return { body: { ...ME, locale: 'en' } }
    },
  })
  renderApp(<LocaleProbe />, { session: AUTHENTICATED })
  await user.click(screen.getByRole('button', { name: 'English' }))
  await waitFor(() => expect(screen.getByTestId('locale')).toHaveTextContent('en'))
  expect(callsTo('/me', 'PATCH')).toHaveLength(1)
})
```

- [ ] **Step 6: Run the frontend test and observe RED**

Run: `cd frontend && npm test -- --run src/auth/session.test.tsx`

Expected: FAIL because `updateLocale` does not exist.

- [ ] **Step 7: Add the frontend endpoint and session action**

In `frontend/src/api/endpoints.ts` add to `auth`:

```ts
updateLocale: (locale: Locale) =>
  request<Me>('/me', { method: 'PATCH', body: { locale } }),
```

Extend `SessionValue` and `SessionProvider` with:

```ts
updateLocale: (locale: Locale) => Promise<void>

const updateLocale = useCallback(async (locale: Locale) => {
  const me = await auth.updateLocale(locale)
  if (mounted.current) setState({ status: 'authenticated', me })
}, [])
```

Include `updateLocale` in the memoized context value and dependencies.

- [ ] **Step 8: Verify and commit locale mutation**

```bash
uv run pytest -q tests/test_account_locale.py tests/test_accounts_security.py
cd frontend
npm test -- --run src/auth/session.test.tsx src/auth/auth.test.tsx
cd ..
git add tests/test_account_locale.py src/signals/accounts/service.py \
  src/signals/api/routes_auth.py frontend/src/api/endpoints.ts \
  frontend/src/auth/SessionProvider.tsx frontend/src/auth/session.test.tsx
git commit -m "feat(account): persist connected locale"
```

Expected: both focused suites pass.

## Task 3: Store signal notes without fabricating relevance

**Files:**
- Create: `src/signals/engagement/notes.py`
- Modify: `src/signals/engagement/schema.py`
- Create: `src/signals/api/routes_notes.py`
- Modify: `src/signals/api/app.py`
- Create: `src/signals/persistence/migrations/versions/0027_signal_notes.py`
- Create: `tests/test_signal_notes.py`
- Create: `tests/test_signal_notes_migration.py`
- Modify: `tests/test_accounts_migration_and_ownership.py`
- Modify: `tests/test_acquisition_migration.py`
- Modify: `tests/test_acquisition_runtime_migration.py`
- Modify: `tests/test_alert_recipient_context_migration.py`
- Modify: `tests/test_billing_entitlements.py`
- Modify: `tests/test_campaign_factory_migration.py`
- Modify: `tests/test_company_research_migration.py`
- Modify: `tests/test_compliance_migration.py`
- Modify: `tests/test_contact_discovery_migration.py`
- Modify: `tests/test_contract_award_text_capacity_migration.py`
- Modify: `tests/test_conversion_tracking_migration.py`
- Modify: `tests/test_decision_engine_migration.py`
- Modify: `tests/test_learning_migration.py`
- Modify: `tests/test_personalization_migration.py`
- Modify: `tests/test_policy_persistence.py`
- Modify: `tests/test_reliability_operations_migration.py`
- Modify: `tests/test_response_intelligence_migration.py`
- Modify: `tests/test_saas_company_migration.py`
- Modify: `tests/test_supplier_discovery_migration.py`
- Modify: `tests/test_transactional_email_migration.py`

- [ ] **Step 1: Write the failing note API tests**

Start `tests/test_signal_notes.py` with the established engagement fixtures and
the local paid-signal helper:

```py
from __future__ import annotations
import pathlib
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from engagement_helpers import (
    Clock, events, icp_of, make_app, make_engine, pay, seed, signed_up,
)
from feed_helpers import ORIGIN
from signals.engagement.schema import MAXIMUM_NOTE_LENGTH, signal_feedback


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    return make_engine(tmp_path)


@pytest.fixture
def app(engine, clock: Clock):
    return make_app(engine, clock)


@pytest.fixture
def alice(app):
    return signed_up(app)


def paid_signal(engine, client, *, plan: str = "pro") -> str:
    icp = icp_of(client)
    pay(engine, client, plan=plan)
    return seed(engine, icp, count=1)[0]


def test_note_roundtrip_does_not_create_feedback_or_analytics(alice, engine):
    key = paid_signal(engine, alice)
    response = alice.put(f"/signals/{key}/note", json={"note": "Appeler lundi"})
    assert response.status_code == 200
    assert response.json()["note"] == "Appeler lundi"
    assert alice.get(f"/signals/{key}/note").json()["note"] == "Appeler lundi"
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(signal_feedback)
        ).scalar_one() == 0
    assert events(engine) == []


def test_empty_note_deletes_only_the_current_note(alice, engine):
    key = paid_signal(engine, alice)
    alice.put(f"/signals/{key}/note", json={"note": "Temporaire"})
    cleared = alice.put(f"/signals/{key}/note", json={"note": "   "})
    assert cleared.json()["note"] is None
    assert alice.get(f"/signals/{key}/note").json()["note"] is None


def test_note_is_private_and_requires_unlocked_access(app, engine):
    alice = signed_up(app, "alice@example.test")
    bob = signed_up(app, "bob@example.test")
    key = paid_signal(engine, alice)
    assert alice.put(f"/signals/{key}/note", json={"note": "privé"}).status_code == 200
    assert bob.get(f"/signals/{key}/note").status_code == 404
    assert bob.put(f"/signals/{key}/note", json={"note": "vol"}).status_code == 404


def test_locked_anonymous_foreign_origin_and_long_notes_fail_closed(alice, app, engine):
    icp = icp_of(alice)
    seed(engine, icp, count=5)
    items = alice.get("/signals?limit=50").json()["items"]
    locked = next(item["signal_id"] for item in items if item["locked"])
    unlocked = next(item["signal_id"] for item in items if not item["locked"])

    assert alice.get(f"/signals/{locked}/note").status_code == 403
    assert alice.put(f"/signals/{locked}/note", json={"note": "interdit"}).status_code == 403
    assert alice.put(
        f"/signals/{unlocked}/note", json={"note": "x" * (MAXIMUM_NOTE_LENGTH + 1)}
    ).status_code == 422
    assert alice.put(
        f"/signals/{unlocked}/note",
        json={"note": "attaque"},
        headers={"Origin": "https://attacker.example"},
    ).status_code == 403

    anonymous = TestClient(app, headers={"Origin": ORIGIN})
    assert anonymous.get(f"/signals/{unlocked}/note").status_code == 401
    assert anonymous.put(
        f"/signals/{unlocked}/note", json={"note": "anonyme"}
    ).status_code == 401
```

- [ ] **Step 2: Run the note API tests and observe RED**

Run: `uv run pytest -q tests/test_signal_notes.py`

Expected: FAIL because the routes and table do not exist.

- [ ] **Step 3: Declare the isolated note table**

Change the module introduction from “Cinq tables” to “Six tables”, add this
table immediately after `signal_feedback`, and include `signal_note` in
`ENGAGEMENT_TABLES` immediately after `signal_feedback`:

```py
signal_note = sa.Table(
    "signal_note",
    METADATA,
    sa.Column(
        "account_id",
        sa.String(64),
        sa.ForeignKey("account.account_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("signal_key", sa.String(64), primary_key=True),
    sa.Column("note", sa.String(MAXIMUM_NOTE_LENGTH), nullable=False),
    *_timestamps(),
)

ENGAGEMENT_TABLES: tuple[sa.Table, ...] = (
    signal_feedback,
    signal_note,
    product_event,
    account_notification_preference,
    signal_alert_delivery,
    signal_alert_job_lease,
)
```

- [ ] **Step 4: Implement the note service**

`src/signals/engagement/notes.py`:

```py
from __future__ import annotations

import dataclasses
import datetime as dt
import sqlalchemy as sa

from signals.engagement.schema import signal_note


@dataclasses.dataclass(frozen=True)
class StoredNote:
    account_id: str
    signal_key: str
    note: str
    updated_at: dt.datetime


def get(connection: sa.Connection, *, account_id: str, signal_key: str) -> StoredNote | None:
    row = connection.execute(
        sa.select(signal_note).where(
            signal_note.c.account_id == account_id,
            signal_note.c.signal_key == signal_key,
        )
    ).first()
    if row is None:
        return None
    from signals.billing.service import aware_datetime
    return StoredNote(row.account_id, row.signal_key, row.note, aware_datetime(row.updated_at))


def put(
    connection: sa.Connection,
    *,
    account_id: str,
    signal_key: str,
    note: str,
    now: dt.datetime,
) -> StoredNote | None:
    current = get(connection, account_id=account_id, signal_key=signal_key)
    if not note.strip():
        connection.execute(
            sa.delete(signal_note).where(
                signal_note.c.account_id == account_id,
                signal_note.c.signal_key == signal_key,
            )
        )
        return None
    if current is None:
        connection.execute(
            sa.insert(signal_note).values(
                account_id=account_id,
                signal_key=signal_key,
                note=note,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        connection.execute(
            sa.update(signal_note)
            .where(
                signal_note.c.account_id == account_id,
                signal_note.c.signal_key == signal_key,
            )
            .values(note=note, updated_at=now)
        )
    return get(connection, account_id=account_id, signal_key=signal_key)
```

- [ ] **Step 5: Implement the authenticated routes**

`src/signals/api/routes_notes.py` must import and reuse
`_accessible_signal` from `routes_feedback.py` so the authorization behavior
cannot drift:

```py
from typing import Any
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.routes_feedback import _accessible_signal
from signals.engagement import notes
from signals.engagement.schema import MAXIMUM_NOTE_LENGTH

router = APIRouter()


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(max_length=MAXIMUM_NOTE_LENGTH)


def _response(signal_key: str, stored: notes.StoredNote | None) -> dict[str, Any]:
    return {
        "signal_id": signal_key,
        "note": None if stored is None else stored.note,
        "updated_at": None if stored is None else stored.updated_at.isoformat(),
    }


@router.get("/signals/{signal_key}/note")
def read_note(signal_key: str, request: Request) -> dict[str, Any]:
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_signal(connection, session, signal_key, now)
        stored = notes.get(connection, account_id=session.account_id, signal_key=signal_key)
    return _response(signal_key, stored)


@router.put("/signals/{signal_key}/note")
def write_note(signal_key: str, payload: NoteRequest, request: Request) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_signal(connection, session, signal_key, now)
        stored = notes.put(
            connection,
            account_id=session.account_id,
            signal_key=signal_key,
            note=payload.note,
            now=now,
        )
    return _response(signal_key, stored)
```

Import `notes_router` in `src/signals/api/app.py` and call
`app.include_router(notes_router)` immediately after `feedback_router`.

- [ ] **Step 6: Write the failing migration tests**

`tests/test_signal_notes_migration.py`:

```py
from __future__ import annotations
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from signals.persistence.database import (
    alembic_config,
    create_database_engine,
    current_revision,
)

PREVIOUS = "0026_acquisition_runtime"
HEAD = "0027_signal_notes"


def _engine(tmp_path, name):
    return create_database_engine(f"sqlite+pysqlite:///{tmp_path / name}")


def test_signal_note_migration_is_one_additive_table(tmp_path):
    engine = _engine(tmp_path, "signal-note.db")
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    before = set(sa.inspect(engine).get_table_names())
    command.upgrade(config, HEAD)
    assert set(sa.inspect(engine).get_table_names()) - before == {"signal_note"}
    assert current_revision(engine) == HEAD
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]


def test_signal_note_migration_roundtrips_without_touching_feedback(tmp_path):
    engine = _engine(tmp_path, "signal-note-roundtrip.db")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    assert "signal_feedback" in sa.inspect(engine).get_table_names()
    command.downgrade(config, PREVIOUS)
    tables = set(sa.inspect(engine).get_table_names())
    assert "signal_note" not in tables
    assert "signal_feedback" in tables
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
```

- [ ] **Step 7: Create the additive migration**

`src/signals/persistence/migrations/versions/0027_signal_notes.py`:

```py
"""Add private account-scoped signal notes.

Revision ID: 0027_signal_notes
Revises: 0026_acquisition_runtime
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op

revision = "0027_signal_notes"
down_revision = "0026_acquisition_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_note",
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("account.account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("signal_key", sa.String(64), primary_key=True),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("signal_note")
```

- [ ] **Step 8: Update only the enumerated global current-head assertions**

In the files where 0026 is only the value of `CURRENT_HEAD`, change that value
to `"0027_signal_notes"`. Change the two direct post-`migrate_to_latest`
assertions in `tests/test_billing_entitlements.py` and the direct assertion in
`tests/test_accounts_migration_and_ownership.py` likewise.

Four migration-graph tests also assert the immediate parent. Preserve that
proof by adding the intermediate revision explicitly:

```py
RUNTIME = "0026_acquisition_runtime"
LATEST = "0027_signal_notes"
```

Use those constants in `tests/test_alert_recipient_context_migration.py`,
`tests/test_campaign_factory_migration.py`, and `tests/test_learning_migration.py`
so their chain contains both exact edges:

```py
assert scripts.get_revision(LATEST).down_revision == RUNTIME
assert scripts.get_revision(RUNTIME).down_revision == ALERT_RECIPIENT_CONTEXT
```

In `tests/test_contract_award_text_capacity_migration.py`, use the existing
`*_REVISION` naming:

```py
ACQUISITION_RUNTIME_REVISION = "0026_acquisition_runtime"
CURRENT_HEAD = "0027_signal_notes"
```

and assert both `CURRENT_HEAD -> ACQUISITION_RUNTIME_REVISION` and
`ACQUISITION_RUNTIME_REVISION -> ALERT_RECIPIENT_CONTEXT_REVISION`.

In `tests/test_compliance_migration.py`, rename its chain-wide `HEAD` constant
to `CURRENT_HEAD` while changing the value, so its historical compliance
revision assertions stay explicit. In
`tests/test_acquisition_runtime_migration.py`, keep
`HEAD = "0026_acquisition_runtime"`, add:

```py
CURRENT_HEAD = "0027_signal_notes"
```

and change only:

```py
assert scripts.get_heads() == [CURRENT_HEAD]
```

Keep every occurrence in
`tests/test_acquisition_runtime_authorization_migration.py`,
`tests/test_acquisition_runtime_units.py`, the `HEAD`/path assertions in
`tests/test_acquisition_runtime_migration.py`, and `PREVIOUS` in
`tests/test_signal_notes_migration.py`: those occurrences describe revision
0026 itself, not the repository head.

- [ ] **Step 9: Verify API, migration, and engine isolation**

Run:

```bash
uv run pytest -q tests/test_signal_notes.py tests/test_signal_notes_migration.py \
  tests/test_engagement_feedback.py tests/test_engagement_analytics.py \
  tests/test_accounts_migration_and_ownership.py
uv run ruff check src/signals/engagement/notes.py src/signals/api/routes_notes.py \
  src/signals/persistence/migrations/versions/0027_signal_notes.py \
  tests/test_signal_notes.py tests/test_signal_notes_migration.py
```

Expected: all focused tests pass; no feedback or analytics expectation changes.

- [ ] **Step 10: Commit the isolated note capability**

```bash
git add src/signals/engagement/notes.py src/signals/engagement/schema.py \
  src/signals/api/routes_notes.py src/signals/api/app.py \
  src/signals/persistence/migrations/versions/0027_signal_notes.py \
  tests/test_signal_notes.py tests/test_signal_notes_migration.py \
  tests/test_accounts_migration_and_ownership.py \
  tests/test_acquisition_migration.py tests/test_acquisition_runtime_migration.py \
  tests/test_alert_recipient_context_migration.py tests/test_billing_entitlements.py \
  tests/test_campaign_factory_migration.py tests/test_company_research_migration.py \
  tests/test_compliance_migration.py tests/test_contact_discovery_migration.py \
  tests/test_contract_award_text_capacity_migration.py \
  tests/test_conversion_tracking_migration.py tests/test_decision_engine_migration.py \
  tests/test_learning_migration.py tests/test_personalization_migration.py \
  tests/test_policy_persistence.py tests/test_reliability_operations_migration.py \
  tests/test_response_intelligence_migration.py tests/test_saas_company_migration.py \
  tests/test_supplier_discovery_migration.py tests/test_transactional_email_migration.py
git commit -m "feat(signals): store private notes without feedback"
```

## Task 4: Build the exact reference styling boundary and router adapters

**Files:**
- Create: `frontend/postcss.config.mjs`
- Create: `frontend/src/reference/surface/SurfaceBoundary.tsx`
- Create: `frontend/src/reference/router/ReferenceLink.tsx`
- Create: `frontend/src/reference/public/public-reference.css`
- Create: `frontend/src/reference/dashboard/dashboard-reference.css`
- Create: `frontend/src/reference/dashboard/vendor/shadcn-tailwind-4.13.0.css`
- Create: `frontend/src/reference/dashboard/vendor/shadcn-tailwind-4.13.0.LICENSE.md`
- Create: `frontend/src/reference/dashboard/ui/{button,input,textarea,checkbox,progress,separator,sheet,skeleton,switch,tooltip,sidebar}.tsx`
- Create: `frontend/src/reference/dashboard/use-mobile.ts`
- Create: `frontend/src/reference/dashboard/utils.ts`
- Create: `frontend/public/reference/public-favicon.svg`
- Create: `frontend/public/reference/dashboard-favicon.svg`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/index.html`
- Modify: `frontend/src/styles/fonts.test.ts`
- Test: `frontend/src/styles/referenceSurface.test.tsx`

- [ ] **Step 1: Write RED tests for route-owned global styling**

```tsx
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

it('sets and restores the public/dashboard surface on html', () => {
  const { rerender, unmount } = render(
    <SurfaceBoundary surface="public"><span /></SurfaceBoundary>,
  )
  expect(document.documentElement.dataset.kivouSurface).toBe('public')
  rerender(<SurfaceBoundary surface="dashboard"><span /></SurfaceBoundary>)
  expect(document.documentElement.dataset.kivouSurface).toBe('dashboard')
  unmount()
  expect(document.documentElement).not.toHaveAttribute('data-kivou-surface')
})

it('uses the exact route-owned favicon and dashboard body class', () => {
  const icon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')!
  const original = icon.getAttribute('href')
  const { rerender, unmount } = render(
    <SurfaceBoundary surface="public"><span /></SurfaceBoundary>,
  )
  expect(icon).toHaveAttribute('href', '/reference/public-favicon.svg')
  expect(document.body).not.toHaveClass('antialiased')
  rerender(<SurfaceBoundary surface="dashboard"><span /></SurfaceBoundary>)
  expect(icon).toHaveAttribute('href', '/reference/dashboard-favicon.svg')
  expect(document.body).toHaveClass('antialiased')
  unmount()
  expect(icon.getAttribute('href')).toBe(original)
  expect(document.body).not.toHaveClass('antialiased')
})

it('maps dashboard hrefs while preserving public same-origin hrefs', () => {
  renderApp(<>
    <ReferenceLink dashboard href="/signals?signal=sig_1">open signal</ReferenceLink>
    <ReferenceLink dashboard href="/checkout?plan=pro">checkout</ReferenceLink>
    <ReferenceLink href="/">public home</ReferenceLink>
  </>)
  expect(screen.getByRole('link', { name: 'open signal' })).toHaveAttribute(
    'href', '/app/signals/sig_1',
  )
  expect(screen.getByRole('link', { name: 'public home' })).toHaveAttribute(
    'href', '/',
  )
  expect(screen.getByRole('link', { name: 'checkout' })).toHaveAttribute(
    'href', '/checkout?plan=pro',
  )
})

it('does not retain the legacy no-script landing page', () => {
  const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
  expect(html).not.toContain('LES ENTREPRISES QUI VIENNENT DE GAGNER')
  expect(html).not.toContain('<noscript>')
  expect(html).toContain('Kivou | Signaux commerciaux post-attribution')
})
```

- [ ] **Step 2: Run and observe RED**

Run: `cd frontend && npm test -- --run src/styles/referenceSurface.test.tsx`

Expected: FAIL because both adapters are missing.

- [ ] **Step 3: Implement the synchronous surface boundary**

```tsx
import { useLayoutEffect, type ReactNode } from 'react'

export function SurfaceBoundary({
  surface,
  children,
}: {
  surface: 'public' | 'dashboard'
  children: ReactNode
}) {
  useLayoutEffect(() => {
    const html = document.documentElement
    const previous = html.dataset.kivouSurface
    const bodyHadAntialiased = document.body.classList.contains('antialiased')
    const icon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
    const previousIcon = icon?.getAttribute('href') ?? null
    html.dataset.kivouSurface = surface
    document.body.classList.toggle('antialiased', surface === 'dashboard')
    icon?.setAttribute(
      'href',
      surface === 'public'
        ? '/reference/public-favicon.svg'
        : '/reference/dashboard-favicon.svg',
    )
    return () => {
      if (previous) html.dataset.kivouSurface = previous
      else delete html.dataset.kivouSurface
      document.body.classList.toggle('antialiased', bodyHadAntialiased)
      if (icon && previousIcon) icon.setAttribute('href', previousIcon)
    }
  }, [surface])
  return children
}
```

- [ ] **Step 4: Implement the link mapping in one place**

`ReferenceLink` accepts the reference's `href`. It maps only the approved
dashboard routes when `dashboard` is true; public links pass through unchanged:

```tsx
function dashboardDestination(href: string): string {
  const url = new URL(href, 'https://reference.invalid')
  if (url.pathname === '/') return '/app/dashboard'
  if (url.pathname === '/signals') {
    const signal = url.searchParams.get('signal')
    return signal ? `/app/signals/${encodeURIComponent(signal)}` : '/app/signals'
  }
  if (url.pathname === '/companies') {
    const company = url.searchParams.get('company')
    return company ? `/app/companies/${encodeURIComponent(company)}` : '/app/companies'
  }
  const routes: Record<string, string> = {
    '/targeting': '/app/icps',
    '/settings': '/app/settings',
    '/settings/profile': '/app/settings/profile',
    '/settings/security': '/app/settings/security',
    '/settings/billing': '/app/billing',
    '/settings/notifications': '/app/notifications',
    '/plans': '/app/billing',
    '/billing': '/app/billing',
  }
  return `${routes[url.pathname] ?? url.pathname}${url.search}${url.hash}`
}

import { Link, type LinkProps } from 'react-router-dom'

export function ReferenceLink({
  href,
  dashboard = false,
  ...props
}: Omit<LinkProps, 'to'> & { href: string; dashboard?: boolean }) {
  return <Link to={dashboard ? dashboardDestination(href) : href} {...props} />
}
```

- [ ] **Step 5: Copy the exact styles and required primitives**

First run the verifier. Read each source file completely, then create the
destination with `apply_patch` byte-for-byte before adapting imports. Do not
use `cp`, `cat`, shell redirection, or a generator to write repository files.
`apply_patch` creates every text/SVG file in the reviewable diff; directory
creation alone may use `install -d`:

```bash
cd frontend
node scripts/verify-reference-source.mjs
install -d src/reference/public src/reference/dashboard/vendor \
  src/reference/dashboard/ui public/reference
sha256sum /tmp/kivou-sites-source-public/app/globals.css \
  /tmp/kivou-sites-source-dashboard/app/globals.css \
  /tmp/kivou-sites-source-public/public/favicon.svg \
  /tmp/kivou-sites-source-dashboard/public/favicon.svg
```

The four printed hashes must equal `reference-source.json`. Use
`apply_patch` for this exact source-to-destination map:

```text
/tmp/kivou-sites-source-public/app/globals.css
  -> frontend/src/reference/public/public-reference.css
/tmp/kivou-sites-source-dashboard/app/globals.css
  -> frontend/src/reference/dashboard/dashboard-reference.css
/tmp/kivou-sites-source-dashboard/vendor/shadcn-tailwind-4.13.0.css
  -> frontend/src/reference/dashboard/vendor/shadcn-tailwind-4.13.0.css
/tmp/kivou-sites-source-dashboard/vendor/shadcn-tailwind-4.13.0.LICENSE.md
  -> frontend/src/reference/dashboard/vendor/shadcn-tailwind-4.13.0.LICENSE.md
/tmp/kivou-sites-source-dashboard/components/ui/{button,input,textarea,checkbox,progress,separator,sheet,skeleton,switch,tooltip,sidebar}.tsx
  -> frontend/src/reference/dashboard/ui/{same-name}.tsx
/tmp/kivou-sites-source-dashboard/hooks/use-mobile.ts
  -> frontend/src/reference/dashboard/use-mobile.ts
/tmp/kivou-sites-source-dashboard/lib/utils.ts
  -> frontend/src/reference/dashboard/utils.ts
/tmp/kivou-sites-source-public/public/favicon.svg
  -> frontend/public/reference/public-favicon.svg
/tmp/kivou-sites-source-dashboard/public/favicon.svg
  -> frontend/public/reference/dashboard-favicon.svg
```

Change only import paths in copied TSX files. Do not alter their rendered
elements, classes, variants, or constants.

- [ ] **Step 6: Scope only the two reference stylesheets after Tailwind**

`frontend/postcss.config.mjs`:

```js
import tailwind from '@tailwindcss/postcss'

const surfaceByFile = new Map([
  ['public-reference.css', 'public'],
  ['dashboard-reference.css', 'dashboard'],
  ['shadcn-tailwind-4.13.0.css', 'dashboard'],
])

function scopeReferenceCss() {
  return {
    postcssPlugin: 'scope-kivou-reference-css',
    Rule(rule) {
      const file = rule.source?.input.file ?? ''
      const name = [...surfaceByFile.keys()].find((candidate) => file.endsWith(candidate))
      if (!name) return
      for (let parent = rule.parent; parent; parent = parent.parent) {
        if (parent.type === 'atrule' && /keyframes$/i.test(parent.name)) return
      }
      const prefix = `html[data-kivou-surface="${surfaceByFile.get(name)}"]`
      rule.selectors = rule.selectors.map((selector) => {
        if (selector === ':root' || selector === 'html') return prefix
        if (selector === 'body') return `${prefix} body`
        if (selector.startsWith('html ')) return `${prefix} ${selector.slice(5)}`
        return `${prefix} ${selector}`
      })
    },
  }
}
scopeReferenceCss.postcss = true

export default { plugins: [tailwind(), scopeReferenceCss()] }
```

Update the dashboard CSS vendor import to the new relative path only:

```css
@import "./vendor/shadcn-tailwind-4.13.0.css";
```

In `main.tsx`, replace the legacy global reset import with the non-visual token
definitions, then import both scoped references after the existing font imports:

```ts
import '@fontsource-variable/lora/wght.css'
import '@fontsource-variable/instrument-sans/wght.css'
import './styles/tokens.css'
import './reference/public/public-reference.css'
import './reference/dashboard/dashboard-reference.css'
```

Do not import `styles/global.css`: its inherited body line-height, old link
color, focus ring, and image constraints would leak into both approved
references even when the old CSS-module components are no longer mounted.
Update `fonts.test.ts` to retain both Fontsource assertions and add:

```ts
expect(main).toContain("import './styles/tokens.css'")
expect(main).not.toContain("import './styles/global.css'")
expect(main).toContain("import './reference/public/public-reference.css'")
expect(main).toContain("import './reference/dashboard/dashboard-reference.css'")
```

In `frontend/index.html`, point the initial icon to
`/reference/public-favicon.svg`, use the public reference default title and
description, and remove the complete legacy `<noscript>...</noscript>` block:

```html
<link rel="icon" type="image/svg+xml" href="/reference/public-favicon.svg" />
<meta
  name="description"
  content="Kivou transforme les marchés publics attribués en signaux commerciaux documentés."
/>
<title>Kivou | Signaux commerciaux post-attribution</title>
```

Do not replace it with another invented no-script design.

- [ ] **Step 7: Verify compiled selectors and focused tests**

```bash
cd frontend
npm test -- --run src/styles/referenceSurface.test.tsx
npm run build
rg -n 'data-kivou-surface="(public|dashboard)"' dist/assets/*.css
! rg -n 'body\{[^}]*var\(--kivou-bg-canvas\)|a\{color:var\(--kivou-action-primary\)' \
  dist/assets/*.css
```

Expected: tests and build pass; compiled CSS contains both prefixes; no
unprefixed `.site-header`, `.dashboard-provider`, or reference `body` rule.

- [ ] **Step 8: Commit the presentation foundation**

```bash
git add frontend/postcss.config.mjs frontend/src/reference frontend/src/main.tsx \
  frontend/index.html frontend/src/styles/referenceSurface.test.tsx \
  frontend/src/styles/fonts.test.ts \
  frontend/public/reference/public-favicon.svg \
  frontend/public/reference/dashboard-favicon.svg
git commit -m "feat(frontend): add exact reference presentation foundation"
```

## Task 5: Port the public shell and all public pages exactly

**Files:**
- Modify: `frontend/src/layouts/PublicLayout.tsx`
- Modify: `frontend/src/pages/Landing.tsx`
- Modify: `frontend/src/pages/Product.tsx`
- Modify: `frontend/src/pages/PublicPricing.tsx`
- Modify: `frontend/src/pages/PublicSignalDemo.tsx`
- Modify: `frontend/src/pages/Contact.tsx`
- Modify: `frontend/src/pages/LegalInformation.tsx`
- Delete: `frontend/src/content/marketingCopy.ts`
- Create: `frontend/src/reference/public/PricingResource.tsx`
- Test: `frontend/src/pages/publicReferencePort.test.tsx`
- Modify: `frontend/src/pages/landingHero.test.tsx`
- Modify: `frontend/src/pages/landingHowItWorks.test.tsx`
- Modify: `frontend/src/pages/landingPricing.test.tsx`
- Modify: `frontend/src/pages/publicDemo.test.tsx`
- Modify: `frontend/src/pages/publicLegal.test.tsx`

- [ ] **Step 1: Write RED structural and route tests**

Pin the exact reference class hierarchy, French-only menu, and same-origin CTAs:

```tsx
import { screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, UNAUTHENTICATED, callsTo, mockApi, renderApp } from '../test/harness'

it('renders the exact public reference shell without a locale switch', () => {
  mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
  renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
  const nav = screen.getByRole('navigation', { name: 'Navigation principale' })
  expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual([
    expect.stringContaining('KIVOU'),
    'Accueil',
    'Comment ça marche',
    'Exemple de signal',
    'Tarifs',
    'Contact',
    'Se connecter',
    'Essayer gratuitement',
  ])
  expect(document.querySelector('.site-header .site-nav.container')).not.toBeNull()
  expect(screen.queryByText(/^FR$|^EN$/)).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Se connecter' })).toHaveAttribute('href', '/login')
})

it.each(['/produit', '/tarifs', '/exemple-de-signal', '/contact', '/informations-legales'])(
  'keeps the reference header and footer on %s',
  async (route) => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
    expect(screen.getByRole('banner')).toHaveClass('site-header')
    expect(screen.getByRole('contentinfo')).toHaveClass('site-footer')
    expect(screen.getAllByRole('main')).toHaveLength(1)
  },
)

it.each(['/contact', '/informations-legales'])(
  'does not load the catalogue on non-packaging page %s',
  async (route) => {
    mockApi({})
    renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
    await screen.findByRole('main')
    expect(callsTo('/billing/plans', 'GET')).toHaveLength(0)
  },
)
```

- [ ] **Step 2: Run and observe RED**

Run: `cd frontend && npm test -- --run src/pages/publicReferencePort.test.tsx`

Expected: FAIL on old DOM/classes and the visible locale control.

- [ ] **Step 3: Port the public shell byte-for-byte**

Copy `components/site-shell.tsx` into `PublicLayout.tsx`, then make only these
runtime substitutions:

- replace `next/link` with `ReferenceLink`/React Router `Link`;
- replace external dashboard reference URLs with `/login` and
  `/signup?plan=discovery`;
- replace `children` with `<Outlet />`;
- wrap the resulting fragment in `<SurfaceBoundary surface="public">`;
- retain the exact logo SVG, nav array, class names, footer DOM, and French copy.

The visible result must remain:

```tsx
function activePublicRoute(pathname: string) {
  if (pathname === '/') return 'accueil'
  if (pathname === '/produit') return 'produit'
  if (pathname === '/exemple-de-signal') return 'signal'
  if (pathname === '/tarifs') return 'tarifs'
  if (pathname === '/contact') return 'contact'
  return undefined
}

export function PublicLayout() {
  const { pathname } = useLocation()
  return (
    <SurfaceBoundary surface="public">
      <a className="skip-link" href="#main">Aller au contenu</a>
      <SiteHeader active={activePublicRoute(pathname)} />
      <Outlet />
      <SiteFooter />
    </SurfaceBoundary>
  )
}
```

- [ ] **Step 4: Port the five static public bodies and legal document**

Copy these exact source bodies, remove only `Metadata`, `PageFrame`, and Next
imports, and adapt links through `ReferenceLink`:

```text
/tmp/kivou-sites-source-public/app/page.tsx                    -> Landing.tsx
/tmp/kivou-sites-source-public/app/produit/page.tsx            -> Product.tsx
/tmp/kivou-sites-source-public/app/exemple-de-signal/page.tsx  -> PublicSignalDemo.tsx
/tmp/kivou-sites-source-public/app/contact/page.tsx            -> Contact.tsx
/tmp/kivou-sites-source-public/app/informations-legales/page.tsx -> LegalInformation.tsx
```

Do not rewrite copy or class names. Keep the contact form's exact `mailto:`
action, required fields, encoding, and explanatory text. Keep all legal IDs so
legacy redirects continue to target the same anchors. Replace each removed
Next `Metadata` export with the existing `PublicPageMeta`, using the exact
reference title/description and canonical Kivou path; metadata must not be lost
merely because the runtime is a SPA.

- [ ] **Step 5: Write RED API-authority tests for pricing**

```tsx
it('uses catalogue prices in the exact reference pricing cards and table', async () => {
  const catalogue = {
    ...CATALOGUE,
    plans: CATALOGUE.plans.map((plan) => ({
      ...plan,
      monthly_price:
        plan.plan_code === 'essential'
          ? { chf: { amount_minor_units: 5700, currency: 'chf' as const } }
          : plan.plan_code === 'pro'
            ? { chf: { amount_minor_units: 11300, currency: 'chf' as const } }
            : plan.monthly_price,
    })),
  }
  mockApi({ 'GET /billing/plans': { body: catalogue } })
  renderApp(<AppRoutes />, { route: '/tarifs', session: UNAUTHENTICATED })
  const essential = (await screen.findByRole('heading', { name: 'Essentiel' })).closest('article')!
  expect(within(essential).getByText('CHF')).toBeInTheDocument()
  expect(within(essential).getByText('57')).toBeInTheDocument()
  expect(within(essential).queryByText('49')).not.toBeInTheDocument()
  const pro = screen.getByRole('heading', { name: 'Pro' }).closest('article')!
  expect(within(pro).getByText('113')).toBeInTheDocument()
  expect(document.querySelectorAll('.pricing-grid .price-card')).toHaveLength(4)
})

it('shows an honest same-geometry error when the catalogue is unavailable', async () => {
  mockApi({
    'GET /billing/plans': {
      status: 503,
      body: { detail: { code: 'billing_unavailable' } },
    },
  })
  renderApp(<AppRoutes />, { route: '/tarifs', session: UNAUTHENTICATED })
  expect(await screen.findByRole('alert')).toHaveTextContent('tarifs')
  expect(document.querySelector('.pricing-grid')).not.toBeNull()
  expect(screen.queryByText(/CHF 49|CHF 99|CHF 199/)).not.toBeInTheDocument()
})

it('uses the same catalogue authority in the home offer matrix', async () => {
  const catalogue = {
    ...CATALOGUE,
    plans: CATALOGUE.plans.map((plan) => ({
      ...plan,
      monthly_price: plan.plan_code === 'essential'
        ? { chf: { amount_minor_units: 5700, currency: 'chf' as const } }
        : plan.monthly_price,
    })),
  }
  mockApi({ 'GET /billing/plans': { body: catalogue } })
  renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
  expect(await screen.findByText(/CHF\s+57/)).toBeInTheDocument()
  expect(screen.queryByText('CHF 49')).not.toBeInTheDocument()
})
```

- [ ] **Step 6: Port pricing DOM with server-authoritative values**

Copy the exact `tarifs/page.tsx` composition. Replace only the static `plans`
array and static price cells with a `PricingResource` that loads
`billing.plans()`. Use the same `PricingResource` in `Landing.tsx` for the
`.offer-matrix`; the landing matrix must not retain its three source-example
prices. Map `plan_code`, `recommended`, `purchasable`, entitlements, and
`monthly_price[currency]` into the same card/table slots. Format
`amount_minor_units / 100` only as currency display; never use reference prices
as fallback. Select `chf` when the catalogue exposes it, otherwise the first
catalogue currency; never convert between currencies. Preserve exact feature
copy where it describes entitlements, but
derive every number and purchasable CTA state from the catalogue.
Render only the four public slots `discovery|essential|pro|scale`; never expose
the server-internal/founding offer even if it appears in the catalogue.

The same resource supplies the Discovery `granted_signals` count and
`alert_cadence` wherever the source copy says “3 signaux” or “1 par semaine”
(home hero facts/CTA/matrix, Product final CTA, public-signal final CTA, and
Pricing hero/table/final CTA). With the current API
fixture the visible French remains byte-for-byte equal to the reference; if the
catalogue changes, the sentence changes rather than lying. A catalogue error
keeps the source geometry but removes every packaging number and disables the
signup CTA with the same inline tariff-unavailable alert.

`PricingResource.tsx` provides one catalogue read only on the public pages that
render packaging, plus fixed French formatting:

```tsx
import { useEffect, useState } from 'react'
import { billing } from '../../api/endpoints'
import type { CataloguePlan, Currency, PlanCatalogue } from '../../api/types'

type PricingState =
  | { status: 'loading'; catalogue: null; currency: null }
  | { status: 'error'; catalogue: null; currency: null }
  | { status: 'ready'; catalogue: PlanCatalogue; currency: Currency | null }

export function usePricingResource(): PricingState {
  const [state, setState] = useState<PricingState>({
    status: 'loading', catalogue: null, currency: null,
  })
  useEffect(() => {
    let active = true
    billing.plans().then((catalogue) => {
      if (!active) return
      const currency = catalogue.currencies.includes('chf')
        ? 'chf'
        : catalogue.currencies[0] ?? null
      setState({ status: 'ready', catalogue, currency })
    }).catch(() => {
      if (active) setState({ status: 'error', catalogue: null, currency: null })
    })
    return () => { active = false }
  }, [])
  return state
}

export interface PublicPrice {
  currency: string
  amount: string
}

export function publicPrice(
  plan: CataloguePlan,
  currency: Currency | null,
): PublicPrice | null {
  if (!currency) return null
  const price = plan.monthly_price[currency]
  if (!price) return null
  return {
    currency: price.currency.toUpperCase(),
    amount: new Intl.NumberFormat('fr-CH', {
      minimumFractionDigits: price.amount_minor_units % 100 === 0 ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(price.amount_minor_units / 100),
  }
}
```

Call `usePricingResource()` in `Landing`, `Product`, `PublicSignalDemo`, and
`PublicPricing`. Render `Gratuit` only for the catalogue's `discovery` plan;
a paid plan without a price in the selected catalogue currency renders the
same unavailable slot and no checkout CTA. Contact and Legal must issue no
catalogue request.

CTA rules:

```ts
const href = plan.plan_code === 'discovery'
  ? '/signup?plan=discovery'
  : plan.purchasable
    ? `/signup?plan=${plan.plan_code}`
    : '/contact'
```

- [ ] **Step 7: Verify public behavior and commit**

Before running the suite, replace assertions that encode the superseded
reconstruction:

```text
landingHero.test.tsx
  remove: "localise intégralement la nouvelle promesse en anglais"
  add: public remains the exact French source even with initialLocale="en"

landingHowItWorks.test.tsx
  remove: legacy #comment/#tarifs anchor assertions absent from the source
  keep: the four exact signal-reading steps and both dedicated-page links

landingPricing.test.tsx
  change: ul/li/old PlanGrid selectors to .pricing-grid/.price-card and
          .offer-matrix while preserving API-only price/recommended assertions

publicDemo.test.tsx
  replace: all prior reconstructed-panel ordering assertions with the exact
           source h1, .signal-layout, .signal-detail-card, source link,
           limitation copy, and same-origin CTA assertions; permit only the
           public `/billing/plans` read used to keep Discovery packaging true

publicLegal.test.tsx
  remove: public-language switching and English rendering assertions
  keep: complete validated French clauses, canonical anchors, redirects,
        focus restoration, metadata, and contact form contract
```

The replacement expectations are the exact DOM/classes already pinned in
Steps 1, 4, 5, and 6; do not alter source DOM to satisfy an old test.

Delete `marketingCopy.ts` after every public component has switched to the
pinned French source. Its bilingual public reconstruction is superseded; the
connected English dictionary remains in `i18n/en.ts` and is unrelated.

```bash
cd frontend
npm test -- --run src/pages/publicReferencePort.test.tsx \
  src/pages/landingHero.test.tsx src/pages/landingHowItWorks.test.tsx \
  src/pages/landingPricing.test.tsx src/pages/publicDemo.test.tsx \
  src/pages/publicLegal.test.tsx
npm run typecheck
cd ..
git add frontend/src/layouts/PublicLayout.tsx \
  frontend/src/pages/Landing.tsx frontend/src/pages/Product.tsx \
  frontend/src/pages/PublicPricing.tsx frontend/src/pages/PublicSignalDemo.tsx \
  frontend/src/pages/Contact.tsx frontend/src/pages/LegalInformation.tsx \
  frontend/src/pages/publicReferencePort.test.tsx \
  frontend/src/reference/public/PricingResource.tsx \
  frontend/src/pages/landingHero.test.tsx \
  frontend/src/pages/landingHowItWorks.test.tsx \
  frontend/src/pages/landingPricing.test.tsx \
  frontend/src/pages/publicDemo.test.tsx frontend/src/pages/publicLegal.test.tsx
git add frontend/src/content/marketingCopy.ts
git commit -m "feat(frontend): port exact public reference"
```

Expected: focused public tests and typecheck pass.

## Task 6: Port auth, onboarding, and checkout surfaces without changing actions

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/layouts/AuthLayout.tsx`
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/pages/Signup.tsx`
- Modify: `frontend/src/pages/PasswordReset.tsx`
- Modify: `frontend/src/pages/Onboarding.tsx`
- Modify: `frontend/src/pages/Checkout.tsx`
- Delete: `frontend/src/pages/DashboardDemoCapture.tsx`
- Delete: `frontend/src/pages/DashboardDemoCapture.module.css`
- Delete: `frontend/src/components/HeroSignalCarousel.tsx`
- Delete: `frontend/src/components/HeroSignalCarousel.module.css`
- Delete: `frontend/src/components/PublicSignalPreview.tsx`
- Delete: `frontend/src/components/PublicSignalPreview.module.css`
- Delete: `frontend/src/content/landingDashboardDemo.ts`
- Delete: `frontend/src/content/landingHeroSignals.ts`
- Delete: `frontend/src/content/legalContent.ts`
- Delete: `frontend/src/content/publicDemoSignal.ts`
- Create: `frontend/src/billing/planRoute.ts`
- Create: `frontend/src/reference/dashboard/targetingInput.ts`
- Create: `frontend/src/reference/dashboard/AuthShell.tsx`
- Create: `frontend/src/reference/dashboard/AuthFlow.tsx`
- Create: `frontend/src/reference/dashboard/PasswordField.tsx`
- Create: `frontend/src/reference/dashboard/OnboardingFlow.tsx`
- Create: `frontend/src/reference/dashboard/CheckoutHandoff.tsx`
- Create: `frontend/src/reference/dashboard/SystemState.tsx`
- Modify: `frontend/src/auth/auth.test.tsx`
- Test: `frontend/src/auth/referenceAuthFlow.test.tsx`

- [ ] **Step 1: Write RED route and mutation tests**

Pin the exact reference shell classes while retaining existing API calls:

```tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { planFromSearch } from '../billing/planRoute'
import {
  DISCOVERY_STATUS, ICP, ME, LOCKED_ITEM, UNAUTHENTICATED, UNLOCKED_ITEM,
  feedPage, mockApi, renderApp,
} from '../test/harness'

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

it('logs in through the reference form and opens overview', async () => {
  const user = userEvent.setup()
  mockApi({
    'POST /auth/login': (request) => {
      expect(request.body).toEqual({
        email: 'test@example.test', password: 'correct-password',
      })
      return { body: ME }
    },
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /notification-preferences': {
      body: {
        email_enabled: false,
        notification_email: null,
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/login', session: UNAUTHENTICATED })
  expect(document.querySelector('.auth-shell')).not.toBeNull()
  await user.type(screen.getByLabelText(/adresse/i), 'test@example.test')
  await user.type(screen.getByLabelText(/mot de passe/i), 'correct-password')
  await user.click(screen.getByRole('button', { name: /se connecter/i }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeVisible()
})

it('submits signup to the existing API without demo storage', async () => {
  const user = userEvent.setup()
  mockApi({
    'POST /auth/signup': (request) => {
      expect(request.body).toEqual({
        company_name: 'Entreprise Test',
        email: 'test@example.test',
        password: 'correct-password',
        locale: 'fr',
      })
      return { status: 201, body: { ...ME, onboarding_status: 'account_created' } }
    },
  })
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  renderApp(<><AppRoutes /><LocationProbe /></>, {
    route: '/signup?plan=discovery', session: UNAUTHENTICATED,
  })
  await user.type(screen.getByLabelText('Entreprise'), 'Entreprise Test')
  await user.type(screen.getByLabelText('Adresse e-mail professionnelle'), 'test@example.test')
  await user.type(screen.getByLabelText(/^Mot de passe$/), 'correct-password')
  await user.type(screen.getByLabelText('Confirmer le mot de passe'), 'correct-password')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: /continuer vers le ciblage/i }))
  expect(await screen.findByText('Première configuration')).toBeVisible()
  expect(screen.getByTestId('location')).toHaveTextContent('/onboarding?plan=discovery')
  expect(storage).not.toHaveBeenCalled()
})

it('carries a paid catalogue choice from signup to onboarding without storage', async () => {
  const user = userEvent.setup()
  mockApi({
    'POST /auth/signup': { status: 201, body: ME },
  })
  const storage = vi.spyOn(Storage.prototype, 'setItem')
  renderApp(<><AppRoutes /><LocationProbe /></>, {
    route: '/signup?plan=pro', session: UNAUTHENTICATED,
  })
  await user.type(screen.getByLabelText('Entreprise'), 'Entreprise Test')
  await user.type(screen.getByLabelText('Adresse e-mail professionnelle'), 'test@example.test')
  await user.type(screen.getByLabelText(/^Mot de passe$/), 'correct-password')
  await user.type(screen.getByLabelText('Confirmer le mot de passe'), 'correct-password')
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: /continuer vers le ciblage/i }))
  expect(screen.getByTestId('location')).toHaveTextContent('/onboarding?plan=pro')
  expect(storage).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run and observe RED**

Run: `cd frontend && npm test -- --run src/auth/referenceAuthFlow.test.tsx`

Expected: FAIL on the reference shell/classes.

- [ ] **Step 3: Move auth routes outside the public shell**

In `App.tsx`, keep public content under `PublicLayout`, but place `/login`,
`/signup`, `/forgot-password`, `/reset-password`, `/onboarding`, and checkout
return routes under the dashboard surface/auth layouts. Preserve
`RedirectIfAuthenticated` and `RequireAuth` boundaries exactly.

Remove the `DashboardDemoCapture` import and the complete
`import.meta.env.DEV` capture route. The approved dashboard reference replaces
that earlier reconstruction even in local development. Delete the enumerated
demo page/components/content after the Task 5 tests no longer import them; they
must not survive as a second dormant frontend implementation. The route
skeleton is:

```tsx
<Routes>
  <Route element={<PublicLayout />}>
    <Route index element={<Landing />} />
    <Route path="produit" element={<Product />} />
    <Route path="tarifs" element={<PublicPricing />} />
    <Route path="exemple-de-signal" element={<PublicSignalDemo />} />
    <Route path="contact" element={<Contact />} />
    <Route path="informations-legales" element={<LegalInformation />} />
    <Route path="mentions-legales" element={<Navigate to="/informations-legales#mentions-legales" replace />} />
    <Route path="confidentialite" element={<Navigate to="/informations-legales#confidentialite" replace />} />
    <Route path="cgu" element={<Navigate to="/informations-legales#cgu" replace />} />
    <Route path="*" element={<NotFound />} />
  </Route>
  <Route element={<DashboardSurface />}>
    <Route element={<RedirectIfAuthenticated />}>
      <Route path="login" element={<Login />} />
      <Route path="signup" element={<Signup />} />
    </Route>
    <Route path="forgot-password" element={<ForgotPassword />} />
    <Route path="reset-password" element={<ResetPassword />} />
    <Route element={<RequireAuth />}>
      <Route path="onboarding" element={<Onboarding />} />
      <Route path="checkout" element={<Checkout />} />
      <Route path="app" element={<AppShell />}>
        <Route index element={<Navigate to="/app/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="signals" element={<SignalsFeed />} />
        <Route path="signals/:signalKey" element={<SignalsFeed />} />
        <Route path="companies" element={<Companies />} />
        <Route path="companies/:companyKey" element={<Companies />} />
        <Route path="icps" element={<Icps />} />
        <Route path="billing" element={<Billing />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="settings" element={<Settings />} />
        <Route path="internal/cockpit" element={<CommercialCockpit />} />
      </Route>
      <Route path="checkout/success" element={<CheckoutSuccess />} />
      <Route path="checkout/cancel" element={<CheckoutCancel />} />
      <Route path="billing/success" element={<Navigate to="/checkout/success" replace />} />
      <Route path="billing/cancel" element={<Navigate to="/checkout/cancel" replace />} />
      <Route path="billing" element={<Navigate to="/app/billing" replace />} />
    </Route>
  </Route>
</Routes>

function DashboardSurface() {
  return <SurfaceBoundary surface="dashboard"><Outlet /></SurfaceBoundary>
}
```

- [ ] **Step 4: Copy the exact reference compositions and wire existing handlers**

Retain the reference DOM/classes/labels. Replace only:

- local demo login/signup with `auth.login`/`auth.signup` and `session.adopt`;
- local onboarding storage with `icps.create`/`icps.update` and
  `session.refresh`;
- demo checkout with `billing.checkout`, using the query-string plan and
  server-returned `checkout_url`;
- demo notices with honest loading/error copy in the same reference notice box;
- Next navigation with React Router.

No component may write a key containing `demo`, `plan`, `target`, `workflow`,
or `account` to localStorage.

Carry the selected plan only in the URL. Parse `plan` against
`discovery|essential|pro|scale`; an absent or unknown value becomes
`discovery`. Signup navigates to `/onboarding?plan=<code>`. After the ICP create
and authoritative session refresh, onboarding navigates to `/app/signals` for
Discovery and `/checkout?plan=<code>` for a paid plan. `CheckoutHandoff` loads
`/billing/plans`, proves that the code is currently purchasable, and only then
calls the existing `billing.checkout({ plan, currency })`; it navigates to the
server-returned Stripe TEST URL exactly as the existing billing page does.
Neither query state nor a successful POST is persisted in browser storage.

Use this shared parser in all three pages:

```ts
import type { PlanCode } from '../api/types'

const ROUTABLE_PLANS: readonly PlanCode[] = [
  'discovery', 'essential', 'pro', 'scale',
]

export function planFromSearch(search: string): PlanCode {
  const candidate = new URLSearchParams(search).get('plan')
  return ROUTABLE_PLANS.includes(candidate as PlanCode)
    ? candidate as PlanCode
    : 'discovery'
}

export function planSearch(plan: PlanCode): string {
  return `?plan=${encodeURIComponent(plan)}`
}
```

Pin it in `referenceAuthFlow.test.tsx`:

```ts
expect(planFromSearch('?plan=pro')).toBe('pro')
expect(planFromSearch('?plan=founding')).toBe('discovery')
expect(planFromSearch('?plan=unknown')).toBe('discovery')
expect(planFromSearch('')).toBe('discovery')
```

Use one fail-closed mapper for onboarding and Account targeting:

```ts
import { BUYER_TRADES, OFFER_KINDS } from '../../api/types'
import type {
  BuyerTrade, OfferKind, TargetIcpInput,
} from '../../api/types'
import { MVP_THRESHOLD_CURRENCIES, MVP_TERRITORIES } from '../../api/capabilities'
import type { Dictionary } from '../../i18n/fr'

export type TargetingField = 'offers' | 'buyer_trades' | 'territories' | 'threshold'

export class UnknownTargetingToken extends Error {
  constructor(readonly field: TargetingField, readonly token: string) {
    super(`${field}: ${token}`)
  }
}

export interface ReferenceTargetingDraft {
  name: string
  offer: string
  precision: string
  companies: string
  territory: string
  terms: string
  minAmount: string
  currency: string
}

const normalized = (value: string) => value.trim().toLocaleLowerCase('fr')
const tokens = (value: string) =>
  [...new Set(value.split(',').map((item) => item.trim()).filter(Boolean))]

function resolveCodes<T extends string>(
  raw: string,
  field: TargetingField,
  codes: readonly T[],
  labels: Record<T, string>,
): T[] {
  const lookup = new Map<string, T>()
  for (const code of codes) {
    lookup.set(normalized(code), code)
    lookup.set(normalized(labels[code]), code)
  }
  return tokens(raw).map((token) => {
    const code = lookup.get(normalized(token))
    if (!code) throw new UnknownTargetingToken(field, token)
    return code
  })
}

export function toTargetIcpPayload(
  draft: ReferenceTargetingDraft,
  dictionary: Dictionary,
  previous?: TargetIcpInput,
): { label: string; customer_input: TargetIcpInput } {
  // The connected locale chooses labels before this function is called. Add
  // both language labels to the lookup without guessing any prose.
  const territoryLookup = new Map<string, string>()
  for (const item of MVP_TERRITORIES) {
    for (const value of [item.code, item.fr, item.en]) {
      territoryLookup.set(normalized(value), item.code)
    }
  }
  const territories = tokens(draft.territory).map((token) => {
    const code = territoryLookup.get(normalized(token))
    if (!code) throw new UnknownTargetingToken('territories', token)
    return code
  })
  const currency = draft.currency.trim().toUpperCase()
  const minimum = Number(draft.minAmount)
  if (!MVP_THRESHOLD_CURRENCIES.includes(currency) || !Number.isFinite(minimum) || minimum < 0) {
    throw new UnknownTargetingToken('threshold', `${draft.minAmount} ${draft.currency}`.trim())
  }
  const offer = draft.offer.trim()
  const precision = draft.precision.trim()
  return {
    label: draft.name.trim(),
    customer_input: {
      offer_summary: precision ? `${offer}\n\n${precision}` : offer,
      offers: resolveCodes<OfferKind>(draft.terms, 'offers', OFFER_KINDS, dictionary.offers),
      secondary_offers: previous?.secondary_offers ?? [],
      buyer_trades: resolveCodes<BuyerTrade>(
        draft.companies, 'buyer_trades', BUYER_TRADES, dictionary.trades,
      ),
      secondary_buyer_trades: previous?.secondary_buyer_trades ?? [],
      territories,
      minimum_contract_value: {
        currency,
        minimum_amount: minimum,
        maximum_amount: previous?.minimum_contract_value?.maximum_amount ?? null,
      },
    },
  }
}
```

The reference onboarding fields do not directly expose Kivou's enum contracts.
Keep their exact visible DOM, but parse only explicit comma-separated localized
labels or machine codes: `Mots-clés à surveiller` maps to `OFFER_KINDS`,
`Entreprises recherchées` maps to `BUYER_TRADES`, and `Territoire couvert` maps
to `MVP_TERRITORIES`. Unknown tokens produce an inline field error and no API
call; never infer a category from prose. `Produits et services proposés` and
the optional `Précision utile` are two visible parts of one backend field:
`offer_summary` is the first trimmed value alone when the optional value is
empty, otherwise `${offer.trim()}\n\n${summary.trim()}`. This preserves both
user texts without inventing a backend field. The threshold maps verbatim to
`minimum_contract_value`. Pin these mappings in `onboarding.test.tsx`.

- [ ] **Step 5: Verify all auth/onboarding/checkout tests and commit**

Update `auth.test.tsx` only for the approved reference labels/composition and
the new rule that auth remains French even when an account/browser locale is
English. Preserve its session redirect, password validation, enumeration-safe
errors, exact signup payload, onboarding redirect, logout, and reset contracts.

```bash
cd frontend
npm test -- --run src/auth src/pages/onboarding.test.tsx \
  src/billing/checkoutFlow.test.tsx src/billing/checkoutIntent.test.ts \
  src/billing/paywallContinuity.test.tsx
npm run typecheck
cd ..
git add frontend/src/App.tsx frontend/src/layouts/AuthLayout.tsx \
  frontend/src/pages/Login.tsx frontend/src/pages/Signup.tsx \
  frontend/src/pages/PasswordReset.tsx frontend/src/pages/Onboarding.tsx \
  frontend/src/pages/Checkout.tsx frontend/src/reference/dashboard
git add frontend/src/billing/planRoute.ts \
  frontend/src/reference/dashboard/targetingInput.ts \
  frontend/src/auth/referenceAuthFlow.test.tsx frontend/src/auth/auth.test.tsx \
  frontend/src/pages/onboarding.test.tsx \
  frontend/src/billing/checkoutFlow.test.tsx \
  frontend/src/billing/checkoutIntent.test.ts \
  frontend/src/billing/paywallContinuity.test.tsx
git add frontend/src/pages/DashboardDemoCapture.tsx \
  frontend/src/pages/DashboardDemoCapture.module.css \
  frontend/src/components/HeroSignalCarousel.tsx \
  frontend/src/components/HeroSignalCarousel.module.css \
  frontend/src/components/PublicSignalPreview.tsx \
  frontend/src/components/PublicSignalPreview.module.css \
  frontend/src/content/landingDashboardDemo.ts \
  frontend/src/content/landingHeroSignals.ts frontend/src/content/legalContent.ts \
  frontend/src/content/publicDemoSignal.ts
git commit -m "feat(frontend): port exact connected entry flows"
```

## Task 7: Create truthful view models and the exact connected shell

**Files:**
- Create: `frontend/src/reference/dashboard/models.ts`
- Create: `frontend/src/reference/dashboard/adapters.ts`
- Create: `frontend/src/reference/dashboard/resources.ts`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: `frontend/src/i18n/index.tsx`
- Test: `frontend/src/reference/dashboard/adapters.test.ts`
- Test: `frontend/src/layouts/appShellReference.test.tsx`

- [ ] **Step 1: Write RED pure-adapter tests**

Define fixtures using current `FeedPage`, `UnlockedDetail`, `LockedFeedItem`,
`TargetIcp`, `BillingStatus`, and `CompanyProfile` contracts. Assert:

```ts
expect(toSignalCard(UNLOCKED_FEED_ITEM)).toEqual({
  id: UNLOCKED_FEED_ITEM.signal_id,
  locked: false,
  companyName: UNLOCKED_FEED_ITEM.company.name,
  eventTitle: UNLOCKED_FEED_ITEM.contract.title,
  amount: UNLOCKED_FEED_ITEM.contract.amount,
  location: UNLOCKED_FEED_ITEM.contract.location,
  eventDate: UNLOCKED_FEED_ITEM.event.date,
  matchLabel: UNLOCKED_FEED_ITEM.analysis.fit.label,
  whyNow: UNLOCKED_FEED_ITEM.event.why_now,
})
expect(toSignalCard(LOCKED_FEED_ITEM).companyName).toBeNull()
expect(toSignalCard(LOCKED_FEED_ITEM).locked).toBe(true)
expect(toSignalDetailView(UNLOCKED_DETAIL).facts.sourceUrl).toBe(
  UNLOCKED_DETAIL.source.url,
)
```

Add negative assertions that no returned string contains a fixed reference
company, `Compte démo`, or `Mode démonstration`.

- [ ] **Step 2: Define narrow presentation models**

`models.ts` must define nullable fields rather than fabricated strings. Include:

```ts
export interface SignalCardView {
  id: string
  locked: boolean
  companyName: string | null
  eventTitle: string | null
  amount: Money | null
  location: Place | null
  eventDate: string | null
  matchLabel: string | null
  whyNow: string
}

export interface SignalDetailView {
  id: string
  title: string | null
  companyName: string | null
  companyKey: string | null
  summary: string | null
  brief: {
    whyNow: string
    offerCoverage: string | null
    functionToFind: string | null
    unknown: string | null
  }
  facts: {
    amount: Money | null
    concludedAt: string | null
    execution: string | null
    buyer: string | null
    notice: string | null
    cpv: string | null
    sourceUrl: string | null
  }
  scope: { value: string; label: string }[]
  questions: string[]
}
```

- [ ] **Step 3: Implement pure adapters with one missing-value rule**

Use `null` in models for absent API fields. Rendering components alone convert
`null` to the localized `Non publié`; adapters must never emit invented copy.
Map backend-authored `event.headline`, `event.why_now`, `analysis` statements,
and evidence excerpts verbatim.

- [ ] **Step 4: Write RED connected-shell tests**

```tsx
it('renders the exact five-item shell with real account values', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /notification-preferences': {
      body: {
        email_enabled: false,
        notification_email: null,
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })
  await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })
  for (const label of [
    'Vue d’ensemble', 'Signaux', 'Entreprises', 'Profil de ciblage', 'Compte',
  ]) expect(screen.getByRole('link', { name: label })).toBeVisible()
  expect(document.querySelector('.dashboard-provider .kivou-sidebar')).not.toBeNull()
  expect(screen.getByText(ME.account_display_name)).toBeVisible()
  expect(screen.queryByText(/Compte démo|Mode démonstration/)).not.toBeInTheDocument()
})

it('keeps public routes French and applies account locale only to connected routes', async () => {
  const englishSession = {
    status: 'authenticated' as const,
    me: { ...ME, locale: 'en' as const },
  }
  const { unmount } = renderApp(<AppRoutes />, { route: '/', session: englishSession })
  expect(screen.getByRole('link', { name: 'Comment ça marche' })).toBeVisible()
  expect(document.documentElement.lang).toBe('fr')
  unmount()

  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /notification-preferences': {
      body: {
        email_enabled: false,
        notification_email: null,
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/dashboard', session: englishSession })
  expect(await screen.findByRole('link', { name: 'Overview' })).toBeVisible()
  expect(document.documentElement.lang).toBe('en')
})
```

- [ ] **Step 5: Port the shell exactly and substitute real labels**

Copy `kivou-dashboard-shell.tsx` and `kivou-brand.tsx`. Replace only:

- `children` with `<Outlet />`;
- reference links with `ReferenceLink`;
- fixed `profileLabel` with the first active ICP label plus its first territory;
- fixed account name/initials with `useCurrentUser()`;
- `Mode démonstration` with the backend billing plan label in the same badge;
- title selection with `useLocation()` for the mapped `/app` routes.

Keep the exact sidebar components, 240px width, class names, icon order, mobile
offcanvas behavior, and topbar DOM. Wrap it in
`<SurfaceBoundary surface="dashboard">`.

Derive the reference active view/title from the canonical route only:

```ts
function connectedLocation(pathname: string) {
  if (pathname === '/app/dashboard') return { active: 'overview', title: t.reference.overview }
  if (pathname.startsWith('/app/signals')) return { active: 'signals', title: t.reference.signals }
  if (pathname.startsWith('/app/companies')) return { active: 'companies', title: t.reference.companies }
  if (pathname.startsWith('/app/icps')) return { active: 'target', title: t.reference.targeting }
  return { active: 'settings', title: t.reference.account }
}
```

Billing, notifications, and every `/app/settings/*` child therefore highlight
`Compte`. The internal cockpit keeps its route and capabilities guard; it may
use the settings active item but none of its data or actions are changed.

Move every connected reference string into one `reference` dictionary subtree.
The French values must be copied byte-for-byte from the pinned source; add the
corresponding English values with the same keys. Components call `useI18n()` but
do not change their visible French DOM. Add the five navigation labels, all
page headings, field labels, statuses, missing-value copy, and local error/save
messages to both dictionaries; `boundary.test.tsx` must assert identical key
shape.

Public rendering must never follow `navigator.language` or an authenticated
account locale. Initialize `I18nProvider` with French when no explicit test
locale is supplied, and make `LocaleFollowsAccount` route-aware:

```tsx
const PUBLIC_PATHS = new Set([
  '/', '/produit', '/tarifs', '/exemple-de-signal', '/contact',
  '/informations-legales', '/mentions-legales', '/confidentialite', '/cgu',
  '/login', '/signup', '/forgot-password', '/reset-password',
])

function LocaleFollowsAccount() {
  const { pathname } = useLocation()
  const { state } = useSession()
  const { locale, setLocale } = useI18n()
  const connected = !PUBLIC_PATHS.has(pathname)
  const wanted = connected && state.status === 'authenticated'
    ? accountLocale(state.me) ?? 'fr'
    : 'fr'

  useEffect(() => {
    if (wanted !== locale) setLocale(wanted)
    else document.documentElement.lang = wanted
  }, [wanted, locale, setLocale])
  return null
}
```

In `I18nProvider`, replace `initialLocale ?? preferredLocale()` with
`initialLocale ?? 'fr'` and remove the now-unused browser preference helper.

- [ ] **Step 6: Verify and commit adapters/shell**

Keep the complete `/app` child tree pinned in Task 6. In particular, both the
list and deep company routes render `Companies`, which owns the exact reference
master/detail composition; `CompanyProfile` becomes its detail child and never
renders a competing standalone page. Preserve the internal cockpit route
unchanged. Task 10 adds the two account subroutes only when their components
exist.

```bash
cd frontend
npm test -- --run src/reference/dashboard/adapters.test.ts \
  src/layouts/appShellReference.test.tsx src/api/boundary.test.tsx
npm run typecheck
cd ..
git add frontend/src/reference/dashboard frontend/src/layouts/AppShell.tsx \
  frontend/src/App.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts \
  frontend/src/i18n/index.tsx
git commit -m "feat(frontend): port exact connected shell"
```

## Task 8: Port Overview and Signals with real data, paywall, and notes

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`
- Modify: `frontend/src/pages/SignalDetail.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/pages/dashboard.test.tsx`
- Test: `frontend/src/pages/referenceDashboardData.test.tsx`
- Test: `frontend/src/signals/referenceSignalWorkspace.test.tsx`

- [ ] **Step 1: Write RED Overview tests**

Assert `/app/dashboard` opens the exact Overview, not the signal workspace:

```tsx
it('opens the reference overview at /app/dashboard with only real API values', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /notification-preferences': {
      body: {
        email_enabled: false,
        notification_email: null,
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })
  expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeVisible()
  expect(screen.getByRole('heading', { level: 2, name: /attributions documentées/i })).toBeVisible()
  expect(screen.getByText(UNLOCKED_ITEM.contract.title!)).toBeVisible()
  expect(document.querySelector('.overview-focus-grid .priority-card')).not.toBeNull()
  expect(document.querySelector('.workspace-grid')).toBeNull()
})
```

- [ ] **Step 2: Port Overview composition**

Copy `overview-page.tsx` and `target-profile-snapshot.tsx`, remove their shell
wrapper, and replace `awardSignals`/`prioritySignal` with adapter output from
`GET /signals`, `GET /target-icps`, and `GET /billing/status`. The first real
unlocked item is the priority card. If none exists, render the reference card
geometry as an honest empty/locked state; do not promote a locked item into a
fake unlocked detail.

- [ ] **Step 3: Write RED Signals access and route tests**

```tsx
it('uses the exact reference workspace and never fetches locked detail', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /billing/plans': { body: CATALOGUE },
  })
  const user = userEvent.setup()
  renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })
  await user.click(await screen.findByRole('button', { name: /accessible avec/i }))
  expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  expect(await screen.findByRole('heading', { level: 1, name: 'Facturation' })).toBeVisible()
})

it('deep-links selected real signal at /app/signals/:id', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  })
  renderApp(<AppRoutes />, {
    route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    session: AUTHENTICATED,
  })
  expect(await screen.findByRole('heading', { level: 2, name: UNLOCKED_ITEM.contract.title! })).toBeVisible()
  expect(document.querySelector('.workspace-grid .feed-panel + .detail-panel')).not.toBeNull()
})
```

- [ ] **Step 4: Port exact Signals DOM and route selection**

Copy `signals-page.tsx`, remove demo plan/localStorage/workflow imports and the
shell wrapper, and substitute:

- `awardSignals` with `FeedPage.items` mapped to `SignalCardView`;
- selected query-string state with `useParams()` and `navigate()`;
- demo plan limit with each item's backend `locked` value;
- demo detail with `GET /signals/{id}` only after the selected feed item is
  confirmed unlocked;
- fixed detail sections with `SignalDetailView` values;
- missing values with localized `Non publié` in the same slots;
- source/company actions with real `source.url` and `company_key` only.

Keep the exact `.workspace-grid`, `.feed-panel`, `.signal-item`, `.detail-panel`,
brief, facts, questions, company, and note DOM/classes.

- [ ] **Step 5: Add the typed note client and RED autosave test**

Add to `api/types.ts`:

```ts
export interface SignalNote {
  signal_id: string
  note: string | null
  updated_at: string | null
}
```

Add to `api/endpoints.ts`:

```ts
export const signalNotes = {
  read: (signalKey: string) =>
    request<SignalNote>(`/signals/${encodeURIComponent(signalKey)}/note`),
  write: (signalKey: string, note: string) =>
    request<SignalNote>(`/signals/${encodeURIComponent(signalKey)}/note`, {
      method: 'PUT', body: { note },
    }),
}
```

Test debounced write, local save state, and error honesty:

```tsx
vi.useFakeTimers()
const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
await user.type(screen.getByLabelText('Note sur ce signal'), 'Appeler lundi')
await vi.advanceTimersByTimeAsync(600)
expect(noteWrites).toEqual([{ note: 'Appeler lundi' }])
expect(await screen.findByText('Note enregistrée')).toBeVisible()
```

- [ ] **Step 6: Implement note loading and 500ms autosave**

Read only for an unlocked selected signal. Keep list/detail available if the
note request fails. On edit, show `Enregistrement…`, debounce 500ms, PUT the
exact textarea value, then show `Note enregistrée`; on failure show an inline
error plus `Réessayer` in the existing note footer. Cancel stale timers and
ignore stale responses when the selected signal changes.

- [ ] **Step 7: Verify Signals and Overview, then commit**

Update `dashboard.test.tsx` rather than deleting it. Preserve its existing
behavioral assertions for independent loading/retry, stale-response rejection,
locked-detail privacy, company authorization, session expiry, navigation
history, locale parity, backend billing authority, and browser-storage
privacy. Replace only selectors/copy tied to the superseded light dashboard:
summary metrics become the exact Overview cards, old feed rows become
`.signal-item`, old company rows become `.company-list-item`, and every route
heading/menu assertion uses the five-item reference shell. Do the same for old
DOM-only assertions in `feed.test.tsx`, `detail.test.tsx`, and
`signalWorkspace.test.tsx`; never change the reference port to satisfy an old
class name.

```bash
cd frontend
npm test -- --run src/pages/referenceDashboardData.test.tsx \
  src/signals/referenceSignalWorkspace.test.tsx src/pages/dashboard.test.tsx \
  src/signals/feed.test.tsx \
  src/signals/detail.test.tsx src/signals/signalWorkspace.test.tsx \
  src/billing/paywallContinuity.test.tsx
npm run typecheck
cd ..
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/SignalsFeed.tsx \
  frontend/src/pages/SignalDetail.tsx frontend/src/api/types.ts \
  frontend/src/api/endpoints.ts frontend/src/reference/dashboard \
  frontend/src/pages/dashboard.test.tsx frontend/src/signals/feed.test.tsx \
  frontend/src/signals/detail.test.tsx frontend/src/signals/signalWorkspace.test.tsx
git commit -m "feat(frontend): connect exact overview and signal workspace"
```

## Task 9: Port Companies and Targeting without crossing access boundaries

**Files:**
- Modify: `frontend/src/pages/Companies.tsx`
- Modify: `frontend/src/pages/CompanyProfile.tsx`
- Modify: `frontend/src/pages/Icps.tsx`
- Test: `frontend/src/companies/referenceCompanies.test.tsx`
- Test: `frontend/src/pages/referenceTargeting.test.tsx`

- [ ] **Step 1: Write RED company privacy tests**

```tsx
it('resolves companies only through unlocked signal details', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  })
  renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
  await screen.findByRole('heading', { name: 'Entreprises' })
  expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
  expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(1)
})
```

- [ ] **Step 2: Port exact Companies list/detail**

Copy `companies-page.tsx`, remove demo data and shell wrapper, and feed it only
with companies resolved from unlocked detail responses. Preserve exact
`.companies-layout`, company list, profile card, facts, and related-signals DOM.
`/app/companies/:companyKey` may request the company only if the key was returned
by one of this account's accessible signal details; otherwise show the same
honest unavailable card and do not issue the company request.

- [ ] **Step 3: Write RED targeting data/action tests**

```tsx
it('maps only explicit reference-form tokens to the existing ICP contract', async () => {
  const user = userEvent.setup()
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    [`PATCH /target-icps/${ICP.target_icp_id}`]: (request) => {
      const body = request.body as { label: string; customer_input: TargetIcpInput }
      return { body: { ...ICP, label: body.label, customer_input: body.customer_input } }
    },
  })
  renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
  await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
  await user.clear(screen.getByLabelText('Ce que vous vendez'))
  await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats et enrobés')
  await user.clear(screen.getByLabelText('Entreprises recherchées'))
  await user.type(screen.getByLabelText('Entreprises recherchées'), 'roads_and_civil_works')
  await user.clear(screen.getByLabelText('Territoire commercial'))
  await user.type(screen.getByLabelText('Territoire commercial'), 'FR')
  await user.clear(screen.getByLabelText('Mots-clés surveillés'))
  await user.type(screen.getByLabelText('Mots-clés surveillés'), 'materials_and_components')
  await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
  expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')[0].body).toEqual({
    label: ICP.label,
    customer_input: {
      ...ICP.customer_input,
      offer_summary: 'Granulats et enrobés',
      offers: ['materials_and_components'],
      buyer_trades: ['roads_and_civil_works'],
      territories: ['FR'],
    },
  })
})

it('rejects an unknown free-text category without calling the API', async () => {
  const user = userEvent.setup()
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  })
  renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
  await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
  await user.clear(screen.getByLabelText('Mots-clés surveillés'))
  await user.type(screen.getByLabelText('Mots-clés surveillés'), 'catégorie inventée')
  await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('catégorie')
  expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(0)
})
```

- [ ] **Step 4: Port exact Targeting composition**

Copy `targeting-page.tsx`, remove demo localStorage and fixed `awardSignals`, and
bind the reference inputs to existing ICP create/update handlers. Keep the
reference progress, summary, offer, trade, territory, and budget layout. Keep
backend `plan_limit` and errors authoritative. Never synthesize a profile from
signal content.

Use the same fail-closed token parser defined for onboarding in Task 6. Existing
secondary offer/trade arrays remain unchanged unless their exact machine code is
entered; prose is never converted heuristically.

- [ ] **Step 5: Verify and commit Companies/Targeting**

```bash
cd frontend
npm test -- --run src/companies/referenceCompanies.test.tsx \
  src/companies/companyProfile.test.tsx \
  src/pages/referenceTargeting.test.tsx src/pages/onboarding.test.tsx
npm run typecheck
cd ..
git add frontend/src/pages/Companies.tsx frontend/src/pages/CompanyProfile.tsx \
  frontend/src/pages/Icps.tsx frontend/src/reference/dashboard \
  frontend/src/companies/companyProfile.test.tsx
git commit -m "feat(frontend): connect exact companies and targeting views"
```

## Task 10: Port Account, Billing, Notifications, and Security with real actions

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Create: `frontend/src/pages/ProfileSettings.tsx`
- Create: `frontend/src/pages/SecuritySettings.tsx`
- Modify: `frontend/src/pages/Billing.tsx`
- Modify: `frontend/src/pages/Notifications.tsx`
- Delete: `frontend/src/billing/PlanGrid.tsx`
- Delete: `frontend/src/billing/PlanGrid.module.css`
- Modify: `frontend/src/billing/billing.test.tsx`
- Modify: `frontend/src/billing/billingMatrix.test.tsx`
- Modify: `frontend/src/billing/packaging.test.tsx`
- Modify: `frontend/src/billing/reviewFixes.test.tsx`
- Modify: `frontend/src/billing/scheduledCancellation.test.tsx`
- Modify: `frontend/src/billing/truthfulCopy.test.tsx`
- Modify: `frontend/src/notifications/notifications.test.tsx`
- Test: `frontend/src/pages/referenceAccount.test.tsx`
- Test: `frontend/src/billing/referenceBilling.test.tsx`
- Test: `frontend/src/notifications/referenceNotifications.test.tsx`

- [ ] **Step 1: Write RED account/locale tests**

```tsx
it('changes the connected language from the exact account form', async () => {
  const user = userEvent.setup()
  mockApi({
    'PATCH /me': (request) => {
      expect(request.body).toEqual({ locale: 'en' })
      return { body: { ...ME, locale: 'en' } }
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  })
  renderApp(<AppRoutes />, {
    route: '/app/settings/profile', session: AUTHENTICATED,
  })
  await user.selectOptions(screen.getByLabelText('Langue'), 'en')
  await user.click(screen.getByRole('button', { name: 'Enregistrer les préférences' }))
  expect(callsTo('/me', 'PATCH').map((call) => call.body)).toEqual([{ locale: 'en' }])
  expect(await screen.findByText('Saved')).toBeVisible()
})
```

- [ ] **Step 2: Port Settings overview/profile/security**

Copy `settings-overview-page.tsx`, `account-settings-forms.tsx`,
`profile-settings-page.tsx`, `security-settings-page.tsx`, and
`settings-nav.tsx`; remove shell wrappers. Substitute:

- real company name and email from `Me`;
- locale select wired to `session.updateLocale`;
- company/email as read-only because no mutation contract exists;
- fixed `Europe/Zurich` as display-only product timezone, not a mutable backend
  promise;
- logout button wired to `session.signOut`;
- password action linked to `/forgot-password`;
- all demo notices with honest capability wording in the same boxes.

Register the components only now that they exist:

```tsx
<Route path="settings/profile" element={<ProfileSettings />} />
<Route path="settings/security" element={<SecuritySettings />} />
```

- [ ] **Step 3: Write RED billing-authority tests**

```tsx
it.each([
  [PRO_STATUS, /gérer l’abonnement/i],
  [RECOVER_STATUS, /régulariser le paiement/i],
] as const)('uses the portal only when the backend action is %s', async (status, label) => {
  const user = userEvent.setup()
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: status },
    'GET /billing/plans': { body: CATALOGUE },
    'POST /billing/portal': { body: { portal_url: 'https://billing.stripe.test/session' } },
  })
  renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })
  await user.click(await screen.findByRole('button', { name: label }))
  expect(callsTo('/billing/portal')).toHaveLength(1)
  expect(callsTo('/billing/checkout')).toHaveLength(0)
})

it('offers checkout only for choose_plan and an explicit live catalogue plan', async () => {
  const user = userEvent.setup()
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /billing/plans': { body: CATALOGUE },
    'POST /billing/checkout': (request) => ({
      body: {
        checkout_url: 'https://checkout.stripe.test/session',
        plan: (request.body as { plan: string }).plan,
        currency: 'chf',
      },
    }),
  })
  renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })
  expect(callsTo('/billing/checkout')).toHaveLength(0)
  await user.click(await screen.findByRole('button', { name: /choisir essentiel/i }))
  expect(callsTo('/billing/checkout')[0].body).toEqual({ plan: 'essential', currency: 'chf' })
})

it('renders contact support without any Stripe mutation', async () => {
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: SUPPORT_STATUS },
    'GET /billing/plans': { body: CATALOGUE },
  })
  renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })
  expect(await screen.findByRole('link', { name: /contacter/i })).toHaveAttribute(
    'href', 'mailto:contact@kivou.eu',
  )
  expect(callsTo('/billing/portal')).toHaveLength(0)
  expect(callsTo('/billing/checkout')).toHaveLength(0)
})
```

Also assert `cancel_at_period_end` and `scheduled_cancellation_at` render the
backend date verbatim through the existing date formatter.

- [ ] **Step 4: Port exact Billing panel with real status/catalogue**

Copy `billing-settings-page.tsx` and `billing-settings-panel.tsx`, remove demo
plan storage/selector, and bind the exact card layout to `billing.status()` and
`billing.plans()`. Keep all price display server-backed. The management button
must follow `billing_action`; never infer it from `plan_code` or
`subscription_status`.

- [ ] **Step 5: Write RED notification tests**

```tsx
it('loads and updates only the real notification contract', async () => {
  const user = userEvent.setup()
  const preference = {
    email_enabled: false,
    notification_email: null,
    updated_at: '2026-08-29T09:00:00+00:00',
  }
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /notification-preferences': { body: preference },
    'PATCH /notification-preferences': (request) => {
      const body = request.body as {
        email_enabled: boolean
        notification_email: string | null
      }
      return { body: { ...preference, ...body } }
    },
  })
  renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })
  await user.click(await screen.findByRole('switch', { name: /activer les alertes/i }))
  await user.type(screen.getByLabelText('Adresse de réception'), 'alerts@example.test')
  await user.click(screen.getByRole('button', { name: /enregistrer/i }))
  expect(callsTo('/notification-preferences', 'PATCH')[0].body).toEqual({
    email_enabled: true,
    notification_email: 'alerts@example.test',
  })
  expect(callsTo('/signals', 'GET')).toHaveLength(0)
})

it('keeps edited notification values visible after a failed save', async () => {
  const user = userEvent.setup()
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /notification-preferences': {
      body: {
        email_enabled: true,
        notification_email: 'old@example.test',
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
    'PATCH /notification-preferences': {
      status: 503,
      body: { detail: { code: 'notification_unavailable' } },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })
  const input = await screen.findByLabelText('Adresse de réception')
  await user.clear(input)
  await user.type(input, 'new@example.test')
  await user.click(screen.getByRole('button', { name: /enregistrer/i }))
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(input).toHaveValue('new@example.test')
})
```

- [ ] **Step 6: Port exact Notifications form**

Copy the reference notification form and bind the exact switch/input/action
geometry to the existing endpoints. Display cadence as the read-only entitlement
from billing status; do not add an unsupported cadence mutation.

- [ ] **Step 7: Verify and commit account surfaces**

Delete the now-unreferenced `PlanGrid.tsx` and `PlanGrid.module.css`. Update the
enumerated legacy billing/notification tests only where they address the old
light-card DOM. Preserve their assertions for exact catalogue prices, explicit
plan choice, single checkout call, backend `billing_action`, portal handoff,
scheduled cancellation date, truthful success/cancel copy, retry behavior, and
notification payloads. No old selector is a reason to change the reference
card hierarchy.

```bash
cd frontend
npm test -- --run src/pages/referenceAccount.test.tsx \
  src/billing/referenceBilling.test.tsx src/billing \
  src/notifications/referenceNotifications.test.tsx src/notifications
npm run typecheck
cd ..
git add frontend/src/pages/Settings.tsx frontend/src/pages/ProfileSettings.tsx \
  frontend/src/pages/SecuritySettings.tsx frontend/src/pages/Billing.tsx \
  frontend/src/pages/Notifications.tsx frontend/src/App.tsx \
  frontend/src/reference/dashboard \
  frontend/src/billing frontend/src/notifications
git commit -m "feat(frontend): connect exact account and billing views"
```

## Task 11: Make loading, empty, error, stale, and mobile states honest in reference geometry

**Files:**
- Modify: `frontend/src/reference/dashboard/resources.ts`
- Modify: connected page files touched in Tasks 8-10
- Delete: `frontend/src/layouts/{AppShell,AuthLayout,PublicLayout}.module.css`
- Delete: `frontend/src/pages/{AuthPages,Billing,Checkout,Companies,CompanyProfile,Contact,Dashboard,IcpForm,Icps,Landing,LegalInformation,MarketingPage,Notifications,Onboarding,PublicSignalDemo,Settings,SignalDetail,SignalsFeed}.module.css`
- Delete: `frontend/src/pages/IcpForm.tsx`
- Delete: `frontend/src/activation/{ActivationProgress,ActivationSuccess}.{tsx,module.css}`
- Delete: `frontend/src/signals/activation.test.tsx`
- Delete: `frontend/src/signals/{DiscoveryPanel,EvidenceGroup,NeedList,SignalListRow}.{tsx,module.css}`
- Delete: `frontend/src/feedback/FeedbackControl.tsx`
- Delete: `frontend/src/feedback/FeedbackControl.module.css`
- Delete: `frontend/src/feedback/feedback.test.tsx`
- Test: `frontend/src/pages/referenceResourceStates.test.tsx`
- Test: `frontend/src/pages/referenceResponsiveContract.test.tsx`

- [ ] **Step 1: Write RED independent-resource tests**

```tsx
it('keeps real overview signals visible when billing fails', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': {
      status: 503, body: { detail: { code: 'billing_unavailable' } },
    },
    'GET /notification-preferences': {
      body: {
        email_enabled: false,
        notification_email: null,
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })
  expect(await screen.findByText(UNLOCKED_ITEM.contract.title!)).toBeVisible()
  expect(await screen.findByRole('alert')).toHaveTextContent('facturation')
})

it('keeps the signal list usable when selected detail fails', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
      status: 503, body: { detail: { code: 'signal_unavailable' } },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  })
  renderApp(<AppRoutes />, {
    route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    session: AUTHENTICATED,
  })
  expect(await screen.findByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
})

it('keeps signal detail visible when its private note request fails', async () => {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      status: 503, body: { detail: { code: 'note_unavailable' } },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
  })
  renderApp(<AppRoutes />, {
    route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    session: AUTHENTICATED,
  })
  expect(await screen.findByText(UNLOCKED_DETAIL.contract.title!)).toBeVisible()
  expect(await screen.findByText(/note.*indisponible/i)).toBeVisible()
})

it('keeps billing context visible when the overview feed fails', async () => {
  mockApi({
    'GET /signals': {
      status: 503, body: { detail: { code: 'signal_unavailable' } },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /notification-preferences': {
      body: {
        email_enabled: true,
        notification_email: 'alerts@example.test',
        updated_at: '2026-08-29T09:00:00+00:00',
      },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })
  expect(await screen.findByText(/Pro/)).toBeVisible()
  expect(await screen.findByRole('alert')).toHaveTextContent('signaux')
})

it('keeps the account shell visible when notifications fail', async () => {
  mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /notification-preferences': {
      status: 503, body: { detail: { code: 'notification_unavailable' } },
    },
  })
  renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })
  expect(await screen.findByRole('heading', { level: 1, name: 'Compte' })).toBeVisible()
  expect(await screen.findByRole('alert')).toHaveTextContent('notification')
  expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
})
```

- [ ] **Step 2: Implement generation-guarded resource state**

Use one state and generation counter per request:

```ts
export interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

export function useResource<T>(load: () => Promise<T>) {
  const generation = useRef(0)
  const mounted = useRef(true)
  const [state, setState] = useState<ResourceState<T>>({ data: null, loading: true, error: null })
  const retry = useCallback(async () => {
    const current = ++generation.current
    setState((previous) => ({ ...previous, loading: true, error: null }))
    try {
      const data = await load()
      if (mounted.current && current === generation.current) {
        setState({ data, loading: false, error: null })
      }
    } catch (error) {
      if (mounted.current && current === generation.current) {
        setState((previous) => ({ ...previous, loading: false, error }))
      }
    }
  }, [load])
  useEffect(() => {
    mounted.current = true
    void retry()
    return () => {
      mounted.current = false
      generation.current += 1
    }
  }, [retry])
  return { ...state, retry }
}
```

Retain stale data only while a refresh is visibly marked loading; after a
failed refresh, keep it visible only with an explicit error banner that says the
refresh failed. Never label stale data as freshly loaded.

- [ ] **Step 3: Write RED responsive contracts at 390px**

```tsx
function mobileMatchMedia(matches: boolean): MediaQueryList {
  return {
    matches,
    media: '(max-width: 767px)',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }
}

it('keeps one main/h1 and exposes the reference mobile navigation trigger', async () => {
  vi.stubGlobal('matchMedia', mobileMatchMedia(true))
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
  })
  renderApp(<AppRoutes />, {
    route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    session: AUTHENTICATED,
  })
  await screen.findByText(UNLOCKED_ITEM.contract.title!)
  expect(screen.getAllByRole('main')).toHaveLength(1)
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Ouvrir la navigation' })).toBeVisible()
  expect(screen.getByRole('button', { name: /retour.*liste/i })).toBeVisible()
})
```

Playwright in Task 12 verifies layout.

- [ ] **Step 4: Preserve reference breakpoints and accessibility**

Do not add new breakpoint declarations. Use the exact dashboard/public CSS.
Ensure route focus moves to the detail heading on mobile selection and returns
to the originating signal control on back. Preserve one `<main>`, one page h1,
reference landmarks, visible focus, and reduced-motion rules.

- [ ] **Step 5: Remove the superseded surface implementation**

After Tasks 5-10 no ported route may import a legacy CSS module or the old
activation/feed/detail/feedback presentation components. Delete the enumerated
files. The account-owned targeting mapping now lives in `targetingInput.ts`;
the exact onboarding/targeting forms own their visible controls, so the old
`IcpForm.tsx` is removed as well. Delete `signals/activation.test.tsx` only
after its still-valid post-feed billing refresh, truthful Discovery count, and
unlocked-first assertions have been moved into `dashboard.test.tsx` and
`referenceDashboardData.test.tsx`; its banner DOM is absent from the approved
reference. Backend feedback routes, storage, analytics, and their Python tests
are untouched; only the frontend control absent from the approved reference is
removed, as required by the design contract.

Prove there is no dangling import or dormant legacy class in the runtime tree:

```bash
cd frontend
npm run typecheck
npm run build
! rg -n "ActivationProgress|ActivationSuccess|DiscoveryPanel|EvidencePanel|NeedList|SignalListRow|FeedbackControl|IcpForm" src \
  --glob '!**/*.test.ts' --glob '!**/*.test.tsx'
! rg -n "Landing_module|Dashboard_module|SignalsFeed_module|SignalDetail_module|PlanGrid_module" \
  dist/assets
```

Expected: typecheck/build pass and both forbidden scans are empty. If a valid
behavior test used a deleted component directly, move that behavioral assertion
to the owning reference page test; do not retain its old DOM.

- [ ] **Step 6: Verify and commit truthful states**

```bash
cd frontend
npm test -- --run src/pages/referenceResourceStates.test.tsx \
  src/pages/referenceResponsiveContract.test.tsx
npm run typecheck
npm run lint
cd ..
git add frontend/src/reference/dashboard/resources.ts frontend/src/pages \
  frontend/src/pages/referenceResourceStates.test.tsx \
  frontend/src/pages/referenceResponsiveContract.test.tsx \
  frontend/src/layouts frontend/src/activation frontend/src/signals \
  frontend/src/feedback
git commit -m "fix(frontend): preserve truthful reference states"
```

## Task 12: Add deterministic visual regression against the pinned references

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/visual/fixtures.ts`
- Create: `frontend/tests/visual/reference-port.spec.ts`
- Create: `frontend/scripts/capture-reference-goldens.mjs`
- Create: `frontend/tests/visual/reference-goldens/*.png`
- Delete: `frontend/src/pages/referenceFidelity.test.tsx`
- Modify: `frontend/package.json`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add Playwright scripts and config**

Add:

```json
{
  "scripts": {
    "test:visual": "playwright test",
    "capture:reference": "node scripts/capture-reference-goldens.mjs"
  }
}
```

`playwright.config.ts` must use pinned Chromium, one worker, no retries locally,
French locale, UTC timezone, animations disabled, and the Vite server:

```ts
export default defineConfig({
  testDir: './tests/visual',
  fullyParallel: false,
  workers: 1,
  snapshotPathTemplate: '{testDir}/reference-goldens/{arg}',
  expect: { toMatchSnapshot: { maxDiffPixelRatio: 0.001 } },
  use: {
    browserName: 'chromium',
    locale: 'fr-CH',
    timezoneId: 'UTC',
    colorScheme: 'light',
    reducedMotion: 'reduce',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
  },
})
```

- [ ] **Step 2: Build deterministic API/session fixtures**

`fixtures.ts` must intercept `/me`, `/signals`, signal detail/note, companies,
target ICPs, billing status/plans, and notification preferences. Copy the six
records from the pinned
`/tmp/kivou-sites-source-dashboard/lib/kivou-data.ts` into this test-only file,
then map them into complete `FeedPage`, `UnlockedDetail`, and `CompanyProfile`
objects with `satisfies` so a contract change fails TypeScript. Never import
the temporary source tree at test runtime: CI receives the committed fixture,
and `verify-reference-source.mjs` proves the authority from which it came.

Use exactly these scenarios and route mappings:

```ts
export type VisualScenario =
  | 'public-pricing'
  | 'auth'
  | 'connected-pro'
  | 'connected-discovery'

export const LOCAL_REFERENCE_ROUTES = [
  { golden: 'public-home', source: '/', local: '/', scenario: 'public-pricing' },
  { golden: 'public-product', source: '/produit', local: '/produit', scenario: 'public-pricing' },
  { golden: 'public-pricing', source: '/tarifs', local: '/tarifs', scenario: 'public-pricing' },
  { golden: 'public-signal', source: '/exemple-de-signal', local: '/exemple-de-signal', scenario: 'public-pricing' },
  { golden: 'public-contact', source: '/contact', local: '/contact', scenario: 'public-pricing' },
  { golden: 'public-legal', source: '/informations-legales', local: '/informations-legales', scenario: 'public-pricing' },
  { golden: 'dashboard-login', source: '/login', local: '/login', scenario: 'auth' },
  { golden: 'dashboard-signup', source: '/signup', local: '/signup', scenario: 'auth' },
  { golden: 'dashboard-overview', source: '/', local: '/app/dashboard', scenario: 'connected-pro' },
  { golden: 'dashboard-signals', source: '/signals?signal=tm-ausbau-campus-ost', local: '/app/signals/tm-ausbau-campus-ost', scenario: 'connected-discovery' },
  { golden: 'dashboard-companies', source: '/companies', local: '/app/companies', scenario: 'connected-pro' },
  { golden: 'dashboard-targeting', source: '/targeting', local: '/app/icps', scenario: 'connected-pro' },
  { golden: 'dashboard-account', source: '/settings', local: '/app/settings', scenario: 'connected-pro' },
] as const
```

The `connected-pro` feed contains six unlocked items so Overview and Companies
have the same repeated-card count as the source. `connected-discovery` contains
the same six positions with the final three as valid locked teasers; it never
registers a detail or company handler for those three keys. The catalogue uses
the reference-visible CHF values only inside this test fixture, while runtime
components still obtain every number from `/billing/plans`. Every other
unhandled API request is fulfilled with 501 and makes the test fail.

Install the fixture before navigation and record every request:

```ts
export async function installReferenceApi(page: Page, scenario: VisualScenario) {
  const calls: Array<{ method: string; path: string }> = []
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (!isApiPath(url.pathname)) return route.continue()
    const key = `${request.method()} ${url.pathname}`
    calls.push({ method: request.method(), path: url.pathname })
    const response = visualResponse(scenario, key)
    if (!response) {
      calls.push({ method: request.method(), path: '/__unhandled__' })
      await route.fulfill({
        status: 501,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'unhandled_visual_request', key } }),
      })
      return
    }
    await route.fulfill({
      status: response.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response.body),
    })
  })
  return calls
}
```

`isApiPath` uses the exact `API_PREFIXES` from `vite.config.ts` plus the new
note route. `visualResponse` is a total switch over the four scenarios and the
enumerated endpoints; it returns `GET /me` as 401 for `public-pricing` and
`auth`, and an authenticated `Me` everywhere under `/app`.

- [ ] **Step 3: Capture golden images from the two authority sites**

Install each pinned source tree through its locked installer, then the capture
script launches both source Vite servers locally. It never captures the mutable
public URLs:

```bash
cd /tmp/kivou-sites-source-public && npm run install:ci
cd /tmp/kivou-sites-source-dashboard && npm run install:ci
cd /home/jaybe/.config/superpowers/worktrees/Kivou/exact-reference-port/frontend
node scripts/verify-reference-source.mjs
```

`capture-reference-goldens.mjs` creates detached temporary worktrees from the
pinned commits and serves only those worktrees. Use this complete script:

```js
import { spawn, execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from '@playwright/test'

const manifest = JSON.parse(readFileSync(resolve('reference-source.json'), 'utf8'))
const output = resolve('tests/visual/reference-goldens')
const temporaryRoot = execFileSync('mktemp', ['-d', join(tmpdir(), 'kivou-reference.XXXXXX')], {
  encoding: 'utf8',
}).trim()
const children = []
const worktrees = []

function addWorktree(source, name) {
  const target = join(temporaryRoot, name)
  execFileSync('git', ['-C', source.path, 'worktree', 'add', '--detach', target, source.commit], {
    stdio: 'inherit',
  })
  symlinkSync(join(source.path, 'node_modules'), join(target, 'node_modules'), 'dir')
  worktrees.push({ repository: source.path, target })
  return target
}

function start(cwd, port) {
  const child = spawn(
    'npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(port)],
    { cwd, detached: true, stdio: 'ignore' },
  )
  children.push(child)
  return child
}

async function ready(url) {
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {}
    await new Promise((accept) => setTimeout(accept, 250))
  }
  throw new Error(`reference server did not become ready: ${url}`)
}

const font = (path) => readFileSync(resolve(path)).toString('base64')
const fontCss = `
@font-face { font-family: "Instrument Sans Variable"; src: url(data:font/woff2;base64,${font('node_modules/@fontsource-variable/instrument-sans/files/instrument-sans-latin-ext-wght-normal.woff2')}) format("woff2"); font-weight: 100 900; font-style: normal; font-display: block; }
@font-face { font-family: "Lora Variable"; src: url(data:font/woff2;base64,${font('node_modules/@fontsource-variable/lora/files/lora-latin-ext-wght-normal.woff2')}) format("woff2"); font-weight: 400 700; font-style: normal; font-display: block; }
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
`

const pages = [
  ['public', '/', 'public-home', 'Repérez les entreprises qui viennent de gagner un marché public.'],
  ['public', '/produit', 'public-product', 'Kivou suit ce qui se passe après l’attribution.'],
  ['public', '/tarifs', 'public-pricing', 'Choisissez la couverture adaptée à votre prospection.'],
  ['public', '/exemple-de-signal', 'public-signal', 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.'],
  ['public', '/contact', 'public-contact', 'Contact'],
  ['public', '/informations-legales', 'public-legal', 'Informations légales et contractuelles'],
  ['dashboard', '/login', 'dashboard-login', 'Retrouver vos signaux'],
  ['dashboard', '/signup', 'dashboard-signup', 'Commencer avec un ciblage clair'],
  ['dashboard', '/', 'dashboard-overview', 'Vue d’ensemble'],
  ['dashboard', '/signals?signal=tm-ausbau-campus-ost', 'dashboard-signals', 'Signaux'],
  ['dashboard', '/companies', 'dashboard-companies', 'Entreprises'],
  ['dashboard', '/targeting', 'dashboard-targeting', 'Profil de ciblage'],
  ['dashboard', '/settings', 'dashboard-account', 'Compte'],
]

async function normalizeConnectedText(page) {
  await page.evaluate(() => {
    const root = document.querySelector('.dashboard-provider, .auth-shell')
    if (!root) return
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    const nodes = []
    while (walker.nextNode()) nodes.push(walker.currentNode)
    for (const node of nodes) {
      if (node.nodeValue?.trim()) node.nodeValue = 'Texte'
    }
    for (const field of root.querySelectorAll('input, textarea')) {
      field.setAttribute('placeholder', 'Texte')
      if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
        field.value = ''
      }
    }
  })
}

async function capture(page, site, base, path, name, heading, viewportName) {
  await page.setViewportSize(viewportName === 'desktop'
    ? { width: 1440, height: 900 }
    : { width: 390, height: 844 })
  await page.goto(`${base}${path}`, { waitUntil: 'networkidle' })
  await page.addStyleTag({ content: fontCss })
  await page.evaluate(() => document.fonts.ready)
  await page.getByText(heading, { exact: true }).first().waitFor()
  if (site === 'dashboard') await normalizeConnectedText(page)
  await page.screenshot({
    path: join(output, `${name}-${viewportName}.png`),
    fullPage: true,
    animations: 'disabled',
  })
}

try {
  mkdirSync(output, { recursive: true })
  const publicTree = addWorktree(manifest.public, 'public')
  const dashboardTree = addWorktree(manifest.dashboard, 'dashboard')
  start(publicTree, 4174)
  start(dashboardTree, 4175)
  await Promise.all([
    ready('http://127.0.0.1:4174/'),
    ready('http://127.0.0.1:4175/'),
  ])
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ locale: 'fr-CH', timezoneId: 'UTC' })
    for (const [site, path, name, heading] of pages) {
      const base = site === 'public'
        ? 'http://127.0.0.1:4174'
        : 'http://127.0.0.1:4175'
      await capture(page, site, base, path, name, heading, 'desktop')
      await capture(page, site, base, path, name, heading, 'mobile')
    }

    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('http://127.0.0.1:4174/', { waitUntil: 'networkidle' })
    await page.addStyleTag({ content: fontCss })
    await page.getByRole('button', { name: 'Ouvrir le menu' }).click()
    await page.screenshot({ path: join(output, 'public-menu-open-mobile.png'), fullPage: true })

    await page.goto('http://127.0.0.1:4175/', { waitUntil: 'networkidle' })
    await page.addStyleTag({ content: fontCss })
    await page.getByRole('button', { name: 'Ouvrir la navigation' }).click()
    await normalizeConnectedText(page)
    await page.screenshot({ path: join(output, 'dashboard-sidebar-open-mobile.png'), fullPage: true })
  } finally {
    await browser.close()
  }
} finally {
  for (const child of children.reverse()) {
    if (child.pid) {
      try { process.kill(-child.pid, 'SIGTERM') } catch {}
    }
  }
  await new Promise((accept) => setTimeout(accept, 500))
  for (const child of children.reverse()) {
    if (child.pid) {
      try { process.kill(-child.pid, 'SIGKILL') } catch {}
    }
  }
  for (const { repository, target } of worktrees.reverse()) {
    try { execFileSync('git', ['-C', repository, 'worktree', 'remove', '--force', target]) } catch {}
  }
  rmSync(temporaryRoot, { recursive: true, force: true })
}
```

The injected fonts are the same locked local assets used by Kivou, so both
renders exercise the font families requested by the reference CSS. Public
captures remain completely unmasked. Connected captures normalize text only:
this removes intentional differences between real API copy and the source's
demo copy while retaining the exact number of nodes, DOM geometry, icons,
colors, spacing, and responsive composition under one common text payload. It
does not claim to compare natural reflow of unequal live strings. Unit tests in
Tasks 7-11 assert the unnormalized real text and values, and Task 16 checks
unmasked live wrapping/overflow at both viewports. The harness
lives only in disposable worktrees and cannot enter either authority tree or
the product bundle. Never update goldens from the Kivou port or the mutable
hosted URLs.

Run:

```bash
cd frontend
npx playwright install chromium
npm run capture:reference
git status --short tests/visual/reference-goldens
```

Expected: only the named PNG goldens are created.

- [ ] **Step 4: Write the local comparison suite and observe genuine differences**

For each golden, intercept API calls, navigate to the mapped Kivou path, wait
for fonts/network/UI state, call the same `normalizeConnectedText()` only for
dashboard/auth captures, and compare. Export that helper from `fixtures.ts`;
its body must be byte-for-byte the same as the capture script above.

```ts
for (const route of LOCAL_REFERENCE_ROUTES) {
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'mobile', width: 390, height: 844 },
  ] as const) {
    test(`${route.golden} ${viewport.name}`, async ({ page }) => {
      const calls = await installReferenceApi(page, route.scenario)
      await page.setViewportSize(viewport)
      await page.goto(route.local)
      await waitForScenario(page, route.scenario, route.golden)
      await page.evaluate(() => document.fonts.ready)
      if (route.golden.startsWith('dashboard-')) {
        await normalizeConnectedText(page)
      }
      const actual = await page.screenshot({ fullPage: true, animations: 'disabled' })
      expect(actual).toMatchSnapshot(`${route.golden}-${viewport.name}.png`, {
        maxDiffPixelRatio: 0.001,
      })
      expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
    })
  }
}
```

`waitForScenario` waits for the mapped steady-state h1 before normalization:
`Vue d’ensemble`, `Signaux`, `Entreprises`, `Profil de ciblage`, or `Compte`.
Public/auth entries wait for their pinned h1. The suite also captures the
public mobile menu and connected sidebar-open state using the matching golden
names and the same normalization rule.

Do not compare connected inline loading/error/empty panels to the source's
full-page `loading.tsx`, `error.tsx`, or `SystemState`: Kivou deliberately keeps
independent resources and the authenticated shell visible when one request
fails. Task 11 asserts their exact reference classes, truthful copy, retry
scope, and responsive contract; Task 16 inspects their unmasked live geometry.
Treating the source full-page fallback as a pixel golden for an inline resource
failure would force a functional regression.

Expected on the first run: any remaining port mismatch fails with a diff image.

- [ ] **Step 5: Fix only evidenced port differences**

For each diff, compare DOM/classes and computed boxes to the pinned source. Fix
the Kivou port; do not update the golden. Allowed differences are limited to
antialiasing under the 0.1% threshold. Re-run until all named comparisons pass.

- [ ] **Step 6: Add visual CI without duplicating workflow runs**

In the existing frontend job, after unit tests and before build:

```yaml
      - name: Installer Chromium verrouillé
        run: npx playwright install --with-deps chromium

      - name: Régression visuelle des références
        run: npm run test:visual
```

Do not create a second workflow. This preserves one CI invocation per commit.

- [ ] **Step 7: Verify and commit visual protection**

Delete `frontend/src/pages/referenceFidelity.test.tsx`. That file protects the
superseded light-shell reconstruction and must not remain as a reason to alter
the pinned public/dashboard DOM. Its still-valid behavioral guarantees are
covered by `publicReferencePort.test.tsx`, `appShellReference.test.tsx`,
`referenceDashboardData.test.tsx`, `referenceSignalWorkspace.test.tsx`,
`referenceResourceStates.test.tsx`, and the browser comparisons created here.

```bash
cd frontend
npm run test:visual
npm test -- --run src/pages/publicReferencePort.test.tsx \
  src/layouts/appShellReference.test.tsx \
  src/pages/referenceDashboardData.test.tsx \
  src/signals/referenceSignalWorkspace.test.tsx \
  src/pages/referenceResourceStates.test.tsx
cd ..
git add frontend/playwright.config.ts frontend/tests/visual \
  frontend/scripts/capture-reference-goldens.mjs frontend/package.json \
  frontend/package-lock.json .github/workflows/ci.yml \
  frontend/src/pages/referenceFidelity.test.tsx
git commit -m "test(frontend): enforce exact reference rendering"
```

Expected: all desktop/mobile comparisons pass at `maxDiffPixelRatio <= 0.001`.

## Task 13: Full local verification and self-review before GitHub mutation

**Files:**
- Modify only files tied to a concrete failing verification.

- [ ] **Step 1: Verify provenance and scan for forbidden demo runtime data**

```bash
cd frontend
node scripts/verify-reference-source.mjs
rg -n --glob '!**/*.test.ts' --glob '!**/*.test.tsx' \
  "Compte démo|Mode démonstration|kivou-data|DEMO_PLAN_STORAGE_KEY|kivou-target-profile-demo" \
  src
rg -n --glob '!**/*.test.ts' --glob '!**/*.test.tsx' \
  "localStorage" src || true
```

Expected: the first scan has no match. The second has no reference-port match;
if unrelated runtime use appears, inspect its existing contract rather than
removing it mechanically. `sessionStorage` in `billing/checkoutIntent.ts` is a
deliberate, privacy-bounded return-to-signal mechanism and is not a demo
fallback.

- [ ] **Step 2: Run complete backend gates**

```bash
cd ..
uv run pytest -q
uv run ruff check .
```

Expected: all tests pass, only already-known deprecation warnings remain, and no
test is newly skipped.

- [ ] **Step 3: Run complete frontend gates**

```bash
cd frontend
npm test -- --run
npm run test:visual
npm run build
npm run typecheck
npm run lint
```

Expected: all five commands exit 0.

- [ ] **Step 4: Run plan/spec coverage and placeholder scans**

```bash
cd ..
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
! rg -n "TODO|TBD|implement later|fill in details|similar to Task" \
  docs/superpowers/plans/2026-08-29-exact-reference-frontend-port.md | \
  grep -v 'rg -n'
```

Expected: clean diff check; only scoped frontend, note, locale, migration, tests,
CI, spec, and plan files changed; placeholder scan returns no implementation
placeholder after excluding its own literal command.

- [ ] **Step 5: Inspect protected business boundaries**

```bash
git diff origin/main...HEAD -- \
  src/signals/matching src/signals/billing src/signals/campaigns \
  src/signals/acquisition src/signals/decision src/signals/personalization \
  ops
```

Expected: no diff. `routes_auth`, the note-specific engagement files, and the
single additive migration are the only backend changes.

- [ ] **Step 6: Require the reviewed implementation tree to be clean**

```bash
test -z "$(git status --porcelain)"
```

Expected: exit 0. If an earlier gate exposed a defect, return to the task that
owns that file, add a focused RED test, implement the fix, rerun that task's
exact verification command, and commit through that task before repeating this
full review. Never commit generated Playwright failure artifacts
(`test-results/`, reports, traces).

## Task 14: Review, protected PR integration, and exact main CI

**Files:**
- No product changes unless review or CI identifies a concrete defect.

- [ ] **Step 1: Use the required review skill**

Refresh `main` before review so an old local base cannot be mistaken for the
merge candidate:

```bash
git fetch origin main
BASE_SHA=$(git merge-base HEAD origin/main)
if test "$BASE_SHA" != "$(git rev-parse origin/main)"; then
  git rebase origin/main
  uv run pytest -q
  uv run ruff check .
  cd frontend
  npm test -- --run
  npm run test:visual
  npm run build
  npm run typecheck
  npm run lint
  cd ..
fi
```

Expected: the branch is based on the current `origin/main`; any rebase is local
and happens before the first push, so no force push is needed.

Invoke `superpowers:requesting-code-review` against the complete diff. Review
must explicitly check source fidelity, API truthfulness, locked-signal privacy,
company authorization, Stripe action authority, note isolation, locale scope,
and production exclusion. Resolve findings with RED/GREEN evidence.

- [ ] **Step 2: Re-run final gates from a clean tree**

```bash
git status --short
git diff --check origin/main...HEAD
uv run pytest -q
uv run ruff check .
cd frontend
npm test -- --run
npm run test:visual
npm run build
npm run typecheck
npm run lint
```

Expected: clean tree and every gate passes.

- [ ] **Step 3: Push and open one PR**

```bash
git push -u origin fix/exact-reference-port
gh pr create --repo bruppacherrodrigue-art/Kivou \
  --base main \
  --head fix/exact-reference-port \
  --title "Porte exactement les frontends de référence" \
  --body-file /tmp/kivou-exact-reference-pr-body.md
```

Create `/tmp/kivou-exact-reference-pr-body.md` with `apply_patch` using this
exact body after the fresh commands above have all exited zero:

```markdown
## Port exact approuvé

- site public porté depuis `efaa4160f4c3bbbdb01448bf9228772491e614f5` ;
- dashboard porté depuis `05212f2da5197699e6a9bb191556afcb2dcf1bb3` ;
- DOM, classes, CSS et responsive de référence conservés ;
- données, droits, paywall, prix et actions fournis uniquement par les API Kivou.

## Capacités backend bornées

- `PATCH /me` modifie uniquement `fr|en` pour le compte authentifié ;
- migration additive `0027_signal_notes` et ressource de note privée ;
- aucune note ne fabrique de pertinence ou d’événement analytique.

## Vérifications

- source et empreintes : PASS ;
- backend : `uv run pytest -q` et Ruff PASS sur la tête poussée ;
- frontend : Vitest complet PASS sur la tête poussée ;
- build, typecheck, lint : PASS ;
- régression visuelle Chromium 1440/390, public non masqué et connecté à texte
  normalisé, seuil 0,1 % : PASS ;
- la tête poussée est relue par `gh pr view` avant fusion.

## Frontières

Aucun changement du matching, de Stripe, des permissions, du paywall, d’Apollo,
d’Instantly, d’Hermes ou des fournisseurs. Déploiement prévu uniquement sur le
staging après fusion protégée et CI `main` verte. Aucun déploiement production.
```

Do not include credentials or memory citations.

- [ ] **Step 4: Observe the single PR CI run**

```bash
PR_NUMBER=$(gh pr view --repo bruppacherrodrigue-art/Kivou --json number --jq .number)
gh pr checks "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou \
  --watch --interval 20
```

Expected: Backend and Frontend are SUCCESS. Do not rerun an unchanged commit.

- [ ] **Step 5: Re-read exact merge state and protections**

```bash
gh pr view "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou \
  --json state,isDraft,mergeable,headRefOid,baseRefName,statusCheckRollup,reviews
```

Expected: OPEN, not draft, MERGEABLE, base `main`, reviewed exact head, all
required checks SUCCESS, and existing review/protection requirements satisfied.

- [ ] **Step 6: Squash merge without bypass**

```bash
gh pr merge "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou \
  --squash --delete-branch
```

Never use admin bypass, force push, or disabled checks. On a timeout, re-read PR
state and `origin/main` before attempting any second mutation.

- [ ] **Step 7: Verify exact main SHA and main CI**

```bash
git fetch origin main
MAIN_SHA=$(git rev-parse origin/main)
RUN_ID=$(gh run list --repo bruppacherrodrigue-art/Kivou --branch main \
  --commit "$MAIN_SHA" --limit 5 --json databaseId \
  --jq 'map(select(.databaseId != null))[0].databaseId')
test -n "$RUN_ID"
gh run watch "$RUN_ID" --repo bruppacherrodrigue-art/Kivou --interval 20
```

Expected: exact merged `main` SHA and both jobs SUCCESS. If concurrency cancels
this run, follow only the successor for the same current `MAIN_SHA`.

## Task 15: Deploy the exact merged SHA to staging only

**Files:**
- No production or repository changes.

Keep one local deployment shell open from Step 1 through Step 10 so
`PR_NUMBER`, `MAIN_SHA`, `BUILD_ROOT`, `BUILD_WORKTREE`, and
`REMOTE_BACKEND_RELEASE` remain exact. If that shell is lost, stop and recover
the values from the printed command output; never rediscover a backend release
by a 12-character SHA glob. The full SHA and the exact absolute release path
are passed to every remote command below.

- [ ] **Step 1: Record live staging targets and health without secrets**

```bash
cd /home/jaybe/.config/superpowers/worktrees/Kivou/exact-reference-port
PR_NUMBER=$(gh pr list --repo bruppacherrodrigue-art/Kivou --state merged \
  --head fix/exact-reference-port --limit 1 --json number --jq '.[0].number')
test -n "$PR_NUMBER"
MAIN_SHA=$(gh pr view "$PR_NUMBER" --repo bruppacherrodrigue-art/Kivou \
  --json mergeCommit --jq '.mergeCommit.oid')
git fetch origin main
test "$(git rev-parse origin/main)" = "$MAIN_SHA"
printf 'merged_pr=%s\nmain_sha=%s\n' "$PR_NUMBER" "$MAIN_SHA"
ssh kivou-staging 'set -eu
printf "app="; readlink -f /srv/kivou/app
printf "frontend="; readlink -f /srv/kivou/frontend
systemctl is-active kivou-api.service nginx.service kivou-backup.timer
test "$(curl -sS --connect-timeout 1 --max-time 2 -o /dev/null \
  -w '%{http_code}' http://127.0.0.1:8000/openapi.json)" = 200
'
```

Expected: explicit prior backend/frontend release paths and all services active.
Record them for rollback. Do not read `/etc/kivou/staging.env` into the terminal.

- [ ] **Step 2: Build frontend from a detached exact-main worktree**

```bash
BUILD_ROOT=$(mktemp -d /tmp/kivou-exact-reference-build.XXXXXX)
BUILD_WORKTREE="$BUILD_ROOT/checkout"
git worktree add --detach "$BUILD_WORKTREE" "$MAIN_SHA"
cd "$BUILD_WORKTREE/frontend"
npm ci
npm run build
test -f dist/index.html
```

Expected: production frontend build succeeds from `MAIN_SHA`.

- [ ] **Step 3: Take and verify a fresh staging backup**

Run the versioned backup unit without exposing its environment:

```bash
ssh kivou-staging 'set -eu
before=$(sudo -u kivou find /srv/kivou/backups -maxdepth 1 -type f -name "kivou-*.dump" -printf "%T@ %p\n" | sort -n | tail -1 | cut -d" " -f2-)
sudo systemctl start kivou-backup.service
test "$(systemctl show kivou-backup.service -p Result --value)" = success
after=$(sudo -u kivou find /srv/kivou/backups -maxdepth 1 -type f -name "kivou-*.dump" -printf "%T@ %p\n" | sort -n | tail -1 | cut -d" " -f2-)
test -n "$after"; test "$after" != "$before"
sudo -u kivou pg_restore --list "$after" >/dev/null
test "$(sudo -u kivou stat -c "%U:%G:%a" "$after")" = "kivou:kivou:600"
test "$(sudo -u kivou stat -c "%s" "$after")" -gt 0
sudo -u kivou stat -c "%U:%G %a %s %n" "$after"
'
```

Expected: a new `kivou:kivou 600` valid dump with nonzero size.

- [ ] **Step 4: Create the immutable backend release from reviewed main**

```bash
printf '%s\n' "$MAIN_SHA" | grep -Eq '^[0-9a-f]{40}$'
REMOTE_BACKEND_RELEASE=$(ssh kivou-staging 'bash -s' -- "$MAIN_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_SHA=$1
printf '%s\n' "$KIVOU_RELEASE_SHA" | grep -Eq '^[0-9a-f]{40}$'
KIVOU_RELEASE_REMOTE=git@github.com:bruppacherrodrigue-art/Kivou.git
KIVOU_DEPLOY_KEY=/srv/kivou/.ssh/github_deploy
KIVOU_KNOWN_HOSTS=/etc/nginx/kivou-github-known-hosts
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_DEPLOY_KEY")" = kivou:kivou:600
test "$(sudo stat -c '%U:%G:%a' "$KIVOU_KNOWN_HOSTS")" = root:root:644
KIVOU_GIT_SSH_COMMAND="/usr/bin/ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KIVOU_KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null -i $KIVOU_DEPLOY_KEY"
kivou_git() {
  sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 /usr/bin/git "$@"
}
KIVOU_REMOTE_MAIN_SHA=$(sudo -u kivou /usr/bin/env -i \
  HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git ls-remote --exit-code "$KIVOU_RELEASE_REMOTE" refs/heads/main |
  awk '$2 == "refs/heads/main" {print $1}')
test "$KIVOU_REMOTE_MAIN_SHA" = "$KIVOU_RELEASE_SHA"
KIVOU_RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
KIVOU_RELEASE_DIR=/srv/kivou/releases/backend-$KIVOU_RELEASE_UTC-$KIVOU_RELEASE_SHORT
sudo test ! -e "$KIVOU_RELEASE_DIR"
sudo install -o kivou -g kivou -m 755 -d "$KIVOU_RELEASE_DIR"
kivou_git init --quiet --initial-branch=main "$KIVOU_RELEASE_DIR"
kivou_git -C "$KIVOU_RELEASE_DIR" remote add origin "$KIVOU_RELEASE_REMOTE"
sudo -u kivou /usr/bin/env -i HOME=/srv/kivou PATH=/usr/bin:/bin \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  GIT_SSH_COMMAND="$KIVOU_GIT_SSH_COMMAND" \
  /usr/bin/git -C "$KIVOU_RELEASE_DIR" fetch --no-tags origin \
  +refs/heads/main:refs/kivou-rollout/reviewed-main >&2
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" rev-parse refs/kivou-rollout/reviewed-main)" = "$KIVOU_RELEASE_SHA"
kivou_git -C "$KIVOU_RELEASE_DIR" checkout --detach "$KIVOU_RELEASE_SHA" >&2
test "$(kivou_git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
sudo -u kivou /usr/bin/env --chdir="$KIVOU_RELEASE_DIR" \
  /usr/local/bin/uv sync --frozen --extra server --extra postgres >&2
test -z "$(kivou_git -C "$KIVOU_RELEASE_DIR" status --porcelain)"
printf '%s\n' "$KIVOU_RELEASE_DIR"
REMOTE
)
case "$REMOTE_BACKEND_RELEASE" in
  (/srv/kivou/releases/backend-*-${MAIN_SHA:0:12}) ;;
  (*) exit 69 ;;
esac
printf 'backend_release=%s\n' "$REMOTE_BACKEND_RELEASE"
```

Do not reuse or mutate `/srv/kivou/app` in place.

- [ ] **Step 5: Prove the migration on a disposable restored database**

```bash
ssh kivou-staging 'bash -s' -- "$REMOTE_BACKEND_RELEASE" "$MAIN_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_RELEASE_SHA=$2
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
test -d "$KIVOU_RELEASE_DIR"
test "$(sudo -u kivou git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
KIVOU_BACKUP=$(sudo -u kivou find /srv/kivou/backups -maxdepth 1 -type f \
  -name 'kivou-*.dump' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
test -n "$KIVOU_BACKUP"
sudo -u kivou pg_restore --list "$KIVOU_BACKUP" >/dev/null
KIVOU_VALIDATION_DB=kivou_exact_ref_$(date -u +%Y%m%dT%H%M%SZ | tr -d ':-')
case "$KIVOU_VALIDATION_DB" in
  (kivou_exact_ref_[0-9]*) ;;
  (*) exit 69 ;;
esac
cleanup() { sudo -u postgres dropdb --if-exists "$KIVOU_VALIDATION_DB"; }
trap cleanup EXIT
sudo -u postgres createdb -T template0 "$KIVOU_VALIDATION_DB"
sudo -u kivou cat "$KIVOU_BACKUP" |
  sudo -u postgres pg_restore --no-owner --no-privileges \
    --dbname="$KIVOU_VALIDATION_DB"
test "$(sudo -u postgres psql -At -d "$KIVOU_VALIDATION_DB" \
  -c 'select version_num from alembic_version')" = 0026_acquisition_runtime
sudo -u postgres /usr/bin/env \
  KIVOU_DATABASE_URL="postgresql+psycopg:///$KIVOU_VALIDATION_DB" \
  "$KIVOU_RELEASE_DIR/.venv/bin/python" - <<'PY'
import sqlalchemy as sa
from alembic import command
from signals.persistence.database import alembic_config, create_database_engine, current_revision

engine = create_database_engine()
config = alembic_config(engine)
assert current_revision(engine) == "0026_acquisition_runtime"
command.upgrade(config, "0027_signal_notes")
assert current_revision(engine) == "0027_signal_notes"
columns = {column["name"] for column in sa.inspect(engine).get_columns("signal_note")}
assert columns == {"account_id", "signal_key", "note", "created_at", "updated_at"}
command.downgrade(config, "0026_acquisition_runtime")
assert current_revision(engine) == "0026_acquisition_runtime"
assert "signal_note" not in sa.inspect(engine).get_table_names()
command.upgrade(config, "0027_signal_notes")
assert current_revision(engine) == "0027_signal_notes"
PY
REMOTE
```

Expected: restore, upgrade, downgrade, and re-upgrade exit 0; the trap drops only
the validated disposable database. Never downgrade the live staging database.

- [ ] **Step 6: Apply the additive migration once to staging**

```bash
ssh kivou-staging 'bash -s' -- "$REMOTE_BACKEND_RELEASE" "$MAIN_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_RELEASE_SHA=$2
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
test "$(sudo -u kivou git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
KIVOU_MIGRATION_UNIT=kivou-migrate-$(date -u +%Y%m%dT%H%M%SZ)
sudo systemd-run --wait --collect --unit="$KIVOU_MIGRATION_UNIT" \
  --property=Type=oneshot \
  --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/python" -c \
  'from signals.persistence.database import create_database_engine,current_revision,migrate_to_latest; engine=create_database_engine(); migrate_to_latest(engine); assert current_revision(engine)=="0027_signal_notes"'
REMOTE
```

Expected: exit 0 and `current_revision` reports `0027_signal_notes` through a
post-migration assertion in the transient unit. No provider or Stripe command
runs.

- [ ] **Step 7: Start the new backend on green port 8001**

```bash
ssh kivou-staging 'bash -s' -- "$REMOTE_BACKEND_RELEASE" "$MAIN_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_RELEASE_SHA=$2
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
test "$(sudo -u kivou git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
sudo systemctl stop kivou-api-green.service 2>/dev/null || true
sudo systemd-run --unit=kivou-api-green --collect \
  --property=Type=exec --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_RELEASE_DIR" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=Restart=on-failure --property=RestartSec=5s \
  --property=StandardOutput=journal --property=StandardError=journal \
  --property=SyslogIdentifier=kivou-api-green \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=ReadWritePaths=/srv/kivou/run \
  --property=ProtectKernelTunables=yes --property=ProtectKernelModules=yes \
  --property=ProtectControlGroups=yes --property=RestrictSUIDSGID=yes \
  --property=RestrictNamespaces=yes --property=LockPersonality=yes \
  --property=MemoryDenyWriteExecute=yes \
  -- "$KIVOU_RELEASE_DIR/.venv/bin/uvicorn" signals.api.asgi:app \
  --host 127.0.0.1 --port 8001 --workers 2 --proxy-headers \
  --forwarded-allow-ips 127.0.0.1 --no-server-header --no-access-log \
  --timeout-keep-alive 20
sudo -u kivou /usr/bin/env -i PATH=/usr/bin:/bin \
  "$KIVOU_RELEASE_DIR/ops/bin/kivou-api-readiness.sh" \
  kivou-api-green.service 8001
test "$(curl -sS --connect-timeout 1 --max-time 2 -o /dev/null \
  -w '%{http_code}' http://127.0.0.1:8001/openapi.json)" = 200
test "$(curl -sS --connect-timeout 1 --max-time 2 -o /dev/null \
  -w '%{http_code}' http://127.0.0.1:8001/me)" = 401
REMOTE
```

Expected: health 200 and unauthenticated `/me` 401.

- [ ] **Step 8: Atomically switch backend to the exact release**

```bash
ssh kivou-staging 'bash -s' -- "$REMOTE_BACKEND_RELEASE" "$MAIN_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_RELEASE_DIR=$1
KIVOU_RELEASE_SHA=$2
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
case "$KIVOU_RELEASE_DIR" in
  (/srv/kivou/releases/backend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
KIVOU_PREVIOUS_RELEASE=$(readlink -f /srv/kivou/app)
case "$KIVOU_PREVIOUS_RELEASE" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
test "$(sudo -u kivou git -C "$KIVOU_RELEASE_DIR" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
sudo test ! -e /srv/kivou/app.new
sudo test ! -e /srv/kivou/app.rollback
sudo ln -s "$KIVOU_RELEASE_DIR" /srv/kivou/app.new
sudo chown -h kivou:kivou /srv/kivou/app.new
test "$(readlink -f /srv/kivou/app.new)" = "$KIVOU_RELEASE_DIR"
sudo mv -Tf /srv/kivou/app.new /srv/kivou/app
if ! sudo systemctl restart kivou-api.service || \
   ! sudo systemctl is-active --quiet kivou-api.service || \
   ! test "$(curl -sS --connect-timeout 1 --max-time 3 -o /dev/null \
      -w '%{http_code}' http://127.0.0.1:8000/openapi.json)" = 200; then
  sudo ln -s "$KIVOU_PREVIOUS_RELEASE" /srv/kivou/app.rollback
  sudo chown -h kivou:kivou /srv/kivou/app.rollback
  sudo mv -Tf /srv/kivou/app.rollback /srv/kivou/app
  sudo systemctl restart kivou-api.service
  test "$(curl -sS --connect-timeout 1 --max-time 3 -o /dev/null \
    -w '%{http_code}' http://127.0.0.1:8000/openapi.json)" = 200
  exit 1
fi
test "$(sudo -u kivou git -C "$(readlink -f /srv/kivou/app)" rev-parse HEAD)" = "$KIVOU_RELEASE_SHA"
sudo systemctl stop kivou-api-green.service
REMOTE
```

This restarts only `kivou-api.service`. Stop and collect green only after the
main 8000 service is healthy.

If the main service fails, restore only the recorded previous app symlink while
keeping the additive schema and current safe nginx/security floor; restart and
recheck health. The additive note table is backward-compatible with the prior
backend.

- [ ] **Step 9: Publish the immutable frontend release atomically**

```bash
RELEASE_UTC=$(date -u +%Y%m%dT%H%M%SZ)
RELEASE_SHORT=$(printf '%s' "$MAIN_SHA" | cut -c1-12)
FRONTEND_RELEASE="/srv/kivou/releases/frontend-${RELEASE_UTC}-${RELEASE_SHORT}"
ssh kivou-staging "test ! -e '$FRONTEND_RELEASE' && sudo install -o kivou -g kivou -m 755 -d '$FRONTEND_RELEASE'"
tar -C "$BUILD_WORKTREE/frontend/dist" -cf - . | \
  ssh kivou-staging "sudo -u kivou tar -C '$FRONTEND_RELEASE' -xf -"
ssh kivou-staging 'bash -s' -- "$FRONTEND_RELEASE" "$MAIN_SHA" <<'REMOTE'
set -euo pipefail
KIVOU_FRONTEND_RELEASE=$1
KIVOU_RELEASE_SHA=$2
KIVOU_RELEASE_SHORT=$(printf '%s' "$KIVOU_RELEASE_SHA" | cut -c1-12)
case "$KIVOU_FRONTEND_RELEASE" in
  (/srv/kivou/releases/frontend-*-$KIVOU_RELEASE_SHORT) ;;
  (*) exit 69 ;;
esac
test -f "$KIVOU_FRONTEND_RELEASE/index.html"
find "$KIVOU_FRONTEND_RELEASE/assets" -type f -print -quit | grep -q .
KIVOU_PREVIOUS_FRONTEND=$(readlink -f /srv/kivou/frontend)
case "$KIVOU_PREVIOUS_FRONTEND" in
  (/srv/kivou/releases/frontend-*) ;;
  (*) exit 69 ;;
esac
sudo test ! -e /srv/kivou/frontend.new
sudo test ! -e /srv/kivou/frontend.rollback
sudo ln -s "$KIVOU_FRONTEND_RELEASE" /srv/kivou/frontend.new
sudo chown -h kivou:kivou /srv/kivou/frontend.new
test "$(readlink -f /srv/kivou/frontend.new)" = "$KIVOU_FRONTEND_RELEASE"
sudo mv -Tf /srv/kivou/frontend.new /srv/kivou/frontend
http_smoke() {
  for KIVOU_PATH in / /produit /tarifs /login /app/dashboard; do
    curl -fsS --connect-timeout 2 --max-time 5 \
      --resolve staging.kivou.eu:443:127.0.0.1 \
      "https://staging.kivou.eu$KIVOU_PATH" >/dev/null || return 1
  done
}
if ! http_smoke; then
  sudo ln -s "$KIVOU_PREVIOUS_FRONTEND" /srv/kivou/frontend.rollback
  sudo chown -h kivou:kivou /srv/kivou/frontend.rollback
  sudo mv -Tf /srv/kivou/frontend.rollback /srv/kivou/frontend
  exit 1
fi
test "$(readlink -f /srv/kivou/frontend)" = "$KIVOU_FRONTEND_RELEASE"
REMOTE
```

Expected: frontend target suffix is the first 12 characters of `MAIN_SHA`.
Keep the prior release for rollback; the command restores it on an immediate
HTTP failure. Do not restart or edit nginx when its configuration has not
changed.

- [ ] **Step 10: Verify deployed SHA and clean local build worktree**

```bash
ssh kivou-staging 'set -eu
APP=$(readlink -f /srv/kivou/app)
FRONT=$(readlink -f /srv/kivou/frontend)
sudo -u kivou git -C "$APP" rev-parse HEAD
printf "%s\n%s\n" "$APP" "$FRONT"
systemctl is-active kivou-api.service nginx.service
'
cd /home/jaybe/.config/superpowers/worktrees/Kivou/exact-reference-port
git worktree remove "$BUILD_WORKTREE"
rmdir "$BUILD_ROOT"
```

Expected: backend SHA equals `MAIN_SHA`, frontend suffix matches `MAIN_SHA`, and
both services remain active.

## Task 16: Validate the version actually visible on staging

**Files:**
- Store screenshots/traces outside Git under a mode-700 temporary evidence
  directory; do not persist test credentials.

- [ ] **Step 1: Open a real browser session without logging secrets**

Use the Playwright skill and the already-authorized test account. Credentials
must never appear in shell arguments, files, screenshots, Git, or reports. If a
new authentication challenge cannot be completed with the existing session,
pause only for the user to take over that browser step.

- [ ] **Step 2: Validate all public routes at 1440px and 390px**

Inspect directly on `https://staging.kivou.eu`:

```text
/
/produit
/tarifs
/exemple-de-signal
/contact
/informations-legales
/login
/signup
```

For each route, require HTTP success, exact reference shell/composition, no
horizontal overflow, no critical console error, correct menu/CTA routes, and
working mobile navigation. Specifically prove `/produit` and `/tarifs` are not
404, `/tarifs` values match the live `/billing/plans` response, contact retains
the intended mail handoff, legal anchors work, and legacy redirects land on the
canonical legal sections.

- [ ] **Step 3: Validate all connected routes at 1440px and 390px**

Inspect:

```text
/app/dashboard
/app/signals
/app/companies
/app/icps
/app/billing
/app/notifications
/app/settings
/app/settings/profile
```

Require the exact dark-green reference sidebar with:

```text
Vue d’ensemble
Signaux
Entreprises
Profil de ciblage
Compte
```

Prove `/app/dashboard` is Overview. Select the first real unlocked signal from
the live feed and prove its `/app/signals/{id}` detail, official source,
company link, and private note read/write. Select a locked signal and prove no
detail request occurs and no identity leaks. Verify companies are only those
reachable through unlocked signals. Verify empty/loading/error wording is
honest and no fixed reference demo record appears.

For the existing Essential test subscription, compare `/me`, `/target-icps`,
`/billing/status`, and `/signals?limit=50`. An active Essential plan with a
complete active ICP must not be explained away as “normal” when the feed is
empty: inspect the account-scoped materialized-signal/eligibility path and the
current staging logs read-only, identify the exact missing prerequisite, and
either fix only a proven deployment defect through a tested PR or report the
precise external/data blocker. Never insert demo signals or loosen matching.

Use the opaque `account_id` returned by `/me` and
`entitlements.max_active_icps` returned by `/billing/status` only in memory.
Run this count-only diagnostic through the protected staging environment; it
prints no e-mail, company, signal, ICP label, database URL, or source payload:

```bash
test -n "$ACCOUNT_ID"
printf '%s\n' "$ACCOUNT_ID" | grep -Eq '^[A-Za-z0-9_-]{1,64}$'
printf '%s\n' "$MAX_ACTIVE_ICPS" | grep -Eq '^[0-9]+$'
ssh kivou-staging 'bash -s' -- "$ACCOUNT_ID" "$MAX_ACTIVE_ICPS" <<'REMOTE'
set -euo pipefail
KIVOU_ACCOUNT_ID=$1
KIVOU_MAX_ACTIVE_ICPS=$2
KIVOU_APP=$(readlink -f /srv/kivou/app)
case "$KIVOU_APP" in (/srv/kivou/releases/backend-*) ;; (*) exit 69 ;; esac
KIVOU_DIAGNOSTIC_UNIT=kivou-feed-diagnostic-$(date -u +%Y%m%dT%H%M%SZ)
sudo systemd-run --wait --collect --pipe --quiet \
  --unit="$KIVOU_DIAGNOSTIC_UNIT" \
  --property=Type=oneshot --property=User=kivou --property=Group=kivou \
  --property=WorkingDirectory="$KIVOU_APP" \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --property=NoNewPrivileges=yes --property=PrivateTmp=yes \
  --property=ProtectHome=yes \
  -- "$KIVOU_APP/.venv/bin/python" - "$KIVOU_ACCOUNT_ID" "$KIVOU_MAX_ACTIVE_ICPS" <<'PY'
import json
import sys
import sqlalchemy as sa
from signals.accounts.schema import target_icp
from signals.billing.service import feedable_target_icps
from signals.persistence.database import create_database_engine
from signals.persistence.schema import materialized_signal

account_id = sys.argv[1]
max_active = int(sys.argv[2])
engine = create_database_engine()
owned = target_icp.join(
    materialized_signal,
    target_icp.c.target_icp_id == materialized_signal.c.target_icp_id,
)

with engine.connect() as connection:
    allowed = feedable_target_icps(
        connection, account_id=account_id, limit=max_active,
    )
    def profile_count(*conditions):
        return connection.execute(
            sa.select(sa.func.count()).select_from(target_icp).where(
                target_icp.c.account_id == account_id, *conditions,
            )
        ).scalar_one()
    def signal_count(*conditions):
        return connection.execute(
            sa.select(sa.func.count()).select_from(owned).where(
                target_icp.c.account_id == account_id, *conditions,
            )
        ).scalar_one()
    counts = {
        "profiles_total": profile_count(),
        "profiles_active": profile_count(target_icp.c.status == "active"),
        "profiles_plan_limited": profile_count(target_icp.c.plan_limit_code.is_not(None)),
        "profiles_feedable": len(allowed),
        "signals_owned": signal_count(),
        "signals_for_feedable_profiles": (
            signal_count(materialized_signal.c.target_icp_id.in_(allowed)) if allowed else 0
        ),
        "signals_invalidated": signal_count(materialized_signal.c.invalidated_at.is_not(None)),
        "signals_revision_stale": signal_count(
            materialized_signal.c.target_icp_revision != target_icp.c.matching_revision,
        ),
        "signals_current": signal_count(
            target_icp.c.status == "active",
            target_icp.c.plan_limit_code.is_(None),
            materialized_signal.c.invalidated_at.is_(None),
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
        ),
    }
print(json.dumps(counts, sort_keys=True))
PY
REMOTE
```

Interpret the counts together with the live feed's
`excluded.by_freshness`/`excluded.without_display_name`, never alone. If the
account is paid and feedable but `signals_owned` is zero, inspect the latest
completed staging ingestion/acquisition invocation boundary and its result,
not historical journal failures:

```bash
ssh kivou-staging 'set -eu
systemctl list-timers --all "kivou-*" --no-pager
systemctl list-units --all "kivou-*" --no-pager
journalctl --since "24 hours ago" -u "kivou-*.service" \
  --grep "result=\|status=\|FAILED\|BLOCKED\|SUPPRESSED" \
  --no-pager -n 250
'
```

Stop before any ingestion/provider mutation. A data-source outage, absent
eligible award, or acquisition suppression is reported as the precise blocker;
only a reproducible code/deployment defect may enter the hotfix path.

- [ ] **Step 4: Validate plan, paywall, subscription, and Stripe TEST handoffs**

Compare UI state with live `/billing/status` and `/billing/plans`. Require real
plan, real accessible-signal counts, backend `billing_action`, and cancellation
date/state. Exercise only the action the server permits:

- if `manage_subscription` or `recover_payment`, open the Stripe TEST Customer
  Portal and confirm the cancellation/manage controls load;
- if `choose_plan`, verify the selected live offer creates a Stripe TEST
  Checkout URL without completing another charge;
- if `contact_support`, verify no Stripe call occurs.

Do not mutate production or use LIVE Stripe.

- [ ] **Step 5: Validate locale and notifications**

Change the test account locale from Account settings, confirm `PATCH /me` 200,
session re-render, translated connected navigation, and localized API data.
Change it back to French after proof, as requested. Read and submit
notification settings only with deliberate test values; verify their API
response and that no unrelated resource disappears.

- [ ] **Step 6: Compare deployed captures to reference captures**

Use the same Chromium version and viewport sizes as Task 12. Dynamic text may
differ because live data is authoritative; compare DOM classes and computed
geometry for each corresponding component, and use masked-text screenshot diffs
to prove layout/color/spacing parity. Any unapproved structural or styling
difference blocks completion.

- [ ] **Step 7: Review network, console, runtime, and production exclusion**

Require:

```text
- no critical browser console error;
- no 5xx on required API calls;
- no forbidden locked-detail/company request;
- no demo/localStorage fallback;
- backend and frontend targets still match MAIN_SHA;
- API service, nginx, and backup timer active;
- no production host, service, database, DNS, Stripe LIVE, or provider mutation.
```

- [ ] **Step 8: Produce the mandatory final verdict**

Use `superpowers:verification-before-completion` immediately before reporting.
Report exactly one verdict:

```text
STAGING DÉPLOYÉ ET VALIDÉ
```

only if every direct staging check above passed. Otherwise report:

```text
STAGING NON DÉPLOYÉ
```

Then list the exact deployed commit, merged PR, PR/main CI, deployment state,
public routes checked, connected routes checked, anomalies, GitHub links, and
staging link. Never infer visible staging correctness from CI, HTTP 200, or a
symlink alone.
