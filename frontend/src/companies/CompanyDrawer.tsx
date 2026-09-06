import { useEffect, useState } from 'react'
import type { CompanyContactStatus, CompanyProfile, UnlockedFeedItem } from '../api/types'
import { companies } from '../api/endpoints'
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

function safeWebsite(value: string | null): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
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

  const identity = profile.official_identity
  const website = safeWebsite(identity.website_url)
  const identityText = [identifier(profile), city].filter((part): part is string => Boolean(part))
  return (
    <>
      <aside className={styles.drawer} aria-label={identity.name}>
        <header className={styles.drawerHeader}>
          <div>
            <h2>{identity.name}</h2>
            {identityText.length || website ? (
              <p className={styles.identityLine}>
                {identityText.map((part, index) => <span key={part}>{index ? ' · ' : ''}{part}</span>)}
                {website ? <><span>{identityText.length ? ' · ' : ''}</span><a href={website} target="_blank" rel="noreferrer">Site ↗</a></> : null}
              </p>
            ) : null}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer">×</button>
        </header>

        <div className={styles.drawerActions}>
          <button type="button" className={profile.contact_status === 'contacted' ? styles.currentAction : undefined} aria-pressed={profile.contact_status === 'contacted'} disabled={contactBusy || profile.contact_status === 'contacted'} onClick={() => void setContact('contacted')}>Marquer contactée</button>
          <button type="button" className={profile.contact_status === 'replied' ? styles.currentAction : undefined} aria-pressed={profile.contact_status === 'replied'} disabled={contactBusy || profile.contact_status === 'replied'} onClick={() => void setContact('replied')}>A répondu</button>
        </div>
        {contactError ? <p className={styles.actionError} role="alert">{contactError}</p> : null}

        <section>
          <h3>Ses marchés</h3>
          {profile.signals.length ? (
            <table className={styles.compactTable}><tbody>
              {profile.signals.map((signal) => (
                <SignalRow key={signal.signal_id} item={signal} compact={false} companyCompact selected={selectedSignal?.signal_id === signal.signal_id} onOpen={() => setSelectedSignal(signal)} />
              ))}
            </tbody></table>
          ) : <p>Aucun marché attribué pour l’instant</p>}
        </section>

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
          <SignalDrawer item={selectedSignal} loading={false} error={null} onClose={() => setSelectedSignal(null)} onRetry={() => undefined} onContacted={() => undefined} onSave={() => undefined} onIgnore={() => undefined} busy={false} />
        </div>
      ) : null}
    </>
  )
}
