import { useEffect, useRef, useState } from 'react'
import {
  loadFounderOverview,
  loadFounderProspection,
  loadFounderSession,
  loadFounderSystem,
} from './api'
import { AcquisitionStatus } from './AcquisitionStatus'
import { ProspectionPage } from './ProspectionPage'
import type {
  AttentionItem,
  FounderOverview,
  FounderProspection,
  FounderProspectionFilters,
  FounderSession,
  FounderSystem,
  FounderTunnelPeriod,
  GateStatus,
  HealthStatus,
  MoneyTotal,
} from './types'

type TodaySnapshot = {
  page: 'today'
  session: FounderSession
  overview: FounderOverview
}

type ProspectionSnapshot = {
  page: 'prospection'
  session: FounderSession
  prospection: FounderProspection
}

type SystemSnapshot = {
  page: 'system'
  session: FounderSession
  system: FounderSystem
}

type Snapshot = TodaySnapshot | ProspectionSnapshot | SystemSnapshot

const INITIAL_PROSPECTION_FILTERS: FounderProspectionFilters = {
  page: 1,
  q: '',
  family: '',
  department: '',
  status: '',
  reverification_reason: '',
}

const WEEK_OFFSETS = Array.from({ length: 52 }, (_, index) => index)
const STATUS_LABELS: Record<HealthStatus | GateStatus, string> = {
  READY: 'Prêt',
  DEGRADED: 'Dégradé',
  NOT_READY: 'Non prêt',
  INSUFFICIENT_EVIDENCE: 'Preuves insuffisantes',
}
const GATE_LABELS = {
  h_b_state: 'État durable',
  h_c_policy: 'Policy Gateway',
  h_d_shadow: 'Validation shadow',
  h_e_capped: 'Autonomie plafonnée',
  h_f_closed_loop: 'Boucle revenu',
  h_g_precision: 'Passage à l’échelle',
} as const

