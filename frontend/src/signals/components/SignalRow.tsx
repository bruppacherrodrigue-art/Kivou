import type { MouseEvent } from 'react'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import type { Locale, Place, UnlockedFeedItem } from '../../api/types'
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
  onOpen,
}: {
  item: UnlockedFeedItem
  selected: boolean
  compact: boolean
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
      <td className={styles.cellDate}>{shortDate(item.factual_display.date.value) ?? MISSING}</td>
      <td className={styles.cellWinner}>
        <button type="button" className={styles.winnerButton} onClick={openFromButton}>
          {item.company.name ?? MISSING}
        </button>
        {item.company.consortium ? (
          <span className={styles.consortium}>{t.signalsTable.consortium}</span>
        ) : null}
      </td>
      <td className={styles.cellObject}>
        {object ? <span title={object}>{truncate(object)}</span> : MISSING}
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
