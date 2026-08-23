import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useCurrentUser } from '../auth/SessionProvider'
import { Button } from '../components/Button'
import { Callout, SectionHeading } from '../components/Surfaces'
import { useI18n } from '../i18n'
import { billing, icps, notifications, signals } from '../api/endpoints'
import type {
  BillingStatus,
  FeedPage,
  NotificationPreference,
  TargetIcp,
  UnlockedFeedItem,
} from '../api/types'

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
  const { t } = useI18n()

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

  return (
    <div>
      <SectionHeading level={1} title={t.dashboard.title} lead={t.dashboard.lead} />

      <section aria-labelledby="dashboard-opportunities-title">
        <h2 id="dashboard-opportunities-title">{t.dashboard.opportunities}</h2>
        {feedState.loading && !feedState.data ? <p>{t.common.loading}</p> : null}
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
      </section>

      <section aria-labelledby="dashboard-icps-title">
        <h2 id="dashboard-icps-title">{t.dashboard.icps}</h2>
        {icpState.loading && !icpState.data ? <p>{t.common.loading}</p> : null}
      </section>

      <section aria-labelledby="dashboard-billing-title">
        <h2 id="dashboard-billing-title">{t.dashboard.billing}</h2>
        {billingState.loading && !billingState.data ? <p>{t.common.loading}</p> : null}
        {billingState.data ? <p>{t.billing.plans[billingState.data.plan_code]}</p> : null}
      </section>

      <section aria-labelledby="dashboard-alerts-title">
        <h2 id="dashboard-alerts-title">{t.dashboard.alerts}</h2>
        {notificationState.loading && !notificationState.data ? <p>{t.common.loading}</p> : null}
      </section>

      {companyState.status !== 'idle' ? (
        <section aria-labelledby="dashboard-company-title">
          <h2 id="dashboard-company-title">{t.dashboard.company}</h2>
          {companyState.status === 'loading' ? <p>{t.common.loading}</p> : null}
          {companyState.status === 'available' ? (
            <Link to={`/app/companies/${encodeURIComponent(companyState.companyKey)}`}>
              {t.dashboard.companyAction}
            </Link>
          ) : null}
          {companyState.status === 'unavailable' ? (
            <p>{t.dashboard.companyUnavailable}</p>
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
        </section>
      ) : null}
    </div>
  )
}
