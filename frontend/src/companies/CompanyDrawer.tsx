import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type {
  CompanyContactStatus,
  CompanyContactLookup,
  CompanyProfile,
  DirectoryCompany,
  DirectoryCompanyProfile,
  UnlockedFeedItem,
} from '../api/types'
import { companies, signals as signalApi } from '../api/endpoints'
import { ApiError } from '../api/client'
import { SignalDrawer } from '../signals/components/SignalDrawer'
import { SignalRow } from '../signals/components/SignalRow'
import { useI18n } from '../i18n'
import styles from './CompaniesPage.module.css'

function identifier(profile: CompanyProfile): string | null {
  const first = profile.official_identity.identifiers.find((candidate) => ['SIRET', 'IDE', 'TVA'].includes(candidate.scheme.toUpperCase()))
  if (!first) return null
  const value = first.scheme.toUpperCase() === 'SIRET' && /^\d{14}$/.test(first.value)
    ? `${first.value.slice(0, 3)} ${first.value.slice(3, 6)} ${first.value.slice(6, 9)} ${first.value.slice(9)}`
    : first.value
  return `${first.scheme.toUpperCase()} ${value}`
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

function sourceLabel(source: string): string {
  if (source === 'public_notice') return 'avis public'
  if (source === 'serper') return 'moteur de recherche'
  if (source === 'apollo') return 'Apollo'
  if (source === 'official_register' || source === 'registre') return 'registre'
  return source
}

export function DirectoryFacts({
  directory,
  identityIdentifier,
  city,
  officialWebsite,
  identitySource = 'public_notice',
}: {
  directory?: DirectoryCompany | null
  identityIdentifier?: string | null
  city?: string | null
  officialWebsite?: string | null
  identitySource?: 'public_notice' | 'official_register' | 'registre'
}) {
  const directoryWebsite = safeWebsite(directory?.website_url)
  const officialWebsiteUrl = directoryWebsite ? null : safeWebsite(officialWebsite)
  const website = directoryWebsite ?? officialWebsiteUrl
  const websiteSource = directoryWebsite
    ? directory?.website_source ?? directory?.source
    : officialWebsiteUrl
      ? identitySource
      : null
  const identityFacts = [
    identityIdentifier,
    directory?.city ? null : city,
  ].filter((value): value is string => Boolean(value))
  const directoryLocation = [directory?.city, directory?.department].filter(Boolean).join(' · ')
  const directoryFacts = [
    directory?.naf_code ? `NAF ${directory.naf_code}` : null,
    ...(directory?.family_labels ?? []),
    directory?.employees === undefined ? null : `${directory.employees} salariés`,
    directoryLocation || null,
  ].filter((value): value is string => Boolean(value))

  return (
    <section className={styles.valueSection}>
      <h3>Identité</h3>
      {identityFacts.length ? (
        <>
          <ul className={styles.factChips}>{identityFacts.map((fact) => <li key={fact}>{fact}</li>)}</ul>
          <p className={styles.dataSource}>Source : {sourceLabel(identitySource)}</p>
        </>
      ) : null}
      {directoryFacts.length ? <ul className={styles.factChips}>{directoryFacts.map((fact) => <li key={fact}>{fact}</li>)}</ul> : null}
      {directory?.directors?.length ? (
        <div className={styles.directors}>
          <h4>Dirigeants</h4>
          <ul>
            {directory.directors.map((director) => (
              <li key={`${director.name}-${director.title ?? ''}`}>
                <strong>{director.name}</strong>
                {director.title ? <span>{director.title}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {directory ? (
        <p className={styles.dataSource}>
          <span>
            Source : registre
            {directory.resolution_note ? ` · ${directory.resolution_note}` : ''}
          </span>
          {' · '}<Link to={directory.removal_path}>Retrait</Link>
        </p>
      ) : null}
      {website ? <a className={styles.website} href={website} target="_blank" rel="noreferrer">Site internet ↗</a> : null}
      {websiteSource ? <p className={styles.dataSource}>Source du site : {sourceLabel(websiteSource)}</p> : null}
    </section>
  )
}

export function MarketSummaryBlock({
  summary,
}: {
  summary?: DirectoryCompanyProfile['market_summary'] | null
}) {
  const { amount, date, locale } = useI18n()
  if (!summary) return null
  const cadence = summary.awards_per_quarter === undefined
    ? null
    : Number(summary.awards_per_quarter).toLocaleString(locale === 'fr' ? 'fr-FR' : 'en-GB', { maximumFractionDigits: 1 })
  const consortium = new Intl.NumberFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    style: 'percent',
    maximumFractionDigits: 0,
  }).format(Number(summary.consortium_share))
  const facts = [
    summary.first_award_at ? `Première attribution connue le ${date(summary.first_award_at)}` : null,
    cadence ? `${cadence} marché${Number(summary.awards_per_quarter) >= 2 ? 's' : ''} par trimestre` : null,
    ...(summary.median_amounts ?? []).map((money) => `${amount(money.value, money.currency)} de montant médian`),
    `${consortium} en groupement`,
    summary.recurring_buyers?.length ? `Acheteurs récurrents : ${summary.recurring_buyers.join(', ')}` : null,
  ].filter((value): value is string => Boolean(value))

  return (
    <section className={styles.valueSection}>
      <h3>Synthèse des marchés</h3>
      <ul className={styles.summaryList}>{facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>
      {summary.resolution_note ? <p className={styles.dataSource}>{summary.resolution_note}</p> : null}
      <p className={styles.dataSource}>Source : marchés publics</p>
    </section>
  )
}

function ContactLookupBlock({
  companyKey,
  initial,
}: {
  companyKey: string
  initial: CompanyContactLookup
}) {
  const { date } = useI18n()
  const [lookup, setLookup] = useState<CompanyContactLookup | null>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLookup(initial)
    setBusy(false)
    setError(null)
  }, [companyKey, initial])

  useEffect(() => {
    if (lookup?.state !== 'researching') return
    let active = true
    const poll = window.setInterval(() => {
      void companies.get(companyKey).then((profile) => {
        if (active) setLookup(profile.contact_lookup ?? null)
      }).catch(() => undefined)
    }, 2_000)
    return () => {
      active = false
      window.clearInterval(poll)
    }
  }, [companyKey, lookup?.state])

  const run = async () => {
    if (!lookup || busy || lookup.state === 'locked' || lookup.state === 'quota_exhausted' || lookup.state === 'identity_unavailable') return
    setBusy(true)
    setError(null)
    setLookup((current) => current ? ({ ...current, state: 'researching' }) : null)
    try {
      setLookup(await companies.contactLookup(companyKey))
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'contact_lookup_locked') {
        try {
          const profile = await companies.get(companyKey)
          setLookup(profile.contact_lookup ?? null)
        } catch {
          setLookup((current) => current ? ({ ...current, state: 'locked', remaining: 0 }) : null)
        }
      } else if (caught instanceof ApiError && caught.code === 'contact_lookup_quota_exhausted') {
        try {
          const profile = await companies.get(companyKey)
          setLookup(profile.contact_lookup ?? null)
        } catch {
          setLookup((current) => current ? ({ ...current, state: 'quota_exhausted', remaining: 0 }) : null)
        }
        setError('Le quota mensuel vient d’être épuisé.')
      } else if (caught instanceof ApiError && (caught.code === 'contact_lookup_identity_unavailable' || caught.code === 'contact_lookup_suppressed')) {
        setLookup((current) => current ? ({
          state: 'identity_unavailable',
          remaining: current.remaining,
          monthly_quota: current.monthly_quota,
          source: current.source,
          removal_path: current.removal_path,
        }) : null)
        setError('L’identité annuaire de cette entreprise ne permet pas encore la recherche.')
      } else {
        setLookup((current) => current ? ({ ...current, state: 'failed' }) : null)
        setError('La recherche n’a pas abouti. Réessayez dans quelques instants.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!lookup) return null

  const organizationWebsite = safeWebsite(lookup.organization?.website_url)
  const organizationLinkedin = safeWebsite(lookup.organization?.linkedin_url)
  const remainingLabel = `${lookup.remaining} recherche${lookup.remaining > 1 ? 's' : ''} restante${lookup.remaining > 1 ? 's' : ''} ce mois`
  const initialButton = lookup.state === 'locked' || lookup.state === 'available' || lookup.state === 'quota_exhausted' || lookup.state === 'identity_unavailable'
  const refreshButton = lookup.state === 'failed' || Boolean(lookup.can_refresh)

  return (
    <section className={`${styles.valueSection} ${styles.contactLookup}`}>
      <h3>Contact</h3>
      {lookup.organization ? (
        <ul className={styles.factChips}>
          {lookup.organization.employees === undefined ? null : <li>{lookup.organization.employees} salariés</li>}
          {lookup.organization.phone ? <li>{lookup.organization.phone}</li> : null}
          {organizationWebsite ? <li><a href={organizationWebsite} target="_blank" rel="noreferrer">Site internet ↗</a></li> : null}
          {organizationLinkedin ? <li><a href={organizationLinkedin} target="_blank" rel="noreferrer">LinkedIn ↗</a></li> : null}
        </ul>
      ) : null}
      {lookup.contacts?.length ? (
        <ul className={styles.contactCards}>
          {lookup.contacts.map((contact) => {
            const linkedin = safeWebsite(contact.linkedin_url)
            return (
              <li key={`${contact.email}-${contact.name}`}>
                <strong>{contact.name}</strong>
                <span>{contact.title}</span>
                <a href={`mailto:${contact.email}`}>{contact.email}</a>
                <small>E-mail vérifié</small>
                {linkedin ? <a href={linkedin} target="_blank" rel="noreferrer">LinkedIn ↗</a> : null}
              </li>
            )
          })}
        </ul>
      ) : null}
      {lookup.state === 'no_contact' ? <p>Aucun décideur avec un e-mail professionnel vérifié n’a été trouvé.</p> : null}
      {lookup.researched_at ? <p className={styles.dataSource}>Recherche effectuée le {date(lookup.researched_at)}</p> : null}
      {error ? <p className={styles.actionError} role="alert">{error}</p> : null}
      <div className={styles.lookupActions}>
        {initialButton ? (
          <button type="button" disabled={lookup.state !== 'available' || busy} onClick={() => void run()}>
            Trouver le décideur
          </button>
        ) : null}
        {lookup.state === 'researching' ? <button type="button" disabled>Recherche en cours…</button> : null}
        {refreshButton ? (
          <button type="button" disabled={busy || lookup.remaining === 0} onClick={() => void run()}>
            {lookup.can_refresh ? 'Actualiser' : 'Réessayer'}
          </button>
        ) : null}
        <span>{remainingLabel}</span>
      </div>
      {lookup.state === 'locked' ? <p className={styles.lookupInvite}>Cette recherche est incluse dans les formules payantes. <Link to="/tarifs">Voir les offres</Link></p> : null}
      {lookup.remaining === 0 && lookup.next_reset_at ? <p className={styles.lookupInvite}>Quota mensuel épuisé · reprise le {date(lookup.next_reset_at)}</p> : null}
      {lookup.state === 'identity_unavailable' ? <p className={styles.lookupInvite}>Identité annuaire insuffisante pour lancer la recherche.</p> : null}
      <p className={styles.dataSource}><span>Source : Apollo</span> · <Link to={lookup.removal_path}>Retrait</Link></p>
    </section>
  )
}

export function CompanyDrawer({
  profile,
  city,
  onClose,
  onContact,
  contactBusy,
  contactError,
}: {
  profile: CompanyProfile
  city: string | null
  onClose: () => void
  onContact: (status: CompanyContactStatus) => Promise<void>
  contactBusy: boolean
  contactError: string | null
}) {
  const { date } = useI18n()
  const [note, setNote] = useState(profile.note ?? '')
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [history, setHistory] = useState(profile.history)
  const [selectedSignal, setSelectedSignal] = useState<UnlockedFeedItem | null>(null)
  const [signalLoading, setSignalLoading] = useState(false)
  const [signalError, setSignalError] = useState<unknown | null>(null)

  useEffect(() => {
    setNote(profile.note ?? '')
    setSaved(false)
  }, [profile.company_key, profile.note])

  useEffect(() => {
    setHistory(profile.history)
  }, [profile.history])

  const setContact = async (status: CompanyContactStatus) => {
    if (status === profile.contact_status || contactBusy) return
    await onContact(status)
  }

  const saveNote = async () => {
    if (note === (profile.note ?? '')) return
    const previousHistory = history
    setSaved(false)
    setSaveError(null)
    setHistory([{ type: 'note', occurred_at: new Date().toISOString(), signal_key: null }, ...history])
    try {
      await companies.note(profile.company_key, note)
      setSaved(true)
    } catch {
      setHistory(previousHistory)
      setSaveError('La note n’a pas pu être enregistrée. Réessayez.')
    }
  }

  const openSignal = async (item: UnlockedFeedItem) => {
    setSelectedSignal(item)
    setSignalLoading(true)
    setSignalError(null)
    try {
      const detail = await signalApi.detail(item.signal_id)
      if (!detail.locked) setSelectedSignal(detail)
    } catch (error) {
      setSignalError(error)
    } finally {
      setSignalLoading(false)
    }
  }

  const identity = profile.official_identity
  return (
    <>
      <aside className={styles.drawer} aria-label={identity.name}>
        <header className={styles.drawerHeader}>
          <h2>{identity.name}</h2>
          <button type="button" onClick={onClose} aria-label="Fermer">×</button>
        </header>

        <DirectoryFacts
          directory={profile.directory}
          identityIdentifier={identifier(profile)}
          city={city}
          officialWebsite={identity.website_url}
          identitySource={identity.source}
        />
        <MarketSummaryBlock summary={profile.market_summary} />
        {profile.contact_lookup ? (
          <ContactLookupBlock
            companyKey={profile.company_key}
            initial={profile.contact_lookup}
          />
        ) : null}

        <section>
          <h3>Ses marchés</h3>
          {profile.signals.length ? (
            <table className={styles.compactTable}><tbody>
              {profile.signals.map((signal) => (
                <SignalRow key={signal.signal_id} item={signal} compact={false} companyCompact selected={selectedSignal?.signal_id === signal.signal_id} onOpen={() => void openSignal(signal)} />
              ))}
            </tbody></table>
          ) : <p>Aucun marché attribué pour l’instant</p>}
        </section>

        <div className={styles.drawerActions}>
          <button type="button" className={profile.contact_status === 'contacted' ? styles.currentAction : undefined} aria-pressed={profile.contact_status === 'contacted'} disabled={contactBusy || profile.contact_status === 'contacted'} onClick={() => void setContact('contacted')}>Marquer contactée</button>
          <button type="button" className={profile.contact_status === 'replied' ? styles.currentAction : undefined} aria-pressed={profile.contact_status === 'replied'} disabled={contactBusy || profile.contact_status === 'replied'} onClick={() => void setContact('replied')}>A répondu</button>
        </div>
        {contactError ? <p className={styles.actionError} role="alert">{contactError}</p> : null}

        <section>
          <label htmlFor="company-note"><h3>Notes</h3></label>
          <textarea id="company-note" aria-label="Notes" value={note} onChange={(event) => { setNote(event.target.value); setSaved(false) }} onBlur={() => void saveNote()} />
          <p className={styles.saved} aria-live="polite">{saved ? 'Enregistré' : ''}</p>
          {saveError ? <p className={styles.actionError} role="alert">{saveError}</p> : null}
        </section>

        <section>
          <h3>Historique</h3>
          {history.length ? (
            <ul>
              {history.map((event, index) => (
                <li key={`${event.type}-${event.occurred_at}-${index}`}>
                  {event.type === 'contacted' ? 'Contactée' : event.type === 'replied' ? 'A répondu' : event.type === 'note' ? 'Note mise à jour' : event.type === 'signal_saved' ? 'Signal sauvé' : event.type === 'signal_contacted' ? 'Signal contacté' : 'À contacter'} · {date(event.occurred_at)}
                </li>
              ))}
            </ul>
          ) : <p>Aucune action pour l'instant</p>}
        </section>
      </aside>
      {selectedSignal ? (
        <div className={styles.signalLayer}>
          <SignalDrawer
            item={selectedSignal}
            loading={signalLoading}
            error={signalError}
            onClose={() => setSelectedSignal(null)}
            onRetry={() => void openSignal(selectedSignal)}
            onContacted={() => undefined}
            onSave={() => undefined}
            onIgnore={() => undefined}
            busy={false}
          />
        </div>
      ) : null}
    </>
  )
}
