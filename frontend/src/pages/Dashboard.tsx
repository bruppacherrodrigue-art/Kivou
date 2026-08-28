import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useCurrentUser } from '../auth/SessionProvider'
import { Button, ButtonLink } from '../components/Button'
import { Badge, Callout, Card, DataList, DataRow, EmptyState, SectionHeading, Skeleton } from '../components/Surfaces'
import { useI18n, interpolate, plural } from '../i18n'
import { billing, icps, notifications, signals } from '../api/endpoints'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { SignalListRow } from '../signals/SignalListRow'
import type {
  BillingAction,
  BillingStatus,
  FeedPage,
  NotificationPreference,
  TargetIcp,
  UnlockedFeedItem,
} from '../api/types'
import styles from './Dashboard.module.css'

interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

function emptyResource<T>(): ResourceState<T> {
  return { data: null, loading: true, error: null }
}

type CompanyState =
  | { status: 'idle'; signal: null }
  | { status: 'loading'; signal: UnlockedFeedItem }
  | { status: 'available'; signal: UnlockedFeedItem; companyKey: string }
  | { status: 'unavailable'; signal: UnlockedFeedItem }
  | { status: 'error'; signal: UnlockedFeedItem; error: unknown }

export function Dashboard() {
  const me = useCurrentUser()

  if (me.onboarding_status !== 'ready_for_signals') {
    return <Navigate to="/onboarding" replace />
  }

  return <ReadyDashboard />
}

