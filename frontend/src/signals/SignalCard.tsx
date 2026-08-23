import { Link } from 'react-router-dom'
import { useI18n, plural, interpolate } from '../i18n'
import { Badge } from '../components/Surfaces'
import { ArrowRightIcon, LockIcon, MapPinIcon } from '../assets/Icons'
import type { FeedItem, LockedFeedItem, UnlockedFeedItem } from '../api/types'
import styles from './SignalCard.module.css'

/* La carte du feed — le résumé doit suffire pour décider d'ouvrir ou non.
 *
 * L'entreprise, le montant et le marché précèdent les trois lectures de Kivou :
 * fait public, besoin plausible, correspondance et calendrier. La preuve
 * documentaire détaillée reste dans la route de détail.
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
  if (!company) return null

  const needs = item.analysis.plausible_needs.items
  const primaryNeed = needs.find((need) => need.targeted_by_your_profile) ?? needs[0]
  const eventDate = date(item.event.date)
  const contractAmount = amount(item.contract.amount?.value, item.contract.amount?.currency)
  const place = [item.contract.location?.locality, item.contract.location?.country]
    .filter(Boolean)
    .join(', ')
  const fitReason = item.analysis.fit.reasons[0]

  return (
    <article className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.identity}>
          <div className={styles.avatar} aria-hidden="true">
            {monogram(company)}
          </div>
          <div className={styles.identityCopy}>
            <p className={styles.eyebrow}>{t.feed.winningCompany}</p>
            {/* Le CTA explicite en pied reste l'unique lien de la carte. Le
                pseudo-élément de ce lien étend sa cible à toute la surface. */}
            <h2 className={styles.company}>{company}</h2>
          </div>
        </div>

        {contractAmount ? (
          <div className={styles.amountBlock}>
            <span className={styles.eyebrow}>{t.feed.publishedAmount}</span>
            <strong className={`${styles.amount} kivou-tabular`}>{contractAmount}</strong>
          </div>
        ) : null}
      </div>

      {item.contract.title ? (
        <div className={styles.contractBlock}>
          <p className={styles.eyebrow}>{t.feed.awardedContract}</p>
          <p className={styles.contractTitle}>{item.contract.title}</p>
        </div>
      ) : null}

      <section className={styles.publicFact} aria-label={t.feed.publicFact}>
        <p className={styles.sectionLabel}>{t.feed.publicFact}</p>
        {/* La phrase de fraîcheur vient de `recency.claim` — la seule autorité
            sur ce que Kivou a le droit d'affirmer d'une date. */}
        {item.event.headline ? <p className={styles.headline}>{item.event.headline}</p> : null}
        <ul className={styles.meta}>
          {eventDate ? (
            <li className="kivou-tabular">
              <span className={styles.metaLabel}>{eventClockLabel(item, t)}</span>{' '}
              <time dateTime={item.event.date ?? undefined}>{eventDate}</time>
            </li>
          ) : null}
          {place ? (
            <li className={styles.metaPlace}>
              <MapPinIcon className={styles.metaIcon} aria-hidden="true" />
              {place}
            </li>
          ) : null}
        </ul>
      </section>

      <div className={styles.analysisGrid}>
        {primaryNeed?.label || primaryNeed?.statement ? (
          <section className={styles.analysisBlock} aria-label={t.feed.plausibleNeed}>
            <p className={styles.sectionLabel}>{t.feed.plausibleNeed}</p>
            {primaryNeed.label ? (
              <Badge tone={primaryNeed.targeted_by_your_profile ? 'positive' : 'neutral'}>
                {primaryNeed.label}
              </Badge>
            ) : null}
            {primaryNeed.statement ? (
              <p className={styles.analysisText}>{primaryNeed.statement}</p>
            ) : null}
          </section>
        ) : null}

        {item.analysis.fit.label || fitReason ? (
          <section className={styles.analysisBlock} aria-label={t.feed.profileMatch}>
            <p className={styles.sectionLabel}>{t.feed.profileMatch}</p>
            {/* Le fit n'est jamais un score nu : son libellé et sa première
                raison viennent ensemble de l'API. */}
            {item.analysis.fit.label ? (
              <p className={styles.fitLabel}>{item.analysis.fit.label}</p>
            ) : null}
            {fitReason ? <p className={styles.analysisText}>{fitReason}</p> : null}
          </section>
        ) : null}

        {item.event.why_now ? (
          <section className={styles.analysisBlock} aria-label={t.feed.timing}>
            <p className={styles.sectionLabel}>{t.feed.timing}</p>
            <p className={styles.analysisText}>{item.event.why_now}</p>
          </section>
        ) : null}
      </div>

      <div className={styles.cardFooter}>
        <Link
          to={`/app/signals/${encodeURIComponent(item.signal_id)}`}
          className={`${styles.seeSignal} ${styles.link}`}
        >
          {t.feed.seeSignal}
          <ArrowRightIcon className={styles.metaIcon} aria-hidden="true" />
        </Link>
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
