import type { RefObject } from 'react'
import { ArrowLeft, ArrowRight, Building2, FileCheck2, MapPin, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import type {
  CompanyProfile as CompanyProfilePayload,
  Place,
  SignalEventClock,
} from '../api/types'
import { interpolate, plural, useI18n } from '../i18n'
import { ReferenceLink } from '../reference/router/ReferenceLink'
import styles from './Companies.module.css'

export interface AuthorizedCompanySignal {
  signalId: string
  summary: string | null
  buyerName: string | null
  location: Place | null
  amountValue: string | null
  amountCurrency: string | null
  awardDate: string | null
  eventDate: string | null
  eventClock: SignalEventClock
  fitReason: string | null
  recommendedAction: string | null
  sourceSystem: string | null
  sourceNoticeId: string | null
  sourceUrl: string | null
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

export function CompanyProfileView({
  panelRef,
  profile,
  company,
  signal,
  backToList,
  onSelectSignal,
  selectionFromList,
}: {
  panelRef: RefObject<HTMLElement | null>
  profile: CompanyProfilePayload
  company: AuthorizedCompany
  signal: AuthorizedCompanySignal
  backToList?: () => void
  onSelectSignal: (signalId: string) => void
  selectionFromList: boolean
}) {
  const { t, locale, date, amount } = useI18n()
  const copy = t.reference.companiesPage
  const identity = profile.official_identity
  const localizedCountry = countryLabel(identity.country, locale)
  const partial = profile.coverage.unavailable_fields.length > 0 || !profile.coverage.related_signals_complete
  const summary = signal.summary ?? copy.objectMissing
  const publishedAmount = amount(signal.amountValue, signal.amountCurrency) ?? t.reference.missingValue
  const dateStatementFor = (candidate: AuthorizedCompanySignal) => {
    const publishedAwardDate = date(candidate.awardDate)
    if (publishedAwardDate) return interpolate(copy.awardedOn, { date: publishedAwardDate })
    const observedDate = date(candidate.eventDate)
    if (!observedDate) return copy.awardDateMissing
    if (candidate.eventClock === 'notification') {
      return interpolate(copy.notifiedOn, { date: observedDate })
    }
    if (candidate.eventClock === 'publication') {
      return interpolate(copy.publishedOn, { date: observedDate })
    }
    return interpolate(copy.awardedOn, { date: observedDate })
  }
  const dateStatement = dateStatementFor(signal)
  const territory = placeLabel(signal.location, localizedCountry) ?? copy.territoryMissing
  const otherSignals = company.signals.filter((candidate) => candidate.signalId !== signal.signalId)
  const sourceLabel = [signal.sourceSystem, signal.sourceNoticeId].filter(Boolean).join(' · ')
    || copy.sourceMissing

  return (
    <section
      ref={panelRef}
      className="company-detail"
      id="company-detail"
      aria-labelledby="company-name"
    >
      {backToList ? (
        <button type="button" className={styles.mobileBack} onClick={backToList}>
          <ArrowLeft aria-hidden="true" /> {copy.backToAwards}
        </button>
      ) : null}

      <header className={`company-detail-hero ${styles.contextHero}`}>
        <div>
          <p className="section-label">{copy.awardContext}</p>
          <h2 id="company-name" tabIndex={-1}>{summary}</h2>
          <p>{interpolate(copy.contextLead, { company: identity.name })}</p>
        </div>
      </header>

      {partial ? <p className="companies-panel-note" role="status">{t.companyProfile.partialBody}</p> : null}

      <div className={styles.detailSections}>
        <section className={styles.contextCard} aria-labelledby="selected-award-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.selectedAward}</p>
              <h3 id="selected-award-title">{copy.awardFacts}</h3>
            </div>
            <FileCheck2 aria-hidden="true" />
          </div>
          <article className="company-timeline-item">
            <span className="timeline-marker" aria-hidden="true" />
            <div>
              <time dateTime={signal.awardDate ?? signal.eventDate ?? undefined}>{dateStatement}</time>
              <strong>{summary}</strong>
              <p>{publishedAmount}</p>
            </div>
            <ReferenceLink
              dashboard
              href={`/signals?signal=${encodeURIComponent(signal.signalId)}`}
              aria-label={interpolate(copy.openSignal, { title: summary })}
            >
              <ArrowRight aria-hidden="true" />
            </ReferenceLink>
          </article>
          <dl className={styles.awardFacts}>
            <div><dt>{copy.winningCompany}</dt><dd>{identity.name}</dd></div>
            <div><dt>{copy.publicBuyer}</dt><dd>{signal.buyerName ?? copy.buyerMissing}</dd></div>
            <div><dt>{copy.publishedAmount}</dt><dd>{publishedAmount}</dd></div>
            <div><dt>{copy.awardDate}</dt><dd>{dateStatement}</dd></div>
            <div><dt>{copy.territory}</dt><dd>{territory}</dd></div>
          </dl>
        </section>

        <section className="company-identity-card" aria-labelledby="identity-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.winningCompany}</p>
              <h3 id="identity-title">{t.reference.headings.sourceAssertions}</h3>
            </div>
            <Building2 aria-hidden="true" />
          </div>
          <div className={styles.companyIdentity}>
            <span className="company-hero-avatar" aria-hidden="true">{companyInitials(identity.name)}</span>
            <div>
              <strong>{identity.name}</strong>
              <p>{copy.profileSummary}</p>
            </div>
          </div>
          <dl className="company-identity-list">
            <div><dt>{t.companyProfile.officialName}</dt><dd>{identity.name}</dd></div>
            <div><dt>{t.companyProfile.officialAddress}</dt><dd>{identity.address ?? t.reference.missingValue}</dd></div>
            <div><dt>{t.companyProfile.officialCountry}</dt><dd>{localizedCountry ?? t.reference.missingValue}</dd></div>
          </dl>
          <p className="company-identity-limit">{copy.identityLimit}</p>
        </section>

        <section className={styles.contextCard} aria-labelledby="match-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.matchKicker}</p>
              <h3 id="match-title">{copy.matchTitle}</h3>
            </div>
            <Target aria-hidden="true" />
          </div>
          {signal.fitReason ? (
            <ul className={styles.reasonList}>
              <li>{signal.fitReason}</li>
            </ul>
          ) : <p>{copy.matchMissing}</p>}
        </section>

        <section className="company-roles-card" aria-labelledby="action-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.actionKicker}</p>
              <h3 id="action-title">{copy.actionTitle}</h3>
            </div>
          </div>
          <p>{signal.recommendedAction ?? copy.actionUnavailable}</p>
          <p>{copy.noEnrichedContact}</p>
          <ReferenceLink
            dashboard
            className="primary-action"
            href={`/signals?signal=${encodeURIComponent(signal.signalId)}`}
          >
            {copy.reviewSignal}
          </ReferenceLink>
        </section>

        <section className={styles.contextCard} aria-labelledby="evidence-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.evidenceKicker}</p>
              <h3 id="evidence-title">{copy.evidenceTitle}</h3>
            </div>
            <MapPin aria-hidden="true" />
          </div>
          <div className="company-provenance">
            <FileCheck2 aria-hidden="true" />
            <p><strong>{copy.provenance}</strong> {sourceLabel}</p>
          </div>
          {signal.sourceUrl ? (
            <a className="source-link" href={signal.sourceUrl} target="_blank" rel="noreferrer">
              {copy.openOfficialSource}
            </a>
          ) : <p>{copy.sourceUnavailable}</p>}
        </section>

        <section className="related-signals-card" aria-labelledby="related-title">
          <div className="company-card-heading">
            <div>
              <p className="card-kicker">{copy.documentedContracts}</p>
              <h3 id="related-title">{copy.otherAwards}</h3>
            </div>
            <span>{interpolate(plural(
              otherSignals.length,
              copy.contractOne,
              copy.contractOther,
            ), { count: otherSignals.length })}</span>
          </div>
          {otherSignals.length > 0 ? otherSignals.map((candidate) => {
            const candidateDate = dateStatementFor(candidate)
            const candidateAmount = amount(candidate.amountValue, candidate.amountCurrency)
              ?? t.reference.missingValue
            const candidateSummary = candidate.summary ?? copy.objectMissing
            return (
              <article className="company-timeline-item" key={candidate.signalId}>
                <span className="timeline-marker" aria-hidden="true" />
                <div>
                  <time dateTime={candidate.awardDate ?? candidate.eventDate ?? undefined}>{candidateDate}</time>
                  <strong>{candidateSummary}</strong>
                  <p>{candidateAmount}</p>
                </div>
                <Link
                  to={companyAwardHref(company.key, candidate.signalId)}
                  replace
                  state={{
                    companySelection: {
                      kind: 'company-award',
                      companyKey: company.key,
                      signalId: candidate.signalId,
                      fromList: selectionFromList,
                    },
                  }}
                  aria-label={interpolate(copy.openAward, { title: candidateSummary })}
                  onClick={() => onSelectSignal(candidate.signalId)}
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
  tone = 'status',
  backToList,
}: {
  panelRef: RefObject<HTMLElement | null>
  title: string
  body: string
  retry?: () => void
  tone?: 'status' | 'alert' | null
  backToList?: () => void
}) {
  const { t } = useI18n()
  return (
    <section
      ref={panelRef}
      className="company-detail"
      id="company-detail"
      aria-labelledby="company-name"
      aria-live={tone === 'status' ? 'polite' : undefined}
      aria-busy={tone === 'status' && title === t.reference.loading}
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
