import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { signals } from '../api/endpoints'
import type { UnlockedDetail } from '../api/types'
import { ArrowRightIcon, BuildingIcon } from '../assets/Icons'
import { Button } from '../components/Button'
import { Callout, EmptyState, SectionHeading, Skeleton } from '../components/Surfaces'
import { useI18n } from '../i18n'
import { CompanyProfile } from './CompanyProfile'
import styles from './Companies.module.css'

interface CompanyEntry {
  key: string
  name: string
  country: string | null
  signalCount: number
}

export function Companies() {
  const { companyKey } = useParams()

  return companyKey ? <CompanyProfile /> : <CompaniesIndex />
}

function CompaniesIndex() {
  const { t } = useI18n()
  const [entries, setEntries] = useState<CompanyEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [partialResult, setPartialResult] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const mounted = useRef(false)
  const generation = useRef(0)

  const load = useCallback(async (
    { preserveEntries = false }: { preserveEntries?: boolean } = {},
  ) => {
    const currentGeneration = ++generation.current
    const isCurrent = () => mounted.current && generation.current === currentGeneration

    if (isCurrent()) {
      if (preserveEntries) {
        setRefreshing(true)
      } else {
        setLoading(true)
        setError(null)
        setPartialResult(false)
      }
    }
    try {
      const feed = await signals.feed({ freshness: 'all', limit: 20, offset: 0 })
      if (!isCurrent()) return
      const unlocked = feed.items.filter((item) => item.locked === false)
      const results = await Promise.allSettled(unlocked.map((item) => signals.detail(item.signal_id)))
      const grouped = new Map<string, CompanyEntry>()
      const rejectedCount = results.filter((result) => result.status === 'rejected').length
      results.forEach((result) => {
        if (result.status !== 'fulfilled' || result.value.locked || !result.value.company_key) return
        const detail = result.value as UnlockedDetail
        const companyKey = result.value.company_key
        if (!detail.company.name) return
        const current = grouped.get(companyKey)
        if (current) current.signalCount += 1
        else grouped.set(companyKey, {
          key: companyKey,
          name: detail.company.name,
          country: detail.company.country,
          signalCount: 1,
        })
      })
      if (isCurrent()) {
        if (rejectedCount > 0 && grouped.size === 0) {
          const detailsError = new Error('company_details_unavailable')
          if (preserveEntries) setRefreshError(detailsError)
          else setError(detailsError)
          return
        }
        setEntries([...grouped.values()].sort((a, b) => a.name.localeCompare(b.name)))
        setPartialResult(rejectedCount > 0)
        setRefreshError(null)
      }
    } catch (caught) {
      if (isCurrent()) {
        if (preserveEntries) setRefreshError(caught)
        else setError(caught)
      }
    } finally {
      if (isCurrent()) {
        if (preserveEntries) setRefreshing(false)
        else setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
      generation.current += 1
    }
  }, [load])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SectionHeading level={1} title={t.companiesIndex.title} lead={t.companiesIndex.lead} hideTitle />
        <p className={styles.note}>{t.companiesIndex.partial}</p>
      </header>
      {loading ? (
        <div className={styles.loadingRows} role="status" aria-label={t.common.loading}>
          {[0, 1, 2].map((item) => (
            <div key={item} className={styles.loadingRow} aria-hidden="true">
              <Skeleton width="2.5rem" height="2.5rem" />
              <Skeleton width="62%" height="1.25rem" />
            </div>
          ))}
        </div>
      ) : error ? (
        <Callout
          tone="danger"
          title={t.companiesIndex.errorTitle}
          action={<Button variant="secondary" onClick={() => void load()}>{t.companiesIndex.retry}</Button>}
          live
        />
      ) : entries.length === 0 ? (
        <div className={styles.emptySurface}>
          <EmptyState title={t.companiesIndex.emptyTitle} body={t.companiesIndex.emptyBody} />
        </div>
      ) : (
        <>
          {partialResult ? (
            <section
              className={styles.partialResult}
              aria-label={t.companiesIndex.partialResultTitle}
            >
              <Callout
                tone="warning"
                title={t.companiesIndex.partialResultTitle}
                action={(
                  <Button
                    variant="secondary"
                    loading={refreshing}
                    onClick={() => void load({ preserveEntries: true })}
                  >
                    {t.companiesIndex.retry}
                  </Button>
                )}
                live
              >
                {t.companiesIndex.partialResultBody}
              </Callout>
            </section>
          ) : null}
          {refreshError ? (
            <section
              className={styles.partialResult}
              aria-label={t.companiesIndex.errorTitle}
            >
              <Callout
                tone="danger"
                title={t.companiesIndex.errorTitle}
                action={(
                  <Button
                    variant="secondary"
                    loading={refreshing}
                    onClick={() => void load({ preserveEntries: true })}
                  >
                    {t.companiesIndex.retry}
                  </Button>
                )}
                live
              />
            </section>
          ) : null}
          <ul className={styles.rows} aria-label={t.companiesIndex.title}>
            {entries.map((entry) => (
              <li key={entry.key}>
                <Link
                  to={`/app/companies/${encodeURIComponent(entry.key)}`}
                  className={styles.rowLink}
                >
                  <span className={styles.iconFrame} aria-hidden="true">
                    <BuildingIcon className={styles.icon} />
                  </span>
                  <span className={styles.rowBody}>
                    <span className={styles.companyName}>{entry.name}</span>
                    <span className={styles.metadata}>
                      {entry.country ? <span>{entry.country}</span> : null}
                      <span>{t.companiesIndex.count} · {entry.signalCount}</span>
                    </span>
                  </span>
                  <ArrowRightIcon className={styles.arrow} aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
