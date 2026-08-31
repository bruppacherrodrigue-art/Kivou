import { useCallback, useEffect, useRef, useState } from 'react'
import { LockKeyhole } from 'lucide-react'
import { useLocation, useNavigate, useNavigationType, useParams } from 'react-router-dom'
import { billing, signals } from '../api/endpoints'
import { useCurrentUser } from '../auth/SessionProvider'
import type {
  FeedItem,
  FeedPage,
  BillingStatus,
  SignalDetail as SignalDetailPayload,
} from '../api/types'
import { useI18n } from '../i18n'
import {
  publishedPresentation,
  toSignalCard,
  toSignalDetailView,
} from '../reference/dashboard/adapters'
import { ReferenceSignalDetail } from '../reference/dashboard/ReferenceSignalDetail'
import { useSignalNote } from '../reference/dashboard/useSignalNote'
import { useIsMobile } from '../reference/dashboard/use-mobile'
import type { SignalCardView } from '../reference/dashboard/models'

const PAGE_SIZE = 20

export interface ActivationNavigationState {
  activationCompleted?: boolean
}

interface SignalSelectionNavigationState {
  signalSelection: {
    kind: 'feed'
    key: string
    feedGeneration: number
    query: { freshness: 'new'; targetIcpId: '' }
  }
}

interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

interface DeepLookupState {
  key: string | null
  item: FeedItem | null
  loading: boolean
  exhausted: boolean
  truncated: boolean
  error: unknown | null
}

const emptyResource = <T,>(): ResourceState<T> => ({
  data: null,
  loading: true,
  error: null,
})

