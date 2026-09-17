import { useEffect, useState } from 'react'
import { Search, ArrowLeft, ArrowRight } from 'lucide-react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { signals } from '../api/endpoints'
import type { FeedPage, UnifiedStatus } from '../api/types'
import { useI18n } from '../i18n'
import { useProspecting, useProspectingResource } from '../prospecting/ProspectingProvider'
import { signalDetailPath } from '../prospecting/routeState'
import { SignalListRow } from '../prospecting/components/SignalListRow'
import { SignalDetail } from '../prospecting/components/SignalDetail'
import { TargetBar } from '../prospecting/components/TargetBar'
import styles from '../prospecting/Prospecting.module.css'

export interface ActivationNavigationState { activationCompleted?: boolean; returnToCompany?: { companyKey: string; name?: string } }
const statuses: Array<UnifiedStatus | 'all'> = ['new', 'saved', 'contacted', 'ignored', 'all']
export function SignalsFeed() {
  const { locale, number } = useI18n()
  const fr = locale === 'fr'
  const p = useProspecting()
  const location = useLocation()
  const navigate = useNavigate()
  const { signalKey } = useParams()
  const params = new URLSearchParams(location.search)
  const status = statuses.find((value) => value === params.get('status')) ?? 'new'
  const sort = params.get('sort') === 'amount' ? 'amount' : 'recent'
  const canSearch = p.billingStatus?.entitlements.filter_level === 'basic' || p.billingStatus?.entitlements.filter_level === 'advanced'
  const q = canSearch ? params.get('q')?.slice(0, 120) ?? '' : ''
  const cursor = !canSearch && params.has('q') ? null : params.get('cursor')
  const [search, setSearch] = useState(q)
  useEffect(() => setSearch(q), [q])
  useEffect(() => {
    const next = new URLSearchParams(location.search)
    const legacySignal = !signalKey && next.get('signal')
    const deniedSearch = !p.accessLoading && p.billingStatus && !canSearch && next.has('q')
    if (!legacySignal && !deniedSearch) return
    if (deniedSearch) { next.delete('q'); next.delete('cursor'); next.delete('offset') }
    if (legacySignal) next.delete('signal')
    navigate(legacySignal ? signalDetailPath(legacySignal, next.toString()) : { pathname: location.pathname, search: next.size ? `?${next}` : '', hash: location.hash }, { replace: true, state: location.state })
  }, [location, navigate, signalKey, p.accessLoading, p.billingStatus, canSearch])
  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(location.search)
    next.delete('cursor')
    next.delete('offset')
    for (const [key, value] of Object.entries(patch)) { if (value) next.set(key, value); else next.delete(key) }
    navigate({ pathname: '/app/signals', search: next.toString() ? `?${next}` : '' })
  }
  useEffect(() => {
    if (!canSearch || search === q) return
    const timer = setTimeout(() => {
      const next = new URLSearchParams(location.search)
      next.delete('cursor')
      next.delete('offset')
      if (search.trim().length >= 2) next.set('q', search.trim()); else next.delete('q')
      navigate({ pathname: '/app/signals', search: `?${next}` }, { replace: true })
    }, 300)
    return () => clearTimeout(timer)
  }, [search, q, location.search, navigate, canSearch])
  const resource = useProspectingResource('signal-list', (signal) => signals.feed({ ...p.query, view: 'history', status: status === 'all' ? ['new', 'saved', 'contacted', 'ignored'] : [status], sort, q: q.length >= 2 ? q : null, cursor, limit: 20 }, { signal }), { status, sort, q, cursor })
  const data = resource.data
  const discovery = p.billingStatus?.plan_code === 'discovery' ? p.billingStatus.discovery : null
  const discoveryPending = Boolean(discovery && discovery.remaining_slots > 0)
  const discoveryProgress = discovery
    ? discovery.granted_signal_count === 0
      ? (fr ? `Vos ${number(discovery.limit)} signaux sont en préparation. Kivou sélectionne les meilleures opportunités disponibles.` : `Your ${number(discovery.limit)} signals are being prepared. Kivou is selecting the best available opportunities.`)
      : (fr ? `${number(discovery.granted_signal_count)} de vos ${number(discovery.limit)} signaux ${discovery.granted_signal_count === 1 ? 'est disponible' : 'sont disponibles'}. Kivou prépare ${discovery.remaining_slots === 1 ? 'le suivant' : 'les suivants'}.` : `${number(discovery.granted_signal_count)} of your ${number(discovery.limit)} signals ${discovery.granted_signal_count === 1 ? 'is' : 'are'} available. Kivou is preparing ${discovery.remaining_slots === 1 ? 'the next one' : 'the remaining signals'}.`)
    : null
  const landingPending = Boolean(data?.landing_cohort && data.landing_cohort.materialized < data.landing_cohort.expected && status === 'new' && !q && !cursor)
  const discoveryProgressVisible = Boolean(data && discoveryPending && status === 'new' && !q && !cursor && !landingPending)
  const countsKey = p.resourceKey('signal-counts', { status, sort, q })
  const [cachedCounts, setCachedCounts] = useState<{ key: string; counts: FeedPage['counts']; truncated: boolean } | null>(null)
  useEffect(() => {
    if (data?.counts_available) setCachedCounts({ key: countsKey, counts: data.counts, truncated: data.counts_truncated })
  }, [data, countsKey])
  const counts = data?.counts_available ? { counts: data.counts, truncated: data.counts_truncated } : cachedCounts?.key === countsKey ? cachedCounts : null
  const visibleItems = data && discovery
    ? [...data.items.filter((item) => !item.locked).slice(0, 3), ...data.items.filter((item) => item.locked).slice(0, 10)]
    : data?.items ?? []
  const profileTotal = data?.profile_total_30d ?? data?.total_returned ?? 0
  const remainingMarkets = Math.max(0, profileTotal - 13)
  const profile = p.profile ?? p.profiles[0] ?? null
  const family = profile?.label ?? (fr ? 'votre secteur' : 'your sector')
  const subdivision = profile?.customer_input.territory_subdivisions?.[0]
  const zone = p.targetOptions.zones.find((item) => item.code === subdivision)?.label ?? subdivision ?? (fr ? 'votre département' : 'your area')
  const labels = fr ? { new: 'Nouveaux', saved: 'Sauvegardés', contacted: 'Contactés', ignored: 'Ignorés', all: 'Tous' } : { new: 'New', saved: 'Saved', contacted: 'Contacted', ignored: 'Ignored', all: 'All' }
  return <main className={styles.workspace} data-page="signals">
    <header className={styles.heading}><div><p className={styles.eyebrow}>{fr ? 'Votre prospection' : 'Your prospecting'}</p><h1>{fr ? 'Signaux' : 'Signals'}</h1><p>{fr ? 'Les marchés à transformer en conversations commerciales.' : 'Turn relevant contracts into sales conversations.'}</p></div></header>
    <TargetBar />
    {!p.profilesLoading && p.profiles.length === 0 && <section className={styles.guide}><h2>{fr ? 'Votre prochaine opportunité commence par votre cible' : 'Your next opportunity starts with your target'}</h2><Link to="/app/icps" className={styles.primary}>{fr ? 'Configurer mon profil cible' : 'Set up my target profile'}</Link></section>}
    <section className={styles.panel} aria-label={fr ? 'Liste des signaux' : 'Signal list'}>
      <div className={styles.tabs} role="tablist" aria-label={fr ? 'Statut des signaux' : 'Signal status'}>{statuses.map((value) => <button className={styles.tab} role="tab" aria-selected={status === value} key={value} onClick={() => update({ status: value })}>{labels[value]}{value !== 'all' && value !== 'ignored' && counts && <span className={styles.count}>{number(counts.counts[value])}{counts.truncated ? '+' : ''}</span>}</button>)}</div>
      <div className={styles.toolbar}><label className={styles.search}><Search aria-hidden="true" /><input type="search" maxLength={120} disabled={!canSearch} aria-describedby={!canSearch ? 'signal-search-access' : undefined} aria-label={fr ? 'Rechercher un signal' : 'Search signals'} placeholder={fr ? 'Entreprise, marché, mot-clé…' : 'Company, contract, keyword…'} value={canSearch ? search : ''} onChange={(event) => setSearch(event.target.value)} /></label>
        <select value={sort} aria-label={fr ? 'Trier les signaux' : 'Sort signals'} onChange={(event) => update({ sort: event.target.value })}><option value="recent">{fr ? 'Les plus récents' : 'Most recent'}</option><option value="amount">{fr ? 'Montant décroissant' : 'Highest amount'}</option></select></div>
      {!canSearch && <p className={styles.muted} id="signal-search-access">{fr ? 'La recherche par mot-clé est disponible avec un abonnement.' : 'Keyword search is available with a subscription.'}</p>}
      {data && <div className={styles.resultMeta}><span>{fr ? `${number(profileTotal)} ${profileTotal === 1 ? 'marché attribué correspondant' : 'marchés attribués correspondant'} à votre profil ces 30 jours` : `${number(profileTotal)} awarded ${profileTotal === 1 ? 'contract' : 'contracts'} matching your profile in the last 30 days`}</span>{discovery && <span>{number(discovery.granted_signal_count)}/{number(discovery.limit)} {fr ? 'signaux attribués' : 'signals assigned'}</span>}{data.page.scan_truncated && <span>{fr ? 'Affinez votre recherche pour explorer davantage de résultats.' : 'Refine your search to explore more results.'}</span>}</div>}
      {resource.loading && <div className={styles.loading} role="status">{fr ? 'Chargement des signaux…' : 'Loading signals…'}<div className={styles.skeleton} /><div className={styles.skeleton} /></div>}
      {resource.error != null && <div className={styles.empty} role="alert"><h2>{fr ? 'Vos signaux ne sont pas chargés' : 'Your signals could not load'}</h2><button className={styles.button} onClick={resource.reload}>{fr ? 'Réessayer' : 'Retry'}</button></div>}
      {visibleItems.map((item) => <SignalListRow key={item.signal_id} item={item} onOpen={() => {
        const next = new URLSearchParams(location.search)
        next.delete('presentation_artifact_id')
        if (!item.locked && item.presentation?.artifact_id) next.set('presentation_artifact_id', item.presentation.artifact_id)
        navigate(signalDetailPath(item.signal_id, next.toString()))
      }} />)}
      {data && remainingMarkets > 0 && <p className={styles.waitingRow}><Link to="/tarifs">{fr ? `${number(remainingMarkets)} autres marchés — voir les offres` : `${number(remainingMarkets)} other contracts — view plans`}</Link></p>}
      {landingPending && <div className={styles.waitingRow} role="status"><span className={styles.waitingDot} aria-hidden="true" /><span>{fr ? 'Vos prochains signaux arriveront ici' : 'Your next signals will appear here'}</span></div>}
      {discoveryProgressVisible && discoveryProgress && <div className={styles.waitingRow} role="status"><span className={styles.waitingDot} aria-hidden="true" /><span>{discoveryProgress}</span></div>}
      {data && data.items.length === 0 && !landingPending && !discoveryProgressVisible && <div className={styles.empty}><h2>{status === 'new' ? (fr ? `Nous surveillons ${family} en ${zone}` : `We monitor ${family} in ${zone}`) : (fr ? 'Aucun signal dans cette sélection' : 'No signals in this selection')}</h2><p>{status === 'new' ? (fr ? 'Vos prochains marchés arriveront ici, en général 8 à 12 par mois.' : 'Your next contracts will appear here, usually 8 to 12 per month.') : (fr ? 'Vos prochaines actions apparaîtront ici.' : 'Your next actions will appear here.')}</p></div>}
      {data && (cursor || data.page.has_more) && <footer className={styles.footer}><button className={styles.button} disabled={!cursor} onClick={() => update({ cursor: null })}><ArrowLeft aria-hidden="true" />{fr ? 'Première page' : 'First page'}</button><button className={styles.button} disabled={!data.page.has_more || !data.page.next_cursor} onClick={() => update({ cursor: data.page.next_cursor ?? null })}>{fr ? 'Page suivante' : 'Next page'}<ArrowRight aria-hidden="true" /></button></footer>}
    </section>
    {signalKey && <SignalDetail key={signalKey} signalKey={signalKey} onClose={() => {
      const next = new URLSearchParams(location.search)
      next.delete('presentation_artifact_id')
      navigate({ pathname: '/app/signals', search: next.toString() }, { replace: true })
    }} />}
  </main>
}
