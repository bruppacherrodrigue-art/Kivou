import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { LockKeyhole } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { billing, companies, signals } from '../api/endpoints'
import type { FeedQuery } from '../api/endpoints'
import { useCurrentUser } from '../auth/SessionProvider'
import type {
  BillingStatus,
  CompanyProfile,
  FeedItem,
  FeedPage,
  SignalDetail as SignalDetailPayload,
} from '../api/types'
import { interpolate, useI18n } from '../i18n'
import { toSignalCard, toSignalDetailView } from '../reference/dashboard/adapters'
import { ReferenceSignalDetail } from '../reference/dashboard/ReferenceSignalDetail'
import type { SignalCardView } from '../reference/dashboard/models'
import { useSignalNote } from '../reference/dashboard/useSignalNote'
import styles from './SignalsFeed.module.css'

const PAGE_SIZE = 20
const SINGLE_PANE_QUERY = '(max-width: 1179px)'
const HISTORY_STATUSES = [
  'recent_award',
  'recently_notified_contract',
  'recently_published_award',
  'aging_award',
  'stale_award',
  'award_date_unknown',
  'invalid_award_date',
] as const

export interface ActivationNavigationState {
  activationCompleted?: boolean
}

interface SignalSelectionNavigationState {
  signalSelection: {
    kind: 'feed'
    key: string
    query: string
    fromList: boolean
  }
}

interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

interface PendingDetailFocus {
  key: string
  keyboard: boolean
}

interface FeedFilters {
  view: 'recent' | 'history'
  dateFrom: string
  dateTo: string
  country: string
  subdivision: string
  status: string
  cpv: string
}

const emptyResource = <T,>(): ResourceState<T> => ({
  data: null,
  loading: true,
  error: null,
})

function filtersFrom(search: string): FeedFilters {
  const params = new URLSearchParams(search)
  return {
    view: params.get('view') === 'history' ? 'history' : 'recent',
    dateFrom: params.get('from') ?? '',
    dateTo: params.get('to') ?? '',
    country: (params.get('country') ?? '').toUpperCase(),
    subdivision: (params.get('subdivision') ?? '').toUpperCase(),
    status: params.get('status') ?? '',
    cpv: params.get('cpv') ?? '',
  }
}

function feedQuery(filters: FeedFilters): FeedQuery {
  if (filters.view === 'recent') {
    return { view: 'recent', freshness: 'new', limit: PAGE_SIZE, offset: 0 }
  }
  return {
    view: 'history',
    limit: PAGE_SIZE,
    cursor: null,
    date_from: filters.dateFrom || null,
    date_to: filters.dateTo || null,
    country: filters.country || null,
    subdivision_code: filters.subdivision || null,
    status: filters.status || null,
    cpv_prefix: filters.cpv || null,
  }
}

function singlePaneSnapshot(): boolean {
  if (typeof window.matchMedia === 'function') {
    return window.matchMedia(SINGLE_PANE_QUERY).matches
  }
  return window.innerWidth < 1180
}

function useSinglePane(): boolean {
  const [singlePane, setSinglePane] = useState(singlePaneSnapshot)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mediaQuery = window.matchMedia(SINGLE_PANE_QUERY)
    const onChange = (event: MediaQueryListEvent) => setSinglePane(event.matches)
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', onChange)
      return () => mediaQuery.removeEventListener('change', onChange)
    }
    mediaQuery.addListener(onChange)
    return () => mediaQuery.removeListener(onChange)
  }, [])

  return singlePane
}

