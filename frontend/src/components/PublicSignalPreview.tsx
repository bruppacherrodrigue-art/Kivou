import { Link } from 'react-router-dom'

import { publicDemoSignal } from '../content/publicDemoSignal'
import { useI18n } from '../i18n'
import { Badge, Card } from './Surfaces'
import styles from './PublicSignalPreview.module.css'

/* La carte de signal du hero.
 *
 * Ce qu'elle doit prouver en cinq secondes
 * ────────────────────────────────────────
 * Qui a gagné, quel marché, pour quel montant, quand l'exécution commence, et
 * quel besoin cela rend plausible. C'est la valeur produite par Kivou, montrée
 * plutôt que décrite.
 *
 * Deux garde-fous portés par cette carte
 * ──────────────────────────────────────
 * 1. L'accroche dit « Exemple de signal réel », pas « Signal récent ». Un badge
 *    de fraîcheur figé dans le code deviendrait faux le lendemain, et personne
 *    ne le verrait vieillir.
 * 2. Le mode d'analyse est affiché SUR la carte : « Métadonnées de l'avis —
 *    confiance réduite ». Sans cette mention, un visiteur pourrait croire que
 *    le besoin sort d'un cahier des charges lu par Kivou. Il sort des seules
 *    métadonnées de l'avis, et le dire ici coûte une ligne.
 *
 * Toutes les dates sont ABSOLUES et formatées dans la locale courante. Aucun
 * compte à rebours, aucun « il y a trois jours » : un délai relatif calculé au
 * rendu ment dès que la page est mise en cache.
 */
export function PublicSignalPreview() {
  const { t, amount, date } = useI18n()
  const s = publicDemoSignal
  const value = amount(s.contract.amount, s.contract.currency)

  return (
    <Card padding="lg" className={styles.card} as="article">
      <p className={styles.eyebrow}>{t.publicDemo.previewEyebrow}</p>

      {/* Le gagnant d'abord : c'est l'entreprise à contacter. */}
      <p className={styles.winner}>{s.winner.legalName}</p>
      <p className={styles.object}>{s.contract.title}</p>

      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt className={styles.factLabel}>{t.publicDemo.buyer}</dt>
          <dd className={styles.factValue}>{s.buyer.legalName}</dd>
        </div>
        <div className={styles.fact}>
          <dt className={styles.factLabel}>{t.publicDemo.amountLabel}</dt>
          <dd className={`${styles.factValue} kivou-tabular`}>{value}</dd>
        </div>
        <div className={styles.fact}>
          <dt className={styles.factLabel}>{t.publicDemo.place}</dt>
          <dd className={styles.factValue}>
            {s.contract.locality} · {s.contract.country}
          </dd>
        </div>
      </dl>

      {/* Les deux dates qui font le timing. Absolues, jamais relatives. */}
      <ul className={styles.dates}>
        <li>{interpolate(t.publicDemo.previewAwarded, date(s.timing.awardDate))}</li>
        <li>{interpolate(t.publicDemo.previewStart, date(s.timing.startDate))}</li>
      </ul>

      <div className={styles.needBlock}>
        <p className={styles.needLabel}>{t.publicDemo.previewNeedLabel}</p>
        {/* Un seul besoin dans le preview : au-delà, la carte recopie
            l'analyse au lieu d'inviter à l'ouvrir. */}
        <p className={styles.needStatement}>{s.need.statement}</p>
      </div>

      <p className={styles.mode}>
        <Badge tone="muted">{t.publicDemo.previewMode}</Badge>
      </p>

      <Link to="/exemple-de-signal" className={styles.cta}>
        {t.publicDemo.previewCta}
        <span aria-hidden="true"> →</span>
      </Link>
    </Card>
  )
}

/** `{date}` est le seul jeton de ces chaînes. Une dépendance de gabarit pour
 *  un remplacement unique ne se justifierait pas. */
function interpolate(template: string, value: string | null): string {
  return template.replace('{date}', value ?? '')
}
