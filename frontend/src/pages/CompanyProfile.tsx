import type { RefObject } from 'react'
import { ArrowLeft, ArrowRight, Building2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import type {
  CompanyProfile as CompanyProfilePayload,
  Place,
  SignalEventClock,
} from '../api/types'
import { interpolate, plural, useI18n } from '../i18n'
import styles from './Companies.module.css'

export interface AuthorizedCompanySignal {
  signalId: string
  presentationArtifactId: string | null
  summary: string | null
  buyerName: string | null
  location: Place | null
  amountValue: string | null
  amountCurrency: string | null
  awardDate: string | null
  eventDate: string | null
  eventClock: SignalEventClock
}

export interface AuthorizedCompany {
  key: string
  name: string
  country: string | null
  signals: AuthorizedCompanySignal[]
}

export function companyAwardHref(companyKey: string, signalId: string): string {
  const query = new URLSearchParams({ signal: signalId })
  return `/app/companies/${encodeURIComponent(companyKey)}?${query.toString()}`
}

export function companySignalHref(signal: AuthorizedCompanySignal): string {
  const query = new URLSearchParams()
  if (signal.presentationArtifactId) {
    query.set('presentation_artifact_id', signal.presentationArtifactId)
  }
  const encodedQuery = query.toString()
  const suffix = encodedQuery ? `?${encodedQuery}` : ''
  return `/app/signals/${encodeURIComponent(signal.signalId)}${suffix}`
}

export function companyInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (/^[A-ZÀ-ÖØ-Þ]{2,3}$/u.test(parts[0] ?? '')) return parts[0]
  return (parts.length > 1 ? `${parts[0][0]}${parts[1][0]}` : parts[0]?.slice(0, 2) ?? '?')
    .toLocaleUpperCase()
}

function countryLabel(value: string | null, locale: 'fr' | 'en'): string | null {
  if (!value) return null
  const territory = MVP_TERRITORIES.find((candidate) => candidate.code === value)
  return territory ? territoryLabel(territory, locale) : value
}

function placeLabel(place: Place | null, fallback: string | null): string | null {
  if (place) {
    const value = [place.locality, place.postal_code, place.country].filter(Boolean).join(', ')
    if (value) return value
  }
  return fallback
}

function safeHttpsUrl(value: string | null): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

