import { useId } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { companies } from '../../api/endpoints'
import type { CompanyProfile, PlanCode, UnifiedStatus, UnlockedFeedItem } from '../../api/types'
import { CompanyContactBlock } from '../../companies/CompanyProfileV2'
import { interpolate, useI18n } from '../../i18n'
import { normalCasePlace } from '../../presentation/locationText'
import { MatchDots } from './MatchDots'
import { StatusPill } from './StatusPill'
import {
  MISSING,
  drawerPlaceLabel,
  placeLabel,
  sentenceCase,
  signalObject,
} from './SignalRow'
import { monthLabel } from '../valueFormat'
import styles from './signals.module.css'

function Fact({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode | null
}) {
  if (children === null || children === undefined || children === '' || children === MISSING) return null
  return (
    <>
      <dt>{label}</dt>
      <dd className={className}>{children}</dd>
    </>
  )
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
  redesigned = false,
  holderProfile = null,
  planCode = null,
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
  /** Sous 900 px, le tiroir s'ouvre dans une feuille Radix qui porte déjà son
   *  propre bouton de fermeture : afficher aussi le nôtre donnerait DEUX
   *  contrôles « Fermer » pour un seul geste. */
  compact?: boolean
  redesigned?: boolean
  holderProfile?: CompanyProfile | null
  planCode?: PlanCode | null
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
          <button type="button" className="text-link" onClick={onRetry}>
            {t.common.retry}
          </button>
        </div>
      </aside>
    )
  }

  if (!item) {
    return (
      <aside className={styles.drawer} aria-label={copy.select}>
        <p className={styles.drawerEmpty}>{copy.select}</p>
      </aside>
    )
  }

  const title = sentenceCase(signalObject(item))
  const objectLine = sentenceCase(
    item.factual_display.object_short ?? item.contract.title ?? null,
  )
  const money = amount(item.contract.amount?.value, item.contract.amount?.currency)
  const rawPlace = placeLabel(item.contract.location, locale)
  const place = rawPlace === MISSING
    ? rawPlace
    : item.contract.location?.locality
      ? `à ${rawPlace}`
      : `en ${rawPlace}`
  const reasons = item.analysis.fit.for_you_sentence
    ? [item.analysis.fit.for_you_sentence]
    : []
  const calendarMonth = item.commercial_calendar
    ? monthLabel(item.commercial_calendar.start_month, locale)
    : null
  const calendarText = calendarMonth
    ? [
        interpolate(copy.calendarStart, { month: calendarMonth }),
        item.commercial_calendar?.duration_months
          ? interpolate(copy.calendarDuration, { count: item.commercial_calendar.duration_months })
          : null,
      ].filter(Boolean).join(' · ')
    : null
  const history = item.holder_history?.last_12_months
  const historyParts = history
    ? [
        interpolate(history.awards_count === 1 ? copy.marketWonOne : copy.marketWonOther, {
          count: history.awards_count,
        }),
        history.total_amounts?.map((moneyItem) => amount(moneyItem.value, moneyItem.currency)).filter(Boolean).join(' · '),
        history.recurring_buyers?.length
          ? interpolate(copy.recurringBuyers, { buyers: history.recurring_buyers.join(', ') })
          : null,
      ].filter((part): part is string => Boolean(part))
    : []

  /* Trois horloges, une seule vérité affichée : l'attribution prime, la
   * notification la remplace, la publication ferme la marche. L'intitulé
   * change avec l'horloge — présenter une date de publication comme une date
   * d'attribution serait un mensonge de plus dans un métier qui n'en supporte
   * aucun. */
  const dates = item.contract.dates
  const clock = dates.award
    ? { label: copy.awardedOn, value: dates.award }
    : dates.contract_notification
      ? { label: copy.awardedOn, value: dates.contract_notification }
      : dates.publication
        ? { label: copy.publishedOn, value: dates.publication }
        : { label: copy.awardedOn, value: null }

  const actions: {
    status: UnifiedStatus
    action: string
    state: string
    onClick: () => void
    primary: boolean
  }[] = [
    {
      status: 'contacted',
      action: copy.contact,
      state: copy.contacted,
      onClick: onContacted,
      primary: true,
    },
    { status: 'saved', action: copy.save, state: copy.saved, onClick: onSave, primary: false },
    {
      status: 'ignored',
      action: copy.ignore,
      state: copy.ignored,
      onClick: onIgnore,
      primary: false,
    },
  ]

  const sourceIdentity = [item.source.system, item.source.notice_id].filter(Boolean).join(' ')
  const sourceText = sourceIdentity
    ? interpolate(copy.source, {
        system: item.source.system ?? '',
        notice: item.source.notice_id ?? '',
      }).replace(/\s+/g, ' ').trim()
    : null

  if (redesigned) {
    const decisionPlace = drawerPlaceLabel(item.contract.location)
    const profileDirectory = holderProfile?.directory
    const holderMarketCount = holderProfile?.market_summary?.last_12_months?.awards_count
      ?? item.holder_history?.last_12_months?.awards_count
    const holderActivity = profileDirectory?.naf_label ?? profileDirectory?.family_labels?.[0]
    const holderLocation = normalCasePlace(profileDirectory?.city)
    const holderFacts = [
      holderActivity,
      holderLocation,
      profileDirectory?.employees === undefined ? null : `${profileDirectory.employees} salariés`,
      holderMarketCount === undefined
        ? null
        : `${holderMarketCount} marché${holderMarketCount > 1 ? 's' : ''} gagné${holderMarketCount > 1 ? 's' : ''} en 12 mois`,
    ].filter((value): value is string => Boolean(value))
    const generatedWhy = item.analysis.fit.for_you_sentence?.trim() ?? ''
    const foldedTitle = (title ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr-FR')
    const foldedWhy = generatedWhy.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr-FR')
    const titleLead = foldedTitle.split(/\s+/).slice(0, 4).join(' ')
    const titleRepeated = titleLead.length > 5 && foldedWhy.startsWith(titleLead)
    const fallbackWhy = 'Ce marché correspond à votre profil cible dans cette zone et ce secteur.'
    let why = generatedWhy && !titleRepeated ? generatedWhy : fallbackWhy
    const department = item.contract.location?.subdivision_label?.trim()
    if (!item.contract.location?.locality && department) {
      const escapedDepartment = department.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      why = why.replace(new RegExp(`\\bà ${escapedDepartment}\\b`, 'gi'), `en ${department}`)
    }
    const clockDate = date(clock.value)

    return (
      <aside className={`${styles.drawer} ${styles.decisionDrawer}`} aria-labelledby={titleId} data-signal-key={item.signal_id}>
        <div className={styles.drawerHead}>
          <StatusPill status={item.status} />
          {clockDate ? <span className={styles.datePill}>{clock.label} {clockDate}</span> : null}
          {compact ? null : <button type="button" className={styles.drawerClose} onClick={onClose}>{copy.close}</button>}
        </div>

        <h2 className={styles.decisionTitle} id={titleId}>{title ?? copy.select}</h2>
        <p className={styles.decisionMeta}>
          {[money, decisionPlace === MISSING ? null : decisionPlace, item.contract.buyer?.name ? `acheteur : ${item.contract.buyer.name}` : null]
            .filter(Boolean)
            .join(' · ')}
        </p>

        <section className={styles.holderBlock}>
          <div className={styles.holderHead}>
            <div>
              <h3 className="section-label">Titulaire</h3>
              {item.company.name ? item.company_key ? (
                <Link className={styles.holderName} to={`/app/companies/${item.company_key}`}>{item.company.name}</Link>
              ) : <strong className={styles.holderName}>{item.company.name}</strong> : null}
              {holderFacts.length ? <p>{holderFacts.join(' · ')}</p> : null}
            </div>
            {item.company_key ? <Link className={styles.holderProfileLink} to={`/app/companies/${item.company_key}`}>Voir la fiche →</Link> : null}
          </div>
          {item.company_key ? (
            <CompanyContactBlock
              companyKey={item.company_key}
              directory={profileDirectory}
              fallbackAddress={holderProfile?.official_identity.address}
              fallbackWebsite={holderProfile?.official_identity.website_url}
              fallbackSource={holderProfile?.official_identity.source}
              planCode={holderProfile?.plan_code ?? planCode ?? 'discovery'}
              initialLookup={holderProfile?.contact_lookup}
              onReloadLookup={async () => (await companies.get(item.company_key as string)).contact_lookup ?? null}
              showHeading={false}
            />
          ) : null}
        </section>

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
            <button key={action.status} type="button" className={action.primary ? styles.actionPrimary : styles.action} disabled={busy} onClick={action.onClick}>{action.action}</button>
          ))}
        </div>

        {sourceText && item.source.url ? (
          <a className={`${styles.source} ${styles.decisionSourceLine} source-link`} href={item.source.url} target="_blank" rel="noopener noreferrer">{sourceText} ↗</a>
        ) : sourceText ? <p className={`${styles.source} ${styles.decisionSourceLine}`}>{sourceText}</p> : null}
      </aside>
    )
  }

  return (
    <aside
      className={styles.drawer}
      aria-labelledby={titleId}
      data-signal-key={item.signal_id}
    >
      <div className={styles.drawerHead}>
        <StatusPill status={item.status} />
        <MatchDots item={item} />
        {compact ? null : (
          <button type="button" className={styles.drawerClose} onClick={onClose}>
            {copy.close}
          </button>
        )}
      </div>

      <h2 className={styles.drawerTitle} id={titleId}>
        {title ?? copy.select}
      </h2>
      {objectLine && objectLine !== title ? (
        <p className={styles.drawerObject}>{objectLine}</p>
      ) : null}

      <dl className={styles.facts}>
        <Fact label={copy.winner}>
          {item.company.name === null ? (
            null
          ) : item.company_key ? (
            <Link className={styles.factLink} to={`/app/companies/${item.company_key}`}>
              {item.company.name}
            </Link>
          ) : (
            item.company.name
          )}
        </Fact>
        <Fact label={copy.buyer}>{item.contract.buyer?.name ?? null}</Fact>
        <Fact label={copy.amount} className={styles.factAmount}>
          {money}
        </Fact>
        <Fact label={copy.place}>{place === MISSING ? null : place}</Fact>
        <Fact label={clock.label}>{date(clock.value)}</Fact>
        <Fact label={copy.cpv}>{item.contract.cpv ?? null}</Fact>
      </dl>

      {calendarText ? (
        <section className={styles.valueBlock}>
          <h3 className="section-label">{copy.calendar}</h3>
          <p>{calendarText}</p>
          <small>{copy.publicNoticeSource}</small>
        </section>
      ) : null}

      {historyParts.length > 0 ? (
        <section className={styles.valueBlock}>
          <h3 className="section-label">{copy.holderHistory}</h3>
          <p>{historyParts.join(' · ')}</p>
          {item.company_key ? (
            <Link className={styles.valueLink} to={`/app/companies/${item.company_key}`}>
              {copy.companyProfile}
            </Link>
          ) : null}
          {item.holder_history?.resolution_note ? (
            <small>{item.holder_history.resolution_note}</small>
          ) : null}
          <small>{copy.publicAwardsSource}</small>
        </section>
      ) : null}

      {item.local_circuit?.length ? (
        <section className={styles.valueBlock}>
          <h3 className="section-label">{copy.localCircuit}</h3>
          <ul className={styles.localCircuit}>
            {item.local_circuit.map((company) => (
              <li key={company.siren}>
                <Link to={company.href}>{company.name}</Link>
                <span>
                  {[company.trade, normalCasePlace(company.city), company.employees === undefined
                    ? null
                    : interpolate(copy.employees, { count: company.employees })]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </li>
            ))}
          </ul>
          <small>{copy.registerSource}</small>
        </section>
      ) : null}

      {reasons.length > 0 ? (
        <section className={styles.why}>
          <h3 className="section-label">{copy.why}</h3>
          <ul>
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className={styles.actions}>
        {actions.map((action) =>
          item.status === action.status ? (
            <button
              key={action.status}
              type="button"
              className={styles.actionState}
              data-state={action.status}
              disabled
            >
              {action.state} ✓
            </button>
          ) : (
            <button
              key={action.status}
              type="button"
              className={action.primary ? styles.actionPrimary : styles.action}
              disabled={busy}
              onClick={action.onClick}
            >
              {action.action}
            </button>
          ),
        )}
      </div>

      {sourceText && item.source.url ? (
        <a
          className={`${styles.source} source-link`}
          href={item.source.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {sourceText} ↗
        </a>
      ) : sourceText ? (
        <p className={styles.source}>{sourceText}</p>
      ) : null}
    </aside>
  )
}
