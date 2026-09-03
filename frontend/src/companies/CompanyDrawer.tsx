import { useEffect, useState } from 'react'
import type { CompanyContactStatus, CompanyProfile, UnlockedFeedItem } from '../api/types'
import { companies } from '../api/endpoints'
import { SignalDrawer } from '../signals/components/SignalDrawer'
import { SignalRow, MISSING } from '../signals/components/SignalRow'
import { useI18n } from '../i18n'
import styles from './CompaniesPage.module.css'

function identifier(profile: CompanyProfile): string {
  const first = profile.official_identity.identifiers[0]
  if (!first) return MISSING
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
  onChanged,
}: {
  profile: CompanyProfile
  city: string | null
  onClose: () => void
  onChanged: (status: CompanyContactStatus, contactedAt: string | null) => void
}) {
  const { date } = useI18n()
  const [note, setNote] = useState(profile.note ?? '')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selectedSignal, setSelectedSignal] = useState<UnlockedFeedItem | null>(null)

  useEffect(() => {
    setNote(profile.note ?? '')
    setSaved(false)
  }, [profile.company_key, profile.note])

  const setContact = async (status: CompanyContactStatus) => {
    setBusy(true)
    try {
      const result = await companies.contact(profile.company_key, status)
      onChanged(status, result.contacted_at)
    } finally {
      setBusy(false)
    }
  }

  const saveNote = async () => {
    if (note === (profile.note ?? '')) return
    setSaved(false)
    await companies.note(profile.company_key, note)
    setSaved(true)
  }

  const identity = profile.official_identity
  const website = safeWebsite(identity.website_url)
  return (
    <>
      <div className={styles.overlay} onClick={onClose} aria-hidden="true" />
      <aside className={styles.drawer} aria-label={identity.name}>
        <header className={styles.drawerHeader}>
          <div>
            <h2>{identity.name}</h2>
            <p>{identifier(profile)} · {city ?? MISSING}</p>
            {website ? <a href={website} target="_blank" rel="noreferrer">Site ↗</a> : null}
          </div>
          <button type="button" onClick={onClose} aria-label="Fermer">×</button>
        </header>

        <div className={styles.drawerActions}>
          <button type="button" disabled={busy} onClick={() => void setContact('contacted')}>Marquer contactée</button>
          <button type="button" disabled={busy} onClick={() => void setContact('replied')}>A répondu</button>
        </div>

        <section>
          <h3>Ses marchés</h3>
          {profile.signals.length ? (
            <table className={styles.compactTable}><tbody>
              {profile.signals.map((signal) => (
                <SignalRow key={signal.signal_id} item={signal} compact selected={selectedSignal?.signal_id === signal.signal_id} onOpen={() => setSelectedSignal(signal)} />
              ))}
            </tbody></table>
          ) : <p>{MISSING}</p>}
        </section>

        <section>
          <label htmlFor="company-note"><h3>Notes</h3></label>
          <textarea id="company-note" aria-label="Notes" value={note} onChange={(event) => { setNote(event.target.value); setSaved(false) }} onBlur={() => void saveNote()} />
          <p className={styles.saved} aria-live="polite">{saved ? 'Enregistré' : ''}</p>
        </section>

        <section>
          <h3>Historique</h3>
          <p>{profile.contacted_at ? `Contactée le ${date(profile.contacted_at)}` : MISSING}</p>
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
