import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { companies } from '../api/endpoints'
import type {
  CommercialCalendar,
  CompanyContactLookup,
  CompanyContactStatus,
  CompanyProfile,
  DirectoryCompany,
  DirectoryCompanyProfile,
  Money,
  PlanCode,
} from '../api/types'
import { useI18n } from '../i18n'
import styles from './CompaniesPage.module.css'

export interface CompanyProfileMarket {
  id: string
  title?: string | null
  date?: string | null
  amount?: Money | null
  buyers?: string[]
  sourceUrl?: string | null
  calendar?: CommercialCalendar
  onOpen?: () => void
}

interface CompanyProfileV2Props {
  companyKey: string
  name: string
  directory?: DirectoryCompany | null
  fallbackCity?: string | null
  fallbackAddress?: string | null
  fallbackWebsite?: string | null
  fallbackSource?: 'public_notice' | 'official_register'
  planCode: PlanCode
  contactLookup?: CompanyContactLookup | null
  marketSummary?: DirectoryCompanyProfile['market_summary'] | null
  markets: CompanyProfileMarket[]
  contactStatus: CompanyContactStatus
  history: CompanyProfile['history']
  note: string | null
  contactBusy: boolean
  contactError: string | null
  onContact: (status: CompanyContactStatus) => Promise<void>
  onReloadLookup: () => Promise<CompanyContactLookup | null>
  onClose?: () => void
  standalone?: boolean
}

