# Founder Console Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer une Founder Console cohérente qui affiche une seule vérité d'acquisition, un tunnel commercial période/cohorte, un annuaire qualifié en français et l'audit opérationnel de `localbiz.fr`.

**Architecture:** Deux read models ciblés (`acquisition_status.py` et `commercial_tunnel.py`) deviennent les sources de vérité affichées et sont composés par `FounderReadService`; l'ancien cockpit reste présent dans l'API mais n'est plus rendu. L'audit des domaines reste une commande d'exploitation séparée utilisant `rejected_supplier_domain()` et `SupplierDirectoryStore.mark_for_reverification()`. Le frontend partage un seul composant d'état entre Aujourd'hui, Prospection et Système et conserve toutes les routes Founder en lecture seule.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy Core, PostgreSQL/SQLite de test, React 19, TypeScript, Vitest/Testing Library, Playwright, nginx/systemd.

---

### Task 1: Source d'état acquisition unique

**Files:**
- Create: `src/signals/founder_api/acquisition_status.py`
- Modify: `src/signals/founder_api/prospection.py`
- Modify: `src/signals/founder_api/read_models.py`
- Test: `tests/founder_api/test_acquisition_status.py`
- Test: `tests/founder_api/test_prospection.py`
- Test: `tests/founder_api/test_read_models.py`

- [ ] **Step 1: Écrire les tests rouges du contrat et de systemd**

```python
def test_status_joins_runtime_observation_cycle_and_running_timer(engine) -> None:
    _seed_runtime_observation(
        engine,
        mode="SHADOW",
        last_cycle_ref="cycle-1",
        last_cycle_status="SUPPRESSED",
        last_cycle_at=NOW - dt.timedelta(hours=1),
    )
    status = FounderAcquisitionStatusReadService(
        engine,
        timer_reader=lambda _: FounderAcquisitionActivity(
            activity="RUNNING",
            activity_since=NOW - dt.timedelta(hours=2),
        ),
    ).read(now=NOW)
    assert status.mode == "SHADOW"
    assert status.activity == "RUNNING"
    assert status.activity_since == NOW - dt.timedelta(hours=2)
    assert status.last_cycle_ref == "cycle-1"
    assert status.last_cycle_status == "SUPPRESSED"
    assert status.last_cycle_reason_code == "NO_ELIGIBLE_OPPORTUNITY"


def test_status_fails_closed_without_observation_or_stable_systemd_state(engine) -> None:
    status = FounderAcquisitionStatusReadService(
        engine,
        timer_reader=lambda _: FounderAcquisitionActivity(activity="UNKNOWN"),
    ).read(now=NOW)
    assert status.mode is None
    assert status.activity == "UNKNOWN"
    assert status.activity_since is None
    assert status.last_cycle_ref is None


def test_systemd_reader_uses_active_and_inactive_enter_timestamps() -> None:
    running = SystemdAcquisitionActivityReader(
        run=_systemctl_result("ActiveState=active\nActiveEnterTimestamp=Fri 2026-09-11 06:00:00 UTC\n")
    )(NOW)
    stopped = SystemdAcquisitionActivityReader(
        run=_systemctl_result("ActiveState=inactive\nInactiveEnterTimestamp=Thu 2026-09-10 07:48:16 UTC\n")
    )(NOW)
    assert running.activity_since == dt.datetime(2026, 9, 11, 6, tzinfo=dt.UTC)
    assert stopped.activity_since == dt.datetime(2026, 9, 10, 7, 48, 16, tzinfo=dt.UTC)
```

- [ ] **Step 2: Exécuter les tests et constater l'absence du nouveau contrat**

Run: `uv run pytest -q -n 0 tests/founder_api/test_acquisition_status.py`

Expected: FAIL pendant la collecte avec `ModuleNotFoundError: signals.founder_api.acquisition_status`.

- [ ] **Step 3: Créer le contrat, le lecteur systemd et l'agrégateur SQL minimal**

```python
class FounderAcquisitionActivity(FounderContract):
    activity: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    activity_since: dt.datetime | None = None


class FounderAcquisitionStatus(FounderContract):
    mode: str | None = None
    activity: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    activity_since: dt.datetime | None = None
    last_cycle_ref: str | None = None
    last_cycle_at: dt.datetime | None = None
    last_cycle_status: str | None = None
    last_cycle_reason_code: str | None = None


class SystemdAcquisitionActivityReader:
    _PROPERTIES = (
        "LoadState",
        "ActiveState",
        "ActiveEnterTimestamp",
        "InactiveEnterTimestamp",
    )


class FounderAcquisitionStatusReadService:
    def read(self, *, now: dt.datetime) -> FounderAcquisitionStatus:
        activity = self._timer_reader(now)
        with self._engine.connect() as connection:
            observation = connection.execute(
                sa.select(acquisition_runtime_observation).where(
                    acquisition_runtime_observation.c.runtime_name == "acquisition-run-once",
                    acquisition_runtime_observation.c.environment == "PRODUCTION",
                )
            ).mappings().one_or_none()
            cycle = None if observation is None or observation["last_cycle_ref"] is None else (
                connection.execute(
                    sa.select(acquisition_runtime_cycle).where(
                        acquisition_runtime_cycle.c.cycle_ref == observation["last_cycle_ref"]
                    )
                ).mappings().one_or_none()
            )
        return _status_from_rows(activity=activity, observation=observation, cycle=cycle)
```

