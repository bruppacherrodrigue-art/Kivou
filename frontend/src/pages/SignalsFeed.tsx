import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { LockKeyhole } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { billing, feedback, signals } from '../api/endpoints'
import type { FeedQuery } from '../api/endpoints'
import type {
  BillingStatus,
  FeedItem,
  FeedPage,
  LockedFeedItem,
  UnifiedStatus,
  UnlockedFeedItem,
} from '../api/types'
import { interpolate, plural, useI18n } from '../i18n'
import { Sheet, SheetContent, SheetTitle } from '../reference/dashboard/ui/sheet'
import { SignalDrawer } from '../signals/components/SignalDrawer'
import { MISSING, SignalRow, signalObject } from '../signals/components/SignalRow'
import styles from './SignalsFeed.module.css'

/* L'écran « Signaux ».
 *
 * Un tableau dense, une ligne de filtres, un tiroir. Trois règles tiennent
 * tout le fichier :
 *
 *   1. L'état des filtres vit dans l'URL, jamais dans un `useState` parallèle.
 *      Une adresse partagée doit rendre le même écran.
 *   2. Le serveur filtre ce qu'il sait filtrer (statut, zone, secteur,
 *      période) ; le navigateur ne filtre QUE ce que l'API n'expose pas
 *      (montant minimum, recherche texte), et il le dit — « sur les signaux
 *      chargés ».
 *   3. Une action est optimiste, mais elle se dédit : en cas d'échec, la ligne
 *      ET les compteurs reviennent à leur valeur d'avant, et l'échec s'annonce.
 */

const PAGE_SIZE = 20
const COMPACT_QUERY = '(max-width: 899px)'
const DAY_MS = 86_400_000

const SEGMENTS = ['new', 'saved', 'contacted', 'ignored', 'all'] as const
type Segment = (typeof SEGMENTS)[number]

/** Les segments qui portent un chiffre. « Ignorés » et « Tous » n'en portent
 *  pas : compter ce qu'on écarte n'aide personne à vendre. */
const COUNTED_SEGMENTS: UnifiedStatus[] = ['new', 'saved', 'contacted']

const ALL_STATUSES: UnifiedStatus[] = ['new', 'saved', 'contacted', 'ignored']

const PERIODS = ['7', '30', '90', 'all'] as const
type Period = (typeof PERIODS)[number]

export interface ActivationNavigationState {
  activationCompleted?: boolean
}

interface PageFilters {
  segment: Segment
  zone: string
  cpv: string
  min: string
  period: Period
  q: string
}

interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

function filtersFrom(search: string): PageFilters {
  const params = new URLSearchParams(search)
  const segment = SEGMENTS.find((candidate) => candidate === params.get('status')) ?? 'new'
  const period = PERIODS.find((candidate) => candidate === params.get('period')) ?? '30'
  return {
    segment,
    zone: params.get('zone') ?? '',
    cpv: params.get('cpv') ?? '',
    min: params.get('min') ?? '',
    period,
    q: params.get('q') ?? '',
  }
}

function statusesFor(segment: Segment): UnifiedStatus[] {
  return segment === 'all' ? ALL_STATUSES : [segment]
}

/** La borne basse de la période, en date civile. « Tout l'historique » n'en a
 *  pas : l'absence de borne est une réponse, pas une valeur par défaut. */
function dateFrom(period: Period): string | null {
  if (period === 'all') return null
  return new Date(Date.now() - Number(period) * DAY_MS).toISOString().slice(0, 10)
}

function feedQuery(filters: PageFilters, cursor: string | null): FeedQuery {
  return {
    // Zone, secteur et période n'existent que sur l'historique : la page ne
    // change jamais de vue, sans quoi la moitié des filtres disparaîtrait.
    view: 'history',
    limit: PAGE_SIZE,
    cursor,
    status: statusesFor(filters.segment),
    subdivision_code: filters.zone || null,
    cpv_prefix: filters.cpv || null,
    date_from: dateFrom(filters.period),
  }
}

/** Sans accent ni casse : « eolienne » doit trouver « Éolienne ». */
function foldCase(text: string): string {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

function compactSnapshot(): boolean {
  if (typeof window.matchMedia === 'function') return window.matchMedia(COMPACT_QUERY).matches
  return window.innerWidth < 900
}

function useCompact(): boolean {
  const [compact, setCompact] = useState(compactSnapshot)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mediaQuery = window.matchMedia(COMPACT_QUERY)
    const onChange = (event: MediaQueryListEvent) => setCompact(event.matches)
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', onChange)
      return () => mediaQuery.removeEventListener('change', onChange)
    }
    mediaQuery.addListener(onChange)
    return () => mediaQuery.removeListener(onChange)
  }, [])

  return compact
}

