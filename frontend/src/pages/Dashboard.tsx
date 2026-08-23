import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useCurrentUser } from '../auth/SessionProvider'
import { Button, ButtonLink } from '../components/Button'
import { Badge, Callout, Card, DataList, DataRow, EmptyState, SectionHeading, Skeleton } from '../components/Surfaces'
import { useI18n, interpolate } from '../i18n'
import { billing, icps, notifications, signals } from '../api/endpoints'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { SignalCard } from '../signals/SignalCard'
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
  } else if (alertCadence && cadenceCopy) {
    alertsSummary =
      alertCadence === 'none'
        ? t.dashboard.noAlertCadence
        : interpolate(t.dashboard.availableCadence, { cadence: cadenceCopy })
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <SectionHeading level={1} title={t.dashboard.title} lead={t.dashboard.lead} />
      </header>

      <section className={styles.opportunities} aria-labelledby="dashboard-opportunities-title">
        <div className={styles.sectionHeader}>
          <SectionHeading id="dashboard-opportunities-title" title={t.dashboard.opportunities} />
          <ButtonLink to="/app/signals" variant="secondary">
            {t.dashboard.viewAllFeed}
          </ButtonLink>
        </div>
        {feedState.loading && !feedState.data ? (
          <div className={styles.signalList} aria-label={t.common.loading}>
            {[0, 1].map((index) => (
              <Card key={index} padding="lg">
                <Skeleton width="42%" height="1.75rem" />
              </Card>
            ))}
          </div>
        ) : null}
        {feedState.error ? (
          <Callout
            tone="danger"
            title={t.dashboard.opportunitiesError}
            action={
              <Button variant="secondary" onClick={() => void loadFeed()}>
                {t.dashboard.retryOpportunities}
              </Button>
            }
          />
        ) : null}
        {feedItems.length > 0 ? (
          <ol className={styles.signalList} aria-label={t.dashboard.opportunities}>
            {feedItems.map((item) => (
              <li key={item.signal_id} className={styles.listItem}>
                <SignalCard item={item} />
              </li>
            ))}
          </ol>
        ) : null}
        {feedState.data && feedItems.length === 0 ? (
          <Card padding="none">
            <EmptyState
              title={t.dashboard.noOpportunities}
              body={t.dashboard.noOpportunitiesBody}
              action={
                <ButtonLink to="/app/icps" variant="secondary">
                  {t.dashboard.adjustTargeting}
                </ButtonLink>
              }
            />
          </Card>
        ) : null}
        {feedState.data && feedItems.length > 0 && !hasUnlockedSignal ? (
          <p className={styles.supportingCopy}>{t.dashboard.noAccessibleCompany}</p>
        ) : null}
      </section>

      <div className={styles.supportGrid}>
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
          {icpState.error ? (
            <Callout
              tone="danger"
              title={t.dashboard.icpsError}
              action={
                <Button variant="secondary" onClick={() => void loadIcps()}>
                  {t.common.retry}
                </Button>
              }
            />
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
          {billingState.error ? (
            <Callout
              tone="danger"
              title={t.dashboard.billingError}
              action={
                <Button variant="secondary" onClick={() => void loadBilling()}>
                  {t.dashboard.retryBilling}
                </Button>
              }
            />
          ) : null}
          {billingStatus ? (
            <>
              <div className={styles.statusHead}>
                <div>
                  <p className={styles.microLabel}>{t.billing.currentPlan}</p>
                  <p className={styles.planName}>{t.billing.plans[billingStatus.plan_code]}</p>
                </div>
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
          {alertsSummary ? <p className={styles.alertSummary}>{alertsSummary}</p> : null}
          {notificationState.error ? (
            <Callout
              tone="danger"
              title={t.dashboard.alertsError}
              action={
                <Button variant="secondary" onClick={() => void loadNotifications()}>
                  {t.dashboard.retryAlerts}
                </Button>
              }
            />
          ) : null}
          <ButtonLink to="/app/notifications" variant="secondary">
            {t.dashboard.manageAlerts}
          </ButtonLink>
        </Card>

        {companyState.status !== 'idle' ? (
          <Card as="section" padding="lg" ariaLabelledBy="dashboard-company-title">
            <SectionHeading id="dashboard-company-title" title={t.dashboard.company} />
            <p className={styles.supportingCopy}>{companyState.signal.company.name}</p>
            {companyState.status === 'loading' ? (
              <Skeleton width="70%" height="1.25rem" />
            ) : null}
            {companyState.status === 'available' ? (
              <Link to={`/app/companies/${encodeURIComponent(companyState.companyKey)}`}>
                {t.dashboard.companyAction}
              </Link>
            ) : null}
            {companyState.status === 'unavailable' ? (
              <p className={styles.emptyTitle}>{t.dashboard.companyUnavailable}</p>
            ) : null}
            {companyState.status === 'error' ? (
              <Callout
                tone="danger"
                title={t.dashboard.companyError}
                action={
                  <Button
                    variant="secondary"
                    onClick={() => void loadCompany(companyState.signal)}
                  >
                    {t.dashboard.retryCompany}
                  </Button>
                }
              />
            ) : null}
          </Card>
        ) : null}
      </div>
    </div>
  )
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