Le motif est pris dans `acquisition_runtime_cycle.last_reason_code`, colonne déjà présente dans le schéma. Le lecteur retourne `UNKNOWN` et aucune date pour tout état autre que `active` ou `inactive`.

- [ ] **Step 4: Injecter exactement le même objet dans Overview et Prospection**

```python
status = self._acquisition_status.read(now=now)
return FounderConsoleOverview(
    generated_at=now,
    acquisition_status=status,
    today=today,
    attention=attention,
    business=business,
    commercial_tunnel=tunnel,
    quality=quality,
    system=system,
)

return FounderProspection(
    generated_at=now,
    acquisition_status=status,
    queue=queue,
    directory=directory,
    targeting=targeting,
    results=results,
)
```

Supprimer `FounderAcquisitionTimer` de la réponse Prospection et supprimer `system_status`, `hermes_status` et `highest_safe_mode` de `FounderTodaySummary`; conserver les modèles techniques sous `system.health` et `system.readiness` pour diagnostic sans les présenter comme une seconde vérité.

- [ ] **Step 5: Vérifier les contrats et leur identité sémantique**

Run: `uv run pytest -q -n 0 tests/founder_api/test_acquisition_status.py tests/founder_api/test_prospection.py tests/founder_api/test_read_models.py`

Expected: PASS, avec les réponses Overview et Prospection contenant les mêmes valeurs d'état pour le même `now` et le même lecteur.

- [ ] **Step 6: Commit**

```bash
git add src/signals/founder_api/acquisition_status.py src/signals/founder_api/prospection.py src/signals/founder_api/read_models.py tests/founder_api/test_acquisition_status.py tests/founder_api/test_prospection.py tests/founder_api/test_read_models.py
git commit -m "feat(founder): unify acquisition status"
```

### Task 2: Read model du tunnel par période et par cohorte

**Files:**
- Create: `src/signals/founder_api/commercial_tunnel.py`
- Modify: `src/signals/founder_api/read_models.py`
- Modify: `src/signals/founder_api/app.py`
- Test: `tests/founder_api/test_commercial_tunnel.py`
- Test: `tests/founder_api/test_read_models.py`

- [ ] **Step 1: Écrire les tests rouges des bornes calendaires et des dates propres aux étapes**

```python
@pytest.mark.parametrize(
    ("period", "expected_start"),
    [
        (FounderTunnelPeriod.TODAY, dt.datetime(2026, 9, 11, 22, tzinfo=dt.UTC)),
        (FounderTunnelPeriod.LAST_7_DAYS, dt.datetime(2026, 9, 5, 22, tzinfo=dt.UTC)),
    ],
)
def test_period_bounds_use_zurich_midnight(period, expected_start) -> None:
    bounds = period_bounds(dt.datetime(2026, 9, 12, 8, tzinfo=dt.UTC), period)
    assert bounds.start == expected_start
    assert bounds.end == dt.datetime(2026, 9, 12, 8, tzinfo=dt.UTC)


def test_period_counts_each_stage_at_its_own_date(engine) -> None:
    _seed_journey(
        engine,
        sent_at=NOW - dt.timedelta(days=20),
        opened_at=NOW - dt.timedelta(days=2),
        clicked_at=NOW - dt.timedelta(days=1),
        landed_at=NOW - dt.timedelta(hours=20),
        confirmed_at=NOW - dt.timedelta(hours=12),
        paid_at=NOW - dt.timedelta(hours=2),
    )
    tunnel = FounderCommercialTunnelReadService(engine).read(
        now=NOW, period=FounderTunnelPeriod.LAST_7_DAYS, week_offset=0
    )
    assert tunnel.period.sent_count == 0
    assert tunnel.period.opened_count == 1
    assert tunnel.period.click_count == 1
    assert tunnel.period.landing_count == 1
    assert tunnel.period.confirmed_profile_count == 1
    assert tunnel.period.paid_count == 1
```

- [ ] **Step 2: Écrire le test rouge de cohorte ouverte et de situation actuelle**

```python
def test_cohort_includes_click_at_day_ten_and_current_values_ignore_view(engine) -> None:
    sent_at = COMPLETED_WEEK_START + dt.timedelta(hours=4)
    _seed_journey(
        engine,
        sent_at=sent_at,
        opened_at=sent_at + dt.timedelta(days=2),
        clicked_at=sent_at + dt.timedelta(days=10),
        landed_at=sent_at + dt.timedelta(days=10, minutes=1),
        confirmed_at=sent_at + dt.timedelta(days=11),
        paid_at=sent_at + dt.timedelta(days=12),
        mrr_minor_units=19_900,
    )
    result = FounderCommercialTunnelReadService(engine).read(
        now=NOW, period=FounderTunnelPeriod.TODAY, week_offset=0
    )
    assert result.cohort.sent_count == 1
    assert result.cohort.click_count == 1
    assert result.cohort.paid_count == 1
    assert result.current.mrr_by_currency[0].minor_units == 19_900
    assert result.current.churn_count == 0
```