function ReadyDashboard() {
  const { t, date } = useI18n()
  const navigate = useNavigate()

  const [feedState, setFeedState] = useState<ResourceState<FeedPage>>(emptyResource)
  const [billingState, setBillingState] =
    useState<ResourceState<BillingStatus>>(emptyResource)
  const [icpState, setIcpState] = useState<ResourceState<TargetIcp[]>>(emptyResource)
  const [notificationState, setNotificationState] =
    useState<ResourceState<NotificationPreference>>(emptyResource)
  const [companyState, setCompanyState] = useState<CompanyState>({
    status: 'idle',
    signal: null,
  })

  const mountedRef = useRef(false)
  const feedGenerationRef = useRef(0)
  const billingGenerationRef = useRef(0)
  const icpGenerationRef = useRef(0)
  const notificationGenerationRef = useRef(0)
  const companyGenerationRef = useRef(0)

  const loadBilling = useCallback(async () => {
    const generation = ++billingGenerationRef.current
    setBillingState((current) => ({ ...current, loading: true, error: null }))
    try {
      const data = await billing.status()
      if (mountedRef.current && generation === billingGenerationRef.current) {
        setBillingState({ data, loading: false, error: null })
      }
    } catch (error) {
      if (mountedRef.current && generation === billingGenerationRef.current) {
        setBillingState((current) => ({ ...current, loading: false, error }))
      }
    }
  }, [])

  const loadCompany = useCallback(async (signal: UnlockedFeedItem) => {
    const generation = ++companyGenerationRef.current
    setCompanyState({ status: 'loading', signal })
    try {
      const detail = await signals.detail(signal.signal_id)
      if (!mountedRef.current || generation !== companyGenerationRef.current) return
      if (detail.locked) {
        setCompanyState({ status: 'idle', signal: null })
      } else if (detail.company_key) {
        setCompanyState({ status: 'available', signal, companyKey: detail.company_key })
      } else {
        setCompanyState({ status: 'unavailable', signal })
      }
    } catch (error) {
      if (mountedRef.current && generation === companyGenerationRef.current) {
        setCompanyState({ status: 'error', signal, error })
      }
    }
  }, [])

  const loadFeed = useCallback(async () => {
    const generation = ++feedGenerationRef.current
    companyGenerationRef.current += 1
    setCompanyState({ status: 'idle', signal: null })
    setFeedState((current) => ({ ...current, loading: true, error: null }))
    try {
      const data = await signals.feed({ limit: 3, offset: 0 })
      if (!mountedRef.current || generation !== feedGenerationRef.current) return
      setFeedState({ data, loading: false, error: null })
      const firstUnlocked = data.items.find(
        (item): item is UnlockedFeedItem => item.locked === false,
      )
      if (firstUnlocked) void loadCompany(firstUnlocked)
      void loadBilling()
    } catch (error) {
      if (mountedRef.current && generation === feedGenerationRef.current) {
        setFeedState((current) => ({ ...current, loading: false, error }))
      }
    }
  }, [loadBilling, loadCompany])

  const loadIcps = useCallback(async () => {
    const generation = ++icpGenerationRef.current
    setIcpState((current) => ({ ...current, loading: true, error: null }))
    try {
      const data = await icps.list()
      if (mountedRef.current && generation === icpGenerationRef.current) {
        setIcpState({ data, loading: false, error: null })
      }
    } catch (error) {
      if (mountedRef.current && generation === icpGenerationRef.current) {
        setIcpState((current) => ({ ...current, loading: false, error }))
      }
    }
  }, [])

  const loadNotifications = useCallback(async () => {
    const generation = ++notificationGenerationRef.current
    setNotificationState((current) => ({ ...current, loading: true, error: null }))
    try {
      const data = await notifications.read()
      if (mountedRef.current && generation === notificationGenerationRef.current) {
        setNotificationState({ data, loading: false, error: null })
      }
    } catch (error) {
      if (mountedRef.current && generation === notificationGenerationRef.current) {
        setNotificationState((current) => ({ ...current, loading: false, error }))
      }
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void loadFeed()
    void loadBilling()
    void loadIcps()
    void loadNotifications()

    return () => {
      mountedRef.current = false
      feedGenerationRef.current += 1
      billingGenerationRef.current += 1
      icpGenerationRef.current += 1
      notificationGenerationRef.current += 1
      companyGenerationRef.current += 1
    }
  }, [loadBilling, loadFeed, loadIcps, loadNotifications])

  const feedItems = feedState.data?.items.slice(0, 3) ?? []
  const hasUnlockedSignal = feedItems.some((item) => item.locked === false)
  const activeIcps = icpState.data?.filter((profile) => profile.status === 'active') ?? []
  const overLimitIcps = new Set(billingState.data?.target_icps_over_limit ?? [])
  const billingStatus = billingState.data
  const billingActionLabels = {
    choose_plan: t.dashboard.choosePlan,
    manage_subscription: t.dashboard.manageSubscription,
    recover_payment: t.dashboard.recoverPayment,
    contact_support: t.dashboard.contactSupport,
  } satisfies Record<BillingAction, string>
  const notificationPreference = notificationState.data
  const alertCadence = billingStatus?.entitlements.alert_cadence ?? null
  const cadenceCopy = alertCadence ? t.dashboard.cadence[alertCadence] : null
  let alertsSummary: string | null = null

  if (notificationPreference && alertCadence && cadenceCopy) {
    const activation = notificationPreference.email_enabled
      ? t.dashboard.alertsEnabled
      : t.dashboard.alertsDisabled
    const capability =
      alertCadence === 'none'
        ? t.dashboard.noAlertCadence
        : notificationPreference.email_enabled
          ? interpolate(t.dashboard.activeCadence, { cadence: cadenceCopy })
          : interpolate(t.dashboard.availableCadenceForPlan, { cadence: cadenceCopy })
    alertsSummary = `${activation} · ${capability}`
  } else if (notificationPreference) {
    alertsSummary = notificationPreference.email_enabled
      ? t.dashboard.alertsEnabled
      : t.dashboard.alertsDisabled
  }

  const signalsRead = feedState.data
    ? interpolate(
        plural(
          feedState.data.total_returned,
          t.dashboard.signalReadOne,
          t.dashboard.signalReadOther,
        ),
        { count: feedState.data.total_returned },
      )
    : null
  const activeIcpSummary = icpState.data
    ? interpolate(
        plural(activeIcps.length, t.dashboard.activeIcpOne, t.dashboard.activeIcpOther),
        { count: activeIcps.length },
      )
    : null
  const planSummary = billingStatus ? t.billing.plans[billingStatus.plan_code] : null

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <SectionHeading
          level={2}
          eyebrow={t.dashboard.summaryEyebrow}
          title={t.dashboard.summaryTitle}
          lead={t.dashboard.lead}
        />
      </header>

      <ul className={styles.metrics} aria-label={t.dashboard.summaryLabel}>
        <Metric
          label={t.dashboard.signalsRead}
          value={signalsRead}
          loading={feedState.loading && !feedState.data}
          error={feedState.error}
          errorCopy={t.dashboard.opportunitiesError}
          loadingCopy={t.common.loading}
          retryLabel={t.dashboard.retryOpportunities}
          onRetry={() => void loadFeed()}
        />
        <Metric
          label={t.dashboard.activeTargeting}
          value={activeIcpSummary}
          loading={icpState.loading && !icpState.data}
          error={icpState.error}
          errorCopy={t.dashboard.icpsError}
          loadingCopy={t.common.loading}
          retryLabel={t.common.retry}
          onRetry={() => void loadIcps()}
        />
        <Metric
          label={t.dashboard.currentAccess}
          value={planSummary}
          loading={billingState.loading && !billingStatus}
          error={billingState.error}
          errorCopy={t.dashboard.billingError}
          loadingCopy={t.common.loading}
          retryLabel={t.dashboard.retryBilling}
          onRetry={() => void loadBilling()}
        />
        <Metric
          label={t.dashboard.alertState}
          value={alertsSummary}
          loading={notificationState.loading && !notificationPreference}
          error={notificationState.error}
          errorCopy={t.dashboard.alertsError}
          loadingCopy={t.common.loading}
          retryLabel={t.dashboard.retryAlerts}
          onRetry={() => void loadNotifications()}
        />
      </ul>

      <div className={styles.workingSurface}>
        <Card
          as="section"
          padding="none"
          className={styles.feedPane}
          ariaLabelledBy="dashboard-opportunities-title"
        >
          <div className={styles.paneHeader}>
            <SectionHeading
              id="dashboard-opportunities-title"
              title={t.dashboard.opportunities}
            />
            <ButtonLink to="/app/signals" variant="secondary">
              {t.dashboard.viewAllFeed}
            </ButtonLink>
          </div>
          {feedState.loading && !feedState.data ? (
            <div
              className={styles.loadingRows}
              role="status"
              aria-labelledby="dashboard-feed-loading"
            >
              <span id="dashboard-feed-loading" className="kivou-visually-hidden">
                {t.dashboard.opportunities} — {t.common.loading}
              </span>
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} width="100%" height="6.5rem" />
              ))}
            </div>
          ) : null}
          {feedItems.length > 0 ? (
            <ol className={styles.signalList} aria-label={t.dashboard.opportunities}>
              {feedItems.map((item) => {
                const selectionState = dashboardSelectionState(item.signal_id)
                return (
                  <li key={item.signal_id} className={styles.listItem}>
                    <SignalListRow
                      item={item}
                      selectionState={selectionState}
                      onSelectLocked={(locked) => {
                        navigate(`/app/signals/${encodeURIComponent(locked.signal_id)}`, {
                          state: dashboardSelectionState(locked.signal_id),
                        })
                      }}
                    />
                  </li>
                )
              })}
            </ol>
          ) : null}
          {feedState.data && feedItems.length === 0 ? (
            <EmptyState
              title={t.dashboard.noOpportunities}
              body={t.dashboard.noOpportunitiesBody}
              action={
                <ButtonLink to="/app/icps" variant="secondary">
                  {t.dashboard.adjustTargeting}
                </ButtonLink>
              }
            />
          ) : null}
        </Card>

        <Card
          as="aside"
          padding="lg"
          className={styles.contextPane}
          ariaLabelledBy="dashboard-company-title"
        >
          <SectionHeading
            id="dashboard-company-title"
            eyebrow={t.dashboard.contextPreview}
            title={t.dashboard.company}
          />
          {companyState.status === 'loading' ||
          (companyState.status === 'idle' && feedState.loading && !feedState.data) ? (
            <div
              className={styles.contextLoading}
              role="status"
              aria-labelledby="dashboard-company-loading"
            >
              <span id="dashboard-company-loading" className="kivou-visually-hidden">
                {t.dashboard.company} — {t.common.loading}
              </span>
              <Skeleton width="42%" height="1rem" />
              <Skeleton width="78%" height="1.5rem" />
              <Skeleton width="58%" height="2.5rem" />
            </div>
          ) : null}
          {companyState.status === 'available' ? (
            <div className={styles.contextState}>
              <p className={styles.supportingCopy}>{t.dashboard.companyAvailable}</p>
              <ButtonLink
                to={`/app/companies/${encodeURIComponent(companyState.companyKey)}`}
                variant="secondary"
              >
                {t.dashboard.companyAction}
              </ButtonLink>
            </div>
          ) : null}
          {companyState.status === 'unavailable' ? (
            <p className={styles.emptyTitle}>{t.dashboard.companyUnavailable}</p>
          ) : null}
          {companyState.status === 'error' ? (
            <Callout
              tone="danger"
              live
              title={t.dashboard.companyError}
              action={
                <Button variant="secondary" onClick={() => void loadCompany(companyState.signal)}>
                  {t.dashboard.retryCompany}
                </Button>
              }
            />
          ) : null}
          {companyState.status === 'idle' && !(feedState.loading && !feedState.data) ? (
            <p className={styles.supportingCopy}>
              {hasUnlockedSignal
                ? t.dashboard.noAccessibleCompany
                : t.dashboard.contextWithoutUnlocked}
            </p>
          ) : null}
        </Card>
      </div>

      <div className={styles.supportStrip}>
        <Card
          as="section"
          padding="lg"
          className={styles.icpSection}
          ariaLabelledBy="dashboard-icps-title"
        >
          <div className={styles.cardHeader}>
            <SectionHeading id="dashboard-icps-title" title={t.dashboard.icps} />
            <ButtonLink to="/app/icps" variant="secondary">
              {t.dashboard.manageIcps}
            </ButtonLink>
          </div>
          {icpState.loading && !icpState.data ? (
            <div className={styles.compactList} aria-label={t.common.loading}>
              <Skeleton width="58%" height="1.5rem" />
              <Skeleton width="76%" height="1rem" />
            </div>
          ) : null}
          {icpState.data && activeIcps.length === 0 ? (
            <div className={styles.emptyCompact}>
              <p className={styles.emptyTitle}>{t.dashboard.noActiveIcp}</p>
              <p className={styles.supportingCopy}>{t.dashboard.noActiveIcpBody}</p>
            </div>
          ) : null}
          {activeIcps.length > 0 ? (
            <ol className={styles.icpList} aria-label={t.dashboard.icps}>
              {activeIcps.map((profile) => (
                <li key={profile.target_icp_id} className={styles.listItem}>
                  <IcpSummary
                    profile={profile}
                    overLimit={overLimitIcps.has(profile.target_icp_id)}
                  />
                </li>
              ))}
            </ol>
          ) : null}
        </Card>

        <Card
          as="section"
          padding="lg"
          className={styles.sectionCard}
          ariaLabelledBy="dashboard-billing-title"
        >
          <SectionHeading id="dashboard-billing-title" title={t.dashboard.billing} />
          {billingState.loading && !billingStatus ? (
            <Skeleton width="40%" height="1.5rem" />
          ) : null}
          {billingStatus ? (
            <>
              <div className={styles.statusHead}>
                <Badge tone={billingStatus.plan_code === 'discovery' ? 'neutral' : 'positive'}>
                  {t.billing.status[
                    (billingStatus.subscription_status ??
                      'none') as keyof typeof t.billing.status
                  ] ?? t.billing.status.unknown}
                </Badge>
              </div>
              <DataList>
                <DataRow label={t.dashboard.discoveryUsed}>
                  {interpolate(
                    billingStatus.discovery.granted_signal_count === 1
                      ? t.dashboard.discoveryUsedOne
                      : t.dashboard.discoveryUsedOther,
                    { count: billingStatus.discovery.granted_signal_count },
                  )}
                </DataRow>
                <DataRow label={t.dashboard.discoveryRemaining}>
                  {interpolate(
                    billingStatus.discovery.remaining_slots === 1
                      ? t.dashboard.discoveryRemainingOne
                      : t.dashboard.discoveryRemainingOther,
                    { count: billingStatus.discovery.remaining_slots },
                  )}
                </DataRow>
                <DataRow label={t.dashboard.discoveryLimit}>
                  {interpolate(t.dashboard.discoveryLimitValue, {
                    count: billingStatus.discovery.limit,
                  })}
                </DataRow>
              </DataList>
              {billingStatus.discovery.remaining_slots === 0 ? (
                <p className={styles.supportingCopy}>{t.dashboard.discoveryExhausted}</p>
              ) : null}
              {billingStatus.scheduled_cancellation_at ? (
                <Callout tone="warning" title={t.billing.cancellationTitle}>
                  {interpolate(t.dashboard.scheduledCancellation, {
                    date: date(billingStatus.scheduled_cancellation_at) ?? '',
                  })}
                </Callout>
              ) : null}
              <ButtonLink to="/app/billing" variant="secondary">
                {billingActionLabels[billingStatus.billing_action]}
              </ButtonLink>
            </>
          ) : null}
        </Card>

        <Card
          as="section"
          padding="lg"
          className={styles.sectionCard}
          ariaLabelledBy="dashboard-alerts-title"
        >
          <SectionHeading id="dashboard-alerts-title" title={t.dashboard.alerts} />
          {notificationState.loading && !notificationPreference ? (
            <Skeleton width="62%" height="1.25rem" />
          ) : null}
          <ButtonLink to="/app/notifications" variant="secondary">
            {t.dashboard.manageAlerts}
          </ButtonLink>
        </Card>
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  loading,
  error,
  errorCopy,
  loadingCopy,
  retryLabel,
  onRetry,
}: {
  label: string
  value: string | null
  loading: boolean
  error: unknown | null
  errorCopy: string
  loadingCopy: string
  retryLabel: string
  onRetry: () => void
}) {
  const loadingId = useId()

  return (
    <li className={styles.metric}>
      <p className={styles.metricLabel}>{label}</p>
      {error ? (
        <div className={styles.metricError} role="alert">
          <p>{errorCopy}</p>
          <Button variant="secondary" onClick={onRetry}>
            {retryLabel}
          </Button>
        </div>
      ) : loading || value === null ? (
        <div className={styles.metricSkeleton} role="status" aria-labelledby={loadingId}>
          <span id={loadingId} className="kivou-visually-hidden">
            {label} — {loadingCopy}
          </span>
          <Skeleton width="72%" height="1.35rem" />
        </div>
      ) : (
        <p className={styles.metricValue}>{value}</p>
      )}
    </li>
  )
}

