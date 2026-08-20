import { useI18n, interpolate, plural } from '../i18n'
import { Card } from '../components/Surfaces'
import { ButtonLink } from '../components/Button'
import type { BillingStatus, FeedItem, UnlockedFeedItem } from '../api/types'
import styles from './ActivationSuccess.module.css'

/* Le moment où le ciblage devient des signaux.
 *
 * Ce bandeau est PONCTUEL : il appartient à l'arrivée qui suit la création du
 * profil, et disparaît ensuite. L'explication durable du plan Découverte —
 * déblocages restants, offres, verrouillage du reste du flux — reste au
 * `DiscoveryPanel`, qui la porte déjà. La redire ici ferait de la première
 * réussite du client une page de tarifs.
 *
 * Deux choses, et deux seulement, sont dites : le ciblage est prêt, et voici
 * combien de signaux lui sont réellement ouverts.
 *
 *     D'où vient le nombre
 *     ────────────────────
 *     De `discovery.granted_signal_count`, c'est-à-dire du serveur, et jamais
 *     d'un comptage des cartes déverrouillées de la page. La page est paginée
 *     et filtrée ; compter ses items donnerait un nombre qui change avec la
 *     fraîcheur choisie, alors que les déblocages, eux, sont acquis.
 *
 *     D'où vient le premier signal
 *     ────────────────────────────
 *     Du PREMIER `locked === false` dans l'ordre exact reçu de l'API. Le
 *     backend attribue les déblocages depuis le feed par défaut ordonné
 *     (`_grant_discovery`) ; reclasser, rescorer ou recalculer une fraîcheur
 *     ici proposerait comme « premier » un signal que le serveur n'a pas
 *     choisi en premier.
 *
 * Un compte non nul sans aucun signal déverrouillé dans la page est possible —
 * un filtre de fraîcheur restrictif suffit. Le nombre du serveur reste alors
 * affiché tel quel, et AUCUN appel à l'action n'est fabriqué : mieux vaut pas
 * de lien qu'un lien vers un signal inventé.
 */
export function ActivationSuccess({
  status,
  items,
}: {
  status: BillingStatus
  items: FeedItem[]
}) {
  const { t } = useI18n()

  const granted = status.discovery.granted_signal_count
  const first = items.find((item): item is UnlockedFeedItem => item.locked === false)

  return (
    <Card padding="md" as="section" className={styles.card}>
      <h2 className={styles.title}>{t.activation.readyTitle}</h2>

      {granted > 0 ? (
        <p className={styles.count}>
          <span className="kivou-tabular">
            {interpolate(plural(granted, t.activation.countOne, t.activation.countOther), {
              count: granted,
            })}
          </span>
        </p>
      ) : (
        <>
          <p className={styles.count}>{t.activation.noneTitle}</p>
          <p className={styles.note}>{t.activation.noneBody}</p>
        </>
      )}

      {granted > 0 && first ? (
        <div className={styles.action}>
          <ButtonLink to={`/app/signals/${encodeURIComponent(first.signal_id)}`}>
            {t.activation.firstSignal}
          </ButtonLink>
        </div>
      ) : null}
    </Card>
  )
}