- [ ] **Step 3: Exécuter les tests rouges**

Run: `uv run pytest -q -n 0 tests/founder_api/test_commercial_tunnel.py`

Expected: FAIL pendant la collecte avec le module `commercial_tunnel` absent.

- [ ] **Step 4: Créer les contrats et les bornes Europe/Zurich**

```python
class FounderTunnelPeriod(StrEnum):
    TODAY = "today"
    LAST_7_DAYS = "last_7_days"


class FounderTunnelCounts(FounderContract):
    sent_count: int = Field(ge=0)
    opened_count: int = Field(ge=0)
    click_count: int = Field(ge=0)
    landing_count: int = Field(ge=0)
    confirmed_profile_count: int = Field(ge=0)
    paid_count: int = Field(ge=0)


class FounderTunnelSlice(FounderTunnelCounts):
    start_at: dt.datetime
    end_at: dt.datetime


class FounderTunnelCurrent(FounderContract):
    observed_at: dt.datetime
    mrr_by_currency: tuple[FounderMoneyTotal, ...]
    churn_count: int = Field(ge=0)


class FounderCommercialTunnel(FounderContract):
    period_kind: FounderTunnelPeriod
    period: FounderTunnelSlice
    cohort_week_offset: int = Field(ge=0, le=51)
    cohort: FounderTunnelSlice
    current: FounderTunnelCurrent
```

`period_bounds()` convertit `now` en `ZoneInfo("Europe/Zurich")`, remplace l'heure par minuit local, soustrait six jours pour `last_7_days`, puis reconvertit la borne en UTC.

- [ ] **Step 5: Implémenter les requêtes SQL bornées**

```python
sent = _distinct_between(
    connection,
    acquisition_campaign_member.c.member_ref,
    acquisition_campaign_member.c.step_1_sent_at,
    bounds,
)
opened = _distinct_between(
    connection,
    acquisition_provider_event.c.member_ref,
    acquisition_provider_event.c.occurred_at,
    bounds,
    acquisition_provider_event.c.provider_event_type == "email_opened",
    acquisition_provider_event.c.resolution_state.in_(("ACCEPTED", "PROCESSED")),
)
clicks = _distinct_between(
    connection,
    acquisition_conversion_event.c.conversion_event_ref,
    acquisition_conversion_event.c.occurred_at,
    bounds,
    acquisition_conversion_event.c.milestone == "CLICK",
)
```

Les atterrissages et profils utilisent `account_landing_signal.created_at` et `profile_confirmed_at` avec `qa IS FALSE`. Les payants utilisent les comptes distincts des événements `PAID`. La cohorte part d'une sous-requête des `member_ref` envoyés dans la semaine terminée et joint `acquisition_provider_event.member_ref`, `acquisition_conversion_journey.member_ref`, puis les comptes sans appliquer de borne haute autre que `now` et sans compter un événement antérieur à `step_1_sent_at`.

- [ ] **Step 6: Calculer MRR et churn à l'instant présent**

```python
for journey_ref, events in _events_by_journey(rows).items():
    latest_mrr = next(
        (row for row in reversed(events) if row["milestone"] == "MRR_CHANGED"),
        None,
    )
    churned = events[-1]["milestone"] == "CHURNED"
    if churned:
        churn_count += 1
    if churned or latest_mrr is None or latest_mrr["mrr_known"] is not True:
        continue
    totals[str(latest_mrr["currency"]).upper()] += int(latest_mrr["mrr_minor_units"])
```

- [ ] **Step 7: Exposer les sélecteurs bornés dans Overview**

```python
@app.get("/api/founder/overview")
def founder_overview(
    identity: FounderIdentityDependency,
    week_offset: Annotated[int, Query(ge=0, le=51)] = 0,
    period: FounderTunnelPeriod = FounderTunnelPeriod.LAST_7_DAYS,
) -> FounderConsoleOverview:
    return service.overview(now=now(), week_offset=week_offset, period=period)
```

- [ ] **Step 8: Vérifier tunnel, route et régressions Founder**

Run: `uv run pytest -q -n 0 tests/founder_api/test_commercial_tunnel.py tests/founder_api/test_read_models.py tests/founder_api/test_access.py`

Expected: PASS, `period=today|last_7_days` accepté, `week_offset=0..51` accepté et les autres valeurs rejetées en 422.

- [ ] **Step 9: Commit**

```bash
git add src/signals/founder_api/commercial_tunnel.py src/signals/founder_api/read_models.py src/signals/founder_api/app.py tests/founder_api/test_commercial_tunnel.py tests/founder_api/test_read_models.py
git commit -m "feat(founder): add period and cohort tunnel"
```

