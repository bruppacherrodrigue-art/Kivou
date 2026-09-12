import { useId } from 'react'
import { Link } from 'react-router-dom'
import { companies } from '../../api/endpoints'
import type { CompanyProfile, PlanCode, UnifiedStatus, UnlockedFeedItem } from '../../api/types'
import { CompanyPanel } from '../../companies/CompanyPanel'
import { interpolate, useI18n } from '../../i18n'
import { normalCasePlace } from '../../presentation/locationText'
import { StatusPill } from './StatusPill'
import { MISSING, drawerPlaceLabel, sentenceCase, signalObject } from './SignalRow'
import { monthLabel } from '../valueFormat'
import styles from './signals.module.css'

export interface SignalReturnCompany {
  href: string
  name: string
}

export function SignalDrawer({
  item,
  loading,
  error,
  onClose,
  onRetry,
  onContacted,
  onSave,
  onIgnore,
  busy,
  compact = false,
  holderProfile = null,
  planCode = null,
  returnToCompany = null,
}: {
  item: UnlockedFeedItem | null
  loading: boolean
  error: unknown | null
  onClose: () => void
  onRetry: () => void
  onContacted: () => void
  onSave: () => void
  onIgnore: () => void
  busy: boolean
  compact?: boolean
  holderProfile?: CompanyProfile | null
  planCode?: PlanCode | null
  returnToCompany?: SignalReturnCompany | null
  /** Compatibilité d'appel jusqu'à la mise à jour des tests après validation.
   * Le rendu n'a plus aucune branche historique. */
  redesigned?: boolean
}) {
  const { t, locale, amount, date } = useI18n()
  const copy = t.signalsTable.drawer
  const titleId = useId()

  if (loading) {
    return (
      <aside className={styles.drawer} aria-label={copy.loading}>
        <div className={styles.skeleton} role="status" aria-label={copy.loading}>
          <span className={styles.skeletonLine} />
          <span className={styles.skeletonLine} />
          <span className={styles.skeletonLine} />
        </div>
      </aside>
    )
  }

  if (error) {
    return (
      <aside className={styles.drawer} aria-label={copy.error}>
        <div className={styles.drawerNotice} role="alert">
          <p>{copy.error}</p>
          <button type="button" className="text-link" onClick={onRetry}>{t.common.retry}</button>
        </div>
      </aside>
    )
  }

  if (!item) {
    return <aside className={styles.drawer} aria-label={copy.select}><p className={styles.drawerEmpty}>{copy.select}</p></aside>
  }

  const title = sentenceCase(signalObject(item))
  const money = amount(item.contract.amount?.value, item.contract.amount?.currency)
  const decisionPlace = drawerPlaceLabel(item.contract.location)
  const calendarMonth = item.commercial_calendar
    ? monthLabel(item.commercial_calendar.start_month, locale)
    : null
  const dates = item.contract.dates
  const clock = dates.award
    ? { label: copy.awardedOn, value: dates.award }
    : dates.contract_notification
      ? { label: copy.awardedOn, value: dates.contract_notification }
      : { label: copy.awardedOn, value: null }
  const generatedWhy = item.analysis.fit.for_you_sentence?.trim() ?? ''
  const foldedWhy = generatedWhy.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr-FR')
  const titleRepeated = [item.factual_display.object_short, item.contract.title, item.contract.lot_title]
    .some((candidate) => {
      const lead = (candidate ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLocaleLowerCase('fr-FR')
        .split(/\s+/)
        .slice(0, 4)
        .join(' ')
      return lead.length > 5 && foldedWhy.includes(lead)
    })
  const technicalWhy = [
    'territoire metropolitain',
    'france metropolitaine',
  ].some((value) => foldedWhy.includes(value))
    || /\b(?:boamp|decp)\b/u.test(foldedWhy)
  const fallbackWhy = 'Ce marché correspond à votre profil cible dans cette zone et ce secteur.'
  let why = generatedWhy && !titleRepeated && !technicalWhy ? generatedWhy : fallbackWhy
  const department = normalCasePlace(item.contract.location?.subdivision_label)
  if (!item.contract.location?.locality && department) {
    const escapedDepartment = department.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    why = why.replace(
      new RegExp(`(^|\\s)à\\s+${escapedDepartment}(?=\\s|[,(.]|$)`, 'giu'),
      `$1en ${department}`,
    )
  }
  const sourceIdentity = [item.source.system, item.source.notice_id].filter(Boolean).join(' ')
  const sourceText = sourceIdentity
    ? interpolate(copy.source, {
        system: item.source.system ?? '',
        notice: item.source.notice_id ?? '',
      }).replace(/\s+/g, ' ').trim()
    : null
  const actions: Array<{
    status: UnifiedStatus
    action: string
    state: string
    onClick: () => void
  }> = [
    { status: 'contacted', action: copy.contact, state: copy.contacted, onClick: onContacted },
    { status: 'saved', action: copy.save, state: copy.saved, onClick: onSave },
    { status: 'ignored', action: copy.ignore, state: copy.ignored, onClick: onIgnore },
  ]

  return (
    <aside className={`${styles.drawer} ${styles.decisionDrawer}`} aria-labelledby={titleId} data-signal-key={item.signal_id}>
      {returnToCompany ? (
        <Link className={styles.drawerReturn} to={returnToCompany.href}>← Retour à {returnToCompany.name}</Link>
      ) : null}
      <div className={styles.drawerHead}>
        <StatusPill status={item.status} />
        {date(clock.value) ? <span className={styles.datePill}>{clock.label} {date(clock.value)}</span> : null}
        {compact ? null : <button type="button" className={styles.drawerClose} onClick={onClose}>{copy.close}</button>}
      </div>

      <h2 className={styles.decisionTitle} id={titleId}>{title ?? copy.select}</h2>
      <p className={styles.decisionMeta}>
        {[money, decisionPlace === MISSING ? null : decisionPlace, item.contract.buyer?.name ? `acheteur : ${item.contract.buyer.name}` : null]
          .filter(Boolean)
          .join(' · ')}
      </p>

      {item.company.name && item.company_key ? (
        <section className={styles.holderBlock}>
          <h3 className="section-label">Titulaire</h3>
          <CompanyPanel
            mode="holder"
            companyKey={item.company_key}
            companyHref={`/app/companies/${item.company_key}`}
            name={item.company.name}
            directory={holderProfile?.directory}
            fallbackCity={holderProfile?.city}
            fallbackAddress={holderProfile?.official_identity.address}
            fallbackWebsite={holderProfile?.official_identity.website_url}
            fallbackSource={holderProfile?.official_identity.source}
            planCode={holderProfile?.plan_code ?? planCode ?? 'discovery'}
            contactLookup={holderProfile?.contact_lookup}
            marketSummary={holderProfile?.market_summary}
            markets={[]}
            contactStatus={holderProfile?.contact_status ?? 'to_contact'}
            history={holderProfile?.history ?? []}
            note={holderProfile?.note ?? null}
            contactBusy={false}
            contactError={null}
            onContact={async () => undefined}
            onReloadLookup={async () => (await companies.get(item.company_key as string)).contact_lookup ?? null}
          />
        </section>
      ) : item.company.name ? (
        <section className={styles.holderBlock}>
          <h3 className="section-label">Titulaire</h3>
          <strong className={styles.holderName}>{item.company.name}</strong>
        </section>
      ) : null}

      <section className={styles.decisionSection}>
        <h3 className="section-label">Pourquoi ça vous concerne</h3>
        <p className={styles.whySentence}>{why}</p>
      </section>

      {calendarMonth ? (
        <section className={styles.decisionSection}>
          <h3 className="section-label">Calendrier</h3>
          <dl className={styles.calendarFacts}>
            <dt>Démarrage</dt><dd>probable en {calendarMonth}</dd>
            {item.commercial_calendar?.duration_months ? <><dt>Durée</dt><dd>{item.commercial_calendar.duration_months} mois</dd></> : null}
          </dl>
        </section>
      ) : null}

      {item.local_circuit?.length ? (
        <section className={styles.decisionSection}>
          <h3 className="section-label">Le circuit local</h3>
          <ul className={styles.decisionCircuit}>
            {item.local_circuit.slice(0, 4).map((company) => (
              <li key={company.siren}>
                <span><Link to={company.href}>{company.name}</Link>{company.trade ? ` · ${company.trade}` : ''}</span>
                <small>{[normalCasePlace(company.city), company.employees === undefined ? null : `${company.employees} sal.`].filter(Boolean).join(' · ')}</small>
              </li>
            ))}
          </ul>
          <small className={styles.decisionSource}>{copy.registerSource}</small>
        </section>
      ) : null}

      <div className={styles.actions}>
        {actions.map((action) => item.status === action.status ? (
          <button key={action.status} type="button" className={styles.actionState} data-state={action.status} disabled>{action.state} ✓</button>
        ) : (
          <button key={action.status} type="button" className={styles.action} disabled={busy} onClick={action.onClick}>{action.action}</button>
        ))}
      </div>

      {sourceText && item.source.url ? (
        <a className={`${styles.source} ${styles.decisionSourceLine}`} href={item.source.url} target="_blank" rel="noopener noreferrer">{sourceText} ↗</a>
      ) : sourceText ? <p className={`${styles.source} ${styles.decisionSourceLine}`}>{sourceText}</p> : null}
    </aside>
  )
}
