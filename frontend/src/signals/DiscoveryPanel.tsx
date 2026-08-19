import { useI18n, interpolate, plural } from '../i18n'
import { Card } from '../components/Surfaces'
import { ButtonLink } from '../components/Button'
import { LockIcon } from '../assets/Icons'
import type { BillingStatus } from '../api/types'
import styles from './DiscoveryPanel.module.css'

/* L'explication Découverte.
 *
 * Trois choses doivent être dites, et une quatrième ne doit jamais l'être :
 *
 *   — combien de signaux réels sont RÉELLEMENT débloqués. Le nombre vient de
 *     `discovery.granted_signal_count` ; il peut valoir 0, 1 ou 2 si moins de
 *     trois signaux éligibles existent, et c'est alors ce nombre-là qui
 *     s'affiche. Aucun exemple n'est fabriqué pour atteindre trois ;
 *   — que le reste du flux est verrouillé ;
 *   — que ces déblocages sont ACQUIS. Ils ne se renouvellent ni chaque jour ni
 *     chaque mois, et laisser croire l'inverse promettrait un flux gratuit
 *     permanent qui n'existe pas.
 *
 * Le panneau disparaît dès que le compte est payant : il n'y a plus rien à
 * expliquer, et un bandeau de conversion qui survit au paiement est une
 * publicité agressive que la directive §15 écarte.
 */
export function DiscoveryPanel({ status }: { status: BillingStatus }) {
  const { t } = useI18n()

  if (status.plan_code !== 'discovery') return null

  const granted = status.discovery.granted_signal_count
  const remaining = status.discovery.remaining_slots

  return (
    <Card padding="md" as="aside" className={styles.panel}>
      <div className={styles.body}>
        <p className={styles.title}>
          <LockIcon className={styles.icon} aria-hidden="true" />
          {t.discovery.title}
        </p>

        {granted > 0 ? (
          <p className={styles.count}>
            <strong className="kivou-tabular">
              {interpolate(plural(granted, t.discovery.grantedOne, t.discovery.grantedOther), {
                count: granted,
              })}
            </strong>
            {remaining > 0 ? (
              <span className={styles.remaining}>
                {' — '}
                {interpolate(
                  plural(remaining, t.discovery.remainingOne, t.discovery.remainingOther),
                  { count: remaining },
                )}
              </span>
            ) : null}
          </p>
        ) : (
          <p className={styles.count}>{t.discovery.noneYet}</p>
        )}

        <p className={styles.note}>{t.discovery.permanent}</p>
        <p className={styles.note}>{t.discovery.lockedRest}</p>
      </div>

      <ButtonLink to="/app/billing" variant="secondary">
        {t.discovery.seePlans}
      </ButtonLink>
    </Card>
  )
}