### Task 3: Liste noire `localbiz.fr` et audit idempotent

**Files:**
- Modify: `src/signals/company_research/domain.py`
- Create: `src/signals/supplier_directory/domain_audit.py`
- Test: `tests/test_company_domain_resolution.py`
- Test: `tests/test_supplier_directory_domain_audit.py`
- Modify: `docs/FOUNDER_CONSOLE.md`

- [ ] **Step 1: Écrire les tests rouges du rejet exact et des sous-domaines**

```python
@pytest.mark.parametrize("domain", ["localbiz.fr", "neyron.localbiz.fr"])
def test_localbiz_is_rejected_as_a_directory(domain: str) -> None:
    assert rejected_supplier_domain(domain) is True
```

- [ ] **Step 2: Écrire les tests rouges simulation/application/idempotence**

```python
def test_domain_audit_is_dry_run_by_default_and_apply_is_idempotent(engine) -> None:
    _seed_confirmed_directory_row(
        engine,
        siren="402274716",
        domain="neyron.localbiz.fr",
        email="contact@neyron.localbiz.fr",
    )
    dry_run = audit_confirmed_domains(engine, observed_at=NOW, apply=False)
    assert dry_run.examined_count == 1
    assert dry_run.affected_count == 1
    assert dry_run.modified_count == 0
    assert SupplierDirectoryStore(engine).get("402274716").domain == "neyron.localbiz.fr"

    applied = audit_confirmed_domains(engine, observed_at=NOW, apply=True)
    row = SupplierDirectoryStore(engine).get("402274716")
    assert applied.modified_count == 1
    assert row.domain is None
    assert row.professional_email is None
    assert row.apollo_organization_id is None
    assert row.reverification_reason == "blocked_domain_audit"

    second = audit_confirmed_domains(engine, observed_at=NOW, apply=True)
    assert second.affected_count == 0
    assert second.modified_count == 0
```

- [ ] **Step 3: Exécuter les tests rouges**

Run: `uv run pytest -q -n 0 tests/test_company_domain_resolution.py tests/test_supplier_directory_domain_audit.py`

Expected: FAIL sur `localbiz.fr` et sur l'import du module d'audit absent.

- [ ] **Step 4: Ajouter le domaine et la commande d'exploitation**

```python
_DIRECTORY_DOMAINS = frozenset(
    {
        "linkedin.com",
        "localbiz.fr",
        "manageo.fr",
    }
)


class DomainAuditResult(FounderContract):
    examined_count: int
    affected_count: int
    modified_count: int
    affected: tuple[BlockedDomainRecord, ...]


def audit_confirmed_domains(
    engine: Engine, *, observed_at: dt.datetime, apply: bool = False
) -> DomainAuditResult:
    rows = _confirmed_active_domains(engine)
    affected = tuple(
        BlockedDomainRecord(siren=str(row["siren"]), domain=str(row["domain"]))
        for row in rows
        if rejected_supplier_domain(str(row["domain"]))
    )
    modified = 0
    if apply:
        store = SupplierDirectoryStore(engine)
        modified = sum(
            store.mark_for_reverification(
                row.siren, reason="blocked_domain_audit", observed_at=observed_at
            )
            for row in affected
        )
    return DomainAuditResult(
        examined_count=len(rows),
        affected_count=len(affected),
        modified_count=modified,
        affected=affected,
    )
```

Le `main()` exige `KIVOU_DATABASE_URL`, accepte uniquement `--apply`, utilise `create_database_engine()`, écrit un JSON trié sur stdout et ne fait aucune écriture sans le drapeau.

- [ ] **Step 5: Documenter les trois commandes de production**

```bash
sudo --preserve-env=KIVOU_DATABASE_URL -u kivou \
  /srv/kivou/current/.venv/bin/python -m signals.supplier_directory.domain_audit
sudo --preserve-env=KIVOU_DATABASE_URL -u kivou \
  /srv/kivou/current/.venv/bin/python -m signals.supplier_directory.domain_audit --apply
sudo --preserve-env=KIVOU_DATABASE_URL -u kivou \
  /srv/kivou/current/.venv/bin/python -m signals.supplier_directory.domain_audit
```

- [ ] **Step 6: Vérifier l'audit et le formatage Python**

Run: `uv run pytest -q -n 0 tests/test_company_domain_resolution.py tests/test_supplier_directory_domain_audit.py && uv run ruff check src/signals/company_research/domain.py src/signals/supplier_directory/domain_audit.py tests/test_supplier_directory_domain_audit.py`

Expected: PASS et sortie Ruff vide.

- [ ] **Step 7: Commit**

```bash
git add src/signals/company_research/domain.py src/signals/supplier_directory/domain_audit.py tests/test_company_domain_resolution.py tests/test_supplier_directory_domain_audit.py docs/FOUNDER_CONSOLE.md
git commit -m "fix(directory): quarantine blocked confirmed domains"
```

### Task 4: Contrat Annuaire sûr et libellés de départements

