import type { MouseEvent, ReactNode } from 'react'
import { LockKeyhole } from 'lucide-react'
import { MVP_TERRITORIES, territoryLabel } from '../../api/capabilities'
import type { Locale, Place, LockedFeedItem, UnlockedFeedItem } from '../../api/types'
import { useI18n } from '../../i18n'
import { MatchDots } from './MatchDots'
import styles from './signals.module.css'

/** Un champ que l'API ne publie pas. L'interface le montre absent ; elle ne le
 *  commente pas, ne l'excuse pas et n'invente rien à sa place. */
export const MISSING = ''

/** L'objet client réécrit par l'API prime toujours sur les références source. */
export function signalObject(item: UnlockedFeedItem): string | null {
  return item.factual_display.object_short ?? item.contract.title ?? item.contract.lot_title ?? null
}

/** Coupe un texte pour une cellule dense. Le texte complet reste accessible en
 *  infobulle : tronquer ne doit jamais faire perdre l'information. */
export function truncate(text: string, max = 60): string {
  return text.length <= max ? text : `${text.slice(0, max)}…`
}

export function sentenceCase(value: string | null): string | null {
  if (!value) return null
  const trimmed = value.trim()
  return trimmed ? `${trimmed.charAt(0).toLocaleUpperCase('fr-FR')}${trimmed.slice(1)}` : null
}

/** La nouvelle cellule Objet ne dépasse jamais 60 caractères, ellipse
 * comprise. */
export function shortSignalObject(item: UnlockedFeedItem): string | null {
  const value = sentenceCase(signalObject(item))
  if (!value) return null
  return value.length <= 60 ? value : `${value.slice(0, 59).trimEnd()}…`
}

function folded(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr-FR')
}

export function tablePlaceLabel(place: Place | null): string {
  if (!place) return MISSING
  if (place.locality?.trim()) return place.locality.trim()
  const department = place.subdivision_label?.trim()
  if (!department || folded(department) === 'territoire metropolitain') return MISSING
  return department
}

export function drawerPlaceLabel(place: Place | null): string {
  if (!place) return MISSING
  const locality = place.locality?.trim()
  const department = place.subdivision_label?.trim()
  const usableDepartment = department && folded(department) !== 'territoire metropolitain'
    ? department
    : null
  if (locality && usableDepartment && folded(locality) !== folded(usableDepartment)) {
    return `${locality} (${usableDepartment})`
  }
  return locality ?? usableDepartment ?? MISSING
}

export function compactAmount(value: string | null | undefined, currency: string | null | undefined, locale: Locale): string {
  const parsed = Number.parseFloat(value ?? '')
  if (!Number.isFinite(parsed)) return MISSING
  const formatterLocale = locale === 'fr' ? 'fr-FR' : 'en-GB'
  const unit = currency === 'EUR' || !currency ? '€' : currency
  if (Math.abs(parsed) >= 1_000_000) {
    return `${new Intl.NumberFormat(formatterLocale, { maximumFractionDigits: 2 }).format(parsed / 1_000_000)} M${unit}`
  }
  if (Math.abs(parsed) >= 1_000) {
    return `${new Intl.NumberFormat(formatterLocale, { maximumFractionDigits: 0 }).format(parsed / 1_000)} k${unit}`
  }
  return `${new Intl.NumberFormat(formatterLocale, { maximumFractionDigits: 0 }).format(parsed)} ${unit}`
}

const SHORT_REASON_STOPWORDS = new Set([
  'a', 'au', 'aux', 'avec', 'ce', 'ces', 'dans', 'de', 'des', 'du', 'en', 'et',
  'la', 'le', 'les', 'pour', 'sur', 'un', 'une', 'votre', 'vos',
])

export function shortFitReason(item: UnlockedFeedItem): string {
  const raw = item.analysis.plausible_needs.items.find((need) => need.targeted_by_your_profile)?.label
    ?? item.analysis.plausible_needs.items[0]?.label
    ?? item.analysis.fit.reasons?.[0]?.split(':').at(-1)
    ?? item.analysis.fit.label
  const words = (raw ?? '')
    .replace(/[·,.;:()]/g, ' ')
    .split(/\s+/)
    .map((word) => word.trim())
    .filter(Boolean)
  const meaningful = words.filter((word) => !SHORT_REASON_STOPWORDS.has(folded(word)))
  return (meaningful.length ? meaningful : words).slice(0, 2).join(' ').toLocaleLowerCase('fr-FR')
}

/* Un lieu se lit, il ne se décode pas. Un code NUTS ou ISO (« FR-31 ») ne dit
 * rien à un commercial : à défaut d'un libellé lisible, le champ est omis. */
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
  redesigned = false,
  onOpen,
}: {
  item: UnlockedFeedItem
  selected: boolean
  compact: boolean
  companyCompact?: boolean
  redesigned?: boolean
  onOpen: (signalKey: string) => void
}) {
  const { t, locale, amount, shortDate } = useI18n()

  const object = redesigned ? shortSignalObject(item) : signalObject(item)
  const money = redesigned
    ? compactAmount(item.contract.amount?.value, item.contract.amount?.currency, locale)
    : amount(item.contract.amount?.value, item.contract.amount?.currency)

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
        {object ? <span title={signalObject(item) ?? object}>{companyCompact || redesigned ? object : truncate(object)}</span> : MISSING}
      </td>
      <td className={styles.cellAmount}>{money ?? MISSING}</td>
      {compact ? null : (
        <td className={styles.cellPlace}>{redesigned ? tablePlaceLabel(item.contract.location) : placeLabel(item.contract.location, locale)}</td>
      )}
      <td className={redesigned ? styles.cellWhy : styles.cellMatch}>
        {redesigned ? shortFitReason(item) : <MatchDots item={item} />}
      </td>
    </tr>
  )
}

export function SignalCardRow({ item, selected, redesigned = false, onOpen }: {
  item: UnlockedFeedItem
  selected: boolean
  redesigned?: boolean
  onOpen: (signalKey: string) => void
}) {
  const { locale, amount, shortDate } = useI18n()
  const object = redesigned ? shortSignalObject(item) : signalObject(item)
  const money = redesigned
    ? compactAmount(item.contract.amount?.value, item.contract.amount?.currency, locale)
    : amount(item.contract.amount?.value, item.contract.amount?.currency)
  return (
    <SignalCardFrame signalKey={item.signal_id} selected={selected} onOpen={() => onOpen(item.signal_id)}
      title={item.company.name ?? MISSING} object={object ?? ''}
      metadata={[money, redesigned ? tablePlaceLabel(item.contract.location) : placeLabel(item.contract.location, locale), shortDate(item.factual_display.date.value)]}
      match={redesigned ? <span className={styles.cardWhy}>{shortFitReason(item)}</span> : <MatchDots item={item} />} />
  )
}

export function LockedSignalCardRow({ item, redesigned = false, onOpen }: { item: LockedFeedItem; redesigned?: boolean; onOpen: () => void }) {
  const { amount, shortDate } = useI18n()
  return <SignalCardFrame signalKey={item.signal_id} locked selected={false} onOpen={onOpen}
    title="Réservé aux offres Essentiel et Pro" object={item.headline}
    metadata={[item.teaser.amount ? amount(item.teaser.amount.value, item.teaser.amount.currency) : null,
      item.teaser.department, shortDate(item.teaser.date)]}
    match={redesigned ? null : <span className={styles.matchDots} role="img" aria-label="Correspondance réservée">
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
