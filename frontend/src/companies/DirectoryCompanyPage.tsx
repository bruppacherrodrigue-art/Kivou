import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { companies } from '../api/endpoints'
import type { DirectoryCompanyProfile } from '../api/types'
import { useI18n } from '../i18n'
import { DirectoryFacts, MarketSummaryBlock } from './CompanyDrawer'
import styles from './CompaniesPage.module.css'

function safeSourceUrl(value: string | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

export function DirectoryCompanyPage() {
  const { directorySiren } = useParams()
  const { amount, date } = useI18n()
  const [profile, setProfile] = useState<DirectoryCompanyProfile | null>(null)
  const [error, setError] = useState(false)

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

  return (
    <main className={styles.page}>
      <p className={styles.backLink}><Link to="/app/companies">← Retour aux entreprises</Link></p>
      <article className={`${styles.drawer} ${styles.directoryProfile}`} aria-label={profile.directory.name}>
        <header className={styles.drawerHeader}><h2>{profile.directory.name}</h2></header>
        <DirectoryFacts
          directory={profile.directory}
          identityIdentifier={`SIREN ${profile.directory.siren}`}
          identitySource="registre"
        />
        <MarketSummaryBlock summary={profile.market_summary} />
        <section>
          <h3>Marchés gagnés</h3>
          {profile.markets.length ? (
            <ul className={styles.marketList}>
              {profile.markets.map((market) => {
                const sourceUrl = safeSourceUrl(market.source_url)
                return (
                  <li key={market.market_id}>
                    {market.title ? <strong>{market.title}</strong> : null}
                    {[market.date ? date(market.date) : null, market.amount ? amount(market.amount.value, market.amount.currency) : null, market.buyers?.join(', ')]
                      .filter(Boolean).map((fact) => <span key={fact}>{fact}</span>)}
                    {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">Source : marché public ↗</a> : <small>Source : marché public</small>}
                  </li>
                )
              })}
            </ul>
          ) : <p>Aucun marché public rapproché.</p>}
        </section>
      </article>
    </main>
  )
}
