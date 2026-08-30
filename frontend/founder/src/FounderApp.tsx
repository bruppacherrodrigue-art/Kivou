import { useEffect, useState } from 'react'
import { loadFounderOverview, loadFounderSession } from './api'
import type {
  AttentionItem,
  AutonomyMode,
  FounderOverview,
  FounderSession,
  GateStatus,
  HealthStatus,
  MoneyTotal,
} from './types'

type Snapshot = {
  session: FounderSession
  overview: FounderOverview
}

const WEEK_OFFSETS = Array.from({ length: 52 }, (_, index) => index)
const STATUS_LABELS: Record<HealthStatus | GateStatus, string> = {
  READY: 'Prêt',
  DEGRADED: 'Dégradé',
  NOT_READY: 'Non prêt',
  INSUFFICIENT_EVIDENCE: 'Preuves insuffisantes',
}
const GATE_LABELS = {
  h_a_runtime: 'Runtime Hermes',
  h_b_state: 'État durable',
  h_c_policy: 'Policy Gateway',
  h_d_shadow: 'Validation shadow',
  h_e_capped: 'Autonomie plafonnée',
  h_f_closed_loop: 'Boucle revenu',
  h_g_scale: 'Passage à l’échelle',
} as const

export function FounderApp() {
  const [weekOffset, setWeekOffset] = useState(0)
  const [refreshKey, setRefreshKey] = useState(0)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    void Promise.all([
      loadFounderSession(controller.signal),
      loadFounderOverview(weekOffset, controller.signal),
    ])
      .then(([session, overview]) => {
        if (!controller.signal.aborted) setSnapshot({ session, overview })
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
  }, [refreshKey, weekOffset])

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
          <a href="#overview">Vue du moment</a>
          <a href="#attention">À traiter</a>
          <a href="#business">Business</a>
          <a href="#quality">Qualité</a>
          <a href="#system">Système</a>
        </nav>
        <div className="control-sidebar-footer">
          <span className="control-environment">
            <span aria-hidden="true" />
            Production
          </span>
          <span className="control-readonly">Lecture seule</span>
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
                Actualisé {formatDateTime(snapshot.overview.generated_at)}
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
          {snapshot ? (
            <Console
              snapshot={snapshot}
              weekOffset={weekOffset}
              onWeekChange={setWeekOffset}
              refreshing={loading}
            />
          ) : null}
        </main>
      </div>
    </div>
  )
}

function Console({
  snapshot,
  weekOffset,
  onWeekChange,
  refreshing,
}: {
  snapshot: Snapshot
  weekOffset: number
  onWeekChange: (value: number) => void
  refreshing: boolean
}) {
  const { overview } = snapshot
  return (
    <>
      <section id="overview" className="control-section control-overview">
        <div className="control-hero">
          <div>
            <p className="control-eyebrow">Vue du moment</p>
            <h1>Ce qui mérite ton attention.</h1>
            <p>
              Les états opérationnels sont observés au moment de la requête. Les chiffres
              commerciaux ci-dessous concernent la dernière semaine terminée sélectionnée.
            </p>
          </div>
          <div className="control-hero-status">
            <span>État global</span>
            <StatusBadge status={overview.today.system_status} />
            <small>{formatDateTime(overview.today.generated_at)}</small>
          </div>
        </div>

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
          <SummaryCard
            label="Hermes"
            value={STATUS_LABELS[overview.today.hermes_status]}
            detail={`Mode sûr : ${modeLabel(overview.today.highest_safe_mode)}`}
            status={overview.today.hermes_status}
          />
        </div>
      </section>

      <AttentionSection items={overview.attention} />
      <BusinessSection
        overview={overview}
        weekOffset={weekOffset}
        onWeekChange={onWeekChange}
        refreshing={refreshing}
      />
      <QualitySection overview={overview} />
      <SystemSection overview={overview} />
    </>
  )
}

