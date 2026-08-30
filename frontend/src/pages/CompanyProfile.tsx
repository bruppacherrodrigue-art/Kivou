import { ArrowRight, FileCheck2, MapPin } from 'lucide-react'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import type { CompanyProfile as CompanyProfilePayload } from '../api/types'
import { interpolate, plural, useI18n } from '../i18n'
import { ReferenceLink } from '../reference/router/ReferenceLink'

export interface AuthorizedCompanySignal {
  signalId: string
  title: string | null
  amountValue: string | null
  amountCurrency: string | null
  awardDate: string | null
}

export interface AuthorizedCompany {
  key: string
  name: string
  country: string | null
  signals: AuthorizedCompanySignal[]
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

export function CompanyProfileView({
  profile,
}: {
  profile: CompanyProfilePayload
}) {
  const { t, locale, date, amount } = useI18n()
  const copy = t.reference.companiesPage
  const identity = profile.official_identity
  const localizedCountry = countryLabel(identity.country, locale)
  const partial = profile.coverage.unavailable_fields.length > 0 || !profile.coverage.related_signals_complete

  return (
    <section className="company-detail" id="company-detail" aria-labelledby="company-name" tabIndex={-1}>
      <header className="company-detail-hero">
        <div className="company-identity-heading">
          <span className="company-hero-avatar" aria-hidden="true">{companyInitials(identity.name)}</span>
          <div>
            <p className="section-label">{t.reference.headings.company}</p>
            <h2 id="company-name">{identity.name}</h2>
            <p>{copy.profileSummary}</p>
          </div>
        </div>
      </header>

      <div className="company-provenance">
        <FileCheck2 aria-hidden="true" />
        <p><strong>{copy.provenance}</strong> {t.companyProfile.publicNotice}.</p>
      </div>

      {partial ? <p className="companies-panel-note" role="status">{t.companyProfile.partialBody}</p> : null}

      <div className="company-detail-layout company-detail-layout-simple">
        <div className="company-main-column">
          <section className="related-signals-card" aria-labelledby="related-title">
            <div className="company-card-heading">
              <div>
                <p className="card-kicker">{copy.documentedContracts}</p>
                <h3 id="related-title">{t.reference.headings.associatedAwards}</h3>
              </div>
              <span>{interpolate(plural(
                profile.related_signals.length,
                copy.contractOne,
                copy.contractOther,
              ), { count: profile.related_signals.length })}</span>
            </div>

            {profile.related_signals.length > 0 ? profile.related_signals.map((signal) => {
              const eventDate = date(signal.event.date) ?? t.reference.missingValue
              const publishedAmount = signal.amount
                ? amount(signal.amount.value, signal.amount.currency) ?? t.reference.missingValue
                : t.reference.missingValue
              const title = signal.contract_title ?? signal.event.headline
              return (
                <article className="company-timeline-item" key={signal.signal_id}>
                  <span className="timeline-marker" aria-hidden="true" />
                  <div>
                    <time dateTime={signal.event.date ?? undefined}>{eventDate}</time>
                    <strong>{title}</strong>
                    <p>{publishedAmount} · {signal.event.why_now}</p>
                  </div>
                  <ReferenceLink
                    dashboard
                    href={`/signals?signal=${encodeURIComponent(signal.signal_id)}`}
                    aria-label={interpolate(copy.openSignal, { title })}
                  >
                    <ArrowRight aria-hidden="true" />
                  </ReferenceLink>
                </article>
              )
            }) : <p className="companies-panel-note">{t.reference.messages.empty}</p>}
          </section>
        </div>

        <aside className="company-side-column">
          <section className="company-identity-card" aria-labelledby="identity-title">
            <div className="company-card-heading">
              <div>
                <p className="card-kicker">{t.reference.headings.publishedIdentity}</p>
                <h3 id="identity-title">{t.reference.headings.sourceAssertions}</h3>
              </div>
              <MapPin aria-hidden="true" />
            </div>

            <dl className="company-identity-list">
              <div><dt>{t.companyProfile.officialName}</dt><dd>{identity.name}</dd></div>
              <div><dt>{t.companyProfile.officialAddress}</dt><dd>{identity.address ?? t.reference.missingValue}</dd></div>
              <div><dt>{t.companyProfile.officialCountry}</dt><dd>{localizedCountry ?? t.reference.missingValue}</dd></div>
            </dl>
            <p className="company-identity-limit">{copy.identityLimit}</p>
          </section>

          <section className="company-roles-card" aria-labelledby="roles-title">
            <div className="company-card-heading">
              <div>
                <p className="card-kicker">{copy.toResearch}</p>
                <h3 id="roles-title">{t.reference.headings.usefulRoles}</h3>
              </div>
            </div>
            <ul className="company-roles-list">
              {[0, 1, 2].map((slot) => <li key={slot}>{t.reference.missingValue}</li>)}
            </ul>
            <p>{copy.noEnrichedContact}</p>
          </section>
        </aside>
      </div>
    </section>
  )
}

export function CompanyDetailMessage({
  title,
  body,
  retry,
  tone = 'status',
}: {
  title: string
  body: string
  retry?: () => void
  tone?: 'status' | 'alert' | null
}) {
  const { t } = useI18n()
  return (
    <section
      className="company-detail"
      id="company-detail"
      aria-labelledby="company-name"
      role={tone ?? undefined}
      tabIndex={-1}
    >
      <header className="company-detail-hero">
        <div className="company-identity-heading">
          <span className="company-hero-avatar" aria-hidden="true">—</span>
          <div>
            <p className="section-label">{t.reference.headings.company}</p>
            <h2 id="company-name">{title}</h2>
            <p>{body}</p>
            {retry ? <button type="button" className="primary-action" onClick={retry}>{t.reference.retry}</button> : null}
          </div>
        </div>
      </header>
    </section>
  )
}
