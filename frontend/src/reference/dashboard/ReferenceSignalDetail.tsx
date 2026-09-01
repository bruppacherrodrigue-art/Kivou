import { ArrowRight, ExternalLink, FileCheck2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { CompanyProfile } from '../../api/types'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import { interpolate, useI18n } from '../../i18n'
import type { SignalDetailView } from './models'
import { Button } from './ui/button'
import { Textarea } from './ui/textarea'
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
  companyProfile,
  companyLoading = false,
  companyError = null,
  onRetryCompany,
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
  companyProfile?: CompanyProfile | null
  companyLoading?: boolean
  companyError?: unknown | null
  onRetryCompany?: () => void
  announceLoading?: boolean
  announceError?: boolean
}) {
  const { t, locale, date, amount } = useI18n()
  const copy = t.reference.signalsPage
  const missing = t.reference.missingValue

  if (loading) {
    return (
      <div className="detail-hero" role={announceLoading ? 'status' : undefined} aria-live={announceLoading ? 'polite' : undefined}>
        <div>
          <p className="section-label">{copy.awardSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>{t.reference.loading}</h2>
        </div>
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="detail-hero" role={announceError ? 'alert' : undefined}>
        <div>
          <p className="section-label">{copy.awardSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>{errorTitle ?? copy.signalUnavailable}</h2>
          <p className="detail-summary">{t.reference.messages.loadError}</p>
          <button type="button" className="source-link" onClick={onRetry}>{t.reference.retry}</button>
        </div>
      </div>
    )
  }

  const eventDateLabel = detail.eventDateKind === 'award'
    ? t.reference.fields.signalDateAward
    : detail.eventDateKind === 'notification'
      ? t.reference.fields.signalDateNotification
      : detail.eventDateKind === 'publication'
        ? t.reference.fields.signalDatePublication
        : copy.unknownDate
  const eventDateValue = date(detail.eventDate) ?? missing
  const locationTerritory = detail.facts.location
    ? MVP_TERRITORIES.find((candidate) => candidate.code === detail.facts.location?.country)
    : null
  const location = detail.facts.location
    ? [
        detail.facts.location.locality,
        detail.facts.location.subdivision_code,
        locationTerritory ? territoryLabel(locationTerritory, locale) : detail.facts.location.country,
      ].filter(Boolean).join(', ') || missing
    : missing
  const displayAmount = detail.facts.amount
    ? amount(detail.facts.amount.value, detail.facts.amount.currency) ?? missing
    : missing
  const facts = [
    { label: t.reference.fields.amount, value: displayAmount },
    { label: eventDateLabel, value: eventDateValue },
    { label: t.reference.fields.location, value: location },
    { label: t.reference.fields.signalBuyer, value: detail.buyerName ?? missing },
  ]

  const identity = companyProfile?.official_identity
  const companyName = identity?.name ?? detail.companyName ?? missing
  const companyCountryCode = identity?.country ?? detail.companyCountry
  const companyTerritory = MVP_TERRITORIES.find((candidate) => candidate.code === companyCountryCode)
  const companyCountry = companyTerritory
    ? territoryLabel(companyTerritory, locale)
    : companyCountryCode ?? missing
  const website = safeHttpsUrl(identity?.website_url ?? null)
  const sourceUrl = safeHttpsUrl(detail.facts.sourceUrl)
  const enrichment = detail.winnerEnrichment
  const enrichmentStatus = enrichment?.status === 'pending'
    || enrichment?.status === 'in_progress'
    || enrichment?.status === 'partial'
    || enrichment?.status === 'failed'
    ? enrichment.status
    : detail.factualCompleteness ?? 'to_verify'
  const enrichmentLabel = enrichmentStatus in copy.completenessStatus
    ? copy.completenessStatus[enrichmentStatus as keyof typeof copy.completenessStatus]
    : copy.completenessStatus.to_verify
  const enrichmentMessage = enrichment?.status === 'pending'
    ? copy.enrichmentPending
    : enrichment?.status === 'in_progress'
      ? copy.enrichmentInProgress
      : enrichment?.status === 'failed'
        ? copy.enrichmentFailed
        : null
  const otherAwards = companyProfile?.related_signals.filter(
    (candidate) => candidate.signal_id !== detail.id,
  ) ?? []
  const sourceReference = [detail.sourceSystem, detail.facts.notice].filter(Boolean).join(' · ') || missing
  const missingFields = [...new Set([
    ...detail.missingFacts,
    ...(enrichment?.missing_fields ?? []),
    ...(companyProfile?.coverage.unavailable_fields ?? []),
  ])]
  const missingLabel = (field: string) => (
    copy.missingFieldLabels[field as keyof typeof copy.missingFieldLabels] ?? field
  )
  const noteStatus = noteState === 'saving'
    ? t.reference.saving
    : noteState === 'saved'
      ? t.reference.statuses.noteSaved
      : noteState === 'loading'
        ? t.reference.loading
        : note.trim()
          ? t.reference.statuses.noteAdded
          : t.reference.statuses.noNote

  return (
    <>
      <header className="detail-hero signal-presentation-hero">
        <div>
          <p className="section-label">{copy.winnerCompany}</p>
          <h2 id="detail-title" tabIndex={-1}>{detail.title ?? companyName}</h2>
          <p className="detail-summary">{detail.summary ?? missing}</p>
          <p className="signal-limit" role="note">{copy.analysisUnavailable}</p>
        </div>
        <span className={`published-status data-status-${enrichmentStatus}`}>
          <FileCheck2 aria-hidden="true" /> {enrichmentLabel}
        </span>
      </header>

      <section className="facts-card" aria-labelledby="market-facts-title">
        <div className="card-heading">
          <div>
            <p className="card-kicker">{copy.marketSummary}</p>
            <h3 id="market-facts-title">{t.reference.headings.marketDetails}</h3>
          </div>
        </div>
        <dl className="fact-grid signal-fact-grid">
          {facts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}
        </dl>
        <p className="market-amount-note">{copy.totalAmountLimit}</p>
      </section>

      <section className="company-card signal-company-card" aria-labelledby="winner-company-title">
        <div className="company-heading">
          <div>
            <p className="card-kicker">{copy.companyFacts}</p>
            <h3 id="winner-company-title">{companyName}</h3>
          </div>
        </div>
        {companyLoading ? <p role="status">{copy.companyLoading}</p> : null}
        {companyError ? (
          <p role="alert">
            {copy.companyUnavailable}{' '}
            {onRetryCompany ? <button type="button" className="source-link" onClick={onRetryCompany}>{t.reference.retry}</button> : null}
          </p>
        ) : null}
        <dl className="company-facts">
          <div><dt>{t.reference.fields.company}</dt><dd>{companyName}</dd></div>
          <div><dt>{t.reference.fields.country}</dt><dd>{companyCountry}</dd></div>
          <div><dt>{copy.address}</dt><dd>{identity?.address ?? missing}</dd></div>
          <div>
            <dt>{copy.website}</dt>
            <dd>{website ? <a className="source-link" href={website} target="_blank" rel="noopener noreferrer">{website}<ExternalLink aria-hidden="true" /></a> : missing}</dd>
          </div>
          <div><dt>{copy.lastVerified}</dt><dd>{date(identity?.observed_at ?? enrichment?.last_verified_at ?? null) ?? missing}</dd></div>
        </dl>
        {enrichmentMessage ? <p className="signal-limit" role="status">{enrichmentMessage}</p> : null}
        {detail.companyKey ? (
          <Button asChild className="primary-action company-profile-action">
            <Link to={`/app/companies/${encodeURIComponent(detail.companyKey)}?signal=${encodeURIComponent(detail.id)}`}>
              {copy.viewCompany} <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        ) : null}
      </section>

      <section className="evidence-card" aria-labelledby="award-history-title">
        <div className="card-heading">
          <div><p className="card-kicker">{copy.awardsHistory}</p><h3 id="award-history-title">{copy.awardsHistory}</h3></div>
        </div>
        {otherAwards.length > 0 ? (
          <ul className="questions-list">
            {otherAwards.map((award) => (
              <li key={award.signal_id}>
                <Link to={`/app/signals/${encodeURIComponent(award.signal_id)}`}>{award.contract_title ?? missing}</Link>
                <span>{award.amount ? amount(award.amount.value, award.amount.currency) ?? missing : missing} · {date(award.event.date) ?? missing}</span>
              </li>
            ))}
          </ul>
        ) : <p>{copy.noOtherAwards}</p>}
      </section>

      <section className="evidence-card" aria-labelledby="source-evidence-title">
        <div className="card-heading">
          <div><p className="card-kicker">{copy.sourceAndEvidence}</p><h3 id="source-evidence-title">{copy.sourceAndEvidence}</h3></div>
          <span>{sourceReference}</span>
        </div>
        {detail.publicEvidence.length > 0 ? (
          <div className="presentation-claim-groups">
            {detail.publicEvidence.map((group, groupIndex) => (
              <section key={`${group.fact}-${groupIndex}`} aria-label={interpolate(copy.evidenceFor, { fact: group.label })}>
                <h4>{group.label}</h4>
                <ul>
                  {group.items.map((item, index) => (
                    <li key={`${group.fact}-${index}`}>
                      <p>{item.excerpt ?? ([item.source_system, item.notice_id].filter(Boolean).join(' · ') || missing)}</p>
                      {safeHttpsUrl(item.url) ? <a className="source-link" href={safeHttpsUrl(item.url)!} target="_blank" rel="noopener noreferrer">{copy.openNotice}<ExternalLink aria-hidden="true" /></a> : null}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        ) : <p>{copy.companyUnavailable}</p>}
        {sourceUrl ? <a className="source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">{copy.openNotice} <ExternalLink aria-hidden="true" /></a> : null}
      </section>

      <section className="verification-card" aria-labelledby="missing-data-title">
        <div className="card-heading">
          <div><p className="card-kicker">{copy.missingData}</p><h3 id="missing-data-title">{copy.missingData}</h3></div>
        </div>
        {missingFields.length > 0 ? <ul className="questions-list">{missingFields.map((field) => <li key={field}>{missingLabel(field)}</li>)}</ul> : <p>{copy.noMissingData}</p>}
      </section>

      <section className="signal-note-card" aria-labelledby="signal-note-title">
        <div className="card-heading">
          <div><p className="card-kicker">{copy.yourSpace}</p><h3 id="signal-note-title">{t.reference.headings.signalNote}</h3></div>
          <span>{copy.privateNote}</span>
        </div>
        <Textarea
          aria-label={t.reference.headings.signalNote}
          aria-describedby="signal-note-help signal-note-state"
          value={note}
          maxLength={500}
          placeholder={copy.notePlaceholder}
          disabled={noteState === 'loading' || noteState === 'read-error'}
          onChange={(event) => onNoteChange(event.target.value)}
          onBlur={onNoteBlur}
        />
        <div className="signal-note-footer">
          <p id="signal-note-help">{copy.noteHelp}</p>
          {noteError ? (
            <span id="signal-note-state" role="alert">
              {noteState === 'read-error' ? t.reference.messages.noteLoadError : t.reference.messages.noteError}{' '}
              <button type="button" className="shell-resource-retry" onClick={onRetryNote}>{t.reference.retry}</button>
            </span>
          ) : <span id="signal-note-state" role="status">{noteStatus}</span>}
        </div>
      </section>

      <details className="facts-card">
        <summary>{copy.verificationDetails}</summary>
        <dl className="company-facts">
          <div><dt>{t.reference.fields.officialSource}</dt><dd>{sourceReference}</dd></div>
          <div><dt>CPV</dt><dd>{detail.facts.cpv ?? missing}</dd></div>
          <div><dt>{t.reference.fields.officialTitle}</dt><dd>{detail.facts.officialTitle ?? missing}</dd></div>
          {(identity?.identifiers ?? (detail.companyIdentifier ? [detail.companyIdentifier] : [])).map((identifier, index) => (
            <div key={`${identifier.scheme}-${identifier.value}-${index}`}>
              <dt>{t.reference.fields.identifier}</dt>
              <dd>{[identifier.scheme, identifier.value].filter(Boolean).join(' ') || missing}</dd>
            </div>
          ))}
        </dl>
        {enrichment?.source.retrieved_at ? <p>{interpolate(copy.retrievedOn, { date: date(enrichment.source.retrieved_at) ?? missing })}</p> : null}
      </details>
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
