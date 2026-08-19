import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { Card, Callout, SectionHeading } from '../components/Surfaces'
import { Button } from '../components/Button'
import { SignalDetectedIllustration } from '../assets/Illustrations'
import { CompletenessNotice, IcpFields, emptyIcpValue, missingFields } from './IcpForm'
import type { IcpFormValue } from './IcpForm'
import { icps } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import styles from './Onboarding.module.css'

/* L'onboarding.
 *
 * Le design fourni ne montre pas cet écran ; la directive en décrit les étapes
 * en toutes lettres (§14). Le parcours est donc court et d'un seul tenant
 * plutôt qu'un stepper : cinq questions tiennent sur une page, et un assistant
 * en sept écrans ferait perdre de vue que la complétude est un RÉSULTAT, pas
 * une contrainte de saisie — le client doit voir en permanence ce qui lui
 * manque encore.
 *
 * Aucun `account_id` n'est envoyé : la propriété vient de la session.
 */
export function Onboarding() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { refresh } = useSession()

  const [value, setValue] = useState<IcpFormValue>(emptyIcpValue())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const missing = missingFields(value)
  const canSubmit = missing.length === 0 && value.label.trim().length > 0

  async function submit() {
    setError(null)
    setSubmitting(true)
    try {
      await icps.create({ label: value.label.trim(), customer_input: value.input })
      // Le statut d'onboarding est RECALCULÉ côté serveur : le relire est la
      // seule façon d'en connaître la valeur réelle.
      await refresh()
      navigate('/app/signals', { replace: true })
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  const errorCopy = error ? describeError(error, t) : null

  return (
    <main className={styles.page} id="kivou-main">
      <div className={styles.inner}>
        <header className={styles.header}>
          <SignalDetectedIllustration className={styles.illustration} />
          <SectionHeading
            eyebrow={t.onboarding.welcomeTitle}
            title={t.onboarding.title}
            lead={t.onboarding.lead}
            level={1}
          />
        </header>

        {errorCopy ? (
          <Callout tone="danger" title={errorCopy.title} live>
            {errorCopy.body}
          </Callout>
        ) : null}

        <Card padding="lg" as="section">
          <IcpFields value={value} onChange={setValue} error={error} />
        </Card>

        <div className={styles.footer}>
          <CompletenessNotice missing={missing} />
          <Button
            size="lg"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void submit()}
          >
            {t.onboarding.create}
          </Button>
        </div>
      </div>
    </main>
  )
}
