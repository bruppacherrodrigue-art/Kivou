import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useI18n, interpolate, plural } from '../i18n'
import { Button, ButtonLink } from '../components/Button'
import { Callout, Card, EmptyState, Skeleton } from '../components/Surfaces'
import { NoSignalIllustration } from '../assets/Illustrations'
import { SignalListRow } from '../signals/SignalListRow'
import { DiscoveryPanel } from '../signals/DiscoveryPanel'
import { SignalDetailPanel } from './SignalDetail'
import { ActivationProgress } from '../activation/ActivationProgress'
import { ActivationSuccess } from '../activation/ActivationSuccess'
import { signals, billing, icps as icpsApi } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import type {
  BillingStatus,
  FeedItem,
  FeedPage,
  Freshness,
  SignalDetail as SignalDetailPayload,
  TargetIcp,
} from '../api/types'
import styles from './SignalsFeed.module.css'

/* Le feed client.
 *
 * `GET /signals` est la SEULE source. Le frontend ne rejoue ni le classement,
 * ni la fraîcheur, ni la décision de verrouillage : il rend ce que l'API dit.
 * Le tri est déjà fait côté serveur — événement, puis date, puis clé stable —
 * et le refaire ici produirait un ordre différent de celui que la pagination
 * suppose.
 */

const PAGE_SIZE = 20

/** Ce que l'onboarding transmet en rejoignant le feed. */
export interface ActivationNavigationState {
  activationCompleted?: boolean
}

interface SignalSelectionNavigationState {
  signalSelection: {
    kind: 'feed'
    key: string
    feedGeneration: number
    query: { freshness: Freshness; targetIcpId: string }
  }
}

