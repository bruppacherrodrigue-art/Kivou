import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { companies } from '../api/endpoints'
import type { CompanyProfile as CompanyProfilePayload, CompanyRelatedSignal } from '../api/types'
import { ArrowRightIcon, BuildingIcon, ExternalIcon } from '../assets/Icons'
import { ButtonExternalLink, ButtonLink } from '../components/Button'
import { Badge, Callout, Card, DataList, DataRow, SectionHeading, Skeleton } from '../components/Surfaces'
import { interpolate, plural, useI18n } from '../i18n'
import styles from './CompanyProfile.module.css'

export function CompanyProfile() {
  const { companyKey = '' } = useParams()
  const { t } = useI18n()
  const [profile, setProfile] = useState<CompanyProfilePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    companies
      .get(companyKey)
      .then((result) => {
        if (active) setProfile(result)
      })
      .catch((caught) => {
        if (active) setError(caught)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [companyKey])

  if (loading) return <CompanySkeleton />
  if (error) {
    const unavailable = error instanceof ApiError && error.status === 404
    return (
      <div className={styles.page}>
        <BackToSignals />
        <h1 className="kivou-visually-hidden">
          {unavailable ? t.companyProfile.inaccessibleTitle : t.companyProfile.errorTitle}
        </h1>
        <Callout
          tone={unavailable ? 'warning' : 'danger'}
          title={unavailable ? t.companyProfile.inaccessibleTitle : t.companyProfile.errorTitle}
          live
        >
          {unavailable ? t.companyProfile.inaccessibleBody : t.companyProfile.errorBody}
        </Callout>
      </div>
    )
  }
  if (!profile) return null
  return <CompanyProfileView profile={profile} />
}

function safeWebsite(value: string | null): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    const hostname = parsed.hostname.replace(/^\[|\]$/g, '').replace(/\.$/, '').toLowerCase()
    const ipLiteral = /^\d{1,3}(?:\.\d{1,3}){3}$/.test(hostname) || hostname.includes(':')
    if (
      parsed.protocol !== 'https:' ||
      parsed.username ||
      parsed.password ||
      hostname === 'localhost' ||
      hostname.endsWith('.localhost') ||
      hostname.endsWith('.local') ||
      hostname.endsWith('.internal') ||
      ipLiteral ||
      !hostname.includes('.')
    ) {
      return null
    }
    return parsed.toString()
  } catch {
    return null
  }
}

function BackToSignals() {
  const { t } = useI18n()
  return (
    <Link to="/app/signals" className={styles.back}>
      <ArrowRightIcon className={styles.backIcon} aria-hidden="true" />
      {t.companyProfile.backToSignals}
    </Link>
  )
}