/** Un signal que l'offre ne débloque pas. La ligne existe — masquer son
 *  existence serait mentir sur le volume — mais elle ne montre aucune donnée
 *  protégée : seul `item.headline`, le teaser générique et non identifiant
 *  publié par le serveur pour CE signal, porte le nom accessible du bouton. */
function LockedRow({
  item,
  compact,
  note,
  onOpen,
}: {
  item: LockedFeedItem
  compact: boolean
  note: string
  onOpen: () => void
}) {
  return (
    <tr className={styles.lockedRow} onClick={onOpen}>
      <td>{MISSING}</td>
      <td>
        <button type="button" className={styles.lockedButton} onClick={(event) => {
          event.stopPropagation()
          onOpen()
        }}>
          <LockKeyhole aria-hidden="true" /> {item.headline}
        </button>
      </td>
      <td className={styles.lockedNote}>{note}</td>
      <td className={styles.cellNumeric}>{MISSING}</td>
      {compact ? null : <td>{MISSING}</td>}
      <td>{MISSING}</td>
    </tr>
  )
}

export function SignalsFeed() {
  const { t } = useI18n()
  const copy = t.signalsTable
  const location = useLocation()
  const navigate = useNavigate()
  const { signalKey } = useParams()
  const compact = useCompact()

  const filters = useMemo(() => filtersFrom(location.search), [location.search])
  /* Seuls les filtres SERVEUR déclenchent un rechargement. Le montant minimum
   * et la recherche ne quittent jamais le navigateur. */
  const serverSignature = JSON.stringify([
    filters.segment,
    filters.zone,
    filters.cpv,
    filters.period,
  ])

  const mounted = useRef(false)
  const feedGeneration = useRef(0)
  const detailGeneration = useRef(0)
  const paginationRequest = useRef(false)
  const [detailRetryToken, setDetailRetryToken] = useState(0)

  const [activationMoment] = useState(
    () => (location.state as ActivationNavigationState | null)?.activationCompleted === true,
  )
  const postFeedBilling = useRef(activationMoment)
  const [postActivationBilling, setPostActivationBilling] = useState<BillingStatus | null>(null)

  const [feed, setFeed] = useState<ResourceState<FeedPage>>({
    data: null,
    loading: true,
    error: null,
  })
  const [items, setItems] = useState<FeedItem[]>([])
  const [counts, setCounts] = useState<Record<UnifiedStatus, number> | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [paginationError, setPaginationError] = useState<unknown | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(false)
  const [detail, setDetail] = useState<{
    key: string | null
    data: UnlockedFeedItem | null
    loading: boolean
    error: unknown | null
  }>({ key: null, data: null, loading: false, error: null })

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      feedGeneration.current += 1
      detailGeneration.current += 1
      paginationRequest.current = false
    }
  }, [])

  useEffect(() => {
    if (!activationMoment) return
    navigate(location.pathname + location.search, { replace: true, state: null })
    // Le marqueur d'activation ne se consomme qu'une fois.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadFeed = useCallback(async () => {
    const generation = ++feedGeneration.current
    setFeed((current) => ({ ...current, loading: true, error: null }))
    setLoadingMore(false)
    setPaginationError(null)
    try {
      const data = await signals.feed(feedQuery(filters, null))
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed({ data, loading: false, error: null })
      setItems(data.items)
      // `counts_available: false` ne remet pas les compteurs à zéro : un
      // chiffre absent n'est pas un chiffre nul.
      if (data.counts_available !== false) setCounts(data.counts)

      if (postFeedBilling.current) {
        postFeedBilling.current = false
        const refreshed = await billing.status().catch(() => null)
        if (mounted.current && generation === feedGeneration.current && refreshed) {
          setPostActivationBilling(refreshed)
        }
      }
    } catch (error) {
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed((current) => ({ ...current, loading: false, error }))
    }
    // La signature sérialisée des filtres serveur est la frontière de génération.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverSignature])

  useEffect(() => {
    void loadFeed()
  }, [loadFeed])

  const loadMore = useCallback(async () => {
    const currentPage = feed.data
    if (!currentPage?.page.has_more || paginationRequest.current) return
    const generation = feedGeneration.current
    paginationRequest.current = true
    setLoadingMore(true)
    setPaginationError(null)
    try {
      const next = await signals.feed(feedQuery(filters, currentPage.page.next_cursor ?? null))
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed({ data: next, loading: false, error: null })
      if (next.counts_available !== false) setCounts(next.counts)
      setItems((current) => {
        const seen = new Set(current.map((entry) => entry.signal_id))
        return [...current, ...next.items.filter((entry) => !seen.has(entry.signal_id))]
      })
    } catch (error) {
      if (mounted.current && generation === feedGeneration.current) setPaginationError(error)
    } finally {
      paginationRequest.current = false
      if (mounted.current && generation === feedGeneration.current) setLoadingMore(false)
    }
  }, [feed.data, filters])

  const selectedKey = signalKey ?? null
  const rowItem = selectedKey
    ? items.find((entry) => entry.signal_id === selectedKey) ?? null
    : null

  /* Un lien profond vers un signal absent de la page chargée demande le détail.
   * Un signal verrouillé ne passe jamais par là : il part à la facturation. */
  useEffect(() => {
    if (!selectedKey) {
      detailGeneration.current += 1
      setDetail({ key: null, data: null, loading: false, error: null })
      return
    }
    if (feed.loading) return
    if (rowItem?.locked) {
      detailGeneration.current += 1
      setDetail({ key: selectedKey, data: null, loading: false, error: null })
      navigate('/app/billing', { replace: true, state: { lockedSignalKey: selectedKey } })
      return
    }
    if (rowItem) {
      detailGeneration.current += 1
      setDetail({ key: selectedKey, data: null, loading: false, error: null })
      return
    }

    const generation = ++detailGeneration.current
    setDetail({ key: selectedKey, data: null, loading: true, error: null })
    signals.detail(selectedKey).then(
      (data) => {
        if (!mounted.current || generation !== detailGeneration.current) return
        if (data.locked) {
          setDetail({ key: selectedKey, data: null, loading: false, error: null })
          navigate('/app/billing', { replace: true, state: { lockedSignalKey: selectedKey } })
          return
        }
        setDetail({ key: selectedKey, data, loading: false, error: null })
      },
      (error) => {
        if (mounted.current && generation === detailGeneration.current) {
          setDetail({ key: selectedKey, data: null, loading: false, error })
        }
      },
    )
  }, [detailRetryToken, feed.loading, navigate, rowItem, selectedKey])

  const selectedItem: UnlockedFeedItem | null = rowItem && !rowItem.locked
    ? rowItem
    : detail.key === selectedKey
      ? detail.data
      : null
  const drawerLoading = Boolean(selectedKey) && !selectedItem && (feed.loading || detail.loading)
  const drawerError = detail.key === selectedKey ? detail.error : null

  // ── Filtres navigateur ────────────────────────────────────────────────────

  const minAmount = Number.parseFloat(filters.min)
  const hasMin = Number.isFinite(minAmount) && minAmount > 0
  const needle = foldCase(filters.q.trim())

  const rows = useMemo(() => {
    if (!hasMin && !needle) return items
    return items.filter((entry) => {
      // Un signal verrouillé ne publie ni montant ni titulaire : aucun filtre
      // navigateur ne peut affirmer qu'il correspond.
      if (entry.locked) return false
      if (hasMin) {
        const value = Number.parseFloat(entry.contract.amount?.value ?? '')
        if (!Number.isFinite(value) || value < minAmount) return false
      }
      if (needle) {
        const haystack = foldCase(`${entry.company.name ?? ''} ${signalObject(entry) ?? ''}`)
        if (!haystack.includes(needle)) return false
      }
      return true
    })
  }, [hasMin, items, minAmount, needle])

  const zones = useMemo(() => {
    const seen = new Set<string>()
    for (const entry of items) {
      if (entry.locked) continue
      const code = entry.contract.location?.subdivision_code
      if (code) seen.add(code)
    }
    return [...seen]
  }, [items])

  // ── Écriture de l'URL ─────────────────────────────────────────────────────

  const setParam = useCallback(
    (name: string, value: string) => {
      const params = new URLSearchParams(location.search)
      if (value) params.set(name, value)
      else params.delete(name)
      navigate(
        { pathname: location.pathname, search: params.toString() ? `?${params}` : '' },
        { replace: true },
      )
    },
    [location.pathname, location.search, navigate],
  )

  const openSignal = useCallback(
    (key: string) => {
      navigate(`/app/signals/${encodeURIComponent(key)}${location.search}`)
    },
    [location.search, navigate],
  )

  const closeDrawer = useCallback(() => {
    navigate(`/app/signals${location.search}`)
  }, [location.search, navigate])

  const openBilling = useCallback(
    (key: string) => {
      navigate('/app/billing', { state: { lockedSignalKey: key } })
    },
    [navigate],
  )

  /* Échap referme le tiroir de bureau. Sous 900 px, la feuille Radix possède
   * déjà cette touche : deux gestionnaires fermeraient deux fois. */
  useEffect(() => {
    if (!selectedKey || compact) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeDrawer()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [closeDrawer, compact, selectedKey])

  // ── Actions optimistes ────────────────────────────────────────────────────

  const applyStatus = useCallback((key: string, status: UnifiedStatus) => {
    setItems((current) =>
      current.map((entry) =>
        entry.signal_id === key && !entry.locked ? { ...entry, status } : entry,
      ),
    )
    setDetail((current) =>
      current.data && current.data.signal_id === key
        ? { ...current, data: { ...current.data, status } }
        : current,
    )
  }, [])

  const shiftCounts = useCallback((from: UnifiedStatus, to: UnifiedStatus) => {
    setCounts((current) =>
      current
        ? { ...current, [from]: Math.max(0, current[from] - 1), [to]: current[to] + 1 }
        : current,
    )
  }, [])

  const runAction = useCallback(
    async (next: UnifiedStatus, call: (key: string) => Promise<unknown>) => {
      const target = selectedItem
      if (!target || busy) return
      const previous = target.status
      if (previous === next) return
      const key = target.signal_id

      setActionError(false)
      setBusy(true)
      applyStatus(key, next)
      shiftCounts(previous, next)
      try {
        await call(key)
      } catch {
        // Se dédire entièrement : la ligne, le tiroir ET les compteurs.
        applyStatus(key, previous)
        shiftCounts(next, previous)
        if (mounted.current) setActionError(true)
      } finally {
        if (mounted.current) setBusy(false)
      }
    },
    [applyStatus, busy, selectedItem, shiftCounts],
  )

  // ── Rendu ─────────────────────────────────────────────────────────────────

  const planCode = feed.data?.plan_code ?? null
  const discoveryGrantCount = activationMoment
    && planCode === 'discovery'
    && postActivationBilling?.plan_code === 'discovery'
    ? postActivationBilling.discovery.granted_signal_count
    : null
  const shown = discoveryGrantCount ?? rows.length
  const suffix = discoveryGrantCount === null && feed.data?.page.has_more ? '+' : ''
  const signalCount = feed.data
    ? interpolate(plural(shown, copy.count.one, copy.count.other), { count: `${shown}${suffix}` })
    : t.common.loading

  const sectorLocked = feed.data?.filter_access.sector === false

  const drawer = (
    <SignalDrawer
      item={selectedItem}
      loading={drawerLoading}
      error={drawerError}
      busy={busy}
      onClose={closeDrawer}
      onRetry={() => setDetailRetryToken((token) => token + 1)}
      onContacted={() => void runAction('contacted', (key) => feedback.markContacted(key))}
      onSave={() => void runAction('saved', (key) => feedback.write(key, { relevance: 'relevant' }))}
      onIgnore={() =>
        void runAction('ignored', (key) =>
          feedback.write(key, { relevance: 'not_relevant', reason: 'other' }))}
    />
  )

  return (
    <div className={styles.page} data-page="signals">
      {/* Le bandeau applicatif (`AppShell`) porte déjà le seul `h1` de la page,
       * avec le même intitulé : en répéter un second casserait la règle « un
       * h1 par page » et rendrait `getByRole('heading', { name: 'Signaux' })`
       * ambigu. Le titre ici reste du texte, la légende garde son rôle. */}
      <header className={styles.header}>
        <p className={styles.title}>{copy.title}</p>
        <p>{copy.subtitle}</p>
      </header>

      <div
        className={styles.filters}
        role="toolbar"
        aria-label={t.reference.signalsPage.filtersTitle}
      >
        <div
          className={styles.segments}
          role="group"
          aria-label={t.reference.signalsPage.statusFilter}
        >
          {SEGMENTS.map((segment) => {
            const count = segment !== 'all' && COUNTED_SEGMENTS.includes(segment)
              ? counts?.[segment] ?? null
              : null
            return (
              <button
                type="button"
                key={segment}
                data-segment={segment}
                aria-pressed={filters.segment === segment}
                onClick={() => setParam('status', segment)}
              >
                {copy.segments[segment]}
                {count === null ? null : <span className={styles.segmentCount}>{count}</span>}
              </button>
            )
          })}
        </div>

        <label className={styles.filter}>
          <span>{copy.filters.zone}</span>
          <input
            list="signals-zones"
            value={filters.zone}
            onChange={(event) => setParam('zone', event.target.value.toUpperCase())}
          />
          <datalist id="signals-zones">
            {zones.map((zone) => <option value={zone} key={zone} />)}
          </datalist>
        </label>

        <label className={styles.filter}>
          <span>{copy.filters.sector}</span>
          <input
            value={filters.cpv}
            maxLength={8}
            inputMode="numeric"
            disabled={sectorLocked}
            aria-describedby={sectorLocked ? 'signals-sector-restricted' : undefined}
            onChange={(event) => setParam('cpv', event.target.value.replace(/\D/g, ''))}
          />
        </label>

        <label className={styles.filter}>
          <span>{copy.filters.minAmount}</span>
          <input
            type="number"
            min={0}
            step={1000}
            value={filters.min}
            aria-describedby="signals-loaded-only"
            onChange={(event) => setParam('min', event.target.value)}
          />
        </label>

        <label className={styles.filter}>
          <span>{copy.filters.period}</span>
          <select
            value={filters.period}
            onChange={(event) => setParam('period', event.target.value)}
          >
            {PERIODS.map((period) => (
              <option value={period} key={period}>{copy.filters.periodOptions[period]}</option>
            ))}
          </select>
        </label>

        <label className={`${styles.filter} ${styles.searchFilter}`}>
          <span className={styles.visuallyHidden}>{copy.filters.search}</span>
          <input
            type="search"
            value={filters.q}
            placeholder={copy.filters.search}
            aria-describedby="signals-loaded-only"
            onChange={(event) => setParam('q', event.target.value)}
          />
        </label>

        <small id="signals-loaded-only" className={styles.loadedOnly}>
          {copy.filters.loadedOnly}
        </small>
      </div>

      {sectorLocked ? (
        <p id="signals-sector-restricted" className={styles.restrictedNote}>
          {t.reference.signalsPage.restrictedFilter}
        </p>
      ) : null}

      {actionError ? (
        <p className={styles.alert} role="alert">{copy.actionError}</p>
      ) : null}

      <div className={styles.layout}>
        <section className={styles.tableColumn} aria-busy={feed.loading}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">{copy.columns.date}</th>
                <th scope="col">{copy.columns.winner}</th>
                <th scope="col">{copy.columns.object}</th>
                <th scope="col" className={styles.cellNumeric}>{copy.columns.amount}</th>
                {compact ? null : <th scope="col">{copy.columns.place}</th>}
                <th scope="col">{copy.columns.match}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((entry) => (entry.locked ? (
                <LockedRow
                  key={entry.signal_id}
                  item={entry}
                  compact={compact}
                  note={t.reference.signalsPage.lockedReason}
                  onOpen={() => openBilling(entry.signal_id)}
                />
              ) : (
                <SignalRow
                  key={entry.signal_id}
                  item={entry}
                  selected={entry.signal_id === selectedKey}
                  compact={compact}
                  onOpen={openSignal}
                />
              )))}
            </tbody>
          </table>

          {feed.loading && !feed.data ? (
            <p className={styles.note} role="status">{t.common.loading}</p>
          ) : feed.error && !feed.data ? (
            <div className={styles.note} role="alert">
              <p>{t.reference.messages.loadError}</p>
              <button type="button" className="text-link" onClick={() => void loadFeed()}>
                {t.common.retry}
              </button>
            </div>
          ) : rows.length === 0 ? (
            <p className={styles.note}>{copy.empty}</p>
          ) : null}

          <div className={styles.footer}>
            <span className={styles.count}>{signalCount}</span>
            {paginationError ? (
              <span role="alert">
                {t.reference.messages.loadError}{' '}
                <button type="button" className="text-link" onClick={() => void loadMore()}>
                  {t.common.retry}
                </button>
              </span>
            ) : feed.data?.page.has_more ? (
              <button
                type="button"
                className="text-link"
                disabled={loadingMore}
                onClick={() => void loadMore()}
              >
                {loadingMore ? t.common.loading : copy.loadMore}
              </button>
            ) : null}
          </div>
        </section>

        {compact ? null : <div className={styles.drawerColumn}>{drawer}</div>}
      </div>

      {compact ? (
        <Sheet
          open={Boolean(selectedKey)}
          onOpenChange={(open) => {
            if (!open) closeDrawer()
          }}
        >
          <SheetContent
            side="right"
            className={styles.sheet}
            closeLabel={copy.drawer.close}
            aria-describedby={undefined}
          >
            <SheetTitle className={styles.visuallyHidden}>{copy.title}</SheetTitle>
            {drawer}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  )
}
