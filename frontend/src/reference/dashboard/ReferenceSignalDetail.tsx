import { ArrowRight, ExternalLink, FileCheck2, Info } from 'lucide-react'
import type { Place } from '../../api/types'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import { interpolate, type Locale, useI18n } from '../../i18n'
import type { SignalDetailView, SignalPresentationClaimView } from './models'
import { Button } from './ui/button'
import { Textarea } from './ui/textarea'
import { ReferenceLink } from '../router/ReferenceLink'
import type { NoteSaveState } from './useSignalNote'

export function ReferenceSignalDetail({
  detail,
  loading,
  error,
  errorTitle,
  onRetry,
  note,
  noteState,
  noteError,
  onNoteChange,
  onNoteBlur,
  onRetryNote,
  announceLoading = true,
  announceError = true,
}: {
  detail: SignalDetailView | null
  loading: boolean
  error: unknown | null
  errorTitle?: string
  onRetry: () => void
  note: string
  noteState: NoteSaveState
  noteError: unknown | null
  onNoteChange: (value: string) => void
  onNoteBlur: () => void
  onRetryNote: () => void
  announceLoading?: boolean
  announceError?: boolean
}) {
  const { t, locale, date, amount } = useI18n()

  if (loading) {
    return (
      <div
        className="detail-hero"
        role={announceLoading ? 'status' : undefined}
        aria-live={announceLoading ? 'polite' : undefined}
      >
        <div>
          <p className="section-label">{t.reference.signalsPage.awardSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>{t.reference.loading}</h2>
        </div>
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="detail-hero" role={announceError ? 'alert' : undefined}>
        <div>
          <p className="section-label">{t.reference.signalsPage.awardSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>
            {errorTitle ?? t.reference.signalsPage.signalUnavailable}
          </h2>
          <p className="detail-summary">{t.reference.messages.loadError}</p>
          <button type="button" className="source-link" onClick={onRetry}>
            {t.reference.retry}
          </button>
        </div>
      </div>
    )
  }

  const presentation = detail.presentation
  const presentationMode = presentation?.mode ?? 'unavailable'
  const presentationStatus = t.reference.signalsPage.presentationStatus[presentationMode]
  const eventDateLabel = {
    award: t.reference.fields.awardDate,
    notification: t.reference.fields.notificationDate,
    publication: t.reference.fields.publicationDate,
  }[detail.facts.eventDateKind]
  const eventDateValue = detail.facts.eventDate
    ? date(detail.facts.eventDate) ?? t.reference.signalsPage.missingDates[detail.facts.eventDateKind]
    : t.reference.signalsPage.missingDates[detail.facts.eventDateKind]
  const location = placeLabel(detail.facts.location, locale)
  const facts = [
    {
      label: t.reference.fields.amount,
      value: detail.facts.amount
        ? amount(detail.facts.amount.value, detail.facts.amount.currency)
          ?? t.reference.signalsPage.missingAmount
        : t.reference.signalsPage.missingAmount,
    },
    { label: eventDateLabel, value: eventDateValue },
    {
      label: t.reference.fields.location,
      value: location ?? t.reference.signalsPage.missingLocation,
    },
    {
      label: t.reference.fields.execution,
      value: detail.facts.execution ?? t.reference.signalsPage.missingExecution,
    },
    {
      label: t.reference.fields.buyer,
      value: detail.facts.buyer ?? t.reference.signalsPage.missingBuyer,
    },
  ]
  const sourceReference = [detail.sourceSystem, detail.facts.notice].filter(Boolean).join(' ')
  const noticeReference = detail.sourceSystem && detail.facts.notice
    ? interpolate(t.reference.signalsPage.noticeReference, {
        source: detail.sourceSystem,
        notice: detail.facts.notice,
      })
    : sourceReference || t.reference.missingValue
  const companyIdentifier = detail.companyIdentifier
    ? [detail.companyIdentifier.scheme, detail.companyIdentifier.value].filter(Boolean).join(' ')
    : ''
  const companyTerritory = MVP_TERRITORIES.find(
    (candidate) => candidate.code === detail.companyCountry,
  )
  const companyCountry = companyTerritory
    ? territoryLabel(companyTerritory, locale)
    : detail.companyCountry ?? t.reference.missingValue
  const noteStatus = noteState === 'saving'
    ? t.reference.saving
    : noteState === 'saved'
      ? t.reference.statuses.noteSaved
      : noteState === 'loading'
        ? t.reference.loading
        : note.trim()
          ? t.reference.statuses.noteAdded
          : t.reference.statuses.noNote
  const claimsByKind = presentation
    ? {
        FACT: presentation.claims.filter((claim) => claim.kind === 'FACT'),
        INFERENCE: presentation.claims.filter((claim) => claim.kind === 'INFERENCE'),
        RECOMMENDATION: presentation.claims.filter((claim) => claim.kind === 'RECOMMENDATION'),
      }
    : null
  const claimsHeading = presentation?.mode === 'factualFallback'
    ? t.reference.signalsPage.publishedFacts
    : t.reference.signalsPage.qualifiedClaims

  return (
    <>
      <div className="detail-hero signal-presentation-hero">
        <div>
          <p className="section-label">{t.reference.signalsPage.awardSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>
            {presentation?.headline ?? t.reference.signalsPage.presentationUnavailableTitle}
          </h2>
          <p className="detail-summary">
            {presentation?.awardSummary ?? t.reference.signalsPage.presentationUnavailableBody}
          </p>
          <dl className="signal-context-row">
            <div>
              <dt>{t.reference.fields.company}</dt>
              <dd>{detail.companyName ?? t.reference.missingValue}</dd>
            </div>
            <div>
              <dt>{t.reference.fields.amount}</dt>
              <dd>{facts[0].value}</dd>
            </div>
            <div>
              <dt>{t.reference.fields.location}</dt>
              <dd>{facts[2].value}</dd>
            </div>
            <div>
              <dt>{eventDateLabel}</dt>
              <dd>{eventDateValue}</dd>
            </div>
          </dl>
        </div>
        <div className="signal-hero-actions">
          <span className={`published-status presentation-${presentationMode}`}>
            {presentation
              ? <FileCheck2 aria-hidden="true" />
              : <Info aria-hidden="true" />}{' '}
            {presentationStatus}
          </span>
          {detail.companyKey ? (
            <Button asChild className="primary-action company-profile-action">
              <ReferenceLink
                dashboard
                href={`/companies?company=${encodeURIComponent(detail.companyKey)}&signal=${encodeURIComponent(detail.id)}`}
              >
                {t.reference.signalsPage.viewCompany} <ArrowRight aria-hidden="true" />
              </ReferenceLink>
            </Button>
          ) : null}
        </div>
      </div>

      {presentation ? (
        <div
          className={`prototype-notice presentation-notice presentation-${presentationMode}`}
          role="note"
        >
          <Info aria-hidden="true" />
          <p>
            {presentationMode === 'full'
              ? t.reference.signalsPage.presentationDataNotice
              : t.reference.signalsPage.factualFallbackBody}
          </p>
        </div>
      ) : null}

      {presentation?.mode === 'full' ? (
        <section className="commercial-brief-card" aria-labelledby="commercial-conclusion-title">
          <div className="card-heading">
            <div>
              <p className="card-kicker">{t.reference.signalsPage.commercialConclusion}</p>
              <h3 id="commercial-conclusion-title">
                {t.reference.signalsPage.commercialConclusion}
              </h3>
            </div>
          </div>
          <div className="commercial-brief-grid">
            <div>
              <span>{t.reference.signalsPage.commercialImportance}</span>
              <p>{presentation.commercialImportance}</p>
            </div>
            <div>
              <span>{t.reference.signalsPage.fitReason}</span>
              <p>{presentation.fitReason}</p>
            </div>
            <div>
              <span>{t.reference.signalsPage.timing}</span>
              <p>{presentation.timing}</p>
            </div>
            <div>
              <span>{t.reference.signalsPage.recommendedAction}</span>
              <p>{presentation.recommendedAction}</p>
            </div>
          </div>
          <div className="presentation-targets">
            <span>{t.reference.signalsPage.targetRoles}</span>
            <ul>
              {presentation.targetRoles.map((role) => (
                <li key={role}>{t.reference.signalsPage.targetRoleLabels[role]}</li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {presentation && presentation.claims.length > 0 ? (
        <section className="evidence-card presentation-claims" aria-labelledby="presentation-claims-title">
          <div className="card-heading">
            <div>
              <p className="card-kicker">{claimsHeading}</p>
              <h3 id="presentation-claims-title">{claimsHeading}</h3>
            </div>
          </div>
          <div className="presentation-claim-groups">
            {(['FACT', 'INFERENCE', 'RECOMMENDATION'] as const).map((kind) => {
              const claims = claimsByKind?.[kind] ?? []
              return claims.length > 0 ? (
                <section key={kind} aria-labelledby={`claim-kind-${kind}`}>
                  <h4 id={`claim-kind-${kind}`}>{t.reference.signalsPage.claimKinds[kind]}</h4>
                  <ul>
                    {claims.map((claim) => (
                      <ClaimItem key={claim.id} claim={claim} />
                    ))}
                  </ul>
                </section>
              ) : null
            })}
          </div>
        </section>
      ) : null}

      {presentation && presentation.unknowns.length > 0 ? (
        <section className="verification-card presentation-unknowns" aria-labelledby="unknowns-title">
          <div className="card-heading">
            <div>
              <p className="card-kicker">{t.reference.signalsPage.unknowns}</p>
              <h3 id="unknowns-title">{t.reference.signalsPage.unknowns}</h3>
            </div>
          </div>
          <ul className="questions-list">
            {presentation.unknowns.map((unknown, index) => (
              <li key={`${index}-${unknown}`}>{unknown}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="facts-card" aria-labelledby="facts-title">
        <div className="card-heading">
          <div>
            <p className="card-kicker">{t.reference.signalsPage.publishedFacts}</p>
            <h3 id="facts-title">{t.reference.headings.marketDetails}</h3>
          </div>
          <span>{noticeReference}</span>
        </div>

        <dl className="fact-grid signal-fact-grid">
          {facts.map((fact) => (
            <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>
          ))}
        </dl>
        <p className="market-amount-note">{t.reference.signalsPage.totalAmountLimit}</p>

        <details className="signal-source-disclosure">
          <summary>{t.reference.signalsPage.sourceAndFacts}</summary>
          <dl>
            <div>
              <dt>{t.reference.signalsPage.officialTitle}</dt>
              <dd>{detail.facts.officialTitle ?? t.reference.signalsPage.missingOfficialTitle}</dd>
            </div>
            <div>
              <dt>{t.reference.fields.officialSource}</dt>
              <dd>
                {[sourceReference, detail.facts.cpv ? `CPV ${detail.facts.cpv}` : null]
                  .filter(Boolean)
                  .join(' · ') || t.reference.missingValue}
              </dd>
            </div>
          </dl>
          {detail.facts.sourceUrl ? (
            <a
              className="source-link"
              href={detail.facts.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t.reference.signalsPage.openNotice} <ExternalLink aria-hidden="true" />
            </a>
          ) : null}
        </details>
      </section>

      <aside className="company-card signal-company-card" aria-labelledby="company-title">
        <div className="company-heading">
          <div>
            <p className="card-kicker">{t.reference.signalsPage.contractHolder}</p>
            <h3 id="company-title">{detail.companyName ?? t.reference.missingValue}</h3>
          </div>
        </div>
        <dl className="company-facts">
          <div>
            <dt>{t.reference.fields.country}</dt>
            <dd>{companyCountry}</dd>
          </div>
          <div>
            <dt>{t.reference.fields.identifier}</dt>
            <dd>{companyIdentifier || t.reference.missingValue}</dd>
          </div>
        </dl>
      </aside>

      <section className="signal-note-card" aria-labelledby="signal-note-title">
        <div className="card-heading">
          <div>
            <p className="card-kicker">{t.reference.signalsPage.yourSpace}</p>
            <h3 id="signal-note-title">{t.reference.headings.signalNote}</h3>
          </div>
          <span>{t.reference.signalsPage.privateNote}</span>
        </div>
        <Textarea
          aria-label={t.reference.headings.signalNote}
          aria-describedby="signal-note-help signal-note-state"
          value={note}
          maxLength={500}
          placeholder={t.reference.signalsPage.notePlaceholder}
          disabled={noteState === 'loading' || noteState === 'read-error'}
          onChange={(event) => onNoteChange(event.target.value)}
          onBlur={onNoteBlur}
        />
        <div className="signal-note-footer">
          <p id="signal-note-help">{t.reference.signalsPage.noteHelp}</p>
          {noteError ? (
            <span id="signal-note-state" role="alert">
              {noteState === 'read-error'
                ? t.reference.messages.noteLoadError
                : t.reference.messages.noteError}{' '}
              <button type="button" className="shell-resource-retry" onClick={onRetryNote}>
                {t.reference.retry}
              </button>
            </span>
          ) : (
            <span id="signal-note-state" role="status">{noteStatus}</span>
          )}
        </div>
      </section>
    </>
  )

  function ClaimItem({ claim }: { claim: SignalPresentationClaimView }) {
    const metadata = [
      claim.confidence ? t.reference.signalsPage.confidence[claim.confidence] : null,
      claim.evidenceRefs.length > 0 ? t.reference.signalsPage.linkedEvidence : null,
    ].filter((value): value is string => value !== null)
    return (
      <li>
        <p>{claim.text}</p>
        {metadata.length > 0 ? <span>{metadata.join(' · ')}</span> : null}
      </li>
    )
  }
}

function placeLabel(place: Place | null, locale: Locale): string | null {
  if (!place) return null
  const territory = MVP_TERRITORIES.find((candidate) => candidate.code === place.country)
  return [
    place.locality,
    place.postal_code,
    territory ? territoryLabel(territory, locale) : place.country,
  ].filter(Boolean).join(', ') || null
}
