import { useCallback } from 'react'
import { ArrowRight, FileCheck2, MapPin } from 'lucide-react'
import { Navigate } from 'react-router-dom'
import { billing, icps, signals } from '../api/endpoints'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import type { BillingAction, BillingStatus, TargetIcp } from '../api/types'
import { useCurrentUser } from '../auth/SessionProvider'
import { interpolate, plural, useI18n } from '../i18n'
import { toSignalCards } from '../reference/dashboard/adapters'
import type { SignalCardView } from '../reference/dashboard/models'
import { useResource } from '../reference/dashboard/resources'
import { Button } from '../reference/dashboard/ui/button'
import { ReferenceLink } from '../reference/router/ReferenceLink'

export function Dashboard() {
  const me = useCurrentUser()

  if (me.onboarding_status !== 'ready_for_signals') {
    return <Navigate to="/onboarding" replace />
  }

  return <ReadyDashboard />
}

function ReadyDashboard() {
  const { t, locale, date, amount } = useI18n()
  const loadFeed = useCallback(() => signals.feed({ limit: 20, offset: 0 }), [])
  const loadProfiles = useCallback(() => icps.list(), [])
  const loadBilling = useCallback(() => billing.status(), [])
  const feed = useResource(loadFeed)
  const profiles = useResource(loadProfiles)
  const access = useResource(loadBilling)
  const cards = feed.data ? toSignalCards(feed.data) : []
  const priority = cards.find((card) => !card.locked) ?? null
  const additional = priority ? cards.filter((card) => card.id !== priority.id) : cards
  const activeProfile = profiles.data?.find((profile) => profile.status === 'active') ?? null
  const documentedCount = feed.data?.total_returned ?? null
  const countCopy = feed.error && !feed.data
    ? t.reference.headings.documentedAwards
    : documentedCount === null
      ? t.reference.loading
    : interpolate(
        plural(
          documentedCount,
          t.reference.overviewPage.documentedAwardOne,
          t.reference.overviewPage.documentedAwardOther,
        ),
        { count: `${documentedCount}${feed.data?.page.has_more ? '+' : ''}` },
      )

  const displayAmount = (card: SignalCardView) =>
    card.amount
      ? amount(card.amount.value, card.amount.currency) ?? t.reference.missingValue
      : t.reference.missingValue
  const displayLocation = (card: SignalCardView) => {
    if (!card.location) return t.reference.missingValue
    const territory = MVP_TERRITORIES.find(
      (candidate) => candidate.code === card.location?.country,
    )
    const country = territory
      ? territoryLabel(territory, locale)
      : card.location.country
    return [card.location.locality, card.location.postal_code, country]
      .filter(Boolean)
      .join(', ') || t.reference.missingValue
  }
  const displayDate = (value: string | null) =>
    date(value) ?? t.reference.missingValue
  const additionalCountCopy = feed.loading && !feed.data
    ? t.reference.loading
    : feed.error && !feed.data
      ? t.reference.headings.otherDocumentedAwards
      : interpolate(
          plural(
            additional.length,
            t.reference.overviewPage.marketOne,
            t.reference.overviewPage.marketOther,
          ),
          { count: additional.length },
        )

  return (
    <div className="overview-main">
      <section className="overview-intro" aria-labelledby="overview-title">
        <div>
          <p className="section-label">{t.reference.headings.monitoringSummary}</p>
          <h2 id="overview-title">{countCopy}</h2>
          <p>{t.reference.overviewPage.lead}</p>
          {feed.loading && feed.data ? (
            <p className="signal-limit" role="status">{t.reference.messages.refreshing}</p>
          ) : feed.error && feed.data ? (
            <p className="signal-limit" role="alert">{t.reference.messages.refreshFailed}</p>
          ) : null}
        </div>
      </section>

      <div className="overview-focus-grid">
        <PriorityCard
          card={priority}
          feedLoading={feed.loading && !feed.data}
          feedError={feed.data ? null : feed.error}
          billing={access.data}
          billingLoading={access.loading}
          billingError={access.error}
          onRetryFeed={() => void feed.retry()}
          onRetryBilling={() => void access.retry()}
          displayLocation={displayLocation}
          displayDate={displayDate}
        />

        <aside className="overview-side-stack">
          <section className="targeting-card" aria-labelledby="targeting-title">
            <div className="overview-card-heading">
              <div>
                <p className="card-kicker">{t.reference.targeting}</p>
                <h3 id="targeting-title">{t.reference.headings.savedProfile}</h3>
              </div>
              <MapPin aria-hidden="true" />
            </div>
            <TargetProfileSnapshot
              profile={activeProfile}
              loading={profiles.loading}
              error={profiles.error}
              onRetry={() => void profiles.retry()}
            />
          </section>
        </aside>
      </div>

      <section className="recent-card overview-awards-card" aria-labelledby="other-awards-title">
        <div className="overview-card-heading">
          <div>
            <p className="card-kicker">{t.reference.headings.otherDocumentedAwards}</p>
            <h3 id="other-awards-title">{additionalCountCopy}</h3>
          </div>
          <span className="signal-count">{t.reference.overviewPage.publicSources}</span>
        </div>

        <div className="recent-list">
          {additional.map((card) => (
              <ReferenceLink
                dashboard
                className="recent-signal"
                href={`/signals?signal=${encodeURIComponent(card.id)}`}
                key={card.id}
              >
                <span className="recent-company">
                  <strong>{card.companyName ?? t.reference.missingValue}</strong>
                  <span>{card.eventTitle ?? t.reference.missingValue}</span>
                </span>
                <span className="recent-value">
                  <strong>{displayAmount(card)}</strong>
                  <span>{displayDate(card.awardDate)} · {displayLocation(card)}</span>
                </span>
                <span className="recent-match">
                  {card.locked
                    ? t.reference.overviewPage.paidAccessRequired
                    : card.matchLabel ?? t.reference.missingValue}
                </span>
              </ReferenceLink>
          ))}
        </div>

        <ReferenceLink dashboard className="text-link" href="/signals">
          {t.reference.overviewPage.seeSignals} <ArrowRight aria-hidden="true" />
        </ReferenceLink>
      </section>
    </div>
  )
}