**Files:**
- Modify: `src/signals/founder_api/prospection.py`
- Test: `tests/founder_api/test_prospection.py`

- [ ] **Step 1: Écrire le test rouge du masquage de domaine et des libellés**

```python
def test_directory_hides_unconfirmed_domain_and_names_departments(engine) -> None:
    _seed_directory_row(
        engine,
        siren="123456789",
        department="69",
        domain="candidate.example",
        website_url="https://candidate.example",
        domain_validation_method=None,
    )
    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(now=NOW)
    row = result.directory.rows[0]
    assert row.confirmed_domain is False
    assert row.domain is None
    assert row.website_url is None
    assert row.department == "69"
    assert row.department_name == "Rhône"
    assert result.directory.department_counts[0].label == "Rhône (69)"
```

- [ ] **Step 2: Exécuter le test rouge**

Run: `uv run pytest -q -n 0 tests/founder_api/test_prospection.py -k 'hides_unconfirmed_domain or names_departments'`

Expected: FAIL car le domaine brut fuit encore et les champs `department_name`/`label` sont absents.

- [ ] **Step 3: Enrichir les contrats et masquer à la projection**

```python
class FounderCountFacet(FounderContract):
    key: str
    label: str
    count: int = Field(ge=0)


class FounderDirectoryRow(FounderContract):
    department: str | None = None
    department_name: str | None = None
```

Dans `_directory_row`, calculer `confirmed = row["domain"] is not None and row["domain_validation_method"] is not None`, puis ne copier `domain` et `website_url` que si `confirmed` est vrai. Résoudre le nom via `DEPARTMENTS.get(department)` et produire les facettes avec `f"{name} ({code})"` quand le nom existe.

- [ ] **Step 4: Vérifier la pagination et les filtres existants**

Run: `uv run pytest -q -n 0 tests/founder_api/test_prospection.py`

Expected: PASS, toujours 25 lignes maximum et filtres famille/département/statut inchangés.

- [ ] **Step 5: Commit**

```bash
git add src/signals/founder_api/prospection.py tests/founder_api/test_prospection.py
git commit -m "fix(founder): expose qualified directory fields"
```

### Task 5: Contrats TypeScript et composant d'état partagé

**Files:**
- Modify: `frontend/founder/src/types.ts`
- Modify: `frontend/founder/src/api.ts`
- Create: `frontend/founder/src/AcquisitionStatus.tsx`
- Create: `frontend/founder/src/AcquisitionStatus.test.tsx`
- Modify: `frontend/founder/src/styles.css`

- [ ] **Step 1: Écrire les tests rouges du composant partagé**

```tsx
it('rend le mode, la durée et le dernier résultat en français', () => {
  render(<AcquisitionStatus status={STOPPED_STATUS} />)
  expect(screen.getByText('Mode observation')).toBeInTheDocument()
  expect(screen.getByText(/Arrêté depuis le/)).toBeInTheDocument()
  expect(screen.getByText(/Dernier cycle/)).toBeInTheDocument()
  expect(screen.getByText(/Supprimé/)).toBeInTheDocument()
})

it('ne confond pas un état inconnu avec un arrêt', () => {
  render(<AcquisitionStatus status={{ ...STOPPED_STATUS, activity: 'UNKNOWN', activity_since: null }} />)
  expect(screen.getByText('État indisponible')).toBeInTheDocument()
  expect(screen.queryByText(/Arrêté depuis/)).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Exécuter le test rouge**

Run: `npm --prefix frontend test -- --run founder/src/AcquisitionStatus.test.tsx`

Expected: FAIL car `AcquisitionStatus.tsx` n'existe pas.

- [ ] **Step 3: Définir les types exacts et les paramètres d'API**

```ts
export interface FounderAcquisitionStatus {
  mode: string | null
  activity: 'RUNNING' | 'STOPPED' | 'UNKNOWN'
  activity_since: string | null
  last_cycle_ref: string | null
  last_cycle_at: string | null
  last_cycle_status: string | null
  last_cycle_reason_code: string | null
}

export type FounderTunnelPeriod = 'today' | 'last_7_days'

export interface FounderTunnelCounts {
  sent_count: number
  opened_count: number
  click_count: number
  landing_count: number
  confirmed_profile_count: number
  paid_count: number
}
```

`loadFounderOverview(weekOffset, period, signal)` encode `week_offset` et `period`; `last_7_days` reste la valeur initiale dans `FounderApp`.

- [ ] **Step 4: Implémenter le composant partagé et les traductions**

```tsx
export function AcquisitionStatus({ status, compact = false }: Props) {
  return (
    <section className={compact ? 'control-runtime control-runtime--compact' : 'control-runtime'} aria-label="État de l’acquisition">
      <div><span>Mode</span><strong>{modeLabel(status.mode)}</strong></div>
      <div><span>Activité</span><strong>{activityLabel(status)}</strong></div>
      <div><span>Dernier cycle</span><strong>{cycleLabel(status)}</strong></div>
      <div><span>Résultat</span><strong>{cycleStatusLabel(status.last_cycle_status)}</strong></div>
    </section>
  )
}
```

Les dictionnaires rendent au minimum `SHADOW` → `Mode observation`, `RUNNING` → `Actif`, `STOPPED` → `Arrêté`, `SUPPRESSED` → `Supprimé`, `SUCCEEDED` → `Réussi`, `FAILED` → `Échoué`, et toute absence → `Inconnu`/`Aucun cycle observé` selon le champ.

- [ ] **Step 5: Vérifier composant et types**

Run: `npm --prefix frontend test -- --run founder/src/AcquisitionStatus.test.tsx && npm --prefix frontend run typecheck`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/founder/src/types.ts frontend/founder/src/api.ts frontend/founder/src/AcquisitionStatus.tsx frontend/founder/src/AcquisitionStatus.test.tsx frontend/founder/src/styles.css
git commit -m "feat(founder): share acquisition status presentation"
```