export function SignalsFeed() {
  const { t, date, amount } = useI18n()
  const me = useCurrentUser()
  const location = useLocation()
  const navigate = useNavigate()
  const { signalKey } = useParams()
  const filters = useMemo(() => filtersFrom(location.search), [location.search])
  const querySignature = JSON.stringify(filters)
  const singlePane = useSinglePane()

  const mounted = useRef(false)
  const feedGeneration = useRef(0)
  const detailGeneration = useRef(0)
  const companyGeneration = useRef(0)
  const paginationRequest = useRef(false)
  const rowRefs = useRef(new Map<string, HTMLButtonElement>())
  const listPanelRef = useRef<HTMLElement | null>(null)
  const detailPanelRef = useRef<HTMLElement | null>(null)
  const lastSelection = useRef<string | null>(null)
  const previousLocationKey = useRef(location.key)
  const initialFocusRestored = useRef(false)
  const pendingDetailFocus = useRef<PendingDetailFocus | null>(
    signalKey && singlePane ? { key: signalKey, keyboard: false } : null,
  )

  const [activationMoment] = useState(
    () => (location.state as ActivationNavigationState | null)?.activationCompleted === true,
  )
  const postFeedBilling = useRef(activationMoment)
  const [feed, setFeed] = useState<ResourceState<FeedPage>>(emptyResource)
  const [items, setItems] = useState<FeedItem[]>([])
  const [loadingMore, setLoadingMore] = useState(false)
  const [paginationError, setPaginationError] = useState<unknown | null>(null)
  const [postActivationBilling, setPostActivationBilling] = useState<BillingStatus | null>(null)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [detail, setDetail] = useState<{
    key: string | null
    data: SignalDetailPayload | null
    loading: boolean
    error: unknown | null
  }>({ key: null, data: null, loading: false, error: null })
  const [companyAttempt, setCompanyAttempt] = useState(0)
  const [companyProfile, setCompanyProfile] = useState<ResourceState<CompanyProfile>>({
    data: null,
    loading: false,
    error: null,
  })

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      feedGeneration.current += 1
      detailGeneration.current += 1
      companyGeneration.current += 1
      paginationRequest.current = false
    }
  }, [])

  useEffect(() => {
    if (!activationMoment) return
    navigate(location.pathname + location.search, { replace: true, state: null })
    // The activation marker is consumed only once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadFeed = useCallback(async () => {
    const generation = ++feedGeneration.current
    setFeed((current) => ({ ...current, loading: true, error: null }))
    setLoadingMore(false)
    setPaginationError(null)
    try {
      const data = await signals.feed(feedQuery(filters))
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed({ data, loading: false, error: null })
      setItems(data.items)

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
  // The serialised URL state is the generation boundary.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [querySignature])

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
      const nextQuery: FeedQuery = filters.view === 'history'
        ? { ...feedQuery(filters), cursor: currentPage.page.next_cursor ?? null }
        : {
            ...feedQuery(filters),
            offset: currentPage.page.offset + currentPage.page.limit,
          }
      const next = await signals.feed(nextQuery)
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed({ data: next, loading: false, error: null })
      setItems((current) => {
        const seen = new Set(current.map((item) => item.signal_id))
        return [...current, ...next.items.filter((item) => !seen.has(item.signal_id))]
      })
    } catch (error) {
      if (mounted.current && generation === feedGeneration.current) setPaginationError(error)
    } finally {
      paginationRequest.current = false
      if (mounted.current && generation === feedGeneration.current) setLoadingMore(false)
    }
  }, [feed.data, filters])

  const firstUnlocked = items.find((item) => !item.locked) ?? null
  const selectedKey = signalKey ?? firstUnlocked?.signal_id ?? null
  const selectedItem = selectedKey
    ? items.find((item) => item.signal_id === selectedKey) ?? null
    : null

  useEffect(() => {
    if (!selectedKey) {
      detailGeneration.current += 1
      setDetail({ key: null, data: null, loading: false, error: null })
      return
    }
    // Resolve the first authorised feed page before a detail request. This
    // prevents a locked teaser from triggering a detail GET while historical
    // deep-links still use the dedicated endpoint after that single check.
    if (feed.loading) return
    if (selectedItem?.locked) {
      detailGeneration.current += 1
      setDetail({ key: selectedKey, data: null, loading: false, error: null })
      navigate('/app/billing', {
        replace: true,
        state: { lockedSignalKey: selectedKey },
      })
      return
    }

    const generation = ++detailGeneration.current
    setDetail({ key: selectedKey, data: null, loading: true, error: null })
    signals.detail(selectedKey).then(
      (data) => {
        if (!mounted.current || generation !== detailGeneration.current) return
        if (data.locked) {
          setDetail({ key: selectedKey, data: null, loading: false, error: null })
          navigate('/app/billing', {
            replace: true,
            state: { lockedSignalKey: selectedKey },
          })
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
  }, [detailAttempt, feed.loading, navigate, selectedItem, selectedKey, signalKey])

  useLayoutEffect(() => {
    const panel = detailPanelRef.current
    if (panel && typeof panel.scrollTo === 'function') {
      panel.scrollTo({ top: 0, behavior: 'auto' })
    } else if (panel) panel.scrollTop = 0
  }, [selectedKey])

  useEffect(() => {
    if (
      !pendingDetailFocus.current
      || pendingDetailFocus.current.key !== selectedKey
      || detail.key !== selectedKey
      || detail.loading
    ) return
    const frame = window.requestAnimationFrame(() => {
      const title = detailPanelRef.current?.querySelector<HTMLElement>('#detail-title')
      if (!title) return
      const pendingFocus = pendingDetailFocus.current
      if (!pendingFocus || pendingFocus.key !== selectedKey) return
      if (pendingFocus.keyboard) delete title.dataset.programmaticFocus
      else {
        title.dataset.programmaticFocus = 'true'
        title.addEventListener('blur', () => {
          delete title.dataset.programmaticFocus
        }, { once: true })
      }
      title.focus({ preventScroll: true })
      pendingDetailFocus.current = null
    })
    return () => window.cancelAnimationFrame(frame)
  }, [detail.data, detail.error, detail.key, detail.loading, selectedKey])

  useEffect(() => {
    if (previousLocationKey.current === location.key) return
    previousLocationKey.current = location.key
    const selection = readSelectionState(location.state)
    if (signalKey && singlePane) {
      if (pendingDetailFocus.current?.key !== signalKey) {
        pendingDetailFocus.current = { key: signalKey, keyboard: false }
      }
      return
    }
    const focusKey = selection?.key ?? lastSelection.current
    if (!focusKey) return
    lastSelection.current = focusKey
    const frame = window.requestAnimationFrame(() => {
      rowRefs.current.get(focusKey)?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [location.key, location.state, signalKey, singlePane])

  useEffect(() => {
    if (initialFocusRestored.current) return
    const selection = readSelectionState(location.state)
    const focusKey = selection?.key ?? null
    if (!focusKey || !rowRefs.current.has(focusKey)) return
    initialFocusRestored.current = true
    lastSelection.current = focusKey
    const frame = window.requestAnimationFrame(() => {
      rowRefs.current.get(focusKey)?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [items, location.state])

  const visibleDetail = detail.key === selectedKey
    ? detail
    : { key: selectedKey, data: null, loading: Boolean(selectedKey), error: null }
  const contextItem = visibleDetail.data
    && !visibleDetail.data.locked
    && !items.some((item) => item.signal_id === visibleDetail.data?.signal_id)
    ? visibleDetail.data
    : null
  const displayedItems = contextItem ? [contextItem, ...items] : items
  const cards = displayedItems.map(toSignalCard)
  const companyRows = (() => {
    const grouped = new Map<string, { key: string; name: string | null; cards: SignalCardView[] }>()
    cards.forEach((card, index) => {
      const item = displayedItems[index]
      const companyKey = !item.locked && item.company_key
        ? `company:${item.company_key}`
        : `signal:${card.id}`
      const current = grouped.get(companyKey)
      if (current) current.cards.push(card)
      else grouped.set(companyKey, { key: companyKey, name: card.companyName, cards: [card] })
    })
    return [...grouped.values()]
  })()
  const detailView = visibleDetail.data && !visibleDetail.data.locked
    ? toSignalDetailView(visibleDetail.data)
    : null
  const selectedCompanyKey = detailView?.companyKey ?? null
  useEffect(() => {
    if (!selectedCompanyKey) {
      companyGeneration.current += 1
      setCompanyProfile({ data: null, loading: false, error: null })
      return
    }
    const generation = ++companyGeneration.current
    setCompanyProfile({ data: null, loading: true, error: null })
    companies.get(selectedCompanyKey).then(
      (data) => {
        if (mounted.current && generation === companyGeneration.current) {
          setCompanyProfile({ data, loading: false, error: null })
        }
      },
      (error) => {
        if (mounted.current && generation === companyGeneration.current) {
          setCompanyProfile({ data: null, loading: false, error })
        }
      },
    )
  }, [companyAttempt, selectedCompanyKey])
  const note = useSignalNote({
    accountId: me.account_id,
    signalKey: selectedKey,
    enabled: Boolean(detailView),
  })

  const planCode = feed.data?.plan_code ?? null
  const planLabel = planCode ? t.reference.plans[planCode] : t.reference.loading
  const discoveryGrantCount = activationMoment
    && planCode === 'discovery'
    && postActivationBilling?.plan_code === 'discovery'
    ? postActivationBilling.discovery.granted_signal_count
    : null
  const signalCount = feed.data
    ? `${discoveryGrantCount ?? items.length}${discoveryGrantCount === null && feed.data.page.has_more ? '+' : ''} · ${planLabel}`
    : planLabel

  const setSearchValue = (name: string, value: string) => {
    const params = new URLSearchParams(location.search)
    if (value) params.set(name, value)
    else params.delete(name)
    navigate({ pathname: location.pathname, search: params.toString() ? `?${params}` : '' })
  }
  const clearHistoryFilters = () => {
    const params = new URLSearchParams(location.search)
    for (const name of ['from', 'to', 'country', 'subdivision', 'status', 'cpv']) {
      params.delete(name)
    }
    navigate({ pathname: location.pathname, search: params.toString() ? `?${params}` : '' })
  }

  const displayAmount = (card: SignalCardView) => card.amount
    ? amount(card.amount.value, card.amount.currency) ?? t.reference.missingValue
    : t.reference.missingValue
  const displayDate = (value: string | null) => date(value) ?? t.reference.missingValue
  const displayLocation = (card: SignalCardView) => {
    if (!card.location) return t.reference.missingValue
    return [
      card.location.locality,
      card.location.postal_code,
      card.location.subdivision_label ?? card.location.subdivision_code,
      card.location.country,
    ].filter(Boolean).join(', ') || t.reference.missingValue
  }
  const cardStatus = (card: SignalCardView) => {
    if (card.locked) return {
      key: 'locked',
      label: t.reference.signalsPage.paidAccessRequired,
    }
    return { key: 'official-source', label: t.reference.fields.officialSource }
  }
  const historyAccess = feed.data?.history_access
  const historyNote = !historyAccess
    ? null
    : historyAccess.scope === 'grants_only'
      ? t.reference.signalsPage.historyGrantsOnly
      : historyAccess.scope === 'all_available'
        ? t.reference.signalsPage.historyAll
        : interpolate(t.reference.signalsPage.historyWindow, {
            days: historyAccess.history_days ?? 0,
          })
  const filterAccess = feed.data?.filter_access

  return (
    <div
      className={`workspace-grid ${styles.workspace}`}
      data-pane={signalKey ? 'detail' : 'list'}
    >
      <aside
        ref={listPanelRef}
        className={`feed-panel ${styles.listPanel}`}
        data-master-detail-pane="list"
        aria-labelledby="signals-list-title"
      >
        <div className="panel-heading">
          <div>
            <p className="section-label">{t.reference.signalsPage.sourceType}</p>
            <h2 id="signals-list-title">{t.reference.signalsPage.detectedSignals}</h2>
          </div>
          <span className="signal-count">{signalCount}</span>
        </div>

        <div className={styles.viewSwitch} aria-label={t.reference.signalsPage.filtersTitle}>
          <button type="button" aria-pressed={filters.view === 'recent'} onClick={() => setSearchValue('view', '')}>
            {t.reference.signalsPage.recentView}
          </button>
          <button type="button" aria-pressed={filters.view === 'history'} onClick={() => setSearchValue('view', 'history')}>
            {t.reference.signalsPage.historyView}
          </button>
        </div>

        {filters.view === 'history' ? (
          <section className={styles.filters} aria-labelledby="history-filters-title">
            <div className={styles.filterHeading}>
              <h3 id="history-filters-title">{t.reference.signalsPage.filtersTitle}</h3>
              <button type="button" onClick={clearHistoryFilters}>{t.reference.signalsPage.clearFilters}</button>
            </div>
            {historyNote ? <p className={styles.accessNote}>{historyNote}</p> : null}
            <div className={styles.filterGrid}>
              <label>
                <span>{t.reference.signalsPage.dateFrom}</span>
                <input type="date" value={filters.dateFrom} disabled={filterAccess?.date_range === false} onChange={(event) => setSearchValue('from', event.target.value)} />
              </label>
              <label>
                <span>{t.reference.signalsPage.dateTo}</span>
                <input type="date" value={filters.dateTo} disabled={filterAccess?.date_range === false} onChange={(event) => setSearchValue('to', event.target.value)} />
              </label>
              <label>
                <span>{t.reference.signalsPage.countryFilter}</span>
                <input value={filters.country} maxLength={2} disabled={filterAccess?.country === false} onChange={(event) => setSearchValue('country', event.target.value.toUpperCase())} />
              </label>
              <label>
                <span>{t.reference.signalsPage.subdivisionFilter}</span>
                <input value={filters.subdivision} maxLength={16} disabled={filterAccess?.subdivision === false} onChange={(event) => setSearchValue('subdivision', event.target.value.toUpperCase())} />
              </label>
              <label>
                <span>{t.reference.signalsPage.statusFilter}</span>
                <select value={filters.status} disabled={filterAccess?.status === false} onChange={(event) => setSearchValue('status', event.target.value)}>
                  <option value="">{t.reference.signalsPage.allStatuses}</option>
                  {HISTORY_STATUSES.map((status) => <option value={status} key={status}>{status}</option>)}
                </select>
              </label>
              <label>
                <span>{t.reference.signalsPage.sectorFilter}</span>
                <input value={filters.cpv} maxLength={8} inputMode="numeric" disabled={filterAccess?.sector === false} onChange={(event) => setSearchValue('cpv', event.target.value.replace(/\D/g, ''))} />
              </label>
            </div>
            {filterAccess && Object.values(filterAccess).some((allowed) => !allowed) ? (
              <p className={styles.restrictedNote}>{t.reference.signalsPage.restrictedFilter}</p>
            ) : null}
          </section>
        ) : null}

        <div className="signal-list" aria-busy={feed.loading}>
          {feed.loading && !feed.data ? (
            [0, 1, 2].map((index) => (
              <div className="signal-item" aria-hidden="true" key={index}>
                <span className="signal-event">{t.reference.loading}</span>
              </div>
            ))
          ) : feed.error && !feed.data ? (
            <div className="signal-item" role="alert">
              <span className="signal-event">{t.reference.messages.loadError}</span>
              <button type="button" className="source-link" onClick={() => void loadFeed()}>{t.reference.retry}</button>
            </div>
          ) : companyRows.length === 0 ? (
            <div className="signal-item"><span className="signal-event">{t.reference.signalsPage.empty}</span></div>
          ) : companyRows.map((companyRow) => {
            const selectedCard = companyRow.cards.find((candidate) => candidate.id === selectedKey)
            const card = selectedCard ?? companyRow.cards[0]
            const selected = selectedCard !== undefined
            const status = cardStatus(card)
            const selectedNoteIsKnown = selected && note.state !== 'loading' && note.state !== 'read-error'
            const hasSelectedNote = selectedNoteIsKnown && note.value.trim().length > 0
            const cardTitle = card.eventTitle ?? t.reference.missingValue
            return (
              <button
                type="button"
                ref={(node) => {
                  for (const award of companyRow.cards) {
                    if (node) rowRefs.current.set(award.id, node)
                    else rowRefs.current.delete(award.id)
                  }
                }}
                className={`signal-item${selected ? ' is-selected' : ''}${card.locked ? ' is-locked' : ''}`}
                aria-label={card.locked
                  ? interpolate(t.reference.signalsPage.openLockedSignal, { headline: cardTitle, status: status.label })
                  : interpolate(t.reference.signalsPage.openSignal, {
                      company: card.companyName ?? t.reference.missingValue,
                      headline: cardTitle,
                      status: status.label,
                    })}
                aria-pressed={selected}
                onClick={(event) => {
                  lastSelection.current = card.id
                  if (card.locked) {
                    // Persist the originating row on the history entry so a
                    // browser Back from Billing can restore its focus.
                    navigate(`/app/signals${location.search}`, {
                      replace: true,
                      state: selectionState(card.id, location.search, true),
                    })
                    queueMicrotask(() => {
                      navigate('/app/billing', { state: { lockedSignalKey: card.id } })
                    })
                    return
                  }
                  if (singlePane || event.detail === 0) {
                    pendingDetailFocus.current = {
                      key: card.id,
                      keyboard: event.detail === 0,
                    }
                  }
                  navigate(`/app/signals/${encodeURIComponent(card.id)}${location.search}`, {
                    state: selectionState(card.id, location.search, true),
                  })
                }}
                key={companyRow.key}
              >
                <span className="signal-item-head">
                  <strong>{card.locked ? t.reference.missingValue : companyRow.name}</strong>
                  <span className={`data-status-${status.key}`}>{status.label}</span>
                </span>
                <span className={styles.awardCount}>
                  {companyRow.cards.length} attribution{companyRow.cards.length > 1 ? 's' : ''}
                </span>
                <span className={styles.awardContexts}>
                  {companyRow.cards.map((award) => (
                    <span className={styles.awardContext} key={award.id}>
                      <strong>{award.eventTitle ?? t.reference.missingValue}</strong>
                      <small>
                        {displayAmount(award)} · {displayLocation(award)} · {displayDate(award.eventDate)}
                      </small>
                    </span>
                  ))}
                </span>
                {card.locked ? (
                  <span className="signal-reason signal-lock-note"><LockKeyhole aria-hidden="true" />{t.reference.signalsPage.lockedReason}</span>
                ) : <span className="signal-card-action">{t.reference.signalsPage.viewPublishedFacts}</span>}
                {hasSelectedNote ? <span className="signal-note-state">{t.reference.statuses.noteAdded}</span> : null}
              </button>
            )
          })}
        </div>

        {feed.loading && feed.data ? <p className="signal-limit" role="status">{t.reference.messages.refreshing}</p> : null}
        {feed.error && feed.data ? <p className="signal-limit" role="alert">{t.reference.messages.refreshFailed}</p> : null}
        {feed.data?.page.scan_truncated ? <p className="signal-limit" role="status">{t.feed.truncatedNote}</p> : null}
        {paginationError ? (
          <div role="alert">
            <p>{t.reference.messages.loadError}</p>
            <button type="button" className="text-link" onClick={() => void loadMore()}>{t.reference.signalsPage.retryMore}</button>
          </div>
        ) : null}
        {feed.data?.page.has_more && !paginationError ? (
          <button type="button" className="text-link" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? t.reference.loading : t.reference.signalsPage.loadMore}
          </button>
        ) : feed.data && companyRows.length > 0 ? <p className="signal-limit">{t.reference.signalsPage.endOfList}</p> : null}
      </aside>

      <section
        ref={detailPanelRef}
        className={`detail-panel ${styles.detailPanel}`}
        data-master-detail-pane="detail"
        id="signal-detail"
        aria-labelledby="detail-title"
        tabIndex={-1}
      >
        {selectedKey ? (
          <>
            {singlePane ? (
              <button
                type="button"
                className="source-link signal-mobile-back"
                onClick={() => {
                  lastSelection.current = selectedKey
                  const origin = readSelectionState(location.state)
                  if (origin?.fromList) navigate(-1)
                  else navigate(`/app/signals${location.search}`, { replace: true })
                }}
              >
                {t.workspace.backToList}
              </button>
            ) : null}
            <ReferenceSignalDetail
              detail={detailView}
              loading={visibleDetail.loading}
              error={visibleDetail.error}
              onRetry={() => setDetailAttempt((current) => current + 1)}
              note={note.value}
              noteState={note.state}
              noteError={note.error}
              onNoteChange={note.change}
              onNoteBlur={note.flush}
              onRetryNote={note.retry}
              companyProfile={companyProfile.data}
              companyLoading={companyProfile.loading}
              companyError={companyProfile.error}
              onRetryCompany={() => setCompanyAttempt((current) => current + 1)}
            />
          </>
        ) : (
          <div className="detail-hero">
            <div>
              <p className="section-label">{t.reference.headings.selectedSignal}</p>
              <h2 id="detail-title">{t.reference.signalsPage.chooseSignal}</h2>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function selectionState(key: string, query: string, fromList: boolean): SignalSelectionNavigationState {
  return { signalSelection: { kind: 'feed', key, query, fromList } }
}

function readSelectionState(value: unknown): SignalSelectionNavigationState['signalSelection'] | null {
  if (typeof value !== 'object' || value === null || !('signalSelection' in value)) return null
  const selection = (value as { signalSelection?: unknown }).signalSelection
  if (typeof selection !== 'object' || selection === null) return null
  const candidate = selection as Partial<SignalSelectionNavigationState['signalSelection']>
  if (
    candidate.kind !== 'feed'
    || typeof candidate.key !== 'string'
    || candidate.key.length === 0
    || typeof candidate.query !== 'string'
    || typeof candidate.fromList !== 'boolean'
  ) return null
  return candidate as SignalSelectionNavigationState['signalSelection']
}
