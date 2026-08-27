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

/* Le retour client est la dernière étape de lecture du signal.
 *
 * L'avis et la note restent séparés des faits publics et des inférences. Ils
 * sont stockés pour une analyse supervisée ultérieure ; rien ne réécrit le
 * moteur automatiquement. Le suivi commercial « contacté » reste disponible
 * côté backend pour une V2, mais n'est pas exposé dans l'interface V1.
 */
export function FeedbackControl({
  signalKey,
  initial,
}: {
  signalKey: string
  initial: Interaction | null
}) {
  const { t } = useI18n()
  const [interaction, setInteraction] = useState<Interaction | null>(initial)
  const [relevance, setRelevance] = useState<Relevance | null>(initial?.relevance ?? null)
  const [reason, setReason] = useState<NegativeReason | null>(initial?.reason ?? null)
  const [note, setNote] = useState(initial?.note ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  async function submit() {
    setError(null)
    setSaved(false)

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
        note: note.trim() || null,
      })
      setInteraction(result.interaction)
      setSaved(true)
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
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
              setReason(null)
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
        ) : null}

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

        <div className={styles.actions}>
          <Button onClick={() => void submit()} loading={submitting} disabled={relevance === null}>
            {t.feedback.submit}
          </Button>
          {saved && interaction ? (
            <p className={styles.saved} role="status">
              <CheckIcon className={styles.savedIcon} /> {t.feedback.recorded}
            </p>
          ) : null}
        </div>
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