### Task 6: Aujourd'hui et Système sans états contradictoires

**Files:**
- Modify: `frontend/founder/src/FounderApp.tsx`
- Modify: `frontend/founder/src/FounderApp.test.tsx`
- Modify: `frontend/founder/src/styles.css`

- [ ] **Step 1: Écrire le test rouge d'absence des anciens états**

```tsx
it('affiche la source acquisition unique sur Aujourd’hui et Système', async () => {
  render(<FounderApp />)
  await screen.findByRole('heading', { name: 'Aujourd’hui' })
  expect(screen.getAllByLabelText('État de l’acquisition')).toHaveLength(2)
  expect(screen.queryByText(/État global/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Hermes : Prêt/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Mode sûr actuel/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Runtime Hermes/)).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Écrire le test rouge des deux vues du tunnel**

```tsx
it('ouvre sur 7 jours et permet période, aujourd’hui et cohorte', async () => {
  const user = userEvent.setup()
  render(<FounderApp />)
  await screen.findByRole('heading', { name: 'Tunnel commercial' })
  expect(screen.getByRole('button', { name: '7 derniers jours' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByText('Envoyés')).toBeInTheDocument()
  expect(screen.getByText('Ouverts')).toBeInTheDocument()
  expect(screen.getByText('Clics')).toBeInTheDocument()
  expect(screen.getByText('Atterrissages')).toBeInTheDocument()
  expect(screen.getByText('Profils confirmés')).toBeInTheDocument()
  expect(screen.getByText('Payants')).toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: 'Par cohorte' }))
  expect(screen.getByText(/Cohorte envoyée/)).toBeInTheDocument()
  expect(screen.getByText('Situation actuelle')).toBeInTheDocument()
  expect(screen.getByText('MRR')).toBeInTheDocument()
  expect(screen.getByText('Churn')).toBeInTheDocument()
})
```

- [ ] **Step 3: Vérifier que les tests échouent sur l'écran actuel**

Run: `npm --prefix frontend test -- --run founder/src/FounderApp.test.tsx`

Expected: FAIL sur les anciens libellés et sur l'absence d'onglets du tunnel.

- [ ] **Step 4: Remplacer l'entête Aujourd'hui et le résumé Système**

Utiliser `<AcquisitionStatus status={overview.acquisition_status} />` sous l'entête Aujourd'hui et `<AcquisitionStatus status={overview.acquisition_status} compact />` en tête de Système. Garder incidents, lettres mortes, santé détaillée et gates; retirer les cartes et lignes qui reformulent `system_status`, Hermes ou `highest_safe_mode` comme état global.

- [ ] **Step 5: Remplacer Business par Tunnel commercial**

```tsx
<section id="business" className="control-section">
  <SectionHeading eyebrow="Acquisition et revenu" title="Tunnel commercial" />
  <div role="tablist" aria-label="Vue du tunnel commercial">
    <button role="tab" aria-selected={view === 'period'} onClick={() => setView('period')}>Période</button>
    <button role="tab" aria-selected={view === 'cohort'} onClick={() => setView('cohort')}>Par cohorte</button>
  </div>
  {view === 'period' ? <PeriodTunnel tunnel={overview.commercial_tunnel} /> : <CohortTunnel tunnel={overview.commercial_tunnel} />}
  <CurrentCommercialSituation current={overview.commercial_tunnel.current} />
</section>
```

La vue Période propose deux boutons `Aujourd'hui` et `7 derniers jours`; l'onglet Cohorte conserve le sélecteur des semaines terminées. Retirer du DOM proxy, réponses positives, M2, wedge, secteurs non résolus et le tableau analytique; ne pas supprimer leurs champs API.

- [ ] **Step 6: Vérifier l'interface et l'accessibilité de base**

Run: `npm --prefix frontend test -- --run founder/src/FounderApp.test.tsx founder/src/AcquisitionStatus.test.tsx && npm --prefix frontend run typecheck && npm --prefix frontend run lint`

Expected: PASS, aucun ancien libellé dans le rendu.

- [ ] **Step 7: Commit**

