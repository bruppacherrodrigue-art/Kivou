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
          <p className="section-label">{t.reference.headings.selectedSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>{t.reference.loading}</h2>
        </div>
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="detail-hero" role={announceError ? 'alert' : undefined}>
        <div>
          <p className="section-label">{t.reference.headings.selectedSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>{errorTitle ?? t.reference.signalsPage.signalUnavailable}</h2>
          <p className="detail-summary">{t.reference.messages.loadError}</p>
          <button type="button" className="source-link" onClick={onRetry}>
            {t.reference.retry}
          </button>
        </div>
      </div>
    )
  }

  const facts = [
    {
      label: t.reference.fields.amount,
      value: detail.facts.amount
        ? amount(detail.facts.amount.value, detail.facts.amount.currency) ?? missing
        : missing,
    },
    { label: t.reference.fields.awardDate, value: date(detail.facts.awardDate) ?? missing },
    { label: t.reference.fields.execution, value: detail.facts.execution ?? missing },
    { label: t.reference.fields.buyer, value: detail.facts.buyer ?? missing },
  ]
  const scope = detail.scope.length > 0
    ? detail.scope
    : Array.from({ length: 5 }, () => ({
        value: missing,
        label: t.reference.fields.publishedScope,
      }))
  const questions = detail.questions.length > 0
    ? detail.questions
    : Array.from({ length: 3 }, () => missing)
  const sourceReference = [detail.sourceSystem, detail.facts.notice].filter(Boolean).join(' ') || missing
  const noticeReference = detail.sourceSystem && detail.facts.notice
    ? interpolate(t.reference.signalsPage.noticeReference, {
        source: detail.sourceSystem,
        notice: detail.facts.notice,
      })
    : sourceReference
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

  return (
    <>
      <div className="detail-hero">
        <div>
          <p className="section-label">{t.reference.headings.selectedSignal}</p>
          <h2 id="detail-title" tabIndex={-1}>{detail.title ?? missing}</h2>
          <p className="detail-summary">
            {detail.summary ?? detail.brief.whyNow}{' '}
            {t.reference.signalsPage.summaryQualification}
          </p>
        </div>
        <span className="published-status">
          <FileCheck2 aria-hidden="true" />{' '}
          {detail.sourceSystem
            ? interpolate(t.reference.signalsPage.publishedOn, { source: detail.sourceSystem })
            : t.reference.overviewPage.publishedAward}
        </span>
      </div>

      <div className="prototype-notice" role="note">
        <Info aria-hidden="true" />
        <p>{t.reference.signalsPage.dataNotice}</p>
      </div>

      <section className="commercial-brief-card" aria-labelledby="commercial-brief-title">
        <div className="card-heading">
          <div>
            <p className="card-kicker">{t.reference.signalsPage.commercialBrief}</p>
            <h3 id="commercial-brief-title">{t.reference.headings.commercialBrief}</h3>
          </div>
          <span>
            {interpolate(t.reference.signalsPage.targetProfile, {
              profile: detail.targetProfileLabel ?? missing,
            })}
          </span>
        </div>
        <div className="commercial-brief-grid">
          <div><span>{t.reference.fields.whyNow}</span><p>{detail.brief.whyNow}</p></div>
          <div><span>{t.reference.fields.offerCoverage}</span><p>{detail.brief.offerCoverage ?? missing}</p></div>
          <div>
            <span>{t.reference.fields.roleToFind}</span>
            <p>{detail.brief.functionToFind ?? missing}</p>
            <small>{t.reference.signalsPage.noEnrichedContact}</small>
          </div>
          <div><span>{t.reference.fields.unknown}</span><p>{detail.brief.unknown ?? missing}</p></div>
        </div>
      </section>

      <section className="facts-card" aria-labelledby="facts-title">
        <div className="card-heading">
          <div>
            <p className="card-kicker">{t.reference.signalsPage.publishedFacts}</p>
            <h3 id="facts-title">{t.reference.headings.marketDetails}</h3>
          </div>
          <span>{noticeReference}</span>
        </div>

        <dl className="fact-grid">
          {facts.map((fact) => (
            <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>
          ))}
        </dl>
        <p className="market-amount-note">{t.reference.signalsPage.totalAmountLimit}</p>

        <div className="facts-volume-heading">
          <p className="card-kicker">{t.reference.fields.publishedScope}</p>
        </div>
        <div className="volume-grid">
          {scope.map((item, index) => (
            <div className="volume-item" key={`${item.label}-${index}`}>
              <strong>{item.value}</strong>
              <span>{item.label}</span>
            </div>
          ))}
        </div>

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
        </div>
      </section>

      <div className="detail-columns">
        <div className="signal-content">
          <section className="verification-card" aria-labelledby="verification-title">
            <div className="card-heading">
              <div>
                <p className="card-kicker">{t.reference.signalsPage.toConfirm}</p>
                <h3 id="verification-title">{t.reference.headings.questionsBeforeContact}</h3>
              </div>
            </div>
            <ul className="questions-list">
              {questions.map((question, index) => <li key={`${question}-${index}`}>{question}</li>)}
            </ul>
            <p className="signal-limit">{detail.brief.unknown ?? t.reference.signalsPage.verificationLimit}</p>
          </section>
        </div>

        <aside className="company-card" aria-labelledby="company-title">
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
              <ReferenceLink dashboard href={`/companies?company=${encodeURIComponent(detail.companyKey)}`}>
                {t.reference.signalsPage.viewCompany} <ArrowRight aria-hidden="true" />
              </ReferenceLink>
            </Button>
          ) : null}
        </aside>
      </div>

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
}
