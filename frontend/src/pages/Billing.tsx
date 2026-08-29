import { ArrowRight, CreditCard, ExternalLink } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { billing } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import type {
  BillingStatus,
  CataloguePlan,
  Currency,
  Entitlements,
  PlanCode,
  PurchasablePlan,
} from '../api/types'
import {
  clearCheckoutIntent,
  saveCheckoutIntent,
  validateSignalKey,
} from '../billing/checkoutIntent'
import { useCurrentUser } from '../auth/SessionProvider'
import { interpolate, plural, useI18n } from '../i18n'
import { PrototypeNotice } from '../reference/dashboard/PrototypeNotice'
import { SettingsNav } from '../reference/dashboard/SettingsNav'
import { useResource } from '../reference/dashboard/resources'
import { Button } from '../reference/dashboard/ui/button'
import { ReferenceLink } from '../reference/router/ReferenceLink'

const PURCHASABLE_PLANS: readonly PurchasablePlan[] = ['essential', 'pro', 'scale']
const DISPLAYABLE_PLANS: readonly PlanCode[] = ['discovery', 'essential', 'pro', 'scale']

function isPurchasablePlan(value: string): value is PurchasablePlan {
  return PURCHASABLE_PLANS.includes(value as PurchasablePlan)
}

function isDisplayablePlan(value: string): value is PlanCode {
  return DISPLAYABLE_PLANS.includes(value as PlanCode)
}

function secureBillingDestination(value: string): string | null {
  try {
    const destination = new URL(value)
    if (destination.protocol !== 'https:') return null
    if (destination.username || destination.password) return null
    return destination.href
  } catch {
    return null
  }
}

