import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type {
  CompanyContactStatus,
  CompanyProfile,
  DirectoryCompany,
  DirectoryCompanyProfile,
  UnlockedFeedItem,
} from '../api/types'
import { companies, signals as signalApi } from '../api/endpoints'
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

export function DirectoryFacts({
  directory,
  identityIdentifier,
  city,
  officialWebsite,
}: {
  directory?: DirectoryCompany | null
  identityIdentifier?: string | null
  city?: string | null
  officialWebsite?: string | null
}) {
  const website = safeWebsite(directory?.website_url ?? officialWebsite)
  const location = [directory?.city ?? city, directory?.department].filter(Boolean).join(' · ')
  const facts = [
    identityIdentifier,
    directory?.naf_code ? `NAF ${directory.naf_code}` : null,
    ...(directory?.family_labels ?? []),
    directory?.employees === undefined ? null : `${directory.employees} salariés`,
    location || null,
  ].filter((value): value is string => Boolean(value))

  return (
    <section className={styles.valueSection}>
      <h3>Identité</h3>
      {facts.length ? <ul className={styles.factChips}>{facts.map((fact) => <li key={fact}>{fact}</li>)}</ul> : null}
      {website ? <a className={styles.website} href={website} target="_blank" rel="noreferrer">Site internet ↗</a> : null}
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
          Source : registre
          {directory.resolution_note ? ` · ${directory.resolution_note}` : ''}
          {' · '}<Link to={directory.removal_path}>Retrait</Link>
        </p>
      ) : null}
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
        />
        <MarketSummaryBlock summary={profile.market_summary} />

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