function CompanyProfileView({ profile }: { profile: CompanyProfilePayload }) {
  const { t, date } = useI18n()
  const identity = profile.official_identity
  const website = safeWebsite(identity.website_url)
  const observed = date(identity.observed_at) ?? identity.observed_at
  const firstSignal = profile.related_signals[0]
  const countCopy = plural(
    profile.related_signals.length,
    t.companyProfile.relatedCountOne,
    t.companyProfile.relatedCountOther,
  )
  const partial =
    profile.coverage.unavailable_fields.length > 0 ||
    !profile.coverage.related_signals_complete

  return (
    <div className={styles.page}>
      <BackToSignals />

      <header className={styles.hero}>
        <div className={styles.eyebrowRow}>
          <span>{t.companyProfile.eyebrow}</span>
          <Badge tone="neutral">{t.companyProfile.publicNotice}</Badge>
        </div>
        <div className={styles.heroTitleRow}>
          <BuildingIcon className={styles.heroIcon} aria-hidden="true" />
          <h1 className={styles.title}>{identity.name}</h1>
        </div>
        <div className={styles.heroMeta}>
          {identity.country ? <span>{identity.country}</span> : null}
          <span>{interpolate(countCopy, { count: profile.related_signals.length })}</span>
          <span>{interpolate(t.companyProfile.observedOn, { date: observed })}</span>
        </div>
        <div className={styles.actions}>
          {firstSignal ? (
            <ButtonLink to={`/app/signals/${encodeURIComponent(firstSignal.signal_id)}`} size="lg">
              {t.companyProfile.reviewSignal}
            </ButtonLink>
          ) : null}
          <ButtonLink to="/app/signals" variant="secondary" size="lg">
            {t.companyProfile.backToSignals}
          </ButtonLink>
          {website ? (
            <ButtonExternalLink href={website} variant="quiet" size="lg" icon={<ExternalIcon />}>
              {t.companyProfile.openWebsite}
              <span className="kivou-visually-hidden"> {t.companyProfile.externalNewTab}</span>
            </ButtonExternalLink>
          ) : null}
        </div>
      </header>

      {partial ? (
        <Callout tone="info" title={t.companyProfile.partialTitle}>
          {t.companyProfile.partialBody}
        </Callout>
      ) : null}

      <div className={styles.layout}>
        <div className={styles.mainColumn}>
          <section className={styles.section} aria-labelledby="company-official-identity">
            <SectionHeading
              id="company-official-identity"
              title={t.companyProfile.identifiedTitle}
              lead={t.companyProfile.identifiedLead}
            />
            <Card padding="lg" className={styles.officialCard}>
              <DataList>
                <DataRow label={t.companyProfile.officialName}>{identity.name}</DataRow>
                {identity.country ? (
                  <DataRow label={t.companyProfile.officialCountry}>{identity.country}</DataRow>
                ) : null}
                {identity.address ? (
                  <DataRow label={t.companyProfile.officialAddress}>{identity.address}</DataRow>
                ) : null}
                {identity.identifiers.length > 0 ? (
                  <DataRow label={t.companyProfile.officialIdentifiers}>
                    <ul className={styles.identifiers}>
                      {identity.identifiers.map((identifier) => (
                        <li key={`${identifier.scheme}:${identifier.value}`}>
                          <span>{identifier.scheme}</span>
                          <code>{identifier.value}</code>
                        </li>
                      ))}
                    </ul>
                  </DataRow>
                ) : null}
              </DataList>
            </Card>
          </section>

          <section className={styles.section} aria-labelledby="company-related-signals">
            <SectionHeading
              id="company-related-signals"
              title={t.companyProfile.relatedTitle}
              lead={t.companyProfile.relatedLead}
            />
            <div className={styles.signalList}>
              {profile.related_signals.map((signal) => (
                <RelatedSignal key={signal.signal_id} signal={signal} />
              ))}
            </div>
          </section>

        </div>

        <aside className={styles.sideColumn}>
          <section className={styles.section} aria-labelledby="company-attention">
            <SectionHeading
              id="company-attention"
              title={t.companyProfile.whyAttentionTitle}
              lead={t.companyProfile.whyAttentionLead}
            />
            <div className={styles.attentionList}>
              {profile.related_signals.map((signal) => (
                <Card key={signal.signal_id} padding="lg" as="article" className={styles.analysisCard}>
                  <h3 className={styles.cardTitle}>
                    {signal.contract_title ?? signal.event.headline}
                  </h3>
                  {signal.plausible_needs.length > 0 ? (
                    <div className={styles.analysisBlock}>
                      <p className={styles.analysisLabel}>{t.companyProfile.plausibleNeeds}</p>
                      <ul className={styles.needs}>
                        {signal.plausible_needs.map((need) => (
                          <li key={`${signal.signal_id}:${need.label}`}>
                            <strong>{need.label}</strong>
                            {need.statement ? <span>{need.statement}</span> : null}
                            {need.timing_label ? <small>{need.timing_label}</small> : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <div className={styles.analysisBlock}>
                    <p className={styles.analysisLabel}>{t.companyProfile.fit}</p>
                    <p className={styles.fitLabel}>{signal.fit.label}</p>
                    {signal.fit.reasons.length > 0 ? (
                      <ul className={styles.reasons}>
                        {signal.fit.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </Card>
              ))}
            </div>
          </section>

          <section className={styles.section} aria-labelledby="company-sources">
            <SectionHeading
              id="company-sources"
              title={t.companyProfile.sourcesTitle}
              lead={t.companyProfile.sourcesLead}
            />
            <Card padding="md" className={styles.sourceCard}>
              <DataList>
                <DataRow label={t.companyProfile.identitySource}>
                  {t.companyProfile.publicNotice}
                </DataRow>
                <DataRow label={t.companyProfile.signalSource}>
                  {t.companyProfile.signalSourceValue}
                </DataRow>
                <DataRow label={t.companyProfile.observationDate}>{observed}</DataRow>
              </DataList>
            </Card>
          </section>
        </aside>
      </div>
    </div>
  )
}

function RelatedSignal({ signal }: { signal: CompanyRelatedSignal }) {
  const { t, date, amount } = useI18n()
  return (
    <Card padding="lg" as="article" className={styles.signalCard}>
      <div className={styles.signalHeader}>
        <div>
          <h3 className={styles.cardTitle}>{signal.contract_title ?? signal.event.headline}</h3>
          <p className={styles.signalHeadline}>{signal.event.headline}</p>
        </div>
        <Badge tone="neutral">Kivou</Badge>
      </div>
      <DataList>
        {signal.amount ? (
          <DataRow label={t.companyProfile.contractAmount} tabular>
            {amount(signal.amount.value, signal.amount.currency)}
          </DataRow>
        ) : null}
        {signal.event.date ? (
          <DataRow label={t.companyProfile.eventDate} tabular>
            {date(signal.event.date)}
          </DataRow>
        ) : null}
      </DataList>
      <p className={styles.whyNow}>{signal.event.why_now}</p>
      {signal.event.award_date_note ? (
        <p className={styles.awardNote}>{signal.event.award_date_note}</p>
      ) : null}
      <ButtonLink
        to={`/app/signals/${encodeURIComponent(signal.signal_id)}`}
        variant="secondary"
      >
        {t.companyProfile.reviewSignal}
      </ButtonLink>
    </Card>
  )
}

function CompanySkeleton() {
  const { t } = useI18n()
  return (
    <div className={styles.page} role="status" aria-label={t.common.loading}>
      <h1 className="kivou-visually-hidden">{t.common.loading}</h1>
      <div aria-hidden="true" className={styles.skeletonStack}>
        <Skeleton width="10rem" height="1rem" />
        <Skeleton width="70%" height="2.5rem" />
        <Skeleton width="45%" height="1rem" />
        <Card padding="lg">
          <div className={styles.skeletonStack}>
            <Skeleton width="90%" />
            <Skeleton width="75%" />
            <Skeleton width="82%" />
          </div>
        </Card>
      </div>
    </div>
  )
}
