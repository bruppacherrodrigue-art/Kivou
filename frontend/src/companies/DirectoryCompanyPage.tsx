import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { companies } from '../api/endpoints'
import type { CompanyContactStatus, DirectoryCompanyProfile } from '../api/types'
import { CompanyPanel } from './CompanyPanel'
import styles from './CompaniesPage.module.css'

export function DirectoryCompanyPage() {
  const { directorySiren } = useParams()
  const [profile, setProfile] = useState<DirectoryCompanyProfile | null>(null)
  const [error, setError] = useState(false)
  const [contactBusy, setContactBusy] = useState(false)
  const [contactError, setContactError] = useState<string | null>(null)

  useEffect(() => {
    if (!directorySiren) return
    let active = true
    setError(false)
    void companies.directoryGet(directorySiren).then(
      (value) => { if (active) setProfile(value) },
      () => { if (active) setError(true) },
    )
    return () => { active = false }
  }, [directorySiren])

  if (error) {
    return <main className={styles.page}><p role="alert">Cette entreprise n’a pas pu être chargée.</p><Link to="/app/companies">Retour aux entreprises</Link></main>
  }
  if (!profile) return <main className={styles.page}><p role="status">Chargement…</p></main>

  const companyKey = profile.company_key ?? `cmp_directory_${profile.directory.siren}`
  const changeContactStatus = async (status: CompanyContactStatus) => {
    if (contactBusy || profile.contact_status === status) return
    setContactBusy(true)
    setContactError(null)
    const previous = profile
    const occurredAt = new Date().toISOString()
    setProfile({
      ...profile,
      contact_status: status,
      contacted_at: status === 'to_contact' ? null : occurredAt,
      history: [{ type: status, occurred_at: occurredAt, signal_key: null }, ...(profile.history ?? [])],
    })
    try {
      const result = await companies.contact(companyKey, status)
      setProfile((current) => current ? { ...current, contacted_at: result.contacted_at } : current)
    } catch {
      setProfile(previous)
      setContactError('Le statut n’a pas pu être mis à jour. Réessayez.')
    } finally {
      setContactBusy(false)
    }
  }

  return (
    <main className={styles.page}>
      <p className={styles.backLink}><Link to="/app/companies">← Retour aux entreprises</Link></p>
      <CompanyPanel
        standalone
        companyKey={companyKey}
        companyHref={`/app/companies/directory/${encodeURIComponent(profile.directory.siren)}`}
        name={profile.directory.name}
        directory={profile.directory}
        planCode={profile.plan_code ?? 'discovery'}
        contactLookup={profile.contact_lookup}
        marketSummary={profile.market_summary}
        markets={profile.markets.map((market) => ({
          id: market.market_id,
          title: market.title,
          date: market.date,
          amount: market.amount,
          buyers: market.buyers,
          sourceUrl: market.source_url,
        }))}
        contactStatus={profile.contact_status ?? 'to_contact'}
        history={profile.history ?? []}
        note={profile.note ?? null}
        contactBusy={contactBusy}
        contactError={contactError}
        onContact={changeContactStatus}
        onReloadLookup={async () => (await companies.directoryGet(profile.directory.siren)).contact_lookup ?? null}
      />
    </main>
  )
}