export function SignalsFeed() {
  const { t } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const { signalKey } = useParams()
  const navigateRef = useRef(navigate)
  const signalSelection = selectionFromLocation(location.state, signalKey)
  const signalSelectionRef = useRef(signalSelection)

  navigateRef.current = navigate
  signalSelectionRef.current = signalSelection

  /* Le moment d'activation, consommé UNE fois.
   *
   * Il est lu au premier rendu, puis l'entrée d'historique est réécrite sans
   * lui. Se contenter de lire `location.state` laisserait le bandeau
   * réapparaître à chaque rechargement de la page : l'état d'historique du
   * navigateur survit au rechargement, et « vous venez de terminer votre
   * ciblage » deviendrait un message permanent — donc faux.
   */
  const [activationMoment] = useState(
    () => (location.state as ActivationNavigationState | null)?.activationCompleted === true,
  )

  useEffect(() => {
    if (!activationMoment) return
    navigate(location.pathname + location.search, { replace: true, state: null })
    // Une seule fois, au montage : la dépendance est le moment, pas l'URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [page, setPage] = useState<FeedPage | null>(null)
  const [items, setItems] = useState<FeedItem[]>([])
  const [status, setStatus] = useState<BillingStatus | null>(null)
  const [profiles, setProfiles] = useState<TargetIcp[] | null>(null)
  const [freshness, setFreshness] = useState<Freshness>('new')
  const [targetIcpId, setTargetIcpId] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [paginationError, setPaginationError] = useState<unknown>(null)
  const feedGeneration = useRef(signalSelection?.feedGeneration ?? 0)
  const appliedFeedGeneration = useRef(signalSelection?.feedGeneration ?? 0)
  const feedQuery = useRef({ freshness, targetIcpId })
  const detailGeneration = useRef(0)
  const resolvedSignalKey = useRef<string | null>(null)
  const detailPanelRef = useRef<HTMLElement | null>(null)
  const rowControls = useRef(new Map<string, HTMLAnchorElement | HTMLButtonElement>())
  const rowControlRefs = useRef(
    new Map<
      string,
      (element: HTMLAnchorElement | HTMLButtonElement | null) => void
    >(),
  )
  const restoreFocusKey = useRef<string | null>(null)
  const previousSignalKey = useRef(signalKey)
  const suppressRouteFocusRestore = useRef(false)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [detailState, setDetailState] = useState<{
    key: string | null
    data: SignalDetailPayload | null
    loading: boolean
    error: unknown | null
  }>({ key: null, data: null, loading: false, error: null })

  feedQuery.current = { freshness, targetIcpId }

  /* `GET /signals` n'est pas seulement une lecture : c'est l'appel qui ATTRIBUE
   * les déblocages Découverte (`_grant_discovery`). Sur la première arrivée
   * après l'onboarding, lire `GET /billing/status` en parallèle peut donc
   * répondre AVANT que les déblocages soient commités, et annoncer zéro signal
   * accessible à un client qui vient d'en recevoir trois.
   *
   * Pour ce moment-là, et pour lui seul, le statut est relu APRÈS le feed. Le
   * reste du temps les deux appels partent ensemble : rien ne les ordonne. */
  const postFeedBilling = useRef(activationMoment)

  const load = useCallback(
    async (nextFreshness: Freshness, nextIcp: string) => {
      const generation = ++feedGeneration.current
      const query = { freshness: nextFreshness, targetIcpId: nextIcp }
      const isCurrentQuery = () =>
        generation === feedGeneration.current &&
        feedQuery.current.freshness === query.freshness &&
        feedQuery.current.targetIcpId === query.targetIcpId
      setLoading(true)
      setLoadingMore(false)
      setError(null)
      setPaginationError(null)
      try {
        const result = await signals.feed({
          freshness: nextFreshness,
          target_icp_id: nextIcp || null,
          limit: PAGE_SIZE,
          offset: 0,
        })
        if (!isCurrentQuery()) return
        appliedFeedGeneration.current = generation

        const selectedFromFeed = signalSelectionRef.current
        if (selectedFromFeed) {
          const isLaterFeedGeneration = generation > selectedFromFeed.feedGeneration
          const stillPresent = result.items.some(
            (item) => item.signal_id === selectedFromFeed.key,
          )

          if (isLaterFeedGeneration && !stillPresent) {
            restoreFocusKey.current = null
            suppressRouteFocusRestore.current = true
            // La navigation est appliquée par React Router dans un commit
            // distinct. Marquer encore cette clé comme résolue empêche l'effet
            // détail de relancer un GET pendant le bref rendu de l'ancienne URL;
            // le rendu de la route de base remet ensuite la garde à zéro.
            resolvedSignalKey.current = selectedFromFeed.key
            detailGeneration.current += 1
            setDetailState({ key: null, data: null, loading: false, error: null })
            navigateRef.current('/app/signals', { replace: true })
          }
        }

        setPage(result)
        setItems(result.items)

        if (postFeedBilling.current) {
          try {
            const nextStatus = await billing.status()
            if (!isCurrentQuery()) return
            postFeedBilling.current = false
            setStatus(nextStatus)
          } catch {
            if (!isCurrentQuery()) return
            postFeedBilling.current = false
            setStatus(null)
          }
        }
      } catch (caught) {
        if (!isCurrentQuery()) return
        setError(caught)
        setPage(null)
        setItems([])
      } finally {
        if (isCurrentQuery()) setLoading(false)
      }
    },
    [],
  )

  useEffect(
    () => () => {
      feedGeneration.current += 1
      detailGeneration.current += 1
    },
    [],
  )

  useEffect(() => {
    void load(freshness, targetIcpId)
  }, [load, freshness, targetIcpId])

  useEffect(() => {
    // Le statut de facturation porte le compteur Découverte et la limite de
    // profils ; les profils portent l'état d'activation. Un échec sur l'un ou
    // l'autre ne doit pas empêcher le feed de s'afficher.
    if (!activationMoment) {
      billing
        .status()
        .then(setStatus)
        .catch(() => setStatus(null))
    }
    icpsApi
      .list()
      .then(setProfiles)
      .catch(() => setProfiles(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!signalKey) {
      detailGeneration.current += 1
      resolvedSignalKey.current = null
      setDetailState({ key: null, data: null, loading: false, error: null })
      return
    }

    if (loading) {
      if (resolvedSignalKey.current !== signalKey) {
        detailGeneration.current += 1
        resolvedSignalKey.current = null
        setDetailState({ key: signalKey, data: null, loading: true, error: null })
      }
      return
    }

    const selected = items.find((item) => item.signal_id === signalKey)
    if (selected?.locked) {
      detailGeneration.current += 1
      resolvedSignalKey.current = signalKey
      setDetailState({ key: signalKey, data: null, loading: false, error: null })
      return
    }
    if (resolvedSignalKey.current === signalKey) return

    const generation = ++detailGeneration.current
    resolvedSignalKey.current = signalKey
    setDetailState({ key: signalKey, data: null, loading: true, error: null })
    signals.detail(signalKey).then(
      (data) => {
        if (generation === detailGeneration.current) {
          setDetailState({ key: signalKey, data, loading: false, error: null })
        }
      },
      (caught) => {
        if (generation === detailGeneration.current) {
          setDetailState({ key: signalKey, data: null, loading: false, error: caught })
        }
      },
    )
  }, [detailAttempt, items, loading, signalKey])

  const activeSelectionKey = signalKey

  useEffect(() => {
    if (activeSelectionKey) detailPanelRef.current?.focus()
  }, [activeSelectionKey])

  useEffect(() => {
    const previous = previousSignalKey.current
    previousSignalKey.current = signalKey
    if (signalKey || !previous) return
    if (suppressRouteFocusRestore.current) {
      suppressRouteFocusRestore.current = false
      return
    }
    if (!restoreFocusKey.current) restoreFocusKey.current = previous
  }, [signalKey])

  useEffect(() => {
    if (activeSelectionKey || !restoreFocusKey.current) return
    const control = rowControls.current.get(restoreFocusKey.current)
    if (!control) return
    restoreFocusKey.current = null
    control.focus()
  }, [activeSelectionKey, items])

  async function loadMore() {
    if (!page?.page.has_more) return
    const generation = feedGeneration.current
    const query = { freshness, targetIcpId }
    const isCurrentQuery = () =>
      generation === feedGeneration.current &&
      feedQuery.current.freshness === query.freshness &&
      feedQuery.current.targetIcpId === query.targetIcpId
    setLoadingMore(true)
    setPaginationError(null)
    try {
      const next = await signals.feed({
        freshness: query.freshness,
        target_icp_id: query.targetIcpId || null,
        limit: PAGE_SIZE,
        offset: page.page.offset + page.page.limit,
      })
      if (!isCurrentQuery()) return
      setPage(next)
      // La déduplication porte sur `signal_id` : deux pages qui se recouvrent
      // — parce que la fraîcheur a été réévaluée entre deux appels — ne doivent
      // pas produire deux cartes du même signal.
      setItems((current) => {
        const seen = new Set(current.map((item) => item.signal_id))
        return [...current, ...next.items.filter((item) => !seen.has(item.signal_id))]
      })
    } catch (caught) {
      if (!isCurrentQuery()) return
      // Une page suivante ratée ne transforme pas les signaux déjà lus en
      // erreur globale. Ils restent utilisables et le réessai reste local.
      setPaginationError(caught)
    } finally {
      if (isCurrentQuery()) setLoadingMore(false)
    }
  }

  const activeProfiles = profiles?.filter((profile) => profile.status === 'active') ?? []
  const hasNoUsableProfile = profiles !== null && activeProfiles.length === 0
  const selectedItem = activeSelectionKey
    ? items.find((item) => item.signal_id === activeSelectionKey) ?? null
    : null
  const lockedPreview = selectedItem?.locked ? selectedItem : null
  const visibleDetailState =
    detailState.key === (signalKey ?? null)
      ? detailState
      : { key: signalKey ?? null, data: null, loading: Boolean(signalKey), error: null }

  function retryDetail() {
    resolvedSignalKey.current = null
    setDetailAttempt((current) => current + 1)
  }

  function rowControlRef(key: string) {
    const existing = rowControlRefs.current.get(key)
    if (existing) return existing
    const register = (control: HTMLAnchorElement | HTMLButtonElement | null) => {
      if (control) rowControls.current.set(key, control)
      else rowControls.current.delete(key)
    }
    rowControlRefs.current.set(key, register)
    return register
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <p className={styles.lead}>{t.feed.lead}</p>
        <div className={styles.headerActions}>
          <ButtonLink to="/app/icps" variant="secondary">
            {t.feed.configureIcp}
          </ButtonLink>
        </div>
      </header>

      {/* Le moment ponctuel d'abord, l'explication durable ensuite : le
          bandeau d'activation dit que le ciblage est prêt, le panneau
          Découverte explique le plan. Les intervertir ferait ouvrir la
          première réussite du client par un rappel de ce qui reste
          verrouillé. */}
      {activationMoment && status ? (
        <>
          <ActivationProgress current="signals" />
          <ActivationSuccess status={status} items={items} />
        </>
      ) : null}

      {!hasNoUsableProfile ? (
        <>
          <FeedFilters
            freshness={freshness}
            onFreshness={setFreshness}
            profiles={activeProfiles}
            targetIcpId={targetIcpId}
            onProfile={setTargetIcpId}
            disabled={loading}
          />
        </>
      ) : null}

      <div className={styles.workspace} data-testid="signal-workspace">
        <div className={`${styles.master} ${activeSelectionKey ? styles.masterHidden : ''}`}>
          {hasNoUsableProfile ? (
            <Card padding="none">
              <EmptyState
                illustration={<NoSignalIllustration />}
                title={t.feed.noIcpTitle}
                body={t.feed.noIcpBody}
                action={<ButtonLink to="/app/icps">{t.feed.noIcpAction}</ButtonLink>}
              />
            </Card>
          ) : loading ? (
            <FeedSkeleton />
          ) : error ? (
            <FeedError error={error} onRetry={() => void load(freshness, targetIcpId)} />
          ) : items.length === 0 ? (
            <Card padding="none">
              <EmptyState
                illustration={<NoSignalIllustration />}
                title={t.feed.emptyTitle}
                body={t.feed.emptyBody}
                action={
                  freshness !== 'all' ? (
                    <Button variant="secondary" onClick={() => setFreshness('all')}>
                      {t.feed.emptyWiden}
                    </Button>
                  ) : (
                    <ButtonLink to="/app/icps" variant="secondary">
                      {t.feed.configureIcp}
                    </ButtonLink>
                  )
                }
              />
            </Card>
          ) : (
            <>
              <p className={styles.count} role="status">
                {interpolate(plural(items.length, t.feed.countOne, t.feed.countOther), {
                  count: items.length,
                })}
              </p>

              <ul className={styles.list} aria-label={t.feed.aria.list}>
                {items.map((item) => (
                  <li key={item.signal_id}>
                    <SignalListRow
                      item={item}
                      selected={item.signal_id === activeSelectionKey}
                      registerControl={rowControlRef(item.signal_id)}
                      selectionState={selectionState(
                        item.signal_id,
                        appliedFeedGeneration.current,
                        feedQuery.current,
                      )}
                      onSelectLocked={(locked) => {
                        navigate(`/app/signals/${encodeURIComponent(locked.signal_id)}`, {
                          state: selectionState(
                            locked.signal_id,
                            appliedFeedGeneration.current,
                            feedQuery.current,
                          ),
                        })
                      }}
                    />
                  </li>
                ))}
              </ul>

              {paginationError ? (
                <PaginationError error={paginationError} onRetry={() => void loadMore()} />
              ) : null}

              {/* Le dépassement de la fenêtre de lecture est ANNONCÉ par
                  l'API, pas deviné : le taire ferait croire à une liste
                  exhaustive. */}
              {page?.page.scan_truncated ? (
                <Callout tone="info">{t.feed.truncatedNote}</Callout>
              ) : null}

              {page?.page.has_more ? (
                <div className={styles.more}>
                  <Button variant="secondary" loading={loadingMore} onClick={() => void loadMore()}>
                    {t.feed.loadMore}
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className={`${styles.detail} ${activeSelectionKey ? '' : styles.detailHidden}`}>
          <SignalDetailPanel
            detail={visibleDetailState.data}
            loading={visibleDetailState.loading}
            error={visibleDetailState.error}
            embedded
            lockedPreview={lockedPreview}
            lockedPreviewHeadingLevel={signalKey ? 1 : 2}
            panelRef={detailPanelRef}
            onRetry={retryDetail}
            onBackToList={() => {
              restoreFocusKey.current = activeSelectionKey ?? null
              if (signalSelection) navigate(-1)
              else navigate('/app/signals')
            }}
          />
        </div>
      </div>

      {/* L'occasion précède l'explication du plan. Le panneau reste exact et
          accessible, mais ne prend plus la première place lorsque le serveur
          a déjà livré des signaux à examiner. */}
      {status ? <DiscoveryPanel status={status} /> : null}
    </div>
  )
}

function selectionState(
  key: string,
  feedGeneration: number,
  query: { freshness: Freshness; targetIcpId: string },
): SignalSelectionNavigationState {
  return { signalSelection: { kind: 'feed', key, feedGeneration, query: { ...query } } }
}

function selectionFromLocation(state: unknown, signalKey: string | undefined) {
  if (!state || typeof state !== 'object' || !signalKey) return null
  const selection = (state as Partial<SignalSelectionNavigationState>).signalSelection
  if (
    selection?.kind !== 'feed' ||
    selection.key !== signalKey ||
    !Number.isInteger(selection.feedGeneration) ||
    selection.feedGeneration < 0 ||
    typeof selection.query?.targetIcpId !== 'string' ||
    !['new', 'recent_or_aging', 'all'].includes(selection.query?.freshness)
  ) {
    return null
  }
  return selection
}

function FeedFilters({
  freshness,
  onFreshness,
  profiles,
  targetIcpId,
  onProfile,
  disabled,
}: {
  freshness: Freshness
  onFreshness: (value: Freshness) => void
  profiles: TargetIcp[]
  targetIcpId: string
  onProfile: (value: string) => void
  disabled: boolean
}) {
  const { t } = useI18n()
  const options: { value: Freshness; label: string }[] = [
    { value: 'new', label: t.feed.freshnessNew },
    { value: 'recent_or_aging', label: t.feed.freshnessRecentOrAging },
    { value: 'all', label: t.feed.freshnessAll },
  ]

  return (
    <div className={styles.filters}>
      <fieldset className={styles.filterGroup} disabled={disabled}>
        <legend className={styles.filterLegend}>{t.feed.freshness}</legend>
        <div className={styles.chips}>
          {options.map((option) => (
            <label
              key={option.value}
              className={`${styles.chip} ${freshness === option.value ? styles.chipActive : ''}`}
            >
              <input
                type="radio"
                name="kivou-freshness"
                className={styles.chipInput}
                checked={freshness === option.value}
                onChange={() => onFreshness(option.value)}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      {profiles.length > 1 ? (
        <div className={styles.filterGroup}>
          <label className={styles.filterLegend} htmlFor="kivou-icp-filter">
            {t.feed.activeProfile}
          </label>
          <select
            id="kivou-icp-filter"
            className={styles.select}
            value={targetIcpId}
            disabled={disabled}
            onChange={(event) => onProfile(event.target.value)}
          >
            <option value="">{t.feed.allProfiles}</option>
            {profiles.map((profile) => (
              <option key={profile.target_icp_id} value={profile.target_icp_id}>
                {profile.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  )
}

/** Un squelette qui reprend la structure de la carte, pas un rond qui tourne. */
function FeedSkeleton() {
  return (
    <ul className={styles.list} aria-hidden="true">
      {[0, 1, 2].map((index) => (
        <li key={index}>
          <Card padding="md">
            <div className={styles.skeletonRow}>
              <Skeleton width="2.75rem" height="2.75rem" radius="var(--kivou-radius-sm)" />
              <div className={styles.skeletonBody}>
                <Skeleton width="30%" height="0.875rem" />
                <Skeleton width="75%" height="1.25rem" />
                <Skeleton width="55%" height="0.875rem" />
              </div>
            </div>
          </Card>
        </li>
      ))}
    </ul>
  )
}

function FeedError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useI18n()
  const copy = describeError(error, t)
  return (
    <Callout
      tone="danger"
      title={copy.title ?? t.feed.errorTitle}
      live
      action={
        <Button variant="secondary" onClick={onRetry}>
          {t.common.retry}
        </Button>
      }
    >
      {copy.body ?? t.feed.errorBody}
    </Callout>
  )
}

function PaginationError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useI18n()
  const copy = describeError(error, t)
  return (
    <Callout
      tone="danger"
      title={t.feed.moreErrorTitle}
      live
      action={
        <Button variant="secondary" onClick={onRetry}>
          {t.feed.retryMore}
        </Button>
      }
    >
      {copy.body ?? t.feed.moreErrorBody}
    </Callout>
  )
}