export function SignalsFeed() {
  const { t, date, amount } = useI18n()
  const me = useCurrentUser()
  const location = useLocation()
  const navigate = useNavigate()
  const navigationType = useNavigationType()
  const isMobile = useIsMobile()
  const { signalKey } = useParams()
  const mounted = useRef(false)
  const feedGeneration = useRef(0)
  const appliedFeedGeneration = useRef(0)
  const detailGeneration = useRef(0)
  const paginationRequest = useRef(false)
  const deepLookupGeneration = useRef(0)
  const deepLookupStarted = useRef<{ key: string; attempt: number } | null>(null)
  const rowRefs = useRef(new Map<string, HTMLButtonElement>())
  const lastSelection = useRef<string | null>(null)
  const previousLocationKey = useRef(location.key)
  const initialFocusRestored = useRef(false)
  const pendingDetailFocus = useRef<string | null>(null)
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate

  const [activationMoment] = useState(
    () => (location.state as ActivationNavigationState | null)?.activationCompleted === true,
  )
  const postFeedBilling = useRef(activationMoment)
  const [feed, setFeed] = useState<ResourceState<FeedPage>>(emptyResource)
  const [items, setItems] = useState<FeedItem[]>([])
  const [loadingMore, setLoadingMore] = useState(false)
  const [paginationError, setPaginationError] = useState<unknown | null>(null)
  const [postActivationBilling, setPostActivationBilling] = useState<BillingStatus | null>(null)
  const [deepLookup, setDeepLookup] = useState<DeepLookupState>({
    key: null,
    item: null,
    loading: false,
    exhausted: false,
    truncated: false,
    error: null,
  })
  const [deepLookupAttempt, setDeepLookupAttempt] = useState(0)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [detail, setDetail] = useState<{
    key: string | null
    data: SignalDetailPayload | null
    loading: boolean
    error: unknown | null
  }>({ key: null, data: null, loading: false, error: null })

  useEffect(() => {
    if (!activationMoment) return
    navigate(location.pathname + location.search, { replace: true, state: null })
    // Le moment est consommé une fois, indépendamment des navigations suivantes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadFeed = useCallback(async () => {
    const generation = ++feedGeneration.current
    setFeed((current) => ({ ...current, loading: true, error: null }))
    setLoadingMore(false)
    setPaginationError(null)
    try {
      const data = await signals.feed({ freshness: 'new', limit: PAGE_SIZE, offset: 0 })
      if (!mounted.current || generation !== feedGeneration.current) return
      appliedFeedGeneration.current = generation
      setFeed({ data, loading: false, error: null })
      setItems(data.items)

      if (postFeedBilling.current) {
        postFeedBilling.current = false
        // Après une activation, cette lecture volontairement postérieure au
        // feed permet au webhook de devenir l'autorité. L'AppShell possède sa
        // propre lecture d'affichage ; hors activation, on ne la duplique pas.
        const refreshed = await billing.status().catch(() => null)
        if (mounted.current && generation === feedGeneration.current && refreshed) {
          setPostActivationBilling(refreshed)
        }
      }
    } catch (error) {
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed((current) => ({ ...current, loading: false, error }))
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void loadFeed()
    return () => {
      mounted.current = false
      feedGeneration.current += 1
      detailGeneration.current += 1
      deepLookupGeneration.current += 1
      paginationRequest.current = false
    }
  }, [loadFeed])

  const firstUnlocked = items.find((item) => !item.locked) ?? null
  const requestedSelectionKey = signalKey ?? null
  const selectedKey = requestedSelectionKey ?? firstUnlocked?.signal_id ?? null
  const listedSelectedItem = selectedKey
    ? items.find((item) => item.signal_id === selectedKey) ?? null
    : null
  const selectedItem = listedSelectedItem ?? (
    signalKey && deepLookup.key === signalKey ? deepLookup.item : null
  )
  const canResolveMore = Boolean(
    requestedSelectionKey
      && !selectedItem
      && feed.data?.page.has_more
      && !paginationError,
  )
  const shouldResolveHistorical = Boolean(
    signalKey
      && !selectedItem
      && !feed.loading
      && !feed.error
      && feed.data
      && !feed.data.page.has_more
      && !paginationError
      && (deepLookup.key !== signalKey || deepLookup.loading),
  )

  const loadMore = useCallback(async () => {
    const currentPage = feed.data
    if (!currentPage?.page.has_more || paginationRequest.current) return
    const generation = feedGeneration.current
    paginationRequest.current = true
    setLoadingMore(true)
    setPaginationError(null)
    try {
      const next = await signals.feed({
        freshness: 'new',
        limit: PAGE_SIZE,
        offset: currentPage.page.offset + currentPage.page.limit,
      })
      if (!mounted.current || generation !== feedGeneration.current) return
      setFeed({ data: next, loading: false, error: null })
      setItems((current) => {
        const seen = new Set(current.map((item) => item.signal_id))
        return [...current, ...next.items.filter((item) => !seen.has(item.signal_id))]
      })
    } catch (error) {
      if (mounted.current && generation === feedGeneration.current) {
        setPaginationError(error)
      }
    } finally {
      paginationRequest.current = false
      if (mounted.current && generation === feedGeneration.current) setLoadingMore(false)
    }
  }, [feed.data])

  useEffect(() => {
    if (canResolveMore) void loadMore()
  }, [canResolveMore, loadMore])

  useEffect(() => {
    if (
      !signalKey
      || selectedItem
      || feed.loading
      || feed.error
      || !feed.data
      || feed.data.page.has_more
      || paginationError
    ) return
    if (
      deepLookupStarted.current?.key === signalKey
      && deepLookupStarted.current.attempt === deepLookupAttempt
    ) return

    const generation = ++deepLookupGeneration.current
    deepLookupStarted.current = { key: signalKey, attempt: deepLookupAttempt }
    setDeepLookup({
      key: signalKey,
      item: null,
      loading: true,
      exhausted: false,
      truncated: false,
      error: null,
    })
    void (async () => {
      let offset = 0
      try {
        while (true) {
          const page = await signals.feed({ freshness: 'all', limit: PAGE_SIZE, offset })
          if (!mounted.current || generation !== deepLookupGeneration.current) return
          const found = page.items.find((item) => item.signal_id === signalKey)
          if (found) {
            setDeepLookup({
              key: signalKey,
              item: found,
              loading: false,
              exhausted: false,
              truncated: false,
              error: null,
            })
            return
          }
          if (!page.page.has_more) {
            setDeepLookup({
              key: signalKey,
              item: null,
              loading: false,
              exhausted: !page.page.scan_truncated,
              truncated: page.page.scan_truncated,
              error: null,
            })
            return
          }
          offset = page.page.offset + page.page.limit
        }
      } catch (error) {
        if (mounted.current && generation === deepLookupGeneration.current) {
          setDeepLookup({
            key: signalKey,
            item: null,
            loading: false,
            exhausted: false,
            truncated: false,
            error,
          })
        }
      }
    })()
    return () => {
      if (generation === deepLookupGeneration.current) deepLookupGeneration.current += 1
    }
  }, [
    deepLookupAttempt,
    feed.data,
    feed.error,
    feed.loading,
    paginationError,
    selectedItem,
    signalKey,
  ])

  const selectionResolving = canResolveMore || shouldResolveHistorical
  const historicalLookupError = deepLookup.key === signalKey
    ? deepLookup.error ?? (deepLookup.truncated ? deepLookup : null)
    : null
  const selectionLookupError = paginationError ?? historicalLookupError

  useEffect(() => {
    if (feed.loading) {
      if (selectedKey) {
        setDetail({ key: selectedKey, data: null, loading: true, error: null })
      }
      return
    }
    if (!selectedKey) {
      detailGeneration.current += 1
      setDetail({ key: null, data: null, loading: false, error: null })
      return
    }
    if (!selectedItem) {
      detailGeneration.current += 1
      setDetail({
        key: selectedKey,
        data: null,
        loading: selectionResolving,
        error: selectionResolving
          ? null
          : selectionLookupError ?? new Error('signal_not_in_feed'),
      })
      return
    }
    if (selectedItem.locked) {
      detailGeneration.current += 1
      setDetail({ key: selectedKey, data: null, loading: false, error: null })
      navigateRef.current('/app/billing', {
        replace: true,
        state: { lockedSignalKey: selectedItem.signal_id },
      })
      return
    }

    const generation = ++detailGeneration.current
    const feedPresentation = publishedPresentation(selectedItem.presentation)
    const presentationArtifactId = feedPresentation?.artifact_id ?? null
    setDetail({ key: selectedKey, data: null, loading: true, error: null })
    signals.detail(selectedKey, { presentation_artifact_id: presentationArtifactId }).then(
      (data) => {
        if (mounted.current && generation === detailGeneration.current) {
          if (data.locked) {
            detailGeneration.current += 1
            setDetail({ key: selectedKey, data: null, loading: false, error: null })
            navigateRef.current('/app/billing', {
              replace: true,
              state: { lockedSignalKey: selectedKey },
            })
            return
          }
          const detailPresentation = publishedPresentation(data.presentation)
          const pinnedPresentation = presentationArtifactId !== null
            && detailPresentation?.artifact_id === presentationArtifactId
            ? detailPresentation
            : null
          setDetail({
            key: selectedKey,
            data: { ...data, presentation: pinnedPresentation },
            loading: false,
            error: null,
          })
        }
      },
      (error) => {
        if (mounted.current && generation === detailGeneration.current) {
          setDetail({ key: selectedKey, data: null, loading: false, error })
        }
      },
    )
  }, [
    detailAttempt,
    feed.loading,
    selectedItem,
    selectedKey,
    selectionLookupError,
    selectionResolving,
  ])

  useEffect(() => {
    if (previousLocationKey.current === location.key) return
    previousLocationKey.current = location.key
    if (navigationType === 'PUSH' && signalKey) {
      pendingDetailFocus.current = signalKey
      return
    }
    const selection = readSelectionState(location.state)
    const focusKey = selection?.key ?? (signalKey ? selectedKey : lastSelection.current)
    if (!focusKey) return
    lastSelection.current = focusKey
    const frame = window.requestAnimationFrame(() => {
      rowRefs.current.get(focusKey)?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [location.key, location.state, navigationType, selectedKey, signalKey])

  useEffect(() => {
    if (initialFocusRestored.current || navigationType !== 'POP') return
    const selection = readSelectionState(location.state)
    if (!selection || !rowRefs.current.has(selection.key)) return
    initialFocusRestored.current = true
    lastSelection.current = selection.key
    const frame = window.requestAnimationFrame(() => {
      rowRefs.current.get(selection.key)?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [items, location.state, navigationType])

  const cards = items.map(toSignalCard)
  const visibleDetail = detail.key === selectedKey
    ? detail
    : { key: selectedKey, data: null, loading: Boolean(selectedKey), error: null }
  useEffect(() => {
    if (
      !pendingDetailFocus.current
      || pendingDetailFocus.current !== selectedKey
      || visibleDetail.loading
    ) return
    const frame = window.requestAnimationFrame(() => {
      const panel = document.getElementById('signal-detail')
      document.getElementById('detail-title')?.focus()
      if (window.innerWidth < 1180) {
        panel?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
      }
      pendingDetailFocus.current = null
    })
    return () => window.cancelAnimationFrame(frame)
  }, [selectedKey, visibleDetail.loading])
  const detailView = visibleDetail.data && !visibleDetail.data.locked
    ? toSignalDetailView(visibleDetail.data)
    : null
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

  const displayAmount = (card: SignalCardView) =>
    card.amount
      ? amount(card.amount.value, card.amount.currency) ?? t.reference.missingValue
      : t.reference.missingValue
  const displayDate = (value: string | null) => date(value) ?? t.reference.missingValue
  const displayDateLabel = (card: SignalCardView) => {
    switch (card.eventDateKind) {
      case 'award':
        return t.reference.fields.signalDateAward
      case 'notification':
        return t.reference.fields.signalDateNotification
      case 'publication':
        return t.reference.fields.signalDatePublication
    }
  }
  const displayLocation = (card: SignalCardView) => {
    if (!card.location) return t.reference.missingValue
    const region = [card.location.locality, card.location.postal_code, card.location.country]
      .filter(Boolean)
      .join(', ')
    return region || t.reference.missingValue
  }

  return (
    <div className="workspace-grid">
      <aside className="feed-panel" aria-labelledby="signals-list-title">
        <div className="panel-heading">
          <div>
            <p className="section-label">{t.reference.headings.awardedContracts}</p>
            <h2 id="signals-list-title">{t.reference.signalsPage.documentedAwards}</h2>
          </div>
          <span className="signal-count">{signalCount}</span>
        </div>

        <div className="signal-list">
          {feed.loading && !feed.data ? (
            [0, 1, 2].map((index) => (
              <div className="signal-item" aria-hidden="true" key={index}>
                <span className="signal-event">{t.reference.loading}</span>
              </div>
            ))
          ) : feed.error && !feed.data ? (
            <div className="signal-item" role="alert">
              <span className="signal-event">{t.reference.messages.loadError}</span>
              <button type="button" className="source-link" onClick={() => void loadFeed()}>
                {t.reference.retry}
              </button>
            </div>
          ) : cards.length === 0 ? (
            <div className="signal-item">
              <span className="signal-event">{t.reference.signalsPage.empty}</span>
            </div>
          ) : (
            cards.map((card) => {
              const selected = card.id === selectedKey
              const selectedNoteIsKnown = selected
                && note.state !== 'loading'
                && note.state !== 'read-error'
              const hasSelectedNote = selectedNoteIsKnown && note.value.trim().length > 0
              const badge = card.locked
                ? t.reference.signalsPage.paidAccessRequired
                : hasSelectedNote
                  ? t.reference.statuses.noteAdded
                  : t.reference.statuses.documentedSignal
              return (
                <button
                  type="button"
                  ref={(node) => {
                    if (node) rowRefs.current.set(card.id, node)
                    else rowRefs.current.delete(card.id)
                  }}
                  className={`signal-item${selected ? ' is-selected' : ''}${card.locked ? ' is-locked' : ''}`}
                  aria-pressed={selected}
                  onClick={() => {
                    if (card.locked) {
                      lastSelection.current = card.id
                      navigate(location.pathname + location.search, {
                        replace: true,
                        state: selectionState(card.id, appliedFeedGeneration.current),
                        flushSync: true,
                      })
                      navigate('/app/billing', { state: { lockedSignalKey: card.id } })
                    } else {
                      lastSelection.current = card.id
                      navigate(`/app/signals/${encodeURIComponent(card.id)}`, {
                        state: selectionState(card.id, appliedFeedGeneration.current),
                      })
                    }
                  }}
                  key={card.id}
                >
                  <span className="signal-item-head">
                    <strong>
                      {card.locked
                        ? t.reference.missingValue
                        : (
                            <>
                              <span>{t.reference.fields.signalAwardee}</span> :{' '}
                              <span>{card.awardedCompanyName ?? t.reference.missingValue}</span>
                            </>
                          )}
                    </strong>
                    <span>{badge}</span>
                  </span>
                  <span className="signal-event">
                    {card.eventTitle ?? t.reference.signalsPage.presentationNotPublished}
                  </span>
                  {!card.locked ? (
                    <span className="signal-meta">
                      {t.reference.fields.signalBuyer} : {card.buyerName ?? t.reference.missingValue}
                    </span>
                  ) : null}
                  <span className="signal-meta">{displayAmount(card)} · {displayLocation(card)}</span>
                  <span className="signal-fit">
                    <span>{displayDateLabel(card)}</span> : {displayDate(card.eventDate)}
                  </span>
                  {!card.locked && card.fitReason ? (
                    <span className="signal-match">{card.fitReason}</span>
                  ) : null}
                  {card.locked ? (
                    <span className="signal-reason signal-lock-note">
                      <LockKeyhole aria-hidden="true" />
                      {t.reference.signalsPage.lockedReason}
                    </span>
                  ) : null}
                </button>
              )
            })
          )}
        </div>

        {feed.loading && feed.data ? (
          <p className="signal-limit" role="status">{t.reference.messages.refreshing}</p>
        ) : feed.error && feed.data ? (
          <p className="signal-limit" role="alert">{t.reference.messages.refreshFailed}</p>
        ) : null}

        {feed.data?.page.scan_truncated ? (
          <p className="signal-limit" role="status">{t.feed.truncatedNote}</p>
        ) : null}

        {paginationError ? (
          <div role="alert">
            <p>{t.reference.messages.loadError}</p>
            <button type="button" className="text-link" onClick={() => void loadMore()}>
              {t.reference.signalsPage.retryMore}
            </button>
          </div>
        ) : null}
        {feed.data?.page.has_more && !paginationError ? (
          <button
            type="button"
            className="text-link"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore ? t.reference.loading : t.reference.signalsPage.loadMore}
          </button>
        ) : null}
      </aside>

      <section
        className="detail-panel"
        id="signal-detail"
        aria-labelledby="detail-title"
        tabIndex={-1}
      >
        {selectedKey ? (
          <>
            {isMobile ? (
              <button
                type="button"
                className="source-link signal-mobile-back"
                onClick={() => {
                  lastSelection.current = selectedKey
                  const origin = readSelectionState(location.state)
                  if (origin?.key === selectedKey) navigate(-1)
                  else {
                    navigate('/app/signals', {
                      replace: true,
                      state: selectionState(selectedKey, appliedFeedGeneration.current),
                    })
                  }
                }}
              >
                {t.workspace.backToList}
              </button>
            ) : null}
            <ReferenceSignalDetail
              detail={detailView}
              loading={visibleDetail.loading}
              error={visibleDetail.error}
              errorTitle={deepLookup.key === signalKey && deepLookup.truncated
                ? t.feed.truncatedNote
                : selectionLookupError
                  ? t.reference.messages.loadError
                  : undefined}
              onRetry={() => {
                if (!selectedItem && paginationError && feed.data?.page.has_more) void loadMore()
                else if (!selectedItem && (deepLookup.error || deepLookup.truncated)) {
                  deepLookupStarted.current = null
                  setDeepLookup({
                    key: null,
                    item: null,
                    loading: false,
                    exhausted: false,
                    truncated: false,
                    error: null,
                  })
                  setDeepLookupAttempt((current) => current + 1)
                } else if (!selectedItem) {
                  deepLookupGeneration.current += 1
                  deepLookupStarted.current = null
                  setDeepLookup({
                    key: null,
                    item: null,
                    loading: false,
                    exhausted: false,
                    truncated: false,
                    error: null,
                  })
                  void loadFeed()
                }
                else setDetailAttempt((current) => current + 1)
              }}
              note={note.value}
              noteState={note.state}
              noteError={note.error}
              onNoteChange={note.change}
              onNoteBlur={note.flush}
              onRetryNote={note.retry}
              announceLoading={!(feed.loading && feed.data)}
              announceError={Boolean(selectedItem) || (!feed.error && !paginationError)}
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

function selectionState(key: string, feedGeneration: number): SignalSelectionNavigationState {
  return {
    signalSelection: {
      kind: 'feed',
      key,
      feedGeneration,
      query: { freshness: 'new', targetIcpId: '' },
    },
  }
}

function readSelectionState(value: unknown): SignalSelectionNavigationState['signalSelection'] | null {
  if (typeof value !== 'object' || value === null || !('signalSelection' in value)) return null
  const selection = (value as { signalSelection?: unknown }).signalSelection
  if (typeof selection !== 'object' || selection === null) return null
  const candidate = selection as Partial<SignalSelectionNavigationState['signalSelection']>
  if (candidate.kind !== 'feed' || typeof candidate.key !== 'string' || candidate.key.length === 0) {
    return null
  }
  if (typeof candidate.feedGeneration !== 'number') return null
  if (
    typeof candidate.query !== 'object'
    || candidate.query === null
    || candidate.query.freshness !== 'new'
    || candidate.query.targetIcpId !== ''
  ) {
    return null
  }
  return candidate as SignalSelectionNavigationState['signalSelection']
}