```bash
git add frontend/founder/src/FounderApp.tsx frontend/founder/src/FounderApp.test.tsx frontend/founder/src/styles.css
git commit -m "feat(founder): present period and cohort tunnel"
```

### Task 7: Prospection corrigée et entièrement française

**Files:**
- Modify: `frontend/founder/src/ProspectionPage.tsx`
- Modify: `frontend/founder/src/ProspectionPage.test.tsx`
- Modify: `frontend/founder/src/styles.css`

- [ ] **Step 1: Écrire les tests rouges d'ordre, d'état vide et de qualification**

```tsx
it('place toujours File du jour avant Annuaire et reprend le même état acquisition', () => {
  render(<ProspectionPage {...props} />)
  const queue = screen.getByRole('heading', { name: 'File du jour' })
  const directory = screen.getByRole('heading', { name: 'Annuaire' })
  expect(queue.compareDocumentPosition(directory) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByText(/Aucune cible en attente de revue/)).toBeInTheDocument()
  expect(screen.getByLabelText('État de l’acquisition')).toBeInTheDocument()
})

it('masque les domaines non confirmés et traduit les données', () => {
  render(<ProspectionPage {...propsWithUnconfirmedDomain} />)
  expect(screen.queryByText('candidate.example')).not.toBeInTheDocument()
  expect(screen.getByText('À qualifier')).toBeInTheDocument()
  expect(screen.getByText('Rhône (69)')).toBeInTheDocument()
  expect(screen.getByText('MX vérifié')).toBeInTheDocument()
  expect(screen.queryByText('supplier_directory')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Exécuter les tests rouges**

Run: `npm --prefix frontend test -- --run founder/src/ProspectionPage.test.tsx`

Expected: FAIL car Annuaire précède actuellement File du jour et les libellés/masquages ne satisfont pas le nouveau contrat.

- [ ] **Step 3: Réordonner les blocs et brancher le composant partagé**

```tsx
<main className="control-prospection-page" aria-labelledby="prospection-title">
  <ProspectionHero data={data} />
  <QueueSection data={data} onOpenMail={openMailDrawer} />
  <DirectorySection {...directoryProps} />
  <AcquisitionStatus status={data.acquisition_status} compact />
  <TargetingSection data={data} />
  <ResultsSection data={data} />
