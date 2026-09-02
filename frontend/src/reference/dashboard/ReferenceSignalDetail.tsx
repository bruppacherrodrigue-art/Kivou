import { ArrowRight, ExternalLink, FileCheck2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { CompanyProfile } from '../../api/types'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import { useI18n } from '../../i18n'
import type { SignalDetailView } from './models'
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
      <article className="signal-document">
        <div className="detail-hero" role={announceLoading ? 'status' : undefined} aria-live={announceLoading ? 'polite' : undefined}>
          <div>
            <p className="section-label">{copy.awardSignal}</p>
            <h2 id="detail-title" tabIndex={-1}>{t.reference.loading}</h2>
          </div>
        </div>
      </article>
    )
  }

  if (error || !detail) {
    return (
      <article className="signal-document">
        <div className="detail-hero" role={announceError ? 'alert' : undefined}>
          <div>
            <p className="section-label">{copy.awardSignal}</p>
            <h2 id="detail-title" tabIndex={-1}>{errorTitle ?? copy.signalUnavailable}</h2>
            <p className="detail-summary">{t.reference.messages.loadError}</p>
            <button type="button" className="source-link" onClick={onRetry}>{t.reference.retry}</button>
          </div>
        </div>
      </article>
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
  const sourceUrl = safeHttpsUrl(detail.facts.sourceUrl)
  const factualStatus = detail.factualCompleteness ?? 'to_verify'
  const commercialPresentation = detail.presentation?.status === 'PASS'
    && detail.presentation.content.variant === 'FULL'
    ? detail.presentation.content
    : null
  const missingFields = [...new Set(detail.missingFacts)].slice(0, 3)
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
    <article className="signal-document">
      <header className="detail-hero signal-presentation-hero">
        <div>
          <p className="section-label">{copy.winnerCompany}</p>
          <h2 id="detail-title" tabIndex={-1}>{detail.title ?? companyName}</h2>
          <p className="detail-summary">{detail.summary ?? missing}</p>
          {commercialPresentation ? (
            <p className="signal-limit" role="note">{copy.presentationDataNotice}</p>
          ) : null}
        </div>
        <span className={`published-status data-status-${factualStatus}`}>
          <FileCheck2 aria-hidden="true" />
          {commercialPresentation ? copy.presentationStatus.full : t.reference.fields.officialSource}
        </span>
      </header>

      {commercialPresentation ? (
        <section className="commercial-brief-card" aria-labelledby="commercial-brief-title">
          <div className="card-heading">
            <div>
              <p className="card-kicker">{copy.commercialConclusion}</p>
              <h3 id="commercial-brief-title">{copy.commercialBrief}</h3>
            </div>
          </div>
          <div className="commercial-brief-grid">
            <div>
              <span>{copy.commercialImportance}</span>
              <p>{commercialPresentation.commercial_importance}</p>
            </div>
            <div>
              <span>{copy.fitReason}</span>
              <p>{commercialPresentation.fit_reason}</p>
            </div>
            <div>
              <span>{copy.timing}</span>
              <p>{commercialPresentation.timing}</p>
            </div>
            <div>
              <span>{copy.recommendedAction}</span>
              <p>{commercialPresentation.recommended_action}</p>
            </div>
          </div>
          <div className="presentation-targets" aria-labelledby="commercial-target-roles">
            <span id="commercial-target-roles">{copy.targetRoles}</span>
            <ul>
              {commercialPresentation.target_roles.map((target) => (
                <li key={target.role}>
                  <strong>{copy.targetRoleLabels[target.role]}</strong>
                  <small>{target.rationale}</small>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

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
        <div className="facts-source-row">
          {sourceUrl ? (
            <a className="source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">
              {copy.openNotice} <ExternalLink aria-hidden="true" />
            </a>
          ) : null}
        </div>
      </section>

      <section className="company-card signal-company-card" aria-labelledby="winner-company-title">
        <div className="company-heading">
          <div>
            <p className="card-kicker">{copy.contractHolder}</p>
            <h3 id="winner-company-title">{companyName}</h3>
          </div>
        </div>
        {detail.companyKey ? (
          <Link
            className="company-sheet-link"
            to={`/app/companies/${encodeURIComponent(detail.companyKey)}?signal=${encodeURIComponent(detail.id)}`}
          >
            {copy.viewCompany} <ArrowRight aria-hidden="true" />
          </Link>
        ) : null}
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
    </article>
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
