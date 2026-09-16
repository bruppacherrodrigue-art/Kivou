import type { ReactNode } from 'react'
import type {
  ChiefOfStaffFact,
  ChiefOfStaffStatus,
  FounderChiefOfStaffView,
} from './types'

const STATUS_LABELS: Record<ChiefOfStaffStatus, string> = {
  HEALTHY: 'Sain',
  WATCH: 'À surveiller',
  CRITICAL: 'Critique',
  UNKNOWN: 'Inconnu',
}

const OWNER_LABELS = {
  FOUNDER: 'Fondateur',
  ENGINEERING: 'Ingénierie',
  ACQUISITION: 'Acquisition',
  PRODUCT: 'Produit',
  DATA: 'Données',
  NONE: 'À déterminer',
} as const

export function HermesBrief({
  view,
  refreshing = false,
}: {
  view: FounderChiefOfStaffView
  refreshing?: boolean
}) {
  return (
    <section
      id="hermes-brief"
      className="control-section hermes-brief"
      aria-labelledby="hermes-brief-title"
      aria-busy={refreshing}
    >
      <div className="control-section-heading">
        <p className="control-eyebrow">Synthèse en mode observation</p>
        <h2 id="hermes-brief-title">Brief d’Hermes</h2>
        <p>Une lecture transversale et sourcée. Les recommandations affichées n’ont pas été exécutées.</p>
      </div>

      {view.kind === 'empty' ? (
        <BriefState
          title="Aucun brief disponible"
          body="La première génération SHADOW validée n’a pas encore été persistée."
        />
      ) : null}
      {view.kind === 'unavailable' ? (
        <BriefState
          title="Brief momentanément indisponible"
          body="Les autres données Founder restent consultables. Réessaie avec Actualiser."
          unavailable
        />
      ) : null}
      {view.kind === 'available' ? <AvailableBrief data={view.data} /> : null}
    </section>
  )
}

function BriefState({
  title,
  body,
  unavailable = false,
}: {
  title: string
  body: string
  unavailable?: boolean
}) {
  return (
    <div className={unavailable ? 'control-empty hermes-brief-state--unavailable' : 'control-empty'}>
      <span aria-hidden="true">{unavailable ? '!' : '—'}</span>
      <div>
        <strong>{title}</strong>
        <p>{body}</p>
      </div>
    </div>
  )
}

function AvailableBrief({ data }: { data: Extract<FounderChiefOfStaffView, { kind: 'available' }>['data'] }) {
  const { report } = data
  const priorities = report.priorities.slice(0, 3)
  const cited = new Set([
    ...report.source_refs,
    ...report.observations.flatMap((item) => item.fact_refs),
    ...priorities.flatMap((item) => item.fact_refs),
    ...report.decision_requests.flatMap((item) => item.fact_refs),
    ...report.unknowns.flatMap((item) => item.fact_refs),
  ])
  const facts = data.facts.filter((fact) => cited.has(fact.fact_ref))
  return (
    <article className="control-panel hermes-brief-card">
      <header className="hermes-brief-head">
        <div>
          <span className={`hermes-status hermes-status--${report.executive_status.toLowerCase()}`}>
            {STATUS_LABELS[report.executive_status]}
          </span>
          {data.stale ? <span className="hermes-stale">Rapport périmé</span> : null}
        </div>
        <p>
          Créé {formatDateTime(report.created_at)} · période du {formatDate(report.period_start)} au {formatDate(report.period_end)}
        </p>
      </header>

      <p className="hermes-summary">{report.executive_summary}</p>

      <div className="hermes-brief-grid">
        <BriefList title="Points clés" empty="Aucun changement important signalé.">
          {report.observations.map((observation) => (
            <li key={observation.observation_id}>
              <strong>{observation.summary}</strong>
              <p>{observation.impact}</p>
              <ReasonCodes values={observation.reason_codes} />
            </li>
          ))}
        </BriefList>

        <BriefList title="Priorités recommandées" empty="Aucune priorité recommandée.">
          {priorities.map((priority) => (
            <li key={priority.priority}>
              <strong>{priority.priority}. {priority.recommended_action}</strong>
              <p>{OWNER_LABELS[priority.owner]} · recommandation non exécutée{priority.approval_required ? ' · validation requise' : ''}</p>
              <ReasonCodes values={priority.reason_codes} />
            </li>
          ))}
        </BriefList>

        <BriefList title="Décisions demandées" empty="Aucune décision demandée au fondateur.">
          {report.decision_requests.map((decision) => (
            <li key={decision.decision_id}>
              <strong>{decision.question}</strong>
              <p>Décision humaine requise</p>
              <ReasonCodes values={decision.reason_codes} />
            </li>
          ))}
        </BriefList>

        <BriefList title="Inconnues et preuves insuffisantes" empty="Aucune inconnue déclarée.">
          {report.unknowns.map((unknown) => (
            <li key={unknown.unknown_id}>
              <strong>{unknown.summary}</strong>
              <ReasonCodes values={unknown.reason_codes} />
            </li>
          ))}
        </BriefList>
      </div>

      <details className="hermes-evidence">
        <summary>Preuves citées ({facts.length})</summary>
        {facts.length > 0 ? (
          <ul>
            {facts.map((fact) => (
              <li key={fact.fact_ref}>
                <code>{fact.fact_ref}</code>
                <span>{fact.metric_key} · {formatFactValue(fact)} · {fact.data_status}</span>
              </li>
            ))}
          </ul>
        ) : <p>Les références restent identifiables dans le rapport, sans valeur additionnelle.</p>}
      </details>

      <footer className="hermes-brief-meta">
        <span>{report.supervisor_version}</span>
        <span>Profil {report.profile_version}</span>
        <span>{data.model_route}</span>
        {data.actual_cost !== null ? <span>Coût {formatUsd(data.actual_cost)}</span> : null}
      </footer>
    </article>
  )
}

function BriefList({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  const entries = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : []
  return (
    <section className="hermes-brief-list">
      <h3>{title}</h3>
      {entries.length > 0 ? <ol>{children}</ol> : <p className="hermes-list-empty">{empty}</p>}
    </section>
  )
}

function ReasonCodes({ values }: { values: string[] }) {
  return (
    <ul className="control-code-list" aria-label="Codes de raison">
      {values.map((value) => <li key={value}>{value.replaceAll('_', ' ').toLocaleLowerCase('fr')}</li>)}
    </ul>
  )
}

function formatFactValue(fact: ChiefOfStaffFact): string {
  if (fact.value === null) return 'Valeur inconnue'
  if (fact.unit === 'MINOR_UNITS' && typeof fact.value === 'number' && fact.currency) {
    return new Intl.NumberFormat('fr-CH', {
      style: 'currency',
      currency: fact.currency,
      currencyDisplay: 'code',
    }).format(fact.value / 100)
  }
  if (typeof fact.value === 'boolean') return fact.value ? 'Oui' : 'Non'
  return String(fact.value)
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('fr-CH', { dateStyle: 'medium', timeZone: 'Europe/Zurich' }).format(new Date(value))
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('fr-CH', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Zurich' }).format(new Date(value))
}

function formatUsd(value: string): string {
  return new Intl.NumberFormat('fr-CH', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(Number(value))
}
