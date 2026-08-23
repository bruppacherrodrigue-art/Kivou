import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useI18n, interpolate, plural } from '../i18n'
import { Button, ButtonLink } from '../components/Button'
import { Callout, Card, EmptyState, SectionHeading, Skeleton } from '../components/Surfaces'
import { NoSignalIllustration } from '../assets/Illustrations'
import { SignalCard } from '../signals/SignalCard'
import { DiscoveryPanel } from '../signals/DiscoveryPanel'
import { ActivationProgress } from '../activation/ActivationProgress'
import { ActivationSuccess } from '../activation/ActivationSuccess'
import { signals, billing, icps as icpsApi } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import type { BillingStatus, FeedItem, FeedPage, Freshness, TargetIcp } from '../api/types'
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

export function SignalsFeed() {
  const { t } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()

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
      setLoading(true)
      setError(null)
      setPaginationError(null)
      try {
        const result = await signals.feed({
          freshness: nextFreshness,
          target_icp_id: nextIcp || null,
          limit: PAGE_SIZE,
          offset: 0,
        })
        setPage(result)
        setItems(result.items)

        if (postFeedBilling.current) {
          postFeedBilling.current = false
          try {
            setStatus(await billing.status())
          } catch {
            setStatus(null)
          }
        }
      } catch (caught) {
        setError(caught)
        setPage(null)
        setItems([])
      } finally {
        setLoading(false)
      }
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

  async function loadMore() {
    if (!page?.page.has_more) return
    setLoadingMore(true)
    setPaginationError(null)
    try {
      const next = await signals.feed({
        freshness,
        target_icp_id: targetIcpId || null,
        limit: PAGE_SIZE,
        offset: page.page.offset + page.page.limit,
      })
      setPage(next)
      // La déduplication porte sur `signal_id` : deux pages qui se recouvrent
      // — parce que la fraîcheur a été réévaluée entre deux appels — ne doivent
      // pas produire deux cartes du même signal.
      setItems((current) => {
        const seen = new Set(current.map((item) => item.signal_id))
        return [...current, ...next.items.filter((item) => !seen.has(item.signal_id))]
      })
    } catch (caught) {
      // Une page suivante ratée ne transforme pas les signaux déjà lus en
      // erreur globale. Ils restent utilisables et le réessai reste local.
      setPaginationError(caught)
    } finally {
      setLoadingMore(false)
    }
  }

  const activeProfiles = profiles?.filter((profile) => profile.status === 'active') ?? []
  const hasNoUsableProfile = profiles !== null && activeProfiles.length === 0

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SectionHeading title={t.feed.title} lead={t.feed.lead} level={1} />
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

      {hasNoUsableProfile ? (
        <Card padding="none">
          <EmptyState
            illustration={<NoSignalIllustration />}
            title={t.feed.noIcpTitle}
            body={t.feed.noIcpBody}
            action={<ButtonLink to="/app/icps">{t.feed.noIcpAction}</ButtonLink>}
          />
        </Card>
      ) : (
        <>
          <FeedFilters
            freshness={freshness}
            onFreshness={setFreshness}
            profiles={activeProfiles}
            targetIcpId={targetIcpId}
            onProfile={setTargetIcpId}
            disabled={loading}
          />

          {loading ? (
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
                    <SignalCard item={item} />
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
        </>
      )}

      {/* L'occasion précède l'explication du plan. Le panneau reste exact et
          accessible, mais ne prend plus la première place lorsque le serveur
          a déjà livré des signaux à examiner. */}
      {status ? <DiscoveryPanel status={status} /> : null}
    </div>
  )
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
