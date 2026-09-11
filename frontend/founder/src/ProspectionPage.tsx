import { useEffect, useId, useState } from 'react'
import type {
  FounderDirectoryRow,
  FounderDirectoryStatus,
  FounderProspection,
  FounderProspectionFilters,
  FounderProspectionQueueItem,
} from './types'

const ASSISTED_TOOLTIP = 'Disponible quand le mode assisté sera livré'

const FAMILY_LABELS: Record<string, string> = {
  ready_mix_concrete: 'Béton prêt à l’emploi',
  reinforcement_steel: 'Armatures / acier',
  subcontracted_structural_work: 'Gros œuvre sous-traité',
  formwork: 'Coffrage',
}

const DIRECTORY_STATUS_LABELS: Record<FounderDirectoryStatus, string> = {
  confirmed_domain: 'Domaine confirmé',
  without_website: 'Sans site',
  reverification_required: 'À revérifier',
}

type ProspectionPageProps = {
  data: FounderProspection
  filters: FounderProspectionFilters
  refreshing: boolean
  onFiltersChange: (filters: FounderProspectionFilters) => void
}

export function ProspectionPage({
  data,
  filters,
  refreshing,
  onFiltersChange,
}: ProspectionPageProps) {
  const [openMail, setOpenMail] = useState<FounderProspectionQueueItem | null>(null)
  const hasPreparedTargets = data.queue.items.length > 0

  useEffect(() => {
    if (!openMail) return undefined
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenMail(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [openMail])

  const directory = (
    <DirectorySection
      data={data}
      filters={filters}
      refreshing={refreshing}
      onFiltersChange={onFiltersChange}
    />
  )
  const queue = <QueueSection data={data} onOpenMail={setOpenMail} />

  return (
    <>
      <ProspectionHero data={data} />
      {hasPreparedTargets ? queue : directory}
      {hasPreparedTargets ? directory : queue}
      <TargetingSection data={data} />
      <ResultsSection data={data} />
      {openMail ? <MailDrawer item={openMail} onClose={() => setOpenMail(null)} /> : null}
    </>
  )
}

function ProspectionHero({ data }: { data: FounderProspection }) {
  return (
    <section className="control-section prospection-hero" aria-labelledby="prospection-title">
      <div>
        <p className="control-eyebrow">Acquisition assistée</p>
        <h1 id="prospection-title">Prospection</h1>
        <p>
          L’annuaire réel, le dernier cycle d’acquisition et le parcours commercial réunis
          dans une vue en lecture seule.
        </p>
      </div>
      <div className="prospection-runtime-card">
        <span className={`prospection-timer-dot prospection-timer-${data.timer.state.toLowerCase()}`} aria-hidden="true" />
        <div>
          <small>Timer d’acquisition</small>
          <strong>{timerLabel(data)}</strong>
          <span>{lastCycleLabel(data)}</span>
        </div>
      </div>
    </section>
  )
}

function DirectorySection({
  data,
  filters,
  refreshing,
  onFiltersChange,
}: ProspectionPageProps) {
  const [searchDraft, setSearchDraft] = useState(filters.q)
  const { directory } = data
  const { pagination } = directory
  const firstRow = pagination.total_items === 0 ? 0 : (pagination.page - 1) * pagination.page_size + 1
  const lastRow = Math.min(pagination.page * pagination.page_size, pagination.total_items)

  useEffect(() => setSearchDraft(filters.q), [filters.q])

  const changeFilter = (change: Partial<FounderProspectionFilters>) => {
    onFiltersChange({ ...filters, ...change, page: change.page ?? 1 })
  }

  return (
    <section id="directory" className="control-section prospection-section" aria-labelledby="directory-title">
      <ProspectionSectionHeading
        eyebrow="Base fournisseurs"
        title="Annuaire"
        titleId="directory-title"
        description="Entreprises actives de supplier_directory. Les compteurs restent globaux pendant le filtrage."
        meta={`${formatCount(pagination.total_items)} résultat(s) · ${timerShortLabel(data)}`}
      />

      <div className="prospection-kpi-grid" aria-label="Compteurs de l’annuaire">
        <ProspectionKpi label="Entreprises" value={directory.summary.company_count} />
        <ProspectionKpi label="Domaines confirmés" value={directory.summary.confirmed_domain_count} tone="positive" />
        <ProspectionKpi label="E-mails vérifiés" value={directory.summary.verified_email_count} tone="positive" />
        <ProspectionKpi label="À revérifier" value={directory.summary.reverification_required_count} tone="warning" />
      </div>

      <div className="prospection-facets">
        <FacetList
          label="Par famille"
          values={directory.family_counts.map((facet) => ({ ...facet, label: familyLabel(facet.key) }))}
        />
        <FacetList
          label="Par département"
          values={directory.department_counts.map((facet) => ({ ...facet, label: facet.key }))}
        />
      </div>

      <form
        className="prospection-filters"
        role="search"
        onSubmit={(event) => {
          event.preventDefault()
          changeFilter({ q: searchDraft.trim() })
        }}
      >
        <label className="prospection-search">
          <span>Nom de l’entreprise</span>
          <span className="prospection-search-control">
            <input
              type="search"
              value={searchDraft}
              placeholder="Rechercher un fournisseur"
              onChange={(event) => setSearchDraft(event.target.value)}
            />
            <button type="submit" disabled={refreshing}>Rechercher</button>
          </span>
        </label>
        <FilterSelect
          label="Famille"
          value={filters.family}
          disabled={refreshing}
          onChange={(value) => changeFilter({ family: value })}
          options={directory.family_counts.map((facet) => ({
            value: facet.key,
            label: `${familyLabel(facet.key)} (${formatCount(facet.count)})`,
          }))}
        />
        <FilterSelect
          label="Département"
          value={filters.department}
          disabled={refreshing}
          onChange={(value) => changeFilter({ department: value })}
          options={directory.department_counts.map((facet) => ({
            value: facet.key,
            label: `${facet.key} (${formatCount(facet.count)})`,
          }))}
        />
        <FilterSelect
          label="Statut"
          value={filters.status}
          disabled={refreshing}
          onChange={(value) => changeFilter({ status: value as FounderDirectoryStatus | '' })}
          options={Object.entries(DIRECTORY_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
        />
      </form>

      <article className={`control-panel prospection-table-panel ${refreshing ? 'prospection-refreshing' : ''}`}>
        {directory.rows.length === 0 ? (
          <div className="prospection-compact-empty">
            <strong>Aucune entreprise ne correspond à ces filtres.</strong>
            <span>Modifie les critères pour retrouver les fiches actives de l’annuaire.</span>
          </div>
        ) : (
          <div className="control-table-wrap prospection-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Entreprise</th>
                  <th>Métier</th>
                  <th>Localisation</th>
                  <th className="prospection-number">Effectif</th>
                  <th>Domaine</th>
                  <th>E-mail</th>
                  <th>État</th>
                </tr>
              </thead>
              <tbody>
                {directory.rows.map((row) => <DirectoryTableRow key={row.siren} row={row} />)}
              </tbody>
            </table>
          </div>
        )}
        <footer className="prospection-pagination">
          <span>{firstRow}–{lastRow} sur {formatCount(pagination.total_items)}</span>
          <div>
            <button
              type="button"
              disabled={refreshing || pagination.page <= 1}
              onClick={() => changeFilter({ page: pagination.page - 1 })}
            >
              Précédent
            </button>
            <span>Page {pagination.page} / {pagination.total_pages}</span>
            <button
              type="button"
              disabled={refreshing || pagination.page >= pagination.total_pages}
              onClick={() => changeFilter({ page: pagination.page + 1 })}
            >
              Suivant
            </button>
          </div>
        </footer>
      </article>
    </section>
  )
}

function DirectoryTableRow({ row }: { row: FounderDirectoryRow }) {
  const safeWebsite = row.website_url?.startsWith('https://') || row.website_url?.startsWith('http://')
    ? row.website_url
    : null
  return (
    <tr>
      <td>
        <strong className="prospection-primary-cell">{row.legal_name}</strong>
        <small>SIREN {row.siren}</small>
      </td>
      <td>
        <span className="prospection-family-list">
          {row.family_keys.map((family) => <span key={family}>{familyLabel(family)}</span>)}
        </span>
      </td>
      <td>
        <span>{row.city ?? '—'}</span>
        {row.department ? <small>Département {row.department}</small> : null}
      </td>
      <td className="prospection-number">{row.employees === null ? '—' : formatCount(row.employees)}</td>
      <td>
        {row.domain ? (
          <>
            {safeWebsite ? <a href={safeWebsite} target="_blank" rel="noreferrer">{row.domain}</a> : <span>{row.domain}</span>}
            <small>{row.confirmed_domain ? 'Confirmé' : 'À confirmer'}</small>
          </>
        ) : (
          <span className="prospection-missing">Sans site</span>
        )}
      </td>
      <td>
        {row.professional_email ? (
          <>
            <a href={`mailto:${row.professional_email}`}>{row.professional_email}</a>
            <small>{sourceLabel(row.email_source)} · {humanizeCode(row.email_verification_status)}</small>
          </>
        ) : (
          <span className="prospection-missing">—</span>
        )}
      </td>
      <td>
        <DirectoryStatus row={row} />
        <small>Maj. {formatDate(row.updated_at)}</small>
      </td>
    </tr>
  )
}

function QueueSection({
  data,
  onOpenMail,
}: {
  data: FounderProspection
  onOpenMail: (item: FounderProspectionQueueItem) => void
}) {
  const lockedId = useId()
  const items = data.queue.items
  return (
    <section id="queue" className="control-section prospection-section prospection-compact-section" aria-labelledby="queue-title">
      <ProspectionSectionHeading
        eyebrow="Revue assistée"
        title="File du jour"
        titleId="queue-title"
        description="Cibles préparées au statut pending_review. Aucune action n’est écrite depuis cette console."
        meta={`${cycleDateLabel(data.queue.last_cycle_at)} · ${timerShortLabel(data)}`}
      />
      <span id={lockedId} className="control-visually-hidden">{ASSISTED_TOOLTIP}</span>
      <article className="control-panel prospection-queue-panel">
        {items.length === 0 ? (
          <div className="prospection-compact-empty">
            <strong>Aucune cible préparée.</strong>
            <span>Le runtime d’acquisition est à l’arrêt.</span>
            <small>{cycleDateLabel(data.queue.last_cycle_at)}</small>
          </div>
        ) : (
          <div className="control-table-wrap prospection-table-wrap prospection-queue-table">
            <table>
              <thead>
                <tr>
                  <th>Entreprise</th>
                  <th>Métier</th>
                  <th>Dirigeant</th>
                  <th>E-mail</th>
                  <th>Signal d’appât</th>
                  <th>Mail</th>
                  <th>Décision</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.target_ref}>
                    <td>
                      <strong className="prospection-primary-cell">{item.company_name}</strong>
                      <small>{[item.city, item.employees === null ? null : `${formatCount(item.employees)} salariés`].filter(Boolean).join(' · ') || '—'}</small>
                    </td>
                    <td>{familyLabel(item.family_key)}</td>
                    <td>
                      <span>{item.director_name ?? '—'}</span>
                      {item.director_title ? <small>{item.director_title}</small> : null}
                    </td>
                    <td>
                      <span>{item.email_address}</span>
                      <small>{sourceLabel(item.email_source)} · {humanizeCode(item.email_verification_status)}</small>
                    </td>
                    <td>
                      <strong className="prospection-primary-cell">{item.bait_holder}</strong>
                      <span>{item.bait_subject}</span>
                      <small>{formatOptionalMoney(item.bait_amount_minor_units, item.bait_currency)}</small>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="prospection-mail-button"
                        aria-label={`Voir le mail de ${item.company_name}`}
                        onClick={() => onOpenMail(item)}
                      >
                        Voir
                      </button>
                    </td>
                    <td>
                      <div className="prospection-row-actions">
                        <LockedAction describedBy={lockedId}>Valider</LockedAction>
                        <LockedAction describedBy={lockedId}>Corriger</LockedAction>
                        <LockedAction describedBy={lockedId}>Écarter</LockedAction>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <footer className="prospection-queue-footer">
          <span>{formatCount(items.length)} cible(s) en attente de revue</span>
          <LockedAction describedBy={lockedId} emphasis>Envoyer les 0 validées</LockedAction>
        </footer>
      </article>
    </section>
  )
}

function TargetingSection({ data }: { data: FounderProspection }) {
  const cycle = data.targeting
  return (
    <section id="targeting" className="control-section prospection-section prospection-compact-section" aria-labelledby="targeting-title">
      <ProspectionSectionHeading
        eyebrow="Dernier passage"
        title="Ciblage"
        titleId="targeting-title"
        description="Signal, volume et écarts lus dans les journaux du dernier cycle d’acquisition."
        meta={`${cycleDateLabel(cycle?.updated_at ?? null)} · ${timerShortLabel(data)}`}
      />
      {!cycle ? (
        <CompactEmpty title="Aucun cycle enregistré." body="Le runtime n’a produit aucun journal de ciblage." />
      ) : !cycle.recent ? (
        <CompactEmpty title="Aucun cycle récent." body={`Dernier cycle le ${formatDateTime(cycle.updated_at)} · ${humanizeCode(cycle.status)}.`} />
      ) : (
        <article className="control-panel prospection-targeting-grid">
          <div className="prospection-signal">
            <small>Signal choisi</small>
            <strong>{cycle.signal.title ?? 'Signal non résolu'}</strong>
            <span>{formatOptionalMoney(cycle.signal.amount_minor_units, cycle.signal.currency)}</span>
          </div>
          <CompactMetric label="Comptes SIRENE" value={cycle.sirene_account_count} />
          <CompactMetric label="Domaines confirmés" value={cycle.confirmed_domain_count} />
          <div className="prospection-inline-list">
            <small>Familles</small>
            <span>{cycle.family_keys.length > 0 ? cycle.family_keys.map(familyLabel).join(' · ') : '—'}</span>
          </div>
          <div className="prospection-inline-list">
            <small>E-mails par niveau</small>
            <span>{cycle.email_counts_by_level.map((level) => `N${level.level} ${formatCount(level.count)}`).join(' · ') || '—'}</span>
          </div>
          <div className="prospection-inline-list">
            <small>Écarts par motif</small>
            <span>{cycle.deviation_counts.map((deviation) => `${humanizeCode(deviation.reason_code)} ${formatCount(deviation.count)}`).join(' · ') || 'Aucun écart'}</span>
          </div>
        </article>
      )}
    </section>
  )
}

function ResultsSection({ data }: { data: FounderProspection }) {
  const { results } = data
  return (
    <section id="results" className="control-section prospection-section prospection-compact-section" aria-labelledby="results-title">
      <ProspectionSectionHeading
        eyebrow="Boucle commerciale"
        title="Résultats"
        titleId="results-title"
        description="Progression observée depuis les envois jusqu’au revenu récurrent."
        meta={`Actualisé ${formatDateTime(data.generated_at)} · ${timerShortLabel(data)}`}
      />
      <div className="prospection-results-grid">
        <CompactMetric label="Envoyés" value={results.sent_count} />
        <CompactMetric label="Ouvertures" value={results.opened_count} />
        <CompactMetric label="Clics /a/{token}" value={results.attribution_click_count} />
        <CompactMetric label="Atterrissages" value={results.landing_count} />
        <CompactMetric label="Profils confirmés" value={results.confirmed_profile_count} />
        <CompactMetric label="Comptes payants" value={results.paid_account_count} />
        <CompactMetric
          label="MRR"
          value={results.mrr_by_currency.length > 0
            ? results.mrr_by_currency.map((money) => formatMoney(money.minor_units, money.currency)).join(' · ')
            : '0'}
        />
      </div>
      {results.no_sends_yet ? <p className="prospection-no-send">Aucun envoi à ce jour.</p> : null}
    </section>
  )
}

function MailDrawer({ item, onClose }: { item: FounderProspectionQueueItem; onClose: () => void }) {
  return (
    <div className="prospection-drawer-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <aside
        className="prospection-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Mail préparé pour ${item.company_name}`}
      >
        <header>
          <div>
            <small>Mail préparé · lecture seule</small>
            <h2 id="prospection-mail-title">{item.company_name}</h2>
          </div>
          <button type="button" aria-label="Fermer" onClick={onClose}>×</button>
        </header>
        <dl>
          <div><dt>À</dt><dd>{item.email_address}</dd></div>
          <div><dt>Objet</dt><dd>{item.mail_subject}</dd></div>
        </dl>
        <pre>{item.mail_body}</pre>
        <footer>
          <span>{ASSISTED_TOOLTIP}</span>
          <LockedAction>Envoyer</LockedAction>
        </footer>
      </aside>
    </div>
  )
}

function LockedAction({
  children,
  describedBy,
  emphasis = false,
}: {
  children: string
  describedBy?: string
  emphasis?: boolean
}) {
  return (
    <span className="prospection-action-lock" tabIndex={0} data-tooltip={ASSISTED_TOOLTIP}>
      <button
        type="button"
        disabled
        title={ASSISTED_TOOLTIP}
        aria-describedby={describedBy}
        className={emphasis ? 'prospection-action-primary' : undefined}
      >
        {children}
      </button>
    </span>
  )
}

function FilterSelect({
  label,
  value,
  disabled,
  options,
  onChange,
}: {
  label: string
  value: string
  disabled: boolean
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
}) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        <option value="">Tous</option>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  )
}

function DirectoryStatus({ row }: { row: FounderDirectoryRow }) {
  if (row.reverification_required_at) return <span className="prospection-pill prospection-pill-warning">À revérifier</span>
  if (row.confirmed_domain) return <span className="prospection-pill prospection-pill-positive">Domaine confirmé</span>
  if (!row.domain && !row.website_url) return <span className="prospection-pill">Sans site</span>
  return <span className="prospection-pill">À qualifier</span>
}

function FacetList({ label, values }: { label: string; values: Array<{ key: string; label: string; count: number }> }) {
  return (
    <div>
      <span>{label}</span>
      <ul>
        {values.map((value) => (
          <li key={value.key}><span>{value.label}</span><strong>{formatCount(value.count)}</strong></li>
        ))}
      </ul>
    </div>
  )
}

function ProspectionKpi({ label, value, tone = 'neutral' }: { label: string; value: number; tone?: 'neutral' | 'positive' | 'warning' }) {
  return (
    <article className={`prospection-kpi prospection-kpi-${tone}`}>
      <span>{label}</span>
      <strong>{formatCount(value)}</strong>
    </article>
  )
}

function CompactMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="prospection-compact-metric">
      <span>{label}</span>
      <strong>{typeof value === 'number' ? formatCount(value) : value}</strong>
    </article>
  )
}

function ProspectionSectionHeading({
  eyebrow,
  title,
  titleId,
  description,
  meta,
}: {
  eyebrow: string
  title: string
  titleId: string
  description: string
  meta: string
}) {
  return (
    <div className="prospection-section-heading">
      <div>
        <p className="control-eyebrow">{eyebrow}</p>
        <h2 id={titleId}>{title}</h2>
        <p>{description}</p>
      </div>
      <span>{meta}</span>
    </div>
  )
}

function CompactEmpty({ title, body }: { title: string; body: string }) {
  return (
    <div className="prospection-compact-empty control-panel">
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  )
}

function familyLabel(value: string): string {
  return FAMILY_LABELS[value] ?? humanizeCode(value)
}

function sourceLabel(value: string | null): string {
  if (!value) return 'Source inconnue'
  const labels: Record<string, string> = { apollo: 'Apollo', site: 'Site', manual: 'Manuel' }
  return labels[value.toLowerCase()] ?? humanizeCode(value)
}

function timerLabel(data: FounderProspection): string {
  if (data.timer.state === 'RUNNING') {
    return data.timer.next_trigger_at
      ? `Actif · prochain passage ${formatDateTime(data.timer.next_trigger_at)}`
      : 'Actif'
  }
  if (data.timer.state === 'STOPPED') {
    const stoppedAt = data.timer.inactive_since ?? data.timer.last_triggered_at
    return stoppedAt ? `Arrêté depuis le ${formatDateTime(stoppedAt)}` : 'Arrêté'
  }
  return 'État indisponible'
}

function timerShortLabel(data: FounderProspection): string {
  if (data.timer.state === 'RUNNING') return 'timer actif'
  if (data.timer.state === 'STOPPED') {
    const stoppedAt = data.timer.inactive_since ?? data.timer.last_triggered_at
    return stoppedAt ? `arrêté depuis le ${formatDateTime(stoppedAt)}` : 'timer arrêté'
  }
  return 'timer inconnu'
}

function lastCycleLabel(data: FounderProspection): string {
  const cycle = data.targeting
  if (!cycle) return 'Aucun cycle enregistré'
  return `Dernier cycle ${formatDateTime(cycle.updated_at)} · ${humanizeCode(cycle.status)}`
}

function cycleDateLabel(value: string | null): string {
  return value ? `Dernier cycle le ${formatDateTime(value)}` : 'Aucun cycle enregistré'
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('fr-CH').format(value)
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'date indisponible'
  return new Intl.DateTimeFormat('fr-CH', { dateStyle: 'medium', timeZone: 'Europe/Zurich' }).format(parsed)
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

function formatOptionalMoney(minorUnits: number | null, currency: string | null): string {
  if (minorUnits === null || !currency) return 'Montant non renseigné'
  return formatMoney(minorUnits, currency)
}

function formatMoney(minorUnits: number, currency: string): string {
  try {
    return new Intl.NumberFormat('fr-CH', {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }).format(minorUnits / 100)
  } catch {
    return `${formatCount(minorUnits / 100)} ${currency}`
  }
}

function humanizeCode(value: string | null): string {
  if (!value) return '—'
  const words = value.replaceAll('-', ' ').replaceAll('_', ' ').toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : '—'
}