export function FounderApp() {
  const route = normalizedPathname()
  const isProspectionRoute = route === '/prospection'
  const isSystemRoute = route === '/system'
  const [weekOffset, setWeekOffset] = useState(0)
  const [period, setPeriod] = useState<FounderTunnelPeriod>('last_7_days')
  const [prospectionFilters, setProspectionFilters] = useState(INITIAL_PROSPECTION_FILTERS)
  const [refreshKey, setRefreshKey] = useState(0)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const changePeriod = (nextPeriod: FounderTunnelPeriod) => {
    if (nextPeriod === period) {
      setRefreshKey((value) => value + 1)
      return
    }
    setPeriod(nextPeriod)
  }

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    const readSnapshot = async () => {
      if (isSystemRoute) {
        const [session, system] = await Promise.all([
          loadFounderSession(controller.signal),
          loadFounderSystem(controller.signal),
        ])
        return { page: 'system', session, system } satisfies SystemSnapshot
      }
      if (isProspectionRoute) {
        const [session, prospection] = await Promise.all([
          loadFounderSession(controller.signal),
          loadFounderProspection(prospectionFilters, controller.signal),
        ])
        return { page: 'prospection', session, prospection } satisfies ProspectionSnapshot
      }
      const [session, overview] = await Promise.all([
        loadFounderSession(controller.signal),
        loadFounderOverview(weekOffset, period, controller.signal),
      ])
      return { page: 'today', session, overview } satisfies TodaySnapshot
    }
    void readSnapshot()
      .then((nextSnapshot) => {
        if (!controller.signal.aborted) setSnapshot(nextSnapshot)
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return
        setError(
          reason instanceof Error
            ? reason.message
            : 'Le service Founder est momentanément indisponible.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [
    isProspectionRoute,
    isSystemRoute,
    period,
    prospectionFilters,
    refreshKey,
    weekOffset,
  ])

  return (
    <div className="control-shell">
      <a className="control-skip-link" href="#control-main">
        Aller au contenu
      </a>
      <aside className="control-sidebar">
        <a className="control-brand" href="/" aria-label="Kivou Control — accueil">
          <span className="control-mark" aria-hidden="true">K</span>
          <span>
            <strong>Kivou</strong>
            <small>Control</small>
          </span>
        </a>
        <nav aria-label="Navigation de la console">
          <p>Console</p>
          <a href="/" aria-current={!isProspectionRoute && !isSystemRoute ? 'page' : undefined}>Aujourd’hui</a>
          <a href="/prospection" aria-current={isProspectionRoute ? 'page' : undefined}>Prospection</a>
          <a href="/system" aria-current={isSystemRoute ? 'page' : undefined}>Système</a>
        </nav>
        <div className="control-sidebar-footer">
          <span className="control-environment">
            <span aria-hidden="true" />
            Production
          </span>
          {!isProspectionRoute ? <span className="control-readonly">Consultation</span> : null}
          {snapshot ? <small>{snapshot.session.operator_email}</small> : null}
        </div>
      </aside>

      <div className="control-workspace">
        <header className="control-topbar">
          <div>
            <p>Interface privée du fondateur</p>
            <strong>Console fondateur</strong>
          </div>
          <div className="control-topbar-actions">
            {snapshot ? (
              <span className="control-updated">
                Actualisé {formatDateTime(
                  snapshot.page === 'today'
                    ? snapshot.overview.generated_at
                    : snapshot.page === 'prospection'
                      ? snapshot.prospection.generated_at
                      : snapshot.system.generated_at,
                )}
              </span>
            ) : null}
            <button
              type="button"
              className="control-refresh"
              disabled={loading}
              onClick={() => setRefreshKey((value) => value + 1)}
            >
              {loading && snapshot ? 'Actualisation…' : 'Actualiser'}
            </button>
          </div>
        </header>

        <main id="control-main" className="control-main">
          {error ? (
            <div className="control-alert" role="alert">
              <strong>Données indisponibles</strong>
              <span>{error}</span>
            </div>
          ) : null}

          {!snapshot && loading ? <LoadingState /> : null}
          {!snapshot && !loading && error ? <UnavailableState /> : null}
          {snapshot?.page === 'today' ? (
            <Console
              snapshot={snapshot}
              weekOffset={weekOffset}
              onWeekChange={setWeekOffset}
              onPeriodChange={changePeriod}
              refreshing={loading}
            />
          ) : null}
          {snapshot?.page === 'prospection' ? (
            <ProspectionPage
              data={snapshot.prospection}
              filters={prospectionFilters}
              refreshing={loading}
              onFiltersChange={setProspectionFilters}
            />
          ) : null}
          {snapshot?.page === 'system' ? <SystemPage data={snapshot.system} /> : null}
        </main>
      </div>
    </div>
  )
}

function normalizedPathname(): string {
  const pathname = window.location.pathname.replace(/\/+$/, '')
  return pathname || '/'
}

function Console({
  snapshot,
  weekOffset,
  onWeekChange,
  onPeriodChange,
  refreshing,
}: {
  snapshot: TodaySnapshot
  weekOffset: number
  onWeekChange: (value: number) => void
  onPeriodChange: (value: FounderTunnelPeriod) => void
  refreshing: boolean
}) {
  const { overview } = snapshot
  return (
    <>
      <section id="overview" className="control-section control-overview">
        <div className="control-hero control-hero--today">
          <div>
            <p className="control-eyebrow">Vue du moment</p>
            <h1>Aujourd’hui</h1>
            <p>
              L’état de l’acquisition et les faits qui demandent ton attention,
              observés au moment de la requête.
            </p>
          </div>
        </div>
        <AcquisitionStatus status={overview.acquisition_status} />

        <div className="control-summary-grid">
          <SummaryCard
            label="À traiter maintenant"
            value={formatCount(overview.today.open_attention_count)}
            detail={
              overview.today.critical_attention_count > 0
                ? `${formatCount(overview.today.critical_attention_count)} critique(s)`
                : 'Aucun élément critique'
            }
            tone={overview.today.critical_attention_count > 0 ? 'critical' : 'neutral'}
          />
          <SummaryCard
            label="Réponses positives"
            value={formatCount(overview.today.positive_replies_last_completed_week)}
            detail="Dernière semaine terminée"
          />
          <SummaryCard
            label="Comptes payants"
            value={formatCount(overview.today.paid_accounts_last_completed_week)}
            detail="Dernière semaine terminée"
          />
        </div>
      </section>

      <AttentionSection items={overview.attention} />
      <CommercialTunnelSection
        overview={overview}
        weekOffset={weekOffset}
        onWeekChange={onWeekChange}
        onPeriodChange={onPeriodChange}
        refreshing={refreshing}
      />
      <QualitySection overview={overview} />
    </>
  )
}

function AttentionSection({ items }: { items: AttentionItem[] }) {
  return (
    <section id="attention" className="control-section">
      <SectionHeading
        eyebrow="Décisions et incidents"
        title="À traiter"
        description="File de consultation issue des incidents non résolus et de la dead-letter queue."
      />
      {items.length === 0 ? (
        <EmptyState title="Aucun élément ouvert" body="Le système ne remonte actuellement aucun incident ou échec durable à examiner." />
      ) : (
        <div className="control-attention-list">
          {items.map((item) => (
            <article className="control-attention-item" key={`${item.kind}:${item.item_ref}`}>
              <div className="control-attention-head">
                <span className={`control-severity control-severity-${item.severity.toLowerCase()}`}>
                  {severityLabel(item.severity)}
                </span>
                <span>{formatDateTime(item.occurred_at)}</span>
              </div>
              <h3>{humanizeCode(item.title_code)}</h3>
              <code>{item.title_code}</code>
              <div className="control-attention-meta">
                <span>{item.kind === 'INCIDENT' ? 'Incident' : 'Échec durable'}</span>
                <span>{humanizeCode(item.status)}</span>
                <span>{humanizeCode(item.scope_type)} · {item.scope_ref}</span>
                {item.attempt_count ? <span>{item.attempt_count} tentative(s)</span> : null}
              </div>
              {item.reason_codes.length > 0 ? (
                <ul className="control-code-list" aria-label="Raisons">
                  {item.reason_codes.map((reason) => <li key={reason}>{humanizeCode(reason)}</li>)}
                </ul>
              ) : null}
              <div className="control-flags">
                {item.pause_required ? <span>Pause requise</span> : null}
                {item.human_review_required ? <span>Revue humaine requise</span> : null}
                {item.source_component ? <span>Source : {item.source_component}</span> : null}
              </div>
              <small className="control-ref">Réf. {item.item_ref}</small>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function CommercialTunnelSection({
  overview,
  weekOffset,
  onWeekChange,
  onPeriodChange,
  refreshing,
}: {
  overview: FounderOverview
  weekOffset: number
  onWeekChange: (value: number) => void
  onPeriodChange: (value: FounderTunnelPeriod) => void
  refreshing: boolean
}) {
  const [view, setView] = useState<'period' | 'cohort'>('period')
  const periodTabRef = useRef<HTMLButtonElement>(null)
  const cohortTabRef = useRef<HTMLButtonElement>(null)
  const tunnel = overview.commercial_tunnel
  const displayedPeriod = tunnel.period_kind

  const navigateTabs = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const nextView = event.key === 'ArrowRight'
      ? view === 'period' ? 'cohort' : 'period'
      : view === 'cohort' ? 'period' : 'cohort'
    setView(nextView)
    if (nextView === 'period') periodTabRef.current?.focus()
    else cohortTabRef.current?.focus()
  }

  return (
    <section id="business" className="control-section">
      <SectionHeading
        eyebrow="Acquisition et revenu"
        title="Tunnel commercial"
        description="Deux lectures complémentaires des étapes commerciales, sans mélanger flux observé et situation courante."
      />

      <div className="control-tunnel-tabs" role="tablist" aria-label="Vue du tunnel commercial">
        <button
          ref={periodTabRef}
          id="tunnel-period-tab"
          type="button"
          role="tab"
          aria-controls="tunnel-period-panel"
          aria-selected={view === 'period'}
          tabIndex={view === 'period' ? 0 : -1}
          onKeyDown={navigateTabs}
          onClick={() => setView('period')}
        >
          Période
        </button>
        <button
          ref={cohortTabRef}
          id="tunnel-cohort-tab"
          type="button"
          role="tab"
          aria-controls="tunnel-cohort-panel"
          aria-selected={view === 'cohort'}
          tabIndex={view === 'cohort' ? 0 : -1}
          onKeyDown={navigateTabs}
          onClick={() => setView('cohort')}
        >
          Par cohorte
        </button>
      </div>

      {view === 'period' ? (
        <div
          id="tunnel-period-panel"
          className="control-tunnel-panel"
          role="tabpanel"
          aria-labelledby="tunnel-period-tab"
        >
          <div className="control-tunnel-toolbar">
            <div className="control-period-toggle" aria-label="Période observée">
              <button
                type="button"
                aria-pressed={displayedPeriod === 'today'}
                disabled={refreshing}
                onClick={() => onPeriodChange('today')}
              >
                Aujourd’hui
              </button>
              <button
                type="button"
                aria-pressed={displayedPeriod === 'last_7_days'}
                disabled={refreshing}
                onClick={() => onPeriodChange('last_7_days')}
              >
                7 derniers jours
              </button>
            </div>
            <p>
              Période observée : {formatDateTimeRange(tunnel.period.start_at, tunnel.period.end_at)}.
            </p>
          </div>
          <TunnelMetrics counts={tunnel.period} />
        </div>
      ) : (
        <div
          id="tunnel-cohort-panel"
          className="control-tunnel-panel"
          role="tabpanel"
          aria-labelledby="tunnel-cohort-tab"
        >
          <div className="control-tunnel-toolbar">
            <p>
              Cohorte envoyée du {formatDate(tunnel.cohort.start_at)} au {formatDate(tunnel.cohort.end_at)}.
              {' '}Étapes atteintes depuis l’envoi jusqu’au {formatDateTime(tunnel.current.observed_at)}.
            </p>
            <label className="control-week-select">
              <span>Semaine terminée</span>
              <select
                value={weekOffset}
                disabled={refreshing}
                onChange={(event) => onWeekChange(Number(event.target.value))}
              >
                {WEEK_OFFSETS.map((offset) => (
                  <option key={offset} value={offset}>
                    {offset === 0 ? 'Dernière semaine complète' : `Il y a ${offset} semaine(s)`}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <TunnelMetrics counts={tunnel.cohort} />
        </div>
      )}

      <article className="control-panel control-current-situation">
        <div className="control-current-heading">
          <div>
            <p className="control-panel-kicker">À date</p>
            <h3>Situation actuelle</h3>
          </div>
          <span>Observée le {formatDateTime(tunnel.current.observed_at)}</span>
        </div>
        <div className="control-current-metrics">
          <div>
            <span>MRR</span>
            <strong><MoneyList values={tunnel.current.mrr_by_currency} /></strong>
          </div>
          <div>
            <span>Churn</span>
            <strong>{formatCount(tunnel.current.churn_count)}</strong>
          </div>
        </div>
      </article>
    </section>
  )
}

function TunnelMetrics({
  counts,
}: {
  counts: FounderOverview['commercial_tunnel']['period']
}) {
  return (
    <div className="control-metric-grid control-tunnel-metric-grid">
      <Metric label="Envoyés" value={formatCount(counts.sent_count)} />
      <Metric label="Ouverts" value={formatCount(counts.opened_count)} />
      <Metric label="Clics" value={formatCount(counts.click_count)} />
      <Metric label="Atterrissages" value={formatCount(counts.landing_count)} />
      <Metric label="Profils confirmés" value={formatCount(counts.confirmed_profile_count)} />
      <Metric label="Payants" value={formatCount(counts.paid_count)} />
    </div>
  )
}

function QualitySection({ overview }: { overview: FounderOverview }) {
  const quality = overview.quality
  return (
    <section id="quality" className="control-section">
      <SectionHeading
        eyebrow="Vérité produit"
        title="Qualité"
        description={`Feedback courant mis à jour entre ${formatDate(quality.window_start)} et ${formatDate(quality.window_end)}.`}
      />
      <div className="control-metric-grid control-metric-grid-quality">
        <Metric label="Feedbacks mis à jour" value={formatCount(quality.feedback_updated_in_window_count)} />
        <Metric label="Pertinents" value={formatCount(quality.relevant_feedback_updated_in_window_count)} />
        <Metric label="Non pertinents" value={formatCount(quality.not_relevant_feedback_updated_in_window_count)} />
        <Metric label="Contacts déclarés" value={formatCount(quality.contacted_in_window_count)} />
        <Metric label="Taux négatif" value={formatBps(quality.negative_feedback_rate_bps)} />
      </div>
      <div className="control-two-column">
        <article className="control-panel">
          <p className="control-panel-kicker">Motifs de non-pertinence</p>
          <h3>Ce que les clients rejettent</h3>
          {quality.negative_reason_counts.length === 0 ? (
            <p className="control-muted">Aucun motif négatif dans la fenêtre observée.</p>
          ) : (
            <ol className="control-reason-ranking">
              {quality.negative_reason_counts.map((reason) => (
                <li key={reason.reason_code}>
                  <span>{humanizeCode(reason.reason_code)}</span>
                  <strong>{formatCount(reason.count)}</strong>
                </li>
              ))}
            </ol>
          )}
        </article>
        <article className="control-panel">
          <p className="control-panel-kicker">Limite de la mesure</p>
          <h3>Feedback courant, pas historique complet</h3>
          <p className="control-muted">
            Cette vue compte l’état actuel des feedbacks dont la dernière mise à jour tombe
            dans la fenêtre. Elle ne transforme pas un clic négatif en vérité sur le marché
            et ne modifie aucun score automatiquement.
          </p>
        </article>
      </div>
    </section>
  )
}

function SystemPage({ data }: { data: FounderSystem }) {
  const { health, readiness } = data
  const components: Array<[string, HealthStatus]> = [
    ['API', health.api],
    ['Base de données', health.database],
    ['Boucle superviseur', health.supervisor_loop],
    ['Policy Gateway', health.policy_control],
    ['Exécution campagnes', health.campaign_execution],
    ['Dead-letter queue', health.dlq],
    ['Circuit breakers', health.circuit_breakers],
  ]
  const gates = Object.entries(GATE_LABELS).map(([key, label]) => ({
    label,
    evidence: readiness[key as keyof typeof GATE_LABELS],
  }))
  return (
    <section id="system" className="control-section control-system-page">
      <div className="control-hero">
        <div>
          <p className="control-eyebrow">Exploitation en lecture seule</p>
          <h1>Système</h1>
          <p>État de l’hôte, des services et des coûts observés, sans appel fournisseur.</p>
        </div>
      </div>
      <AcquisitionStatus status={data.acquisition_status} compact />

      <div className="control-system-summary">
        <article className="control-panel">
          <p className="control-panel-kicker">Accès aux données</p>
          <h3>PostgreSQL</h3>
          <div className="control-read-boundary">
            <strong>{data.database_access === 'READ_ONLY' ? 'Consultation' : 'État inconnu'}</strong>
            <span>Aucune mutation n’est montée dans cette API.</span>
          </div>
        </article>
        <article className="control-panel">
          <p className="control-panel-kicker">Readiness HTTP</p>
          <h3>Services</h3>
          <div className="control-status-list">
            {data.readiness_checks.map((check) => (
              <div key={check.name}>
                <span>{check.name}</span>
                <strong>{readinessCheckLabel(check.name, check.status)}</strong>
              </div>
            ))}
          </div>
        </article>
        <article className="control-panel">
          <p className="control-panel-kicker">Stockage</p>
          <h3>Disque</h3>
          {data.disk ? (
            <div className="control-read-boundary">
              <strong>{formatPercentNumber(data.disk.used_percent)}</strong>
              <span>{formatBytes(data.disk.used_bytes)} utilisés sur {formatBytes(data.disk.total_bytes)}</span>
              <small>{data.disk.path}</small>
            </div>
          ) : <p className="control-muted">Donnée indisponible.</p>}
        </article>
        <article className="control-panel">
          <p className="control-panel-kicker">Version déployée</p>
          <h3>SHA</h3>
          <code>{data.deployed_sha?.slice(0, 12) ?? '—'}</code>
        </article>
      </div>

      <div className="control-two-column control-system-columns">
        <article className="control-panel">
          <p className="control-panel-kicker">Ordonnanceur</p>
          <h3>Timers</h3>
          <div className="control-table-wrap">
            <table>
              <thead>
                <tr><th>Nom</th><th>État</th><th>Dernier passage</th><th>Prochain passage</th></tr>
              </thead>
              <tbody>
                {data.timers.map((timer) => (
                  <tr key={timer.name}>
                    <td><code>{timer.name}</code></td>
                    <td>{timerStateLabel(timer.state)}</td>
                    <td>{formatOptionalDateTime(timer.last_run_at)}</td>
                    <td>{formatOptionalDateTime(timer.next_run_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
        <article className="control-panel">
          <p className="control-panel-kicker">Protection des données</p>
          <h3>Sauvegardes</h3>
          <div className="control-status-list">
            {data.backups.map((backup) => (
              <div key={backup.kind}>
                <span>{backup.kind === 'local' ? 'Sauvegarde locale' : 'Sauvegarde hors site'}</span>
                <strong>{backupStatusLabel(backup.status)}</strong>
                <small>{formatOptionalDateTime(backup.last_success_at)}</small>
              </div>
            ))}
          </div>
        </article>
      </div>

      <article className="control-panel">
        <p className="control-panel-kicker">Consommation fournisseur</p>
        <h3>Coût du jour et du mois</h3>
        <div className="control-table-wrap">
          <table>
            <thead><tr><th>Fournisseur</th><th>Aujourd’hui</th><th>Mois courant</th></tr></thead>
            <tbody>
              {data.provider_costs.map((cost) => (
                <tr key={cost.provider}>
                  <td>{cost.provider}</td>
                  <td>{formatProviderCost(cost.today, cost.unit)}</td>
                  <td>{formatProviderCost(cost.month, cost.unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="control-muted">Montants facturés quand disponibles ; sinon unités natives observées.</p>
      </article>

      <div className="control-two-column control-system-columns">
        <article className="control-panel">
          <div className="control-panel-head">
            <div>
              <p className="control-panel-kicker">Santé actuelle</p>
              <h3>Composants</h3>
            </div>
            <StatusBadge status={health.status} />
          </div>
          <div className="control-status-list">
            {components.map(([label, status]) => (
              <div key={label}>
                <span>{label}</span>
                <StatusBadge status={status} compact />
              </div>
            ))}
          </div>
        </article>
        <article className="control-panel">
          <div className="control-panel-head">
            <div>
              <p className="control-panel-kicker">Readiness</p>
              <h3>Gates d’autonomie</h3>
            </div>
          </div>
          <div className="control-status-list">
            {gates.map(({ label, evidence }) => (
              <div key={label}>
                <span>{label}</span>
                <StatusBadge status={evidence.status} compact />
              </div>
            ))}
          </div>
        </article>
      </div>

      {readiness.blockers.length > 0 || health.reason_codes.length > 0 ? (
        <article className="control-panel control-blockers">
          <p className="control-panel-kicker">Raisons et blocages</p>
          <div className="control-blocker-columns">
            <div>
              <h3>Blocages d’autonomie</h3>
              <CodeList values={readiness.blockers} empty="Aucun blocage déclaré." />
            </div>
            <div>
              <h3>Raisons de santé</h3>
              <CodeList values={health.reason_codes} empty="Aucune dégradation déclarée." />
            </div>
          </div>
        </article>
      ) : null}
    </section>
  )
}

function SectionHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <div className="control-section-heading">
      <p className="control-eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  label: string
  value: string
  detail: string
  tone?: 'neutral' | 'critical'
}) {
  return (
    <article className={`control-summary-card control-summary-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  )
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <article className="control-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  )
}

function MoneyList({ values }: { values: MoneyTotal[] | null }) {
  if (values === null) return <span>—</span>
  if (values.length === 0) return <span>0 €</span>
  return (
    <span className="control-money-list">
      {values.map((value) => (
        <span key={value.currency}>{formatMoney(value.minor_units, value.currency)}</span>
      ))}
    </span>
  )
}

function StatusBadge({
  status,
  compact = false,
}: {
  status: HealthStatus | GateStatus
  compact?: boolean
}) {
  const className = status.toLowerCase().replaceAll('_', '-')
  return (
    <span className={`control-status control-status-${className} ${compact ? 'control-status-compact' : ''}`}>
      <span aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  )
}

function CodeList({ values, empty }: { values: string[]; empty: string }) {
  if (values.length === 0) return <p className="control-muted">{empty}</p>
  return (
    <ul className="control-code-list">
      {values.map((value) => <li key={value}>{humanizeCode(value)}</li>)}
    </ul>
  )
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="control-empty">
      <span aria-hidden="true">✓</span>
      <div>
        <strong>{title}</strong>
        <p>{body}</p>
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <section className="control-loading" aria-live="polite">
      <span aria-hidden="true" />
      <strong>Connexion aux read models de production…</strong>
      <p>Aucune donnée n’est simulée pendant le chargement.</p>
    </section>
  )
}

function UnavailableState() {
  return (
    <section className="control-loading control-unavailable">
      <strong>La console n’a reçu aucune donnée exploitable.</strong>
      <p>La frontière reste fermée : aucun état de démonstration n’est affiché.</p>
    </section>
  )
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('fr-CH').format(value)
}

function formatMoney(minorUnits: number, currency: 'CHF' | 'EUR'): string {
  return new Intl.NumberFormat('fr-CH', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(minorUnits / 100)
}

function formatBps(value: number | null): string {
  if (value === null) return '—'
  return new Intl.NumberFormat('fr-CH', {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(value / 10_000)
}

function formatOptionalDateTime(value: string | null): string {
  return value === null ? '—' : formatDateTime(value)
}

function formatPercentNumber(value: string): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  return `${new Intl.NumberFormat('fr-CH', { maximumFractionDigits: 1 }).format(parsed)} %`
}

function formatBytes(value: number): string {
  return new Intl.NumberFormat('fr-CH', {
    style: 'unit',
    unit: 'gigabyte',
    maximumFractionDigits: 1,
  }).format(value / 1_000_000_000)
}

function formatProviderCost(value: string, unit: 'USD' | 'request' | 'credit'): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  const formatted = new Intl.NumberFormat('fr-CH', { maximumFractionDigits: 6 }).format(parsed)
  if (unit === 'USD') return `${formatted} $US`
  if (unit === 'request') return `${formatted} requête${parsed === 1 ? '' : 's'}`
  return `${formatted} crédit${parsed === 1 ? '' : 's'}`
}

function readinessCheckLabel(
  name: 'API' | 'Founder',
  status: 'ready' | 'not_ready' | 'unavailable',
): string {
  if (status === 'ready') return `${name} ${name === 'API' ? 'prête' : 'prêt'}`
  if (status === 'not_ready') return `${name} non ${name === 'API' ? 'prête' : 'prêt'}`
  return `${name} indisponible`
}

function timerStateLabel(
  state: 'active' | 'inactive' | 'failed' | 'absent' | 'unknown',
): string {
  return ({
    active: 'Actif',
    inactive: 'Inactif',
    failed: 'En échec',
    absent: 'Absent',
    unknown: 'Inconnu',
  } as const)[state]
}

function backupStatusLabel(status: 'success' | 'failed' | 'unavailable'): string {
  return ({ success: 'Réussie', failed: 'En échec', unavailable: 'Indisponible' } as const)[status]
}

function formatDateTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'date indisponible'
  return new Intl.DateTimeFormat('fr-CH', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Zurich',
  }).format(parsed)
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'date indisponible'
  return new Intl.DateTimeFormat('fr-CH', {
    dateStyle: 'medium',
    timeZone: 'Europe/Zurich',
  }).format(parsed)
}

function formatDateTimeRange(start: string, end: string): string {
  return `${formatDateTime(start)} → ${formatDateTime(end)}`
}

function humanizeCode(value: string): string {
  const words = value.replaceAll('-', ' ').replaceAll('_', ' ').toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : 'Inconnu'
}

function severityLabel(severity: AttentionItem['severity']): string {
  const labels: Record<AttentionItem['severity'], string> = {
    WARNING: 'Attention',
    HIGH: 'Élevé',
    CRITICAL: 'Critique',
  }
  return labels[severity]
}
