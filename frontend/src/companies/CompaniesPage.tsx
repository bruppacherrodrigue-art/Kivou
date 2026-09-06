import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { companies } from '../api/endpoints'
import type { CompanyContactStatus, CompanyListItem, CompanyProfile } from '../api/types'
import { useI18n } from '../i18n'
import { MISSING } from '../signals/components/SignalRow'
import { CompanyDrawer } from './CompanyDrawer'
import styles from './CompaniesPage.module.css'
import { ScreenHeader, ScreenSegments } from '../components/ScreenChrome'

const PAGE_SIZE = 20
const SEGMENTS: { status: CompanyContactStatus | null; label: string }[] = [
  { status: null, label: 'Toutes' },
  { status: 'to_contact', label: 'À contacter' },
  { status: 'contacted', label: 'Contactées' },
  { status: 'replied', label: 'Ont répondu' },
]

async function countCompanies(status: CompanyContactStatus | null): Promise<number> {
  let cursor: string | null = null
  let count = 0
  const seen = new Set<string>()
  let hasMore = true
  while (hasMore) {
    const response = await companies.list({ contact_status: status ? [status] : null, limit: 50, cursor })
    count += response.items.length
    const next = response.page.next_cursor
    hasMore = response.page.has_more && Boolean(next) && !seen.has(next ?? '')
    if (!hasMore || !next) break
    seen.add(next)
    cursor = next
  }
  return count
}

export function CompaniesPage() {
  const { companyKey } = useParams()
  const navigate = useNavigate()
  const { amount, shortDate } = useI18n()
  const [status, setStatus] = useState<CompanyContactStatus | null>(null)
  const [q, setQ] = useState('')
  const [items, setItems] = useState<CompanyListItem[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [profile, setProfile] = useState<CompanyProfile | null>(null)
  const [contactBusy, setContactBusy] = useState(false)
  const [contactError, setContactError] = useState<string | null>(null)
  const generation = useRef(0)
  const contactInFlight = useRef(false)

  useEffect(() => {
    let active = true
    void Promise.all(SEGMENTS.map(async (segment) => {
      const count = await countCompanies(segment.status)
      return [segment.status ?? 'all', count] as const
    })).then((entries) => { if (active) setCounts(Object.fromEntries(entries)) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    const current = ++generation.current
    setLoading(true)
    void companies.list({ contact_status: status ? [status] : null, q: q || null, limit: PAGE_SIZE })
      .then((response) => {
        if (generation.current !== current) return
        setItems(response.items)
        setNextCursor(response.page.next_cursor)
      })
      .finally(() => { if (generation.current === current) setLoading(false) })
  }, [status, q])

  useEffect(() => {
    if (!companyKey) { setProfile(null); return }
    let active = true
    void companies.get(companyKey).then((value) => { if (active) setProfile(value) })
    return () => { active = false }
  }, [companyKey])

  const loadMore = async () => {
    if (!nextCursor) return
    const response = await companies.list({ contact_status: status ? [status] : null, q: q || null, limit: PAGE_SIZE, cursor: nextCursor })
    setItems((current) => [...new Map([...current, ...response.items].map((item) => [item.company_key, item])).values()])
    setNextCursor(response.page.next_cursor)
  }

  const changeContactStatus = async (nextStatus: CompanyContactStatus) => {
    if (!profile || profile.contact_status === nextStatus || contactInFlight.current) return

    contactInFlight.current = true
    const previousProfile = profile
    const previousItems = items
    const previousCounts = counts
    const previousStatus = profile.contact_status
    const occurredAt = new Date().toISOString()
    const optimisticContactedAt = nextStatus === 'to_contact' ? null : occurredAt

    setContactError(null)
    setContactBusy(true)
    setProfile({
      ...profile,
      contact_status: nextStatus,
      contacted_at: optimisticContactedAt,
      history: [{ type: nextStatus, occurred_at: occurredAt, signal_key: null }, ...profile.history],
    })
    setItems((current) => current.map((item) => item.company_key === profile.company_key
      ? { ...item, contact_status: nextStatus, contacted_at: optimisticContactedAt }
      : item))
    setCounts((current) => {
      const updated = { ...current }
      if (previousStatus in updated) updated[previousStatus] = Math.max(0, updated[previousStatus] - 1)
      if (nextStatus in updated) updated[nextStatus] += 1
      return updated
    })

    try {
      const result = await companies.contact(profile.company_key, nextStatus)
      setProfile((current) => current ? { ...current, contacted_at: result.contacted_at } : current)
      setItems((current) => current.map((item) => item.company_key === profile.company_key
        ? { ...item, contacted_at: result.contacted_at }
        : item))
    } catch {
      setProfile(previousProfile)
      setItems(previousItems)
      setCounts(previousCounts)
      setContactError('Le statut n’a pas pu être mis à jour. Réessayez.')
    } finally {
      contactInFlight.current = false
      setContactBusy(false)
    }
  }

  return (
    <main className={styles.page}>
      <ScreenHeader title="Entreprises" description="Les titulaires de vos signaux, avec où vous en êtes" />
      <div className={styles.filters}>
        <ScreenSegments label="Statut de contact">
          {SEGMENTS.map((segment) => (
            <button key={segment.label} type="button" aria-pressed={status === segment.status} onClick={() => setStatus(segment.status)}>
              {segment.label} {counts[segment.status ?? 'all'] ?? 0}
            </button>
          ))}
        </ScreenSegments>
        <input type="search" aria-label="Rechercher une entreprise" placeholder="Rechercher" value={q} onChange={(event) => setQ(event.target.value)} />
      </div>

      {loading ? <p role="status">Chargement…</p> : (
        <div className={styles.contentLayout}>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>Entreprise</th>{profile ? null : <><th>Ville</th><th>Marchés</th><th>Total</th><th>Dernier</th></>}<th>Statut</th></tr></thead>
            <tbody>{items.map((item) => (
              <tr key={item.company_key} aria-current={item.company_key === companyKey ? 'true' : undefined} onClick={() => navigate(`/app/companies/${item.company_key}`)}>
                <td><button type="button">{item.name}</button></td>
                {profile ? null : <><td>{item.city ?? MISSING}</td><td className={styles.numeric}>{item.awards_count}</td><td className={styles.numeric}>{item.total_amount.length ? item.total_amount.map((money) => amount(money.value, money.currency)).join(' · ') : MISSING}</td><td>{shortDate(item.last_award_at) ?? MISSING}</td></>}
                <td><span className={styles.status}>{SEGMENTS.find((segment) => segment.status === item.contact_status)?.label ?? MISSING}</span></td>
              </tr>
            ))}</tbody>
          </table>
          {items.length === 0 ? <p>Les titulaires de vos signaux apparaîtront ici.</p> : null}
          {nextCursor ? <button className={styles.more} type="button" onClick={() => void loadMore()}>Charger plus</button> : null}
        </div>
        {profile ? <CompanyDrawer key={profile.company_key} city={profile.city} profile={profile} onClose={() => navigate('/app/companies')} onContact={changeContactStatus} contactBusy={contactBusy} contactError={contactError} /> : null}
        </div>
      )}
    </main>
  )
}