</main>
```

L'état vide dit « Aucune cible en attente de revue. La Session A n’a encore préparé aucune cible. » et affiche le dernier cycle via `AcquisitionStatus`. Les boutons restent présents, désactivés, avec `title="Disponible quand le mode assisté sera livré"` tant que le contrat Session A ne fournit pas l'action.

- [ ] **Step 4: Corriger le rendu Annuaire**

```tsx
{row.confirmed_domain && row.domain ? (
  <a href={row.website_url ?? `https://${row.domain}`} target="_blank" rel="noreferrer">{row.domain}</a>
) : (
  <StatusPill tone="neutral">À qualifier</StatusPill>
)}
```

Les lignes et options utilisent `department_name ? `${department_name} (${department})` : department`; le dictionnaire d'e-mail rend `mx_verified`, `mx_accepted`, `provider_verified` et `DELIVERABILITY_VERIFIED` en français, avec « MX vérifié » pour les deux codes MX. Le statut « À revérifier » reste prioritaire sur « À qualifier » dans la colonne État.

- [ ] **Step 5: Vérifier les tests Founder frontend complets**

Run: `npm --prefix frontend test -- --run founder/src/*.test.tsx && npm --prefix frontend run build:founder`

Expected: PASS et génération de `frontend/dist-founder`.

- [ ] **Step 6: Commit**

```bash
git add frontend/founder/src/ProspectionPage.tsx frontend/founder/src/ProspectionPage.test.tsx frontend/founder/src/styles.css
git commit -m "fix(founder): clarify prospection directory"
```

### Task 8: Intégration Session A, documentation et vérification locale

**Files:**
- Modify if required by rebase: `src/signals/founder_api/app.py`
- Modify if required by rebase: `src/signals/founder_api/prospection.py`
- Modify: `docs/FOUNDER_CONSOLE.md`
- Modify: `docs/superpowers/plans/2026-09-11-founder-console-corrections.md`

- [ ] **Step 1: Attendre que PR #224 Session A soit fusionnée puis rebaser**

Run: `git fetch origin --prune && gh pr view 224 --json state,mergeCommit,url && git rebase origin/main`

Expected: PR #224 `MERGED`, rebase terminé; en cas de conflit, conserver les routes `/api/founder/actions/*`, le contrat `pending_review` et la correction de revalidation de Session A, puis réappliquer seulement les read models/présentations de ce plan.

- [ ] **Step 2: Vérifier qu'aucune migration n'a été ajoutée par cette branche**

Run: `git diff --name-only origin/main...HEAD | rg 'persistence/migrations'`

Expected: aucune sortie.

- [ ] **Step 3: Lancer les suites ciblées en mode déterministe**

Run: `uv run pytest -q -n 0 tests/founder_api tests/test_company_domain_resolution.py tests/test_supplier_directory.py tests/test_supplier_directory_domain_audit.py`

Expected: PASS, y compris la régression `test_resolver_clears_cached_binding_domain_when_revalidation_fails` réparée par Session A.

- [ ] **Step 4: Lancer la suite locale rapide et la vérification frontend**

Run: `time uv run pytest -q`

Expected: PASS sous huit minutes, marqueurs `slow` exclus par la configuration locale.

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend run build:founder`

Expected: PASS.

- [ ] **Step 5: Vérifier le diff et mettre à jour les cases du plan**

Run: `git diff --check && git status --short && git diff --stat origin/main...HEAD`

Expected: aucun problème d'espaces, seulement les fichiers décrits dans ce plan et aucun secret.

- [ ] **Step 6: Commit de documentation si nécessaire**

```bash
git add docs/FOUNDER_CONSOLE.md docs/superpowers/plans/2026-09-11-founder-console-corrections.md
git commit -m "docs(founder): document tunnel and domain audit"
```

### Task 9: PR, CI, déploiement exact et captures desktop

**Files:**
- Create after deployment: `output/playwright/founder-console-corrections/today-period.png`
- Create after deployment: `output/playwright/founder-console-corrections/today-cohort.png`
- Create after deployment: `output/playwright/founder-console-corrections/prospection.png`
- Create after deployment: `output/playwright/founder-console-corrections/system.png`

- [ ] **Step 1: Pousser la branche et ouvrir une PR courte**

Run: `git push -u origin feat/founder-console-corrections`

Run: `gh pr create --title "fix(founder): align acquisition and commercial views" --fill`

Expected: URL d'une PR contenant résumé, sémantique période/cohorte, résultat d'audit local et commandes de test.

- [ ] **Step 2: Attendre et vérifier tous les checks GitHub**

Run: `gh pr checks --watch`

Expected: tous les checks requis `pass`.

- [ ] **Step 3: Fusionner et résoudre le SHA exact**

Run: `gh pr merge --squash --delete-branch && git fetch origin main && git rev-parse origin/main`

Expected: PR `MERGED`; conserver le SHA complet renvoyé pour le déploiement.

- [ ] **Step 4: Déployer uniquement le SHA fusionné**

Run locally: `kivou_founder_release_sha=$(gh pr view --json mergeCommit --jq '.mergeCommit.oid')`

Run on production with that exact value passed as `KIVOU_FOUNDER_RELEASE_SHA`: `sudo /srv/kivou/current/ops/bin/kivou-deploy.sh "$KIVOU_FOUNDER_RELEASE_SHA"`

Expected: migration sans nouvelle révision de cette branche, build Founder réussi, symlinks atomiques basculés, `kivou-founder-api`, application cliente et nginx sains.

- [ ] **Step 5: Exécuter l'audit de domaine en trois passes**

Run on production: `python -m signals.supplier_directory.domain_audit`

Expected before apply: `affected_count=1`, SIREN `402274716`, domaine `neyron.localbiz.fr`, `modified_count=0`.

Run on production: `python -m signals.supplier_directory.domain_audit --apply`

Expected: `modified_count=1` et motif `blocked_domain_audit`.

Run on production: `python -m signals.supplier_directory.domain_audit`

Expected after apply: `affected_count=0`, `modified_count=0`.

- [ ] **Step 6: Vérifier les frontières HTTP et services**

Run on production: `curl -sS -o /dev/null -w '%{http_code}\n' https://control.kivou.eu/`

Expected: `401` sans Basic Auth.

Run authenticated without printing credentials: `curl -sS -o /dev/null -w '%{http_code}\n' --user "$FOUNDER_BASIC_AUTH" https://control.kivou.eu/api/founder/overview`

Expected: `200`.

Run: `curl -sS -o /dev/null -w '%{http_code}\n' https://kivou.eu/api/founder/overview`

Expected: `404`.

Run: `systemctl is-active kivou-founder-api nginx && systemctl is-active kivou-api`

Expected: trois lignes `active`.

- [ ] **Step 7: Capturer les quatre vues à 1600 px avec Playwright**

À partir d'un contexte authentifié, ouvrir successivement `/`, l'onglet « Par cohorte », `/prospection`, puis `/#system`; fixer le viewport à `1600x1100`, attendre `networkidle`, vérifier l'absence d'erreur console et écrire les quatre PNG sous `output/playwright/founder-console-corrections/`.

- [ ] **Step 8: Inspecter visuellement chaque capture**

Vérifier dans les fichiers rendus : aucun chevauchement, File du jour en premier, lignes Annuaire réelles, états acquisition identiques, 6 étapes visibles, MRR/Churn séparés, textes français et aucun domaine non confirmé rendu.

- [ ] **Step 9: Handoff final avec preuves**

Donner le lien PR fusionné, le SHA déployé, les résultats exacts local/CI/audit/smoke et quatre liens cliquables vers les captures. Ne jamais inclure le mot de passe Basic Auth, le secret d'origine ou une URL PostgreSQL.
