import type { MouseEvent, ReactNode } from 'react'
import { LockKeyhole } from 'lucide-react'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import type { Locale, Place, LockedFeedItem, UnlockedFeedItem } from '../../api/types'
import { useI18n } from '../../i18n'
import { MatchDots } from './MatchDots'
import styles from './signals.module.css'

/** Un champ que l'API ne publie pas. L'interface le montre absent ; elle ne le
 *  commente pas, ne l'excuse pas et n'invente rien à sa place. */
export const MISSING = '—'

/** Le libellé du marché : le lot d'abord, le marché ensuite, l'objet court en
 *  dernier recours. */
export function signalObject(item: UnlockedFeedItem): string | null {
  return item.contract.lot_title ?? item.contract.title ?? item.factual_display.object_short ?? null
}

/** Coupe un texte pour une cellule dense. Le texte complet reste accessible en
 *  infobulle : tronquer ne doit jamais faire perdre l'information. */
export function truncate(text: string, max = 60): string {
  return text.length <= max ? text : `${text.slice(0, max)}…`
}

/* Un lieu se lit, il ne se décode pas. Un code NUTS ou ISO (« FR-31 ») ne dit
 * rien à un commercial : à défaut d'un libellé lisible, mieux vaut un tiret. */
export function placeLabel(place: Place | null, locale: Locale): string {
  if (!place) return MISSING
  if (place.locality) return place.locality
  if (place.subdivision_label) return place.subdivision_label
  if (place.country) {
    const territory = MVP_TERRITORIES.find((candidate) => candidate.code === place.country)
    if (territory) return territoryLabel(territory, locale)
  }
  return MISSING
}

export function SignalRow({
  item,
  selected,
  compact,
  companyCompact = false,
  onOpen,
}: {
  item: UnlockedFeedItem
  selected: boolean
  compact: boolean
  companyCompact?: boolean
  onOpen: (signalKey: string) => void
}) {
  const { t, locale, amount, shortDate } = useI18n()

  const object = signalObject(item)
  const money = amount(item.contract.amount?.value, item.contract.amount?.currency)

  /* La ligne entière est cliquable à la souris ; le bouton du titulaire porte
   * l'accès clavier. Sans l'arrêt de propagation, un clic sur le bouton
   * ouvrirait le signal deux fois. */
  const openFromButton = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    onOpen(item.signal_id)
  }

  return (
    <tr
      className={styles.row}
      data-signal-key={item.signal_id}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onOpen(item.signal_id)}
    >
      {companyCompact ? null : <td className={styles.cellDate}>{shortDate(item.factual_display.date.value) ?? MISSING}</td>}
      {companyCompact ? null : <td className={styles.cellWinner}>
        <button type="button" className={styles.winnerButton} onClick={openFromButton}>
          {item.company.name ?? MISSING}
        </button>
        {item.company.consortium ? (
          <span className={styles.consortium}>{t.signalsTable.consortium}</span>
        ) : null}
      </td>}
      <td className={companyCompact ? styles.companyCellObject : styles.cellObject}>
        {object ? <span title={object}>{companyCompact ? object : truncate(object)}</span> : MISSING}
      </td>
      <td className={styles.cellAmount}>{money ?? MISSING}</td>
      {compact ? null : (
        <td className={styles.cellPlace}>{placeLabel(item.contract.location, locale)}</td>
      )}
      <td className={styles.cellMatch}>
        <MatchDots item={item} />
      </td>
    </tr>
  )
}

export function SignalCardRow({ item, selected, onOpen }: {
  item: UnlockedFeedItem
  selected: boolean
  onOpen: (signalKey: string) => void
}) {
  const { locale, amount, shortDate } = useI18n()
  const object = signalObject(item)
  const money = amount(item.contract.amount?.value, item.contract.amount?.currency)
  return (
    <SignalCardFrame signalKey={item.signal_id} selected={selected} onOpen={() => onOpen(item.signal_id)}
      title={item.company.name ?? MISSING} object={object ?? ''}
      metadata={[money, placeLabel(item.contract.location, locale), shortDate(item.factual_display.date.value)]}
      match={<MatchDots item={item} />} />
  )
}

export function LockedSignalCardRow({ item, onOpen }: { item: LockedFeedItem; onOpen: () => void }) {
  const { amount, shortDate } = useI18n()
  return <SignalCardFrame signalKey={item.signal_id} locked selected={false} onOpen={onOpen}
    title="Réservé aux offres Essentiel et Pro" object={item.headline}
    metadata={[item.teaser.amount ? amount(item.teaser.amount.value, item.teaser.amount.currency) : null,
      item.teaser.department, shortDate(item.teaser.date)]}
    match={<span className={styles.matchDots} role="img" aria-label="Correspondance réservée">
      {[1, 2, 3, 4].map((dot) => <i key={dot} aria-hidden="true" data-dot="empty" />)}
    </span>} />
}

function SignalCardFrame({ signalKey, title, object, metadata, match, selected, locked = false, onOpen }: {
  signalKey: string; title: string; object: string; metadata: (string | null)[]
  match: ReactNode; selected: boolean; locked?: boolean; onOpen: () => void
}) {
  const facts = metadata.filter((value): value is string => Boolean(value) && value !== MISSING)
  return <article className={styles.cardRow} data-signal-key={signalKey} data-locked={locked ? 'true' : undefined}
    aria-current={selected ? 'true' : undefined} onClick={onOpen}>
    <button type="button" className={styles.cardRowWinner} title={title}
      onClick={(event) => { event.stopPropagation(); onOpen() }}>
      {locked ? <LockKeyhole aria-hidden="true" /> : null}{title}
    </button>
    <span className={styles.cardRowObject} title={object}>{object}</span>
    <div className={styles.cardRowFooter}>
      <span className={styles.cardRowMeta} title={facts.join(' · ')}>{facts.join(' · ')}</span>
      {match}
    </div>
  </article>
}
