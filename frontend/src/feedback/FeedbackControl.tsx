import { useState } from 'react'
import { useI18n, interpolate } from '../i18n'
import { Button } from '../components/Button'
import { Callout, Card } from '../components/Surfaces'
import { TextAreaField } from '../components/FormField'
import { CheckIcon } from '../assets/Icons'
import { feedback as feedbackApi } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import { MAXIMUM_NOTE_LENGTH, NEGATIVE_REASONS } from '../api/types'
import type { Interaction, NegativeReason, Relevance } from '../api/types'
import styles from './FeedbackControl.module.css'

/* Le retour client — deux gestes distincts, jamais fusionnés.
 *
 * « Pertinent / Pas pertinent » est un JUGEMENT sur la qualité du signal.
 * « J'ai contacté cette entreprise » est une ACTION commerciale. Les réunir
 * dans un seul interrupteur rendrait indistinguables « ce signal est bon » et
 * « j'ai fait quelque chose », c'est-à-dire précisément les deux mesures que
 * SPEC-014 sépare : jugement d'un côté, étoile polaire de l'autre.
 *
 * Ces contrôles n'apparaissent JAMAIS sur un aperçu verrouillé : juger suppose
 * d'avoir vu, et le backend refuse d'ailleurs un avis sur un signal non
 * débloqué (403 `signal_not_accessible`).
 */
export function FeedbackControl({
  signalKey,
  initial,
}: {
  signalKey: string
  initial: Interaction | null
}) {
  const { t, date } = useI18n()
  const [interaction, setInteraction] = useState<Interaction | null>(initial)
  const [relevance, setRelevance] = useState<Relevance | null>(initial?.relevance ?? null)
  const [reason, setReason] = useState<NegativeReason | null>(initial?.reason ?? null)
  const [note, setNote] = useState(initial?.note ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [contacting, setContacting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const contacted = interaction?.contacted ?? false

  async function submit() {
    setError(null)
    setSaved(false)

    // Le backend refuse un avis négatif sans raison (422 `invalid_feedback`).
    // Le dire ici évite un aller-retour dont le message serait moins précis.
    if (relevance === 'not_relevant' && reason === null) {
      setReasonError(t.feedback.reasonRequired)
      return
    }
    setReasonError(null)
    if (relevance === null) return

    setSubmitting(true)
    try {
      const result = await feedbackApi.write(signalKey, {
        relevance,
        reason: relevance === 'not_relevant' ? reason : null,
        note: relevance === 'not_relevant' && reason === 'other' && note ? note : null,
      })
      setInteraction(result.interaction)
      setSaved(true)
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  async function contact() {
    setError(null)
    setContacting(true)
    try {
      const result = await feedbackApi.markContacted(signalKey)
      setInteraction(result.interaction)
    } catch (caught) {
      setError(caught)
    } finally {
      setContacting(false)
    }
  }

  const errorCopy = error ? describeError(error, t) : null

  return (
    <div className={styles.wrap}>
      <Card padding="md" as="section">
        <h3 className={styles.title}>{t.feedback.title}</h3>
        <p className={styles.lead}>{t.feedback.lead}</p>

        <fieldset className={styles.choices}>
          <legend className="kivou-visually-hidden">{t.feedback.title}</legend>
          <RelevanceChoice
            label={t.feedback.relevant}
            value="relevant"
            selected={relevance === 'relevant'}
            onSelect={() => {
              setRelevance('relevant')
              setReasonError(null)
              setSaved(false)
            }}
          />
          <RelevanceChoice
            label={t.feedback.notRelevant}
            value="not_relevant"
            selected={relevance === 'not_relevant'}
            onSelect={() => {
              setRelevance('not_relevant')
              setSaved(false)
            }}
          />
        </fieldset>

        {relevance === 'not_relevant' ? (
          <div className={styles.reasons}>
            <fieldset className={styles.reasonSet}>
              <legend className={styles.reasonLegend}>{t.feedback.reasonLabel}</legend>
              <div className={styles.reasonOptions}>
                {NEGATIVE_REASONS.map((code) => (
                  <label
                    key={code}
                    className={`${styles.reasonOption} ${reason === code ? styles.reasonSelected : ''}`}
                  >
                    <input
                      type="radio"
                      name="kivou-feedback-reason"
                      className={styles.radio}
                      checked={reason === code}
                      onChange={() => {
                        setReason(code)
                        setReasonError(null)
                        setSaved(false)
                      }}
                    />
                    <span>{t.feedback.reasons[code]}</span>
                  </label>
                ))}
              </div>
              {reasonError ? (
                <p className={styles.error}>
                  <span aria-hidden="true">▲</span> {reasonError}
                </p>
              ) : null}
            </fieldset>

            {reason === 'other' ? (
              <TextAreaField
                label={t.feedback.noteLabel}
                value={note}
                maxLength={MAXIMUM_NOTE_LENGTH}
                optional
                optionalLabel={t.common.optional}
                onChange={(event) => {
                  setNote(event.target.value)
                  setSaved(false)
                }}
                help={interpolate(t.feedback.noteCount, {
                  count: note.length,
                  max: MAXIMUM_NOTE_LENGTH,
                })}
              />
            ) : null}
          </div>
        ) : null}

        <div className={styles.actions}>
          <Button onClick={() => void submit()} loading={submitting} disabled={relevance === null}>
            {t.feedback.submit}
          </Button>
          {saved ? (
            <p className={styles.saved} role="status">
              <CheckIcon className={styles.savedIcon} /> {t.feedback.recorded}
            </p>
          ) : null}
        </div>
      </Card>

      <Card padding="md" as="section">
        <h3 className={styles.title}>{t.feedback.contactedTitle}</h3>
        {/* Le sens de « contacté » est écrit, pas supposé : ni réponse, ni
            rendez-vous, ni affaire gagnée. */}
        <p className={styles.lead}>{t.feedback.contactedLead}</p>

        {contacted ? (
          <p className={styles.contactedState} role="status">
            <CheckIcon className={styles.savedIcon} />
            {interaction?.contacted_at
              ? interpolate(t.feedback.contactedOn, {
                  date: date(interaction.contacted_at) ?? '',
                })
              : t.feedback.contactedAlready}
          </p>
        ) : (
          <div className={styles.actions}>
            <Button variant="secondary" onClick={() => void contact()} loading={contacting}>
              {t.feedback.markContacted}
            </Button>
          </div>
        )}
      </Card>

      {errorCopy ? (
        <Callout tone="danger" title={errorCopy.title} live>
          {errorCopy.body}
        </Callout>
      ) : null}
    </div>
  )
}

function RelevanceChoice({
  label,
  value,
  selected,
  onSelect,
}: {
  label: string
  value: Relevance
  selected: boolean
  onSelect: () => void
}) {
  return (
    <label className={`${styles.choice} ${selected ? styles.choiceSelected : ''}`}>
      <input
        type="radio"
        name="kivou-feedback-relevance"
        value={value}
        className={styles.radio}
        checked={selected}
        onChange={onSelect}
      />
      <span>{label}</span>
    </label>
  )
}