export function CompanyProfileView({
  panelRef,
  profile,
  company,
  backToList,
}: {
  panelRef: RefObject<HTMLElement | null>
  profile: CompanyProfilePayload
  company: AuthorizedCompany
  backToList?: () => void
}) {
  const { t, locale, date, amount } = useI18n()
  const copy = t.reference.companiesPage
  const identity = profile.official_identity
  const localizedCountry = countryLabel(identity.country, locale)
  const partial = profile.coverage.unavailable_fields.length > 0 || !profile.coverage.related_signals_complete
  const dateStatementFor = (candidate: AuthorizedCompanySignal) => {
    const observedDate = date(candidate.eventDate)
    if (candidate.eventClock === 'notification') {
      return observedDate
        ? interpolate(copy.notifiedOn, { date: observedDate })
        : copy.notificationDateMissing
    }
    if (candidate.eventClock === 'publication') {
      return observedDate
        ? interpolate(copy.publishedOn, { date: observedDate })
        : copy.publicationDateMissing
    }
    const awardDate = observedDate ?? date(candidate.awardDate)
    return awardDate
      ? interpolate(copy.awardedOn, { date: awardDate })
      : copy.awardDateMissing
  }
  const website = safeHttpsUrl(identity.website_url)
  const observedOn = date(identity.observed_at) ?? t.reference.missingValue

  return (
    <section
      ref={panelRef}
      className="company-detail"
      data-master-detail-pane="detail"
      id="company-detail"
      aria-labelledby="company-name"
    >
      {backToList ? (
        <button type="button" className={styles.mobileBack} onClick={backToList}>
          <ArrowLeft aria-hidden="true" /> {copy.backToAwards}
        </button>
      ) : null}

      <header className={`company-detail-hero ${styles.contextHero}`}>
        <div className="company-identity-heading">
          <span className="company-hero-avatar" aria-hidden="true">{companyInitials(identity.name)}</span>
          <div>
            <p className="section-label">{t.companyProfile.eyebrow}</p>
            <h2 id="company-name" tabIndex={-1}>{identity.name}</h2>
            <p>{t.companyProfile.identifiedLead}</p>
          </div>
        </div>
      </header>

      {partial ? <p className="companies-panel-note" role="status">{t.companyProfile.partialBody}</p> : null}

      <div className={styles.detailSections}>
        <section className="company-identity-card" aria-labelledby="identity-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{t.companyProfile.publicNotice}</p>
              <h3 id="identity-title">{t.companyProfile.identifiedTitle}</h3>
            </div>
            <Building2 aria-hidden="true" />
          </div>
          <dl className="company-identity-list">
            <div><dt>{t.companyProfile.officialName}</dt><dd>{identity.name}</dd></div>
            <div>
              <dt>{t.companyProfile.officialIdentifiers}</dt>
              <dd>{identity.identifiers.length > 0
                ? identity.identifiers.map((identifier) => (
                    <span className={styles.identifier} key={`${identifier.scheme}:${identifier.value}`}>
                      {identifier.scheme.toLocaleUpperCase()} · {identifier.value}
                    </span>
                  ))
                : t.reference.missingValue}</dd>
            </div>
            <div><dt>{t.companyProfile.officialAddress}</dt><dd>{identity.address ?? t.reference.missingValue}</dd></div>
            <div><dt>{t.companyProfile.officialCountry}</dt><dd>{localizedCountry ?? t.reference.missingValue}</dd></div>
            <div>
              <dt>{t.reference.signalsPage.website}</dt>
              <dd>{website ? (
                <a href={website} target="_blank" rel="noreferrer">{t.companyProfile.openWebsite}</a>
              ) : t.reference.missingValue}</dd>
            </div>
            <div><dt>{t.reference.signalsPage.lastVerified}</dt><dd>{observedOn}</dd></div>
          </dl>
        </section>

        <section className="related-signals-card" aria-labelledby="related-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.documentedContracts}</p>
              <h3 id="related-title">{copy.otherAwards}</h3>
            </div>
            <span>{interpolate(plural(
              company.signals.length,
              copy.contractOne,
              copy.contractOther,
            ), { count: company.signals.length })}</span>
          </div>
          <p className={styles.historyLead}>{t.companyProfile.relatedLead}</p>
          {company.signals.length > 0 ? company.signals.map((candidate) => {
            const candidateDate = dateStatementFor(candidate)
            const candidateAmount = amount(candidate.amountValue, candidate.amountCurrency)
              ?? t.reference.missingValue
            const candidateSummary = candidate.summary ?? copy.objectMissing
            const territory = placeLabel(candidate.location, localizedCountry) ?? copy.territoryMissing
            return (
              <article className="company-timeline-item" key={candidate.signalId}>
                <span className="timeline-marker" aria-hidden="true" />
                <div>
                  <time dateTime={(candidate.eventClock === 'award'
                    ? candidate.eventDate ?? candidate.awardDate
                    : candidate.eventDate) ?? undefined}>{candidateDate}</time>
                  <strong>{candidateSummary}</strong>
                  <p>{candidateAmount} · {territory}</p>
                </div>
                <Link
                  to={companySignalHref(candidate)}
                  aria-label={interpolate(copy.openAward, { title: candidateSummary })}
                >
                  <ArrowRight aria-hidden="true" />
                </Link>
              </article>
            )
          }) : <p className="companies-panel-note">{copy.noOtherAwards}</p>}
        </section>
      </div>
    </section>
  )
}

export function CompanyDetailMessage({
  panelRef,
  title,
  body,
  retry,
  busy = false,
  tone = 'status',
  backToList,
}: {
  panelRef: RefObject<HTMLElement | null>
  title: string
  body: string
  retry?: () => void
  busy?: boolean
  tone?: 'status' | 'alert' | null
  backToList?: () => void
}) {
  const { t } = useI18n()
  return (
    <section
      ref={panelRef}
      className="company-detail"
      data-master-detail-pane="detail"
      id="company-detail"
      aria-labelledby="company-name"
      aria-live={tone === 'status' ? 'polite' : undefined}
      aria-busy={busy || (tone === 'status' && title === t.reference.loading)}
      role={tone ?? undefined}
    >
      {backToList ? (
        <button type="button" className={styles.mobileBack} onClick={backToList}>
          <ArrowLeft aria-hidden="true" /> {t.reference.companiesPage.backToAwards}
        </button>
      ) : null}
      <header className="company-detail-hero">
        <div className="company-identity-heading">
          <span className="company-hero-avatar" aria-hidden="true">—</span>
          <div>
            <p className="section-label">{t.reference.companiesPage.awardContext}</p>
            <h2 id="company-name" tabIndex={-1}>{title}</h2>
            <p>{body}</p>
            {retry ? <button type="button" className="primary-action" onClick={retry}>{t.reference.retry}</button> : null}
          </div>
        </div>
      </header>
    </section>
  )
}