function dashboardSelectionState(key: string) {
  return {
    signalSelection: {
      kind: 'feed' as const,
      key,
      feedGeneration: 0,
      query: { freshness: 'new' as const, targetIcpId: '' },
    },
  }
}

function IcpSummary({ profile, overLimit }: { profile: TargetIcp; overLimit: boolean }) {
  const { t, locale, amount } = useI18n()
  const input = profile.customer_input
  const summary =
    input.offer_summary.trim() ||
    input.offers.map((offer) => t.offers[offer]).join(', ') ||
    t.common.notAvailable
  const territories = input.territories.map((code) => {
    const territory = MVP_TERRITORIES.find((candidate) => candidate.code === code)
    return territory ? territoryLabel(territory, locale) : code
  })
  const threshold = input.minimum_contract_value
    ? amount(
        String(input.minimum_contract_value.minimum_amount),
        input.minimum_contract_value.currency,
      )
    : null

  return (
    <Card as="article" padding="md" className={styles.icpCard}>
      <div className={styles.icpHead}>
        <h3 className={styles.icpTitle}>{profile.label}</h3>
        <div className={styles.badges}>
          {overLimit ? <Badge tone="warm">{t.icp.overLimitBadge}</Badge> : null}
          {profile.plan_limit ? <Badge tone="warm">{t.icp.territoryLimitedBadge}</Badge> : null}
        </div>
      </div>
      <p className={styles.icpSummary}>{summary}</p>
      <DataList>
        <DataRow label={t.icp.territoriesLabel}>
          {territories.length > 0 ? territories.join(', ') : t.common.notAvailable}
        </DataRow>
        {threshold ? <DataRow label={t.icp.thresholdLabel}>{threshold}</DataRow> : null}
      </DataList>
      {profile.plan_limit ? (
        <p className={styles.limitCopy}>
          {interpolate(t.dashboard.territoryLimit, {
            count: profile.plan_limit.territory_count,
            limit: profile.plan_limit.limit,
          })}
        </p>
      ) : null}
    </Card>
  )
}