export function Billing() {
  const me = useCurrentUser()
  const { t, date, money } = useI18n()
  const copy = t.reference.billingSettings
  const location = useLocation()
  const loadStatus = useCallback(() => billing.status(), [])
  const loadCatalogue = useCallback(() => billing.plans(), [])
  const status = useResource(loadStatus)
  const catalogue = useResource(loadCatalogue)
  const [currency, setCurrency] = useState<Currency>('chf')
  const [selectedPlanCode, setSelectedPlanCode] = useState<PlanCode>('essential')
  const [actionError, setActionError] = useState<unknown>(null)
  const [destinationError, setDestinationError] = useState(false)
  const [busyAction, setBusyAction] = useState<'portal' | PurchasablePlan | null>(null)
  const busyRef = useRef(false)
  const mounted = useRef(true)
  const actionGeneration = useRef(0)
  const currencyInitialised = useRef(false)
  const accountId = me.account_id

  const lockedSignalKey = validateSignalKey(
    (location.state as { lockedSignalKey?: unknown } | null)?.lockedSignalKey,
  )

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      actionGeneration.current += 1
      busyRef.current = false
    }
  }, [])

  useEffect(() => {
    if (currencyInitialised.current) return
    const billedCurrency = status.data?.currency
    if (billedCurrency === 'chf' || billedCurrency === 'eur') {
      currencyInitialised.current = true
      setCurrency(billedCurrency)
      return
    }
    if (catalogue.data) {
      currencyInitialised.current = true
      setCurrency(catalogue.data.currencies.includes('chf')
        ? 'chf'
        : catalogue.data.currencies[0] ?? 'chf')
    }
  }, [catalogue.data, status.data])

  const displayablePlans = useMemo(
    () => catalogue.data?.plans.filter(
      (plan): plan is CataloguePlan & { plan_code: PlanCode } =>
        isDisplayablePlan(plan.plan_code),
    ) ?? [],
    [catalogue.data],
  )

  useEffect(() => {
    if (displayablePlans.length === 0) return
    if (!displayablePlans.some((plan) => plan.plan_code === selectedPlanCode)) {
      setSelectedPlanCode(displayablePlans[0].plan_code)
    }
  }, [displayablePlans, selectedPlanCode])

  const authoritativeStatus = !status.loading && !status.error ? status.data : null
  const authoritativeCatalogue = !catalogue.loading && !catalogue.error ? catalogue.data : null
  const authoritativeSelectedPlan = authoritativeCatalogue?.plans.find(
    (plan) => plan.plan_code === selectedPlanCode && isDisplayablePlan(plan.plan_code),
  ) ?? null
  const displayedEntitlements = authoritativeStatus?.billing_action === 'choose_plan'
    ? authoritativeSelectedPlan?.entitlements ?? null
    : authoritativeStatus?.entitlements ?? null

  async function startCheckout(plan: PurchasablePlan) {
    if (busyRef.current) return
    const cataloguePlan = authoritativeCatalogue?.plans.find((item) => item.plan_code === plan)
    if (
      authoritativeStatus?.billing_action !== 'choose_plan' ||
      !cataloguePlan?.purchasable ||
      !cataloguePlan.monthly_price[currency]
    ) return

    busyRef.current = true
    const generation = ++actionGeneration.current
    const startedForAccount = accountId
    setBusyAction(plan)
    setActionError(null)
    setDestinationError(false)

    try {
      const session = await billing.checkout({ plan, currency })
      if (
        !mounted.current ||
        generation !== actionGeneration.current ||
        startedForAccount !== accountId
      ) return
      const destination = secureBillingDestination(session.checkout_url)
      if (!destination) {
        setDestinationError(true)
        setBusyAction(null)
        busyRef.current = false
        return
      }
      clearCheckoutIntent()
      if (lockedSignalKey !== null) saveCheckoutIntent(lockedSignalKey)
      window.location.assign(destination)
    } catch (caught) {
      if (
        !mounted.current ||
        generation !== actionGeneration.current ||
        startedForAccount !== accountId
      ) return
      setActionError(caught)
      setBusyAction(null)
      busyRef.current = false
    }
  }

  async function openPortal() {
    if (busyRef.current) return
    if (
      authoritativeStatus?.billing_action !== 'manage_subscription' &&
      authoritativeStatus?.billing_action !== 'recover_payment'
    ) return

    busyRef.current = true
    const generation = ++actionGeneration.current
    const startedForAccount = accountId
    setBusyAction('portal')
    setActionError(null)
    setDestinationError(false)

    try {
      const session = await billing.portal()
      if (
        !mounted.current ||
        generation !== actionGeneration.current ||
        startedForAccount !== accountId
      ) return
      const destination = secureBillingDestination(session.portal_url)
      if (!destination) {
        setDestinationError(true)
        setBusyAction(null)
        busyRef.current = false
        return
      }
      window.location.assign(destination)
    } catch (caught) {
      if (
        !mounted.current ||
        generation !== actionGeneration.current ||
        startedForAccount !== accountId
      ) return
      setActionError(caught)
      setBusyAction(null)
      busyRef.current = false
    }
  }

  const actionCopy = actionError ? describeError(actionError, t) : null
  const expiresAt = actionError instanceof ApiError && typeof actionError.extra.expires_at === 'string'
    ? date(actionError.extra.expires_at)
    : null

  return (
    <div className="settings-main">
      <section className="settings-intro">
        <p className="section-label">{copy.label}</p>
        <h2>{copy.title}</h2>
        <p>{copy.body}</p>
      </section>
      <SettingsNav active="billing" />
      <section className="settings-form-card billing-settings-card" aria-labelledby="billing-card-title">
        <div className="settings-form-heading">
          <div>
            <p className="card-kicker">
              {authoritativeStatus?.billing_action === 'choose_plan'
                ? copy.selectedOffer
                : copy.currentOffer}
            </p>
            <h3 id="billing-card-title">
              {status.loading
                ? t.reference.loading
                : status.error || !status.data
                  ? t.reference.missingValue
                  : status.data.billing_action === 'choose_plan'
                    ? authoritativeSelectedPlan
                      ? `${t.billing.plans[authoritativeSelectedPlan.plan_code]} · ${planPriceLabel(authoritativeSelectedPlan, currency, money, t)} ${t.billing.perMonth}`
                      : t.reference.missingValue
                    : t.billing.plans[status.data.plan_code]}
            </h3>
          </div>
          <span className="billing-status">
            <span aria-hidden="true" />
            {status.loading
              ? t.reference.loading
              : status.error || !status.data
                ? t.reference.missingValue
                : subscriptionStatusLabel(status.data, t)}
          </span>
        </div>

        <PrototypeNotice>{copy.connectedNotice}</PrototypeNotice>

        {status.error || (!status.loading && !status.data) ? (
          <div className="prototype-notice" role="alert">
            <div>
              <strong>{copy.statusError}</strong>
              <Button type="button" variant="outline" onClick={() => void status.retry()}>
                {copy.retryStatus}
              </Button>
            </div>
          </div>
        ) : null}

        {authoritativeStatus ? (
          <>
            {authoritativeStatus.billing_action === 'manage_subscription' && authoritativeStatus.current_period_end && !authoritativeStatus.scheduled_cancellation_at ? (
              <p className="field-hint">
                {interpolate(t.billing.renewsOn, {
                  date: date(authoritativeStatus.current_period_end) ?? t.reference.missingValue,
                })}
              </p>
            ) : null}

            {authoritativeStatus.billing_action === 'manage_subscription' && authoritativeStatus.scheduled_cancellation_at ? (
              <div className="prototype-notice" role="note">
                <div>
                  <strong>{t.billing.cancellationTitle}</strong>
                  <p>{interpolate(
                    authoritativeStatus.cancel_at_period_end
                      ? t.billing.cancellationAtPeriodEnd
                      : t.billing.cancellationOnDate,
                    {
                      date: date(authoritativeStatus.scheduled_cancellation_at) ?? t.reference.missingValue,
                    },
                  )}</p>
                </div>
              </div>
            ) : null}

            {authoritativeStatus.billing_action === 'manage_subscription' ? (
              <p className="field-hint">{t.billing.manageLead}</p>
            ) : null}

            {authoritativeStatus.billing_action === 'choose_plan' && authoritativeStatus.payment_issue ? (
              <div className="prototype-notice" role="note">
                <div><p>{t.billing.terminalNotice}</p></div>
              </div>
            ) : null}

            {authoritativeStatus.billing_action === 'choose_plan' ? (
              catalogue.loading ? (
                <p className="billing-plan-selector" role="status">{t.reference.loading}</p>
              ) : catalogue.error || !authoritativeCatalogue ? (
                <div className="billing-plan-selector prototype-notice" role="alert">
                  <div>
                    <strong>{copy.catalogueError}</strong>
                    <Button type="button" variant="outline" onClick={() => void catalogue.retry()}>
                      {copy.retryCatalogue}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="billing-plan-selector form-field">
                  <label htmlFor="billing-plan">{copy.planLabel}</label>
                  <select
                    id="billing-plan"
                    className="lifecycle-select"
                    value={selectedPlanCode}
                    disabled={busyAction !== null}
                    onChange={(event) => setSelectedPlanCode(event.target.value as PlanCode)}
                  >
                    {displayablePlans.map((plan) => (
                      <option value={plan.plan_code} key={plan.plan_code}>
                        {t.billing.plans[plan.plan_code]} · {planPriceLabel(plan, currency, money, t)} {t.billing.perMonth}
                        {plan.recommended ? ` · ${t.billing.recommended}` : ''}
                      </option>
                    ))}
                  </select>
                  <fieldset>
                    <legend>{t.billing.currency}</legend>
                    <div className="billing-actions">
                      {authoritativeCatalogue.currencies.map((code) => (
                        <label key={code}>
                          <input
                            type="radio"
                            name="kivou-currency"
                            value={code}
                            checked={currency === code}
                            disabled={busyAction !== null}
                            onChange={() => setCurrency(code)}
                          />
                          {code.toUpperCase()}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  <p className="field-hint">{copy.planHint}</p>
                  {authoritativeSelectedPlan?.purchasable && !authoritativeSelectedPlan.monthly_price[currency] ? (
                    <p>{t.reference.missingValue}</p>
                  ) : null}
                </div>
              )
            ) : null}

            {displayedEntitlements ? (
              <EntitlementList entitlements={displayedEntitlements} />
            ) : null}

            {actionCopy || destinationError ? (
              <div className="prototype-notice" role="alert">
                <div>
                  <strong>{destinationError ? copy.destinationError : actionCopy?.title}</strong>
                  {!destinationError && actionCopy?.body ? <p>{actionCopy.body}</p> : null}
                  {expiresAt ? (
                    <p>{interpolate(t.billing.errors.checkoutInProgressExpiry, { date: expiresAt })}</p>
                  ) : null}
                </div>
              </div>
            ) : null}

            {authoritativeStatus.billing_action === 'recover_payment' ? (
              <div className="prototype-notice" role="note">
                <div>
                  <strong>{t.billing.recoverTitle}</strong>
                  <p>{t.billing.recoverBody}</p>
                </div>
              </div>
            ) : null}

            {authoritativeStatus.billing_action === 'contact_support' ? (
              <div className="prototype-notice" role="note">
                <div>
                  <strong>{t.billing.supportTitle}</strong>
                  <p>{t.billing.supportBody}</p>
                </div>
              </div>
            ) : null}

            <div className="billing-actions">
              {authoritativeStatus.billing_action === 'choose_plan' && authoritativeSelectedPlan?.plan_code === 'discovery' ? (
                <Button asChild className="primary-action">
                  <ReferenceLink href="/app/signals">
                    {copy.seeAccessibleSignals} <ArrowRight aria-hidden="true" />
                  </ReferenceLink>
                </Button>
              ) : null}

              {authoritativeStatus.billing_action === 'choose_plan' && authoritativeSelectedPlan?.purchasable && isPurchasablePlan(authoritativeSelectedPlan.plan_code) ? (
                <Button
                  type="button"
                  className="primary-action"
                  disabled={busyAction !== null || !authoritativeSelectedPlan.monthly_price[currency]}
                  onClick={() => {
                    const planCode = authoritativeSelectedPlan.plan_code
                    if (isPurchasablePlan(planCode)) void startCheckout(planCode)
                  }}
                >
                  {busyAction === authoritativeSelectedPlan.plan_code
                    ? t.billing.choosing
                    : interpolate(t.billing.choose, { plan: t.billing.plans[authoritativeSelectedPlan.plan_code] })}
                  <ArrowRight aria-hidden="true" />
                </Button>
              ) : null}

              {authoritativeStatus.billing_action === 'manage_subscription' ? (
                <Button
                  type="button"
                  className="primary-action"
                  disabled={busyAction !== null}
                  onClick={() => void openPortal()}
                >
                  <CreditCard aria-hidden="true" />
                  {busyAction === 'portal' ? t.billing.openingPortal : t.billing.managePortal}
                  <ExternalLink aria-hidden="true" />
                </Button>
              ) : null}

              {authoritativeStatus.billing_action === 'recover_payment' ? (
                <Button
                  type="button"
                  className="primary-action"
                  disabled={busyAction !== null}
                  onClick={() => void openPortal()}
                >
                  <CreditCard aria-hidden="true" />
                  {busyAction === 'portal' ? t.billing.openingPortal : t.billing.recoverCta}
                  <ExternalLink aria-hidden="true" />
                </Button>
              ) : null}

              {authoritativeStatus.billing_action === 'contact_support' ? (
                <Button asChild className="primary-action">
                  <a href={`mailto:${t.billing.supportEmail}`}>
                    {t.billing.supportCta} <ArrowRight aria-hidden="true" />
                  </a>
                </Button>
              ) : null}
            </div>
          </>
        ) : null}
      </section>
    </div>
  )
}

function EntitlementList({ entitlements }: { entitlements: Entitlements }) {
  const { t } = useI18n()
  const copy = t.reference.billingSettings
  const profiles = interpolate(
    plural(
      entitlements.max_active_icps,
      t.billing.entitlements.icpsOne,
      t.billing.entitlements.icpsOther,
    ),
    { count: entitlements.max_active_icps },
  )
  const territories = entitlements.max_territories_per_icp !== null
    ? interpolate(
        plural(
          entitlements.max_territories_per_icp,
          t.billing.entitlements.territoriesPerProfileOne,
          t.billing.entitlements.territoriesPerProfileOther,
        ),
        { count: entitlements.max_territories_per_icp },
      )
    : entitlements.territory_mode === 'expanded'
      ? t.billing.entitlements.territoryExpanded
      : t.billing.entitlements.territoryMultiple
  const history = entitlements.history_scope === 'all_available'
    ? t.billing.entitlements.historyAll
    : entitlements.history_days && entitlements.history_days > 0
      ? interpolate(t.billing.entitlements.historyWindow, { days: entitlements.history_days })
      : t.billing.entitlements.historyNone
  const feedAccess = entitlements.granted_signals > 0
    ? interpolate(t.billing.entitlements.grantedSignals, {
        count: entitlements.granted_signals,
      })
    : entitlements.detail_access
      ? copy.signalFeedAndDetails
      : entitlements.feed_access
        ? copy.signalFeed
        : copy.signalAccessUnavailable
  const signalAccess = `${feedAccess} · ${entitlements.evidence_access
    ? t.billing.entitlements.evidence
    : copy.evidenceUnavailable}`

  return (
    <dl className="billing-entitlements">
      <div><dt>{copy.targetProfiles}</dt><dd>{profiles}</dd></div>
      <div><dt>{copy.territories}</dt><dd>{territories}</dd></div>
      <div><dt>{copy.alerts}</dt><dd>{t.billing.entitlements[`alert${cadenceKey(entitlements.alert_cadence)}`]}</dd></div>
      <div><dt>{copy.history}</dt><dd>{history}</dd></div>
      <div><dt>{copy.signalAccess}</dt><dd>{signalAccess}</dd></div>
    </dl>
  )
}

function cadenceKey(value: Entitlements['alert_cadence']): 'None' | 'Weekly' | 'Daily' | 'Priority' {
  return `${value[0].toUpperCase()}${value.slice(1)}` as 'None' | 'Weekly' | 'Daily' | 'Priority'
}

function planPriceLabel(
  plan: CataloguePlan,
  currency: Currency,
  money: (minorUnits: number, currency: string) => string,
  t: ReturnType<typeof useI18n>['t'],
): string {
  const price = plan.monthly_price[currency]
  if (price) return money(price.amount_minor_units, price.currency)
  if (!plan.purchasable && plan.plan_code === 'discovery') return t.billing.free
  return t.reference.missingValue
}

function subscriptionStatusLabel(
  status: BillingStatus,
  t: ReturnType<typeof useI18n>['t'],
): string {
  const value = status.subscription_status
  if (value === null) return t.billing.status.none
  if (value in t.billing.status) {
    return t.billing.status[value as keyof typeof t.billing.status]
  }
  return t.billing.status.unknown
}
