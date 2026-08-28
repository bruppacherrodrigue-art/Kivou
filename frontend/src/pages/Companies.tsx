import { useCallback, useEffect, useState } from 'react'
import { signals } from '../api/endpoints'
import type { UnlockedDetail } from '../api/types'
import { BuildingIcon } from '../assets/Icons'
import { Button, ButtonLink } from '../components/Button'
import { Callout, Card, EmptyState, SectionHeading, Skeleton } from '../components/Surfaces'
import { useI18n } from '../i18n'
import styles from './Companies.module.css'

interface CompanyEntry {
  key: string
  name: string
  country: string | null
  signalCount: number
}

export function Companies() {
  const { t } = useI18n()
  const [entries, setEntries] = useState<CompanyEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const feed = await signals.feed({ freshness: 'all', limit: 20, offset: 0 })
      const unlocked = feed.items.filter((item) => item.locked === false)
      const results = await Promise.allSettled(unlocked.map((item) => signals.detail(item.signal_id)))
      const grouped = new Map<string, CompanyEntry>()
      results.forEach((result) => {
        if (result.status !== 'fulfilled' || result.value.locked || !result.value.company_key) return
        const detail = result.value as UnlockedDetail
        const companyKey = result.value.company_key
        const current = grouped.get(companyKey)
        if (current) current.signalCount += 1
        else grouped.set(companyKey, {
          key: companyKey,
          name: detail.company.name ?? '—',
          country: detail.company.country,
          signalCount: 1,
        })
      })
      setEntries([...grouped.values()].sort((a, b) => a.name.localeCompare(b.name)))
    } catch (caught) {
      setError(caught)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SectionHeading level={1} title={t.companiesIndex.title} lead={t.companiesIndex.lead} hideTitle />
        <p className={styles.note}>{t.companiesIndex.partial}</p>
      </header>
      {loading ? (
        <div className={styles.grid} aria-label={t.common.loading}>
          {[0, 1, 2].map((item) => <Card key={item} padding="lg"><Skeleton width="62%" height="1.5rem" /></Card>)}
        </div>
      ) : error ? (
        <Callout tone="danger" title={t.companiesIndex.errorTitle} action={<Button variant="secondary" onClick={() => void load()}>{t.companiesIndex.retry}</Button>} />
      ) : entries.length === 0 ? (
        <Card padding="none"><EmptyState title={t.companiesIndex.emptyTitle} body={t.companiesIndex.emptyBody} /></Card>
      ) : (
        <ul className={styles.grid}>
          {entries.map((entry) => (
            <li key={entry.key}>
              <Card as="article" padding="lg" className={styles.companyCard}>
                <BuildingIcon className={styles.icon} />
                <div><h2>{entry.name}</h2>{entry.country ? <p>{entry.country}</p> : null}</div>
                <p className={styles.count}>{t.companiesIndex.count} · {entry.signalCount}</p>
                <ButtonLink to={`/app/companies/${encodeURIComponent(entry.key)}`} variant="secondary">{t.companiesIndex.open}</ButtonLink>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
