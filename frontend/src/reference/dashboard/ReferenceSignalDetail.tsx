import { ArrowRight, ExternalLink, FileCheck2, Info } from 'lucide-react'
import { interpolate, useI18n } from '../../i18n'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import type { SignalDetailView } from './models'
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
  const missing = t.reference.missingValue

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
  const presentationMode = presentation?.status === 'PASS'
    ? 'full'
    : presentation?.status === 'FALLBACK'
      ? 'factualFallback'
      : 'unavailable'
  const presentationStatus = t.reference.signalsPage.presentationStatus[presentationMode]
  const eventDateLabel = detail.eventDateKind === 'award'
    ? t.reference.fields.signalDateAward
    : detail.eventDateKind === 'notification'
      ? t.reference.fields.signalDateNotification
      : t.reference.fields.signalDatePublication
  const eventDateValue = date(detail.eventDate) ?? missing
  const locationTerritory = detail.facts.location
    ? MVP_TERRITORIES.find((candidate) => candidate.code === detail.facts.location?.country)
    : null
  const location = detail.facts.location
    ? [
        detail.facts.location.locality,
        detail.facts.location.postal_code,
        locationTerritory
          ? territoryLabel(locationTerritory, locale)
          : detail.facts.location.country,
      ].filter(Boolean).join(', ') || missing
    : missing
  const displayAmount = detail.facts.amount
    ? amount(detail.facts.amount.value, detail.facts.amount.currency) ?? missing
    : missing
  const facts = [
    { label: t.reference.fields.amount, value: displayAmount },
    { label: eventDateLabel, value: eventDateValue },
    { label: t.reference.fields.location, value: location },
    { label: t.reference.fields.execution, value: detail.facts.execution ?? missing },
    { label: t.reference.fields.signalBuyer, value: detail.buyerName ?? missing },
    { label: t.reference.fields.signalAwardee, value: detail.awardedCompanyName ?? missing },
    { label: t.reference.fields.officialTitle, value: detail.facts.officialTitle ?? missing },
  ]
  const sourceReference = [detail.sourceSystem, detail.facts.notice].filter(Boolean).join(' ') || missing
  const noticeReference = detail.sourceSystem && detail.facts.notice
    ? interpolate(t.reference.signalsPage.noticeReference, {
        source: detail.sourceSystem,
        notice: detail.facts.notice,
      })
    : sourceReference
  const sourceUrl = safeHttpsUrl(detail.facts.sourceUrl)
  const companyIdentifier = detail.companyIdentifier
    ? [detail.companyIdentifier.scheme, detail.companyIdentifier.value].filter(Boolean).join(' ')
    : ''
  const companyTerritory = MVP_TERRITORIES.find(
    (candidate) => candidate.code === detail.companyCountry,
  )
  const companyCountry = companyTerritory
    ? territoryLabel(companyTerritory, locale)
    : detail.companyCountry ?? missing
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
        FACT: presentation.content.claims.filter((claim) => claim.kind === 'FACT'),
        INFERENCE: presentation.content.claims.filter((claim) => claim.kind === 'INFERENCE'),
        RECOMMENDATION: presentation.content.claims.filter(
          (claim) => claim.kind === 'RECOMMENDATION',
        ),
      }
    : null

  return (
    <>
      <div className="detail-hero signal-presentation-hero">
        <div>
          <p className="section-label">{t.reference.signalsPage.awardSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>
            {presentation?.content.headline ?? t.reference.signalsPage.presentationNotPublished}
          </h2>
          <p className="detail-summary">
            {presentation?.content.award_summary
              ?? t.reference.signalsPage.presentationUnavailableBody}
          </p>
          <dl className="signal-context-row">
            <div>
              <dt>{t.reference.fields.signalAwardee}</dt>
              <dd>{detail.awardedCompanyName ?? missing}</dd>
            </div>
            <div><dt>{t.reference.fields.amount}</dt><dd>{displayAmount}</dd></div>
            <div><dt>{t.reference.fields.location}</dt><dd>{location}</dd></div>
            <div><dt>{eventDateLabel}</dt><dd>{eventDateValue}</dd></div>
          </dl>
        </div>
        <span className={`published-status presentation-${presentationMode}`}>
          {presentation
            ? <FileCheck2 aria-hidden="true" data-presentation-icon="published" />
            : <Info aria-hidden="true" data-presentation-icon="unpublished" />}{' '}
          {presentationStatus}
        </span>
      </div>

      <div className={`prototype-notice presentation-notice presentation-${presentationMode}`} role="note">
        <Info aria-hidden="true" />
        <p>
          {presentation?.status === 'PASS'
            ? t.reference.signalsPage.presentationDataNotice
            : presentation?.status === 'FALLBACK'
              ? t.reference.signalsPage.factualFallbackBody
              : t.reference.signalsPage.dataNotice}
        </p>
      </div>

      {presentation?.status !== 'PASS' ? (
        <p className="signal-limit">
          <span>{t.reference.fields.signalTargetRoleUnavailable}</span>.{' '}
          {t.reference.signalsPage.noEnrichedContact}
        </p>
      ) : null}

      {presentation?.status === 'PASS' ? (
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
              <p>{presentation.content.commercial_importance}</p>
            </div>
            <div>
              <span>{t.reference.signalsPage.fitReason}</span>
              <p>{presentation.content.fit_reason}</p>
            </div>
            <div>
              <span>{t.reference.signalsPage.timing}</span>
              <p>{presentation.content.timing}</p>
            </div>
            <div>
              <span>{t.reference.signalsPage.recommendedAction}</span>
              <p>{presentation.content.recommended_action}</p>
            </div>
          </div>
          <div className="presentation-targets">
            <span>{t.reference.signalsPage.targetRoles}</span>
            <ul>
              {presentation.content.target_roles.map((target) => (
                <li key={target.role}>
                  <strong>{t.reference.signalsPage.targetRoleLabels[target.role]}</strong>
                  <span>{target.rationale}</span>
                  <small>{t.reference.signalsPage.linkedEvidence}</small>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {presentation ? (
        <section className="evidence-card presentation-claims" aria-labelledby="presentation-claims-title">
          <div className="card-heading">
            <div>
              <p className="card-kicker">
                {presentation.status === 'PASS'
                  ? t.reference.signalsPage.qualifiedClaims
                  : t.reference.signalsPage.publishedFacts}
              </p>
              <h3 id="presentation-claims-title">
                {presentation.status === 'PASS'
                  ? t.reference.signalsPage.qualifiedClaims
                  : t.reference.signalsPage.publishedFacts}
              </h3>
            </div>
          </div>
          <div className="presentation-claim-groups">
            {(['FACT', 'INFERENCE', 'RECOMMENDATION'] as const).map((kind) => {
              const claims = claimsByKind?.[kind] ?? []
              return claims.length > 0 ? (
                <section key={kind} aria-labelledby={`claim-kind-${kind}`}>
                  <h4 id={`claim-kind-${kind}`}>
                    {t.reference.signalsPage.claimKinds[kind]}
                  </h4>
                  <ul>
                    {claims.map((claim) => {
                      const confidence = claim.kind === 'INFERENCE'
                        ? t.reference.signalsPage.confidence[claim.confidence]
                        : null
                      return (
                        <li key={claim.claim_id}>
                          <p>{claim.text}</p>
                          <span>
                            {[confidence, t.reference.signalsPage.linkedEvidence]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              ) : null
            })}
          </div>
        </section>
      ) : null}

      {presentation && presentation.content.unknowns.length > 0 ? (
        <section className="verification-card presentation-unknowns" aria-labelledby="unknowns-title">
          <div className="card-heading">
            <div>
              <p className="card-kicker">{t.reference.signalsPage.unknowns}</p>
              <h3 id="unknowns-title">{t.reference.signalsPage.unknowns}</h3>
            </div>
          </div>
          <ul className="questions-list">
            {presentation.content.unknowns.map((unknown) => (
              <li key={unknown.text}>
                <p>{unknown.text}</p>
                <span>{t.reference.signalsPage.linkedEvidence}</span>
              </li>
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

        <div className="facts-source-row">
          <div>
            <FileCheck2 aria-hidden="true" />
            <p>
              <span>{t.reference.fields.officialSource}</span>
              <strong>
                {[sourceReference, detail.facts.cpv ? `CPV ${detail.facts.cpv}` : null]
                  .filter(Boolean)
                  .join(' · ') || missing}
              </strong>
            </p>
          </div>
          {sourceUrl ? (
            <a
              className="source-link"
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t.reference.signalsPage.openNotice} <ExternalLink aria-hidden="true" />
            </a>
          ) : null}
        </div>
      </section>

      <div className="detail-columns signal-support-grid">
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

        <aside className="company-card signal-company-card" aria-labelledby="company-title">
          <div className="company-heading">
            <div>
              <p className="card-kicker">{t.reference.signalsPage.contractHolder}</p>
              <h3 id="company-title">{detail.companyName ?? missing}</h3>
            </div>
          </div>
          <dl className="company-facts">
            <div>
              <dt>{t.reference.fields.company}</dt>
              <dd>{detail.companyName ?? missing}</dd>
            </div>
            <div>
              <dt>{t.reference.fields.country}</dt>
              <dd>{companyCountry}</dd>
            </div>
            <div>
              <dt>{t.reference.fields.identifier}</dt>
              <dd>{companyIdentifier || missing}</dd>
            </div>
          </dl>
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
        </aside>
      </div>
    </>
  )
}

function safeHttpsUrl(value: string | null): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'https:' ? parsed.toString() : null
  } catch {
    return null
  }
}
