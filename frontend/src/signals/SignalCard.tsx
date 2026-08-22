import { Link } from 'react-router-dom'
import { useI18n, plural, interpolate } from '../i18n'
import { Badge } from '../components/Surfaces'
import { ArrowRightIcon, LockIcon, MapPinIcon } from '../assets/Icons'
import type { FeedItem, LockedFeedItem, UnlockedFeedItem } from '../api/types'
import styles from './SignalCard.module.css'

/* La carte du feed — le résumé doit suffire pour décider d'ouvrir ou non.
 *
 * La structure vient de la référence 04 : pastille d'initiales, entreprise,
 * badge de besoin, titre du marché, ligne de méta, et statut de fraîcheur à
 * droite. La preuve documentaire N'Y FIGURE PAS : elle appartient au détail
 * (§16, et docx §SignalCard qui décrit une carte « compacte, sans preuve »).
 *
 * Aucune fraîcheur n'est recalculée ici. `event.status`, `event.date`,
 * `event.headline` et `event.why_now` viennent de l'API, qui les recalcule à
 * chaque lecture depuis les dates brutes. Refaire ce calcul en JavaScript
 * recréerait exactement l'écart que SPEC-009D a mesuré.
 */

export function SignalCard({ item }: { item: FeedItem }) {
  return item.locked ? <LockedSignalCard item={item} /> : <UnlockedSignalCard item={item} />
}

function UnlockedSignalCard({ item }: { item: UnlockedFeedItem }) {
  const { t, date, amount } = useI18n()
  const company = item.company.name
  const needs = item.analysis.plausible_needs.items
  const primaryNeed = needs.find((need) => need.targeted_by_your_profile) ?? needs[0]
  const eventDate = date(item.event.date)
  const contractAmount = amount(item.contract.amount?.value, item.contract.amount?.currency)

  return (
    <article className={styles.card}>
      <div className={styles.avatar} aria-hidden="true">
        {monogram(company)}
      </div>

      <div className={styles.body}>
        <div className={styles.topRow}>
          <p className={styles.company}>{company ?? t.common.notAvailable}</p>
          {primaryNeed?.label ? (
            <Badge tone={primaryNeed.targeted_by_your_profile ? 'positive' : 'neutral'}>
              {primaryNeed.label}
            </Badge>
          ) : null}
        </div>

        {/* h2 : le titre de page est le h1, et sauter un niveau casse la
            navigation par titres d'un lecteur d'écran. */}
        <h2 className={styles.title}>
          {/* Le lien couvre la carte entière via ::after, ce qui donne une
              cible tactile large sans imbriquer de contrôles. */}
          <Link to={`/app/signals/${encodeURIComponent(item.signal_id)}`} className={styles.link}>
            {item.contract.title ?? t.common.notAvailable}
          </Link>
        </h2>

        {/* La phrase de fraîcheur vient de `recency.claim` — la seule autorité
            sur ce que Kivou a le droit d'affirmer d'une date. */}
        <p className={styles.headline}>{item.event.headline}</p>

        <ul className={styles.meta}>
          {eventDate ? (
            <li className="kivou-tabular">
              <span className={styles.metaLabel}>{eventClockLabel(item, t)}</span> {eventDate}
            </li>
          ) : null}
          {contractAmount ? <li className="kivou-tabular">{contractAmount}</li> : null}
          {item.contract.location?.country ? (
            <li className={styles.metaPlace}>
              <MapPinIcon className={styles.metaIcon} />
              {[item.contract.location.locality, item.contract.location.country]
                .filter(Boolean)
                .join(', ')}
            </li>
          ) : null}
        </ul>
      </div>

      <div className={styles.aside}>
        {/* Le fit n'est jamais un score nu : il porte un libellé, et sa raison
            courte est le premier motif calculé par l'API. */}
        <p className={styles.fitLabel}>{item.analysis.fit.label}</p>
        {item.analysis.fit.reasons[0] ? (
          <p className={styles.fitReason}>{item.analysis.fit.reasons[0]}</p>
        ) : null}
        <span className={styles.seeSignal}>
          {t.feed.seeSignal}
          <ArrowRightIcon className={styles.metaIcon} />
        </span>
      </div>
    </article>
  )
}

/* L'aperçu verrouillé.
 *
 * Le frontend ne rend QUE les champs que l'API expose sur un teaser. Il ne
 * tente à aucun moment de reconstituer l'entreprise gagnante depuis l'URL, un
 * identifiant de source, un cache ou une autre réponse : le paywall protège
 * précisément la piste commerciale, et un aperçu qui la laisse deviner rend le
 * paiement décoratif.
 */
export function LockedSignalCard({ item }: { item: LockedFeedItem }) {
  const { t, date } = useI18n()
  const eventDate = date(item.event.date)
  const needCount = item.context.plausible_need_count

  return (
    <article className={`${styles.card} ${styles.locked}`}>
      <div className={`${styles.avatar} ${styles.avatarLocked}`} aria-hidden="true">
        <LockIcon className={styles.lockIcon} />
      </div>

      <div className={styles.body}>
        <div className={styles.topRow}>
          <Badge tone="muted" icon={<LockIcon />}>
            {t.locked.badge}
          </Badge>
          {item.context.sector ? <Badge tone="neutral">{item.context.sector}</Badge> : null}
        </div>

        {/* La phrase décrit l'ÉVÉNEMENT, jamais l'entreprise : c'est la
            formulation sans sujet nommé produite par `paywall.LOCKED_HEADLINE`. */}
        <h2 className={styles.lockedTitle}>{item.headline}</h2>
        <p className={styles.headline}>{item.event.why_now}</p>

        <ul className={styles.meta}>
          {eventDate ? <li className="kivou-tabular">{eventDate}</li> : null}
          {item.context.place_country ?? item.context.country ? (
            <li>{item.context.place_country ?? item.context.country}</li>
          ) : null}
          {item.context.contract_magnitude ? (
            <li className="kivou-tabular">
              {t.magnitude[item.context.contract_magnitude]}
              {item.context.currency ? ` ${item.context.currency.toUpperCase()}` : ''}
            </li>
          ) : null}
          {needCount > 0 ? (
            <li>
              {interpolate(
                plural(needCount, t.locked.needCountOne, t.locked.needCountOther),
                { count: needCount },
              )}
            </li>
          ) : null}
        </ul>
      </div>

      <div className={styles.aside}>
        <p className={styles.lockedPitch}>{t.locked.body}</p>
        {/* SEULE la clé voyage. Ni le gagnant, ni le montant, ni le besoin,
            ni la preuve : ce sont exactement les données que ce teaser
            protège, et l'état de navigation est lisible par le client. */}
        <Link
          to="/app/billing"
          state={{ lockedSignalKey: item.signal_id }}
          className={styles.unlockLink}
        >
          {t.locked.ctaShort}
          <ArrowRightIcon className={styles.metaIcon} />
        </Link>
      </div>
    </article>
  )
}

function monogram(name: string | null): string {
  if (!name) return '—'
  const parts = name.replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '—'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

/** Le libellé de la date affichée dépend de l'horloge qui a DÉCIDÉ du statut —
 *  attribution, notification ou publication. L'API la nomme dans `event.clock` ;
 *  la déduire du statut côté frontend dupliquerait `policy.STATUS_CLOCK`. */
function eventClockLabel(item: UnlockedFeedItem, t: ReturnType<typeof useI18n>['t']): string {
  switch (item.event.clock) {
    case 'award':
      return t.detail.dateAward
    case 'notification':
      return t.detail.dateNotification
    case 'publication':
      return t.detail.datePublication
    default:
      return ''
  }
}