function safeWebsite(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

function websiteLabel(value: string): string {
  return new URL(value).hostname.replace(/^www\./, '')
}

function sourceLabel(value: string | null | undefined): string | null {
  if (!value) return null
  if (value === 'official_register' || value === 'registre') return 'registre national des entreprises'
  if (value === 'public_notice') return 'avis public'
  if (value === 'site') return 'site de l’entreprise'
  if (value === 'model') return 'analyse automatisée'
  if (value === 'serper') return 'moteur de recherche'
  if (value === 'apollo') return 'Apollo'
  return value
}

function factSource(source: string | null | undefined, observedAt: string | null | undefined, formattedDate: (value: string | null | undefined) => string | null) {
  const label = sourceLabel(source)
  const observed = formattedDate(observedAt)
  if (!label) return null
  return `Source : ${label}${observed ? ` · ${observed}` : ''}`
}

function formatSiren(value: string): string {
  return /^\d{9}$/.test(value)
    ? `${value.slice(0, 3)} ${value.slice(3, 6)} ${value.slice(6)}`
    : value
}

function calendarLabel(calendar: CommercialCalendar, locale: string): string | null {
  const parsed = new Date(`${calendar.start_month}-01T12:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return null
  const month = new Intl.DateTimeFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed)
  return `Démarrage probable du dernier chantier : ${month}${calendar.duration_months ? ` · durée ${calendar.duration_months} mois` : ''}`
}

export function CompanyContactBlock({
  companyKey,
  directory,
  fallbackAddress,
  fallbackWebsite,
  fallbackSource,
  planCode,
  initialLookup,
  onReloadLookup,
  showHeading = true,
}: {
  companyKey: string
  directory?: DirectoryCompany | null
  fallbackAddress?: string | null
  fallbackWebsite?: string | null
  fallbackSource?: 'public_notice' | 'official_register'
  planCode: PlanCode
  initialLookup?: CompanyContactLookup | null
  onReloadLookup: () => Promise<CompanyContactLookup | null>
  showHeading?: boolean
}) {
  const { date } = useI18n()
  const [lookup, setLookup] = useState(initialLookup ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLookup(initialLookup ?? null)
    setBusy(false)
    setError(null)
  }, [companyKey, initialLookup])

  useEffect(() => {
    if (lookup?.state !== 'researching') return
    let active = true
    const poll = window.setInterval(() => {
      void onReloadLookup().then((next) => {
        if (active) setLookup(next)
      }).catch(() => undefined)
    }, 2_000)
    return () => {
      active = false
      window.clearInterval(poll)
    }
  }, [lookup?.state, onReloadLookup])

  const runLookup = async () => {
    if (!lookup || busy || lookup.state === 'locked' || lookup.state === 'quota_exhausted' || lookup.state === 'identity_unavailable') return
    setBusy(true)
    setError(null)
    setLookup((current) => current ? { ...current, state: 'researching' } : null)
    try {
      setLookup(await companies.contactLookup(companyKey))
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'contact_lookup_quota_exhausted') {
        setLookup((current) => current ? { ...current, state: 'quota_exhausted', remaining: 0 } : null)
        setError('Le quota mensuel vient d’être épuisé.')
      } else if (caught instanceof ApiError && (caught.code === 'contact_lookup_identity_unavailable' || caught.code === 'contact_lookup_suppressed')) {
        setLookup((current) => current ? {
          state: 'identity_unavailable',
          remaining: current.remaining,
          monthly_quota: current.monthly_quota,
          next_reset_at: current.next_reset_at,
          source: current.source,
          removal_path: current.removal_path,
        } : null)
        setError('L’identité annuaire de cette entreprise ne permet pas encore la recherche.')
      } else {
        setLookup((current) => current ? { ...current, state: 'failed' } : null)
        setError('La recherche n’a pas abouti. Réessayez dans quelques instants.')
      }
    } finally {
      setBusy(false)
    }
  }

  const directoryWebsite = safeWebsite(directory?.website_url)
  const website = directoryWebsite ?? safeWebsite(fallbackWebsite)
  const director = directory?.director_display_name ?? directory?.directors?.[0]?.name
  const directorTitle = directory?.director_display_title
    ?? directory?.directors?.find((item) => item.name === director)?.title
  const contactFacts = Boolean(
    director || directory?.phone || directory?.published_email || website || fallbackAddress,
  )
  const directorSource = factSource('registre', directory?.directors_observed_at, date)
  const phoneSource = factSource(directory?.phone_source, directory?.phone_observed_at, date)
  const emailSource = factSource('site', directory?.published_email_observed_at, date)
  const websiteSource = factSource(
    directoryWebsite ? directory?.website_source ?? directory?.source : fallbackSource,
    directoryWebsite ? directory?.website_observed_at : undefined,
    date,
  )
  const addressSource = factSource(fallbackSource, undefined, date)
  const discovery = planCode === 'discovery'
  const planQuota = planCode === 'essential' ? 20 : planCode === 'pro' ? 100 : 0
  const remainingLabel = lookup
    ? `${lookup.remaining} recherche${lookup.remaining > 1 ? 's' : ''} restante${lookup.remaining > 1 ? 's' : ''} ce mois`
    : planQuota > 0
      ? `${planQuota} recherches restantes ce mois`
      : null
  const showInitialButton = !discovery && (!lookup || ['available', 'quota_exhausted', 'identity_unavailable'].includes(lookup.state))
  const showRefreshButton = lookup && (lookup.state === 'failed' || Boolean(lookup.can_refresh))

  if (discovery) {
    return (
      <section className={`${styles.companyV2Section} ${showHeading ? '' : styles.companyContactEmbedded}`}>
        {showHeading ? <h3>Contact</h3> : null}
        <div className={`${styles.companyContactCard} ${styles.companyContactLocked}`}>
          <div className={styles.companyContactBlur} aria-hidden="true">
            <div className={styles.companyContactLead}>
              <strong>Camille Martin</strong>
              <span className={styles.companyPillNeutral}>Direction</span>
            </div>
            <dl className={styles.companyKeyValues}>
              <dt>Téléphone</dt><dd>01 84 80 20 10</dd>
              <dt>Site</dt><dd>entreprise.fr ↗</dd>
            </dl>
          </div>
          <div className={styles.companyContactOffer}>
            <strong>Le contact du titulaire est inclus dans l'offre Essentiel — 49 €/mois</strong>
            <Link className={styles.companyPrimaryButton} to="/tarifs">Voir l'offre Essentiel</Link>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className={`${styles.companyV2Section} ${showHeading ? '' : styles.companyContactEmbedded}`}>
      {showHeading ? <h3>Contact</h3> : null}
      <div className={styles.companyContactCard}>
        <div>
          {director ? (
            <div className={styles.companyContactLead}>
              <span><strong>{director}</strong>{directorSource ? <small className={styles.companySource}>{directorSource}</small> : null}</span>
              {directorTitle ? <span className={styles.companyPillNeutral}>{directorTitle}</span> : null}
            </div>
          ) : null}
          {contactFacts ? (
            <dl className={styles.companyKeyValues}>
              {directory?.phone ? <><dt>Téléphone</dt><dd><a href={`tel:${directory.phone.replace(/[^+\d]/g, '')}`}>{directory.phone}</a>{phoneSource ? <small className={styles.companySource}>{phoneSource}</small> : null}</dd></> : null}
              {directory?.published_email ? <><dt>E-mail</dt><dd><a href={`mailto:${directory.published_email}`}>{directory.published_email}</a> <span className={styles.companyPill}>publié sur le site</span>{emailSource ? <small className={styles.companySource}>{emailSource}</small> : null}</dd></> : null}
              {website ? <><dt>Site</dt><dd><a href={website} target="_blank" rel="noreferrer">{websiteLabel(website)} ↗</a>{websiteSource ? <small className={styles.companySource}>{websiteSource}</small> : null}</dd></> : null}
              {fallbackAddress ? <><dt>Adresse</dt><dd>{fallbackAddress}{addressSource ? <small className={styles.companySource}>{addressSource}</small> : null}</dd></> : null}
            </dl>
          ) : null}

          {!discovery && lookup?.contacts?.length ? (
            <ul className={styles.companyDecisionMakers}>
              {lookup.contacts.map((contact) => (
                <li key={`${contact.email}-${contact.name}`}>
                  <strong>{contact.name}</strong>
                  <span>{contact.title}</span>
                  <a href={`mailto:${contact.email}`}>{contact.email}</a>
                  <small>E-mail vérifié</small>
                </li>
              ))}
            </ul>
          ) : null}
          {!discovery && lookup?.state === 'no_contact' ? <p className={styles.companyMuted}>Aucun décideur avec un e-mail professionnel vérifié n’a été trouvé.</p> : null}
          {!discovery ? (
            <div className={styles.companyActionRow}>
              {showInitialButton ? <button className={styles.companyPrimaryButton} type="button" disabled={!lookup || lookup.state !== 'available' || busy} onClick={() => void runLookup()}>Trouver le décideur</button> : null}
              {lookup?.state === 'researching' ? <button className={styles.companyPrimaryButton} type="button" disabled>Recherche en cours…</button> : null}
              {showRefreshButton ? <button className={styles.companyPrimaryButton} type="button" disabled={busy || lookup.remaining === 0} onClick={() => void runLookup()}>{lookup.can_refresh ? 'Actualiser' : 'Réessayer'}</button> : null}
              {remainingLabel ? <span className={styles.companySource}>e-mail nominatif vérifié · {remainingLabel}</span> : null}
            </div>
          ) : null}
          {!discovery && !lookup ? <p className={styles.companyMuted}>Recherche temporairement indisponible.</p> : null}
          {!discovery && error ? <p className={styles.actionError} role="alert">{error}</p> : null}
          {!discovery && lookup?.remaining === 0 && lookup.next_reset_at ? <p className={styles.companyMuted}>Quota mensuel épuisé · reprise le {date(lookup.next_reset_at)}</p> : null}
          {!discovery && lookup?.researched_at ? <p className={styles.companySource}>Source du décideur : Apollo · recherche du {date(lookup.researched_at)} · <Link to={lookup.removal_path}>Retrait</Link></p> : null}
        </div>
      </div>
    </section>
  )
}

function IdentityBlock({ directory }: { directory?: DirectoryCompany | null }) {
  if (!directory) return null
  const activity = [directory.naf_code, directory.naf_label].filter(Boolean).join(' — ')
  const directors = directory.directors
    ?.map((director) => [director.name, director.title?.toLocaleLowerCase('fr-FR')].filter(Boolean).join(', '))
    .join(' · ')
  const facts = [
    directory.siren ? ['SIREN', formatSiren(directory.siren)] : null,
    activity ? ['Activité', activity] : null,
    directory.employees === undefined ? null : ['Effectif', `${directory.employees} salariés`],
    directors ? ['Dirigeants', directors] : null,
  ].filter((value): value is string[] => Boolean(value))
  if (!facts.length) return null
  return (
    <section className={styles.companyV2Section}>
      <h3>Identité</h3>
      <dl className={styles.companyKeyValues}>
        {facts.map(([label, value]) => <span className={styles.companyKeyValueRow} key={label}><dt>{label}</dt><dd>{value}</dd></span>)}
      </dl>
      <p className={styles.companySource}>Source : registre national des entreprises{directory.resolution_note ? ` · ${directory.resolution_note}` : ''} · <Link to={directory.removal_path}>Retrait</Link></p>
    </section>
  )
}

function MarketsBlock({
  markets,
  summary,
}: {
  markets: CompanyProfileMarket[]
  summary?: DirectoryCompanyProfile['market_summary'] | null
}) {
  const { amount, date, locale } = useI18n()
  const first = markets[0]
  const lastYear = summary?.last_12_months
  const headingFacts = markets.length >= 2 ? [
    `${lastYear?.awards_count ?? markets.length} gagnés en 12 mois`,
    ...(lastYear?.total_amounts ?? []).map((money) => amount(money.value, money.currency)),
    lastYear?.recurring_buyers?.length ? `acheteurs récurrents : ${lastYear.recurring_buyers.join(', ')}` : null,
  ].filter((value): value is string => Boolean(value)) : []
  const firstFacts = markets.length === 1 ? [
    first.date ? date(first.date) : null,
    first.amount ? amount(first.amount.value, first.amount.currency) : null,
  ].filter((value): value is string => Boolean(value)) : []
  const calendar = first?.calendar ? calendarLabel(first.calendar, locale) : null

  return (
    <section className={styles.companyV2Section}>
      <h3>Marchés publics{headingFacts.length ? ` — ${headingFacts.join(' · ')}` : ''}</h3>
      {!markets.length ? <p className={styles.companyMuted}>Aucun marché public attribué connu.</p> : null}
      {markets.length === 1 && firstFacts.length ? <p className={styles.companyMarketIntro}>Premier marché connu : {firstFacts.join(' · ')}</p> : null}
      {markets.length ? (
        <ul className={styles.companyMarkets}>
          {markets.map((market) => {
            const marketAmount = market.amount ? amount(market.amount.value, market.amount.currency) : null
            const marketDate = date(market.date)
            return (
              <li key={market.id}>
                <button type="button" disabled={!market.onOpen} onClick={market.onOpen}>
                  {market.title ? <strong>{market.title}</strong> : null}
                  {marketAmount ? <span>{marketAmount}</span> : null}
                  {marketDate ? <small>{marketDate}</small> : null}
                </button>
                {market.buyers?.length ? <small>Acheteur : {market.buyers.join(', ')}</small> : null}
                {safeWebsite(market.sourceUrl) ? <a href={safeWebsite(market.sourceUrl) ?? undefined} target="_blank" rel="noreferrer">Source : marché public ↗</a> : <small>Source : marché public</small>}
              </li>
            )
          })}
        </ul>
      ) : null}
      {calendar ? <p className={styles.companyCalendar}>{calendar}</p> : null}
      {summary?.resolution_note ? <p className={styles.companySource}>{summary.resolution_note}</p> : null}
    </section>
  )
}

function EngagementBlock({
  companyKey,
  status,
  history: initialHistory,
  note: initialNote,
  busy,
  error,
  onContact,
}: {
  companyKey: string
  status: CompanyContactStatus
  history: CompanyProfile['history']
  note: string | null
  busy: boolean
  error: string | null
  onContact: (status: CompanyContactStatus) => Promise<void>
}) {
  const { date } = useI18n()
  const [noteOpen, setNoteOpen] = useState(Boolean(initialNote))
  const [note, setNote] = useState(initialNote ?? '')
  const [history, setHistory] = useState(initialHistory)
  const [noteSaved, setNoteSaved] = useState(false)
  const [noteError, setNoteError] = useState<string | null>(null)

  useEffect(() => {
    setNote(initialNote ?? '')
    setNoteOpen(Boolean(initialNote))
  }, [companyKey, initialNote])
  useEffect(() => setHistory(initialHistory), [initialHistory])

  const saveNote = async () => {
    if (note === (initialNote ?? '')) return
    setNoteError(null)
    setNoteSaved(false)
    const occurredAt = new Date().toISOString()
    try {
      await companies.note(companyKey, note)
      setHistory((current) => [{ type: 'note', occurred_at: occurredAt, signal_key: null }, ...current])
      setNoteSaved(true)
    } catch {
      setNoteError('La note n’a pas pu être enregistrée. Réessayez.')
    }
  }

  return (
    <section className={styles.companyV2Section}>
      <h3>Vous et cette entreprise</h3>
      <div className={styles.companyActionRow}>
        <button type="button" className={status === 'contacted' ? styles.companyPrimaryButton : styles.companySecondaryButton} disabled={busy || status === 'contacted'} onClick={() => void onContact('contacted')}>Marquer contactée</button>
        <button type="button" className={status === 'replied' ? styles.companyPrimaryButton : styles.companySecondaryButton} disabled={busy || status === 'replied'} onClick={() => void onContact('replied')}>A répondu</button>
        <button type="button" className={styles.companySecondaryButton} aria-expanded={noteOpen} onClick={() => setNoteOpen((current) => !current)}>Ajouter une note</button>
      </div>
      {error ? <p className={styles.actionError} role="alert">{error}</p> : null}
      {noteOpen ? (
        <div className={styles.companyNoteEditor}>
          <textarea aria-label="Note sur l’entreprise" value={note} onChange={(event) => { setNote(event.target.value); setNoteSaved(false) }} onBlur={() => void saveNote()} />
          <span aria-live="polite">{noteSaved ? 'Enregistré' : ''}</span>
          {noteError ? <p className={styles.actionError} role="alert">{noteError}</p> : null}
        </div>
      ) : null}
      {history.length ? (
        <ul className={styles.companyHistory}>
          {history.map((event, index) => (
            <li key={`${event.type}-${event.occurred_at}-${index}`}>
              {event.type === 'contacted' ? 'Contactée' : event.type === 'replied' ? 'A répondu' : event.type === 'note' ? 'Note mise à jour' : event.type === 'signal_saved' ? 'Signal sauvé' : event.type === 'signal_contacted' ? 'Signal contacté' : 'À contacter'} · {date(event.occurred_at)}
            </li>
          ))}
        </ul>
      ) : <p className={styles.companyMuted}>Aucune action pour l'instant.</p>}
    </section>
  )
}

export function CompanyProfileV2({
  companyKey,
  name,
  directory,
  fallbackCity,
  fallbackAddress,
  fallbackWebsite,
  fallbackSource,
  planCode,
  contactLookup,
  marketSummary,
  markets,
  contactStatus,
  history,
  note,
  contactBusy,
  contactError,
  onContact,
  onReloadLookup,
  onClose,
  standalone = false,
}: CompanyProfileV2Props) {
  const activity = directory?.naf_label ?? directory?.family_labels?.[0]
  const location = directory?.city
    ? `${directory.city}${directory.department_label ? ` (${directory.department_label})` : ''}`
    : fallbackCity
  const subtitle = [
    activity,
    location,
    directory?.employees === undefined ? null : `${directory.employees} salariés`,
  ].filter((value): value is string => Boolean(value))

  return (
    <aside className={`${styles.drawer} ${styles.companyV2} ${standalone ? styles.directoryProfile : ''}`} aria-label={name}>
      <header className={styles.companyV2Header}>
        <div>
          <h2>{name}</h2>
          {subtitle.length ? <p>{subtitle.join(' · ')}</p> : null}
        </div>
        {onClose ? <button type="button" onClick={onClose} aria-label="Fermer">×</button> : null}
      </header>
      <CompanyContactBlock
        companyKey={companyKey}
        directory={directory}
        fallbackAddress={fallbackAddress}
        fallbackWebsite={fallbackWebsite}
        fallbackSource={fallbackSource}
        planCode={planCode}
        initialLookup={contactLookup}
        onReloadLookup={onReloadLookup}
      />
      <IdentityBlock directory={directory} />
      <MarketsBlock markets={markets} summary={marketSummary} />
      <EngagementBlock
        companyKey={companyKey}
        status={contactStatus}
        history={history}
        note={note}
        busy={contactBusy}
        error={contactError}
        onContact={onContact}
      />
    </aside>
  )
}