function PriorityCard({
  card,
  feedLoading,
  feedError,
  billing: billingStatus,
  billingLoading,
  billingError,
  onRetryFeed,
  onRetryBilling,
  displayLocation,
  displayDate,
}: {
  card: SignalCardView | null
  feedLoading: boolean
  feedError: unknown | null
  billing: BillingStatus | null
  billingLoading: boolean
  billingError: unknown | null
  onRetryFeed: () => void
  onRetryBilling: () => void
  displayLocation: (card: SignalCardView) => string
  displayDate: (value: string | null) => string
}) {
  const { t } = useI18n()

  if (feedLoading) {
    return (
      <article className="priority-card" aria-busy="true">
        <p className="card-kicker">{t.reference.overviewPage.reviewFirst}</p>
        <h3>{t.reference.loading}</h3>
      </article>
    )
  }

  if (feedError) {
    return (
      <article className="priority-card">
        <ResourceError
          message={t.reference.messages.loadError}
          retryLabel={t.reference.retry}
          onRetry={onRetryFeed}
        />
      </article>
    )
  }

  if (!card) {
    const billingAction = billingStatus
      ? billingActionLabel(billingStatus.billing_action, t)
      : null
    return (
      <article className="priority-card" aria-labelledby="priority-title">
        <div className="priority-heading">
          <div>
            <p className="card-kicker">{t.reference.overviewPage.reviewFirst}</p>
            <h3 id="priority-title">{t.reference.overviewPage.noAccessibleSignal}</h3>
          </div>
          <span className="published-status">
            <FileCheck2 aria-hidden="true" /> {t.reference.overviewPage.realAccess}
          </span>
        </div>
        <p className="priority-summary">{t.reference.overviewPage.noAccessibleSignalBody}</p>
        <dl className="priority-facts">
          {[t.reference.fields.award, t.reference.fields.plannedStart, t.reference.fields.location].map(
            (label) => (
              <div key={label}><dt>{label}</dt><dd>{t.reference.missingValue}</dd></div>
            ),
          )}
        </dl>
        <div className="priority-footer">
          <p>{t.reference.overviewPage.noAccessibleSignalLimit}</p>
          {billingError ? (
            <ResourceError
              message={t.reference.messages.billingLoadError}
              retryLabel={t.reference.retry}
              onRetry={onRetryBilling}
            />
          ) : billingLoading ? (
            <span>{t.reference.loading}</span>
          ) : billingAction ? (
            <Button asChild className="primary-action priority-action">
              <ReferenceLink dashboard href="/billing">
                {billingAction} <ArrowRight aria-hidden="true" />
              </ReferenceLink>
            </Button>
          ) : null}
        </div>
      </article>
    )
  }

  const reasons = card.matchReasons.length > 0
    ? card.matchReasons
    : [t.reference.missingValue]

  return (
    <article className="priority-card" aria-labelledby="priority-title">
      <div className="priority-heading">
        <div>
          <p className="card-kicker">{t.reference.overviewPage.reviewFirst}</p>
          <h3 id="priority-title">{card.eventTitle ?? t.reference.missingValue}</h3>
        </div>
        <span className="published-status">
          <FileCheck2 aria-hidden="true" />{' '}
          {card.sourceSystem
            ? interpolate(t.reference.overviewPage.publishedOn, { source: card.sourceSystem })
            : t.reference.overviewPage.publishedAward}
        </span>
      </div>

      <p className="priority-summary">{card.whyNow}</p>

      {billingError ? (
        <ResourceError
          message={t.reference.messages.billingLoadError}
          retryLabel={t.reference.retry}
          onRetry={onRetryBilling}
        />
      ) : billingLoading ? (
        <p role="status">{t.reference.loading}</p>
      ) : null}

      <dl className="priority-facts">
        <div><dt>{t.reference.fields.award}</dt><dd>{displayDate(card.awardDate)}</dd></div>
        <div><dt>{t.reference.fields.plannedStart}</dt><dd>{t.reference.missingValue}</dd></div>
        <div><dt>{t.reference.fields.location}</dt><dd>{displayLocation(card)}</dd></div>
      </dl>

      <div className="priority-why">
        <p className="card-kicker">{t.reference.overviewPage.whyFirst}</p>
        <div>{reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
      </div>

      <div className="priority-footer">
        <p>{t.reference.overviewPage.honestyLimit}</p>
        <Button asChild className="primary-action priority-action">
          <ReferenceLink dashboard href={`/signals?signal=${encodeURIComponent(card.id)}`}>
            {t.reference.overviewPage.reviewSignal} <ArrowRight aria-hidden="true" />
          </ReferenceLink>
        </Button>
      </div>
    </article>
  )
}

function TargetProfileSnapshot({
  profile,
  loading,
  error,
  onRetry,
}: {
  profile: TargetIcp | null
  loading: boolean
  error: unknown | null
  onRetry: () => void
}) {
  const { t, locale } = useI18n()

  if (loading) return <p role="status">{t.reference.loading}</p>
  if (error) {
    return (
      <ResourceError
        message={t.reference.messages.profileLoadError}
        retryLabel={t.reference.retry}
        onRetry={onRetry}
      />
    )
  }
  if (!profile) return <p>{t.reference.overviewPage.noActiveProfile}</p>

  const input = profile.customer_input
  const offer = input.offer_summary.trim() ||
    input.offers.map((kind) => t.offers[kind]).join(', ') ||
    t.reference.missingValue
  const companies = input.buyer_trades.map((trade) => t.trades[trade]).join(', ') ||
    t.reference.missingValue
  const territories = input.territories.map((code) => {
    const territory = MVP_TERRITORIES.find((candidate) => candidate.code === code)
    return territory ? territoryLabel(territory, locale) : code
  }).join(', ') || t.reference.missingValue

  return (
    <div className="target-profile-snapshot">
      <strong>{profile.label}</strong>
      <dl className="targeting-list">
        <div><dt>{t.reference.fields.offerSummary}</dt><dd>{offer}</dd></div>
        <div><dt>{t.reference.fields.targetCompanies}</dt><dd>{companies}</dd></div>
        <div><dt>{t.reference.fields.territory}</dt><dd>{territories}</dd></div>
      </dl>
      <ReferenceLink dashboard className="text-link" href="/targeting">
        {t.reference.overviewPage.seeProfile} <ArrowRight aria-hidden="true" />
      </ReferenceLink>
    </div>
  )
}

function ResourceError({
  message,
  retryLabel,
  onRetry,
}: {
  message: string
  retryLabel: string
  onRetry: () => void
}) {
  return (
    <div role="alert">
      <p>{message}</p>
      <button type="button" className="source-link" onClick={onRetry}>{retryLabel}</button>
    </div>
  )
}

function billingActionLabel(
  action: BillingAction,
  t: ReturnType<typeof useI18n>['t'],
): string {
  return {
    choose_plan: t.dashboard.choosePlan,
    manage_subscription: t.dashboard.manageSubscription,
    recover_payment: t.dashboard.recoverPayment,
    contact_support: t.dashboard.contactSupport,
  }[action]
}