function AttentionSection({ items }: { items: AttentionItem[] }) {
  return (
    <section id="attention" className="control-section">
      <SectionHeading
        eyebrow="Décisions et incidents"
        title="À traiter"
        description="File en lecture seule issue des incidents non résolus et de la dead-letter queue."
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

function BusinessSection({
  overview,
  weekOffset,
  onWeekChange,
  refreshing,
}: {
  overview: FounderOverview
  weekOffset: number
  onWeekChange: (value: number) => void
  refreshing: boolean
}) {
  const report = overview.business
  const funnel = report.funnel
  return (
    <section id="business" className="control-section">
      <div className="control-section-toolbar">
        <SectionHeading
          eyebrow="Revenu et acquisition"
          title="Business"
          description={`Période terminée : ${formatDateRange(report.week_start, report.week_end)}.`}
        />
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

      <div className="control-metric-grid">
        <Metric label="Emails délivrés (proxy)" value={formatCount(funnel.delivered_proxy_count)} />
        <Metric label="Réponses positives" value={formatCount(funnel.positive_reply_count)} />
        <Metric label="Clics" value={formatCount(funnel.click_count)} />
        <Metric label="Comptes activés" value={formatCount(funnel.activated_account_count)} />
        <Metric label="Comptes payants" value={formatCount(funnel.paid_account_count)} />
        <Metric label="MRR" value={<MoneyList values={funnel.mrr_by_currency} />} />
        <Metric label="Churn" value={formatCount(funnel.churn_count)} />
      </div>

      <p className="control-truth-note">
        “Délivrés” reste un proxy envoyé moins bounces. Les données MRR incomplètes sont
        signalées plutôt que complétées par une estimation.
      </p>

      <div className="control-two-column">
        <article className="control-panel">
          <div className="control-panel-head">
            <div>
              <p className="control-panel-kicker">Efficacité retenue</p>
              <h3>MRR M2 / 1 000 emails délivrés</h3>
            </div>
          </div>
          {report.wedge_m2_efficiency.length === 0 ? (
            <p className="control-muted">Pas encore de cohorte M2 exploitable.</p>
          ) : (
            <div className="control-wedge-list">
              {report.wedge_m2_efficiency.map((row) => (
                <div className="control-wedge-row" key={`${row.wedge}:${row.currency ?? 'unknown'}`}>
                  <div>
                    <strong>{humanizeCode(row.wedge)}</strong>
                    <span>{formatCount(row.retained_m2_accounts)} compte(s) retenu(s) M2</span>
                  </div>
                  <div>
                    {row.data_status === 'READY' && row.currency && row.retained_m2_mrr_per_1000_delivered
                      ? formatMoney(
                          Math.round(Number(row.retained_m2_mrr_per_1000_delivered)),
                          row.currency,
                        )
                      : 'Preuves M2 insuffisantes'}
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="control-panel">
          <p className="control-panel-kicker">Qualité du parcours revenu</p>
          <h3>Données à interpréter avec prudence</h3>
          <dl className="control-compact-list">
            <div>
              <dt>Secteurs non résolus</dt>
              <dd>{formatCount(report.data_quality.unresolved_sector_count)}</dd>
            </div>
            <div>
              <dt>Parcours MRR incomplets</dt>
              <dd>{formatCount(report.data_quality.unknown_mrr_journey_count)}</dd>
            </div>
            <div>
              <dt>Wedges sans preuve M2</dt>
              <dd>{formatCount(report.data_quality.m2_insufficient_wedges.length)}</dd>
            </div>
          </dl>
        </article>
      </div>

      <article className="control-panel control-table-panel">
        <div className="control-panel-head">
          <div>
            <p className="control-panel-kicker">Détail analytique</p>
            <h3>Pays × secteur × besoin × campagne</h3>
          </div>
          <span>{formatCount(report.analytical_rows.length)} ligne(s)</span>
        </div>
        {report.analytical_rows.length === 0 ? (
          <p className="control-muted">Aucune activité sortante pour cette période.</p>
        ) : (
          <div className="control-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Pays</th>
                  <th>Secteur</th>
                  <th>Besoin</th>
                  <th>Campagne</th>
                  <th>Délivrés</th>
                  <th>Réponses</th>
                  <th>Payants</th>
                  <th>MRR</th>
                </tr>
              </thead>
              <tbody>
                {report.analytical_rows.map((row) => (
                  <tr key={`${row.country}:${row.sector_ref}:${row.need_ref}:${row.campaign_ref}`}>
                    <td>{row.country}</td>
                    <td>{humanizeCode(row.sector_ref)}</td>
                    <td>{humanizeCode(row.need_ref)}</td>
                    <td><code>{row.campaign_ref}</code></td>
                    <td>{formatCount(row.delivered_proxy_count)}</td>
                    <td>{formatCount(row.positive_reply_count)}</td>
                    <td>{formatCount(row.paid_account_count)}</td>
                    <td><MoneyList values={row.mrr_by_currency} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
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

function SystemSection({ overview }: { overview: FounderOverview }) {
  const { health, readiness, hermes } = overview.system
  const components: Array<[string, HealthStatus]> = [
    ['API', health.api],
    ['Base de données', health.database],
    ['Runtime Hermes', health.hermes_runtime],
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
    <section id="system" className="control-section">
      <SectionHeading
        eyebrow="Exploitation"
        title="Système"
        description="Santé et niveau d’autonomie calculés depuis l’état durable, sans appel fournisseur pendant la lecture."
      />
      <div className="control-system-summary">
        <article className="control-panel control-hermes-card">
          <div>
            <p className="control-panel-kicker">Agent autonome</p>
            <h3>{hermes.name}</h3>
            <p>Mode sûr actuel : <strong>{modeLabel(hermes.highest_safe_mode)}</strong></p>
          </div>
          <StatusBadge status={hermes.status} />
          {hermes.reason_codes.length > 0 ? (
            <ul className="control-code-list">
              {hermes.reason_codes.map((reason) => <li key={reason}>{humanizeCode(reason)}</li>)}
            </ul>
          ) : null}
        </article>
        <article className="control-panel">
          <p className="control-panel-kicker">Accès aux données</p>
          <h3>PostgreSQL</h3>
          <div className="control-read-boundary">
            <strong>{overview.system.database_access === 'READ_ONLY' ? 'Lecture seule' : 'État inconnu'}</strong>
            <span>Aucune mutation n’est montée dans cette API.</span>
          </div>
        </article>
      </div>

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
            <span className="control-mode">{modeLabel(readiness.highest_safe_mode)}</span>
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
  status,
}: {
  label: string
  value: string
  detail: string
  tone?: 'neutral' | 'critical'
  status?: HealthStatus
}) {
  return (
    <article className={`control-summary-card control-summary-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
      {status ? <StatusBadge status={status} compact /> : null}
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

function MoneyList({ values }: { values: MoneyTotal[] }) {
  if (values.length === 0) return <span>—</span>
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

function formatDateRange(start: string, end: string): string {
  return `${formatDate(start)} → ${formatDate(end)}`
}

function humanizeCode(value: string): string {
  const words = value.replaceAll('-', ' ').replaceAll('_', ' ').toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : 'Inconnu'
}

function modeLabel(mode: AutonomyMode): string {
  const labels: Record<AutonomyMode, string> = {
    SHADOW: 'Shadow',
    ASSISTED: 'Assisté',
    AUTONOMOUS_CAPPED: 'Autonome plafonné',
    ADAPTIVE_SCALE: 'Échelle adaptative',
  }
  return labels[mode]
}

function severityLabel(severity: AttentionItem['severity']): string {
  const labels: Record<AttentionItem['severity'], string> = {
    WARNING: 'Attention',
    HIGH: 'Élevé',
    CRITICAL: 'Critique',
  }
  return labels[severity]
}
