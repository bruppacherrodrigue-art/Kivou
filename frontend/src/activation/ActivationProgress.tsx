import { useI18n } from '../i18n'
import styles from './ActivationProgress.module.css'

/* Où en est le client dans sa mise en route — trois jalons, pas sept écrans.
 *
 * Ce repère est volontairement MACRO. Un « étape 1 sur 7 » compterait des
 * questions, ce qui donne à un formulaire l'allure d'une formalité
 * administrative et fait paraître la fin lointaine. Les trois jalons répondent
 * à une autre question, la seule qui intéresse quelqu'un qui vient de
 * s'inscrire : combien de choses me séparent encore de mes signaux.
 *
 * Rien n'est interactif. Un jalon cliquable laisserait croire qu'on peut sauter
 * le ciblage pour aller aux signaux, alors que l'un conditionne l'autre. La
 * position courante est portée par `aria-current="step"` ET par un mot lisible
 * — jamais par la seule couleur (§38).
 */

export type ActivationStep = 'account' | 'targeting' | 'signals'

const ORDER: readonly ActivationStep[] = ['account', 'targeting', 'signals'] as const

export function ActivationProgress({ current }: { current: ActivationStep }) {
  const { t } = useI18n()

  const labels: Record<ActivationStep, string> = {
    account: t.activation.stepAccount,
    targeting: t.activation.stepTargeting,
    signals: t.activation.stepSignals,
  }

  const currentIndex = ORDER.indexOf(current)

  return (
    <nav className={styles.nav} aria-label={t.activation.progressLabel}>
      <ol className={styles.list}>
        {ORDER.map((step, index) => {
          const done = index < currentIndex
          const active = index === currentIndex
          const state = done
            ? t.activation.stateDone
            : active
              ? t.activation.stateCurrent
              : t.activation.stateTodo

          return (
            <li
              key={step}
              className={[styles.step, done ? styles.done : '', active ? styles.active : '']
                .filter(Boolean)
                .join(' ')}
              aria-current={active ? 'step' : undefined}
            >
              {/* Le repère porte une forme, pas seulement une couleur : une
                  coche pour ce qui est fait, un rang pour le reste. */}
              <span className={styles.marker} aria-hidden="true">
                {done ? '✓' : index + 1}
              </span>
              <span className={styles.label}>{labels[step]}</span>
              <span className="kivou-visually-hidden"> — {state}</span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
