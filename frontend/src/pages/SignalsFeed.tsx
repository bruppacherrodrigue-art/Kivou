import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { LockKeyhole } from 'lucide-react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
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
import { Sheet, SheetContent, SheetTitle } from '../presentation/dashboard/ui/sheet'
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
      <td>{item.teaser.date ?? MISSING}</td>
      <td>
        <button type="button" className={styles.lockedButton} onClick={(event) => {
          event.stopPropagation()
          onOpen()
        }}>
          <LockKeyhole aria-hidden="true" /> {item.headline}
        </button>
      </td>
      <td className={styles.lockedNote}>{note}</td>
      <td className={styles.cellNumeric}>{item.teaser.amount ? `${item.teaser.amount.value} ${item.teaser.amount.currency}` : MISSING}</td>
      {compact ? null : <td>{item.teaser.department ?? MISSING}</td>}
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

  /* La ligne qui a ouvert le tiroir : sa clé, pour lui rendre le focus à la
   * fermeture plutôt que de le laisser tomber sur le document. */
  const openerKey = useRef<string | null>(null)

  const openSignal = useCallback(
    (key: string) => {
      openerKey.current = key
      navigate(`/app/signals/${encodeURIComponent(key)}${location.search}`)
    },
    [location.search, navigate],
  )

  /* `replace` : fermer le tiroir ne doit pas laisser une entrée d'historique
   * derrière soi. Sans quoi « Précédent » rouvrirait le tiroir qu'on vient de
   * fermer plutôt que de quitter la page. L'ouverture, elle, reste un `push` :
   * chaque signal ouvert mérite sa propre étape dans l'historique. */
  const closeDrawer = useCallback(() => {
    navigate(`/app/signals${location.search}`, { replace: true })
  }, [location.search, navigate])

  useEffect(() => {
    if (selectedKey) return
    const key = openerKey.current
    if (!key) return
    openerKey.current = null
    document
      .querySelector<HTMLElement>(`[data-signal-key="${CSS.escape(key)}"] button`)
      ?.focus()
  }, [selectedKey])

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

  /** Déplace un signal d'un compteur à l'autre. `clampedOut`, si fourni, reçoit
   *  si le décrément a été plafonné à 0 (le compteur d'origine était déjà nul :
   *  un signal peut apparaître dans un segment sans que son compteur le porte,
   *  par exemple juste après une pagination). Le rollback en a besoin : il ne
   *  doit réinjecter le point que si un point a réellement été retiré, sans
   *  quoi une action annulée gonflerait le compteur au-delà de sa vraie
   *  valeur. */
  const shiftCounts = useCallback(
    (from: UnifiedStatus, to: UnifiedStatus, clampedOut?: { current: boolean }) => {
      setCounts((current) => {
        if (!current) return current
        const clamped = current[from] <= 0
        if (clampedOut) clampedOut.current = clamped
        return { ...current, [from]: Math.max(0, current[from] - 1), [to]: current[to] + 1 }
      })
    },
    [],
  )

  const runAction = useCallback(
    async (next: UnifiedStatus, call: (key: string) => Promise<unknown>) => {
      const target = selectedItem
      if (!target || busy) return
      const previous = target.status
      if (previous === next) return
      const key = target.signal_id

      const clamped = { current: false }
      setActionError(false)
      setBusy(true)
      applyStatus(key, next)
      shiftCounts(previous, next, clamped)
      try {
        await call(key)
      } catch {
        // Se dédire entièrement : la ligne, le tiroir ET les compteurs — mais
        // sans réinjecter un point qui n'en a jamais été retiré.
        applyStatus(key, previous)
        setCounts((current) =>
          current
            ? {
                ...current,
                [next]: Math.max(0, current[next] - 1),
                [previous]: clamped.current ? current[previous] : current[previous] + 1,
              }
            : current,
        )
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
  /* Le compteur décrit UNE seule population à la fois :
   *  - sans filtre navigateur, le nombre de signaux CHARGÉS (`items`) ;
   *  - avec un filtre navigateur (montant, recherche), le nombre RETENU sur
   *    ce total chargé — jamais les deux mélangés dans un seul chiffre.
   * `has_more` et `counts_truncated` disent tous deux que ce total peut être
   * un plancher, pas une somme définitive : c'est le signal du « + ». */
  const hasClientFilter = hasMin || Boolean(needle)
  const loadedCount = discoveryGrantCount ?? items.length
  const moreBeyondLoaded = Boolean(feed.data?.page.has_more) || Boolean(feed.data?.counts_truncated)
  const suffix = discoveryGrantCount === null && moreBeyondLoaded ? '+' : ''
  const signalCount = !feed.data
    ? t.common.loading
    : hasClientFilter
      ? interpolate(copy.countFiltered, { count: `${rows.length}`, total: `${loadedCount}${suffix}` })
      : interpolate(plural(loadedCount, copy.count.one, copy.count.other), {
        count: `${loadedCount}${suffix}`,
      })

  const sectorLocked = feed.data?.filter_access.sector === false
  const displayedRows = useMemo(() => {
    if (planCode !== 'discovery') return rows
    const unlocked = rows.filter((item) => !item.locked)
    const locked = rows.filter((item) => item.locked)
    return [...unlocked, ...locked.slice(0, 5)]
  }, [planCode, rows])
  const hiddenDiscoveryCount = planCode === 'discovery'
    ? Math.max(0, rows.length - displayedRows.length)
    : 0

  const drawer = (
    <SignalDrawer
      item={selectedItem}
      loading={drawerLoading}
      error={drawerError}
      busy={busy}
      compact={compact}
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
      <header className={styles.header}>
        <h1>{copy.title}</h1>
        <p>{copy.subtitle}</p>
      </header>

      {feed.data?.provisional_profile ? (
        <aside className={styles.provisionalBanner} role="note">
          <span>Ces signaux viennent d’un profil provisoire. Confirmez-le en 30 secondes pour recevoir les vôtres.</span>
          <Link to="/onboarding">Confirmer mon profil</Link>
        </aside>
      ) : null}

      <div
        className={styles.filters}
        role="toolbar"
        aria-label={copy.filters.toolbar}
      >
        <div
          className={styles.segments}
          role="group"
          aria-label={copy.filters.statusGroup}
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

        <div className={styles.filter} title={sectorLocked ? t.reference.signalsPage.restrictedFilter : undefined}>
          <input
            list="signals-zones"
            placeholder={copy.filters.zone}
            aria-label={copy.filters.zone}
            value={filters.zone}
            onChange={(event) => setParam('zone', event.target.value.toUpperCase())}
          />
          <datalist id="signals-zones">
            {zones.map((zone) => <option value={zone} key={zone} />)}
          </datalist>
        </div>

        <div className={styles.filter} title={copy.filters.loadedOnly}>
          <input
            placeholder={copy.filters.sectorPlaceholder}
            aria-label={copy.filters.sector}
            value={filters.cpv}
            maxLength={8}
            inputMode="numeric"
            disabled={sectorLocked}
            aria-describedby={sectorLocked ? 'signals-sector-restricted' : undefined}
            onChange={(event) => setParam('cpv', event.target.value.replace(/\D/g, ''))}
          />
          {sectorLocked ? <span role="tooltip" id="signals-sector-restricted" className={styles.filterTooltip}>{t.reference.signalsPage.restrictedFilter}</span> : null}
        </div>

        <div className={styles.filter}>
          <input
            type="number"
            min={0}
            step={1000}
            placeholder={copy.filters.minAmount}
            aria-label={copy.filters.minAmount}
            value={filters.min}
            aria-describedby="signals-loaded-only"
            onChange={(event) => setParam('min', event.target.value)}
          />
        </div>

        <div className={styles.filter}>
          <select
            aria-label={copy.filters.period}
            value={filters.period}
            onChange={(event) => setParam('period', event.target.value)}
          >
            {PERIODS.map((period) => (
              <option value={period} key={period}>{copy.filters.periodOptions[period]}</option>
            ))}
          </select>
        </div>

        <div className={`${styles.filter} ${styles.searchFilter}`} title={copy.filters.loadedOnly}>
          <input
            type="search"
            value={filters.q}
            placeholder={copy.filters.search}
            aria-label={copy.filters.search}
            aria-describedby="signals-loaded-only"
            onChange={(event) => setParam('q', event.target.value)}
          />
        </div>
      </div>

      <span role="tooltip" id="signals-loaded-only" className={styles.filterTooltip}>
        {copy.filters.loadedOnly}
      </span>

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
              {displayedRows.map((entry) => (entry.locked ? (
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
              {hiddenDiscoveryCount ? (
                <tr className={styles.lockedRow}>
                  <td colSpan={compact ? 5 : 6}>
                    {hiddenDiscoveryCount} autres signaux dans votre zone — <Link to="/pricing">voir les offres</Link>
                  </td>
                </tr>
              ) : null}
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
