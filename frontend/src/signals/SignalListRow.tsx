import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import type { FeedItem, LockedFeedItem, UnlockedFeedItem } from '../api/types'
import styles from './SignalListRow.module.css'

export interface SignalListRowProps {
  item: FeedItem
  selected?: boolean
  selectionState?: unknown
  onSelectLocked?: (item: LockedFeedItem) => void
  registerControl?: (element: HTMLAnchorElement | HTMLButtonElement | null) => void
}

export function SignalListRow({
  item,
  selected = false,
  selectionState,
  onSelectLocked,
  registerControl,
}: SignalListRowProps) {
  return item.locked ? (
    <LockedRow
      item={item}
      selected={selected}
      onSelect={onSelectLocked}
      registerControl={registerControl}
    />
  ) : (
    <UnlockedRow
      item={item}
      selected={selected}
      selectionState={selectionState}
      registerControl={registerControl}
    />
  )
}

function UnlockedRow({
  item,
  selected,
  selectionState,
  registerControl,
}: {
  item: UnlockedFeedItem
  selected: boolean
  selectionState?: unknown
  registerControl?: (element: HTMLAnchorElement | HTMLButtonElement | null) => void
}) {
  const { t, amount, date } = useI18n()
  const company = item.company.name ?? t.common.notAvailable
  const contract = item.contract.title ?? t.common.notAvailable
  const formattedAmount =
    amount(item.contract.amount?.value, item.contract.amount?.currency) ?? t.common.notAvailable
  const formattedDate = date(item.event.date) ?? t.common.notAvailable

  return (
    <article className={`${styles.row} ${selected ? styles.selected : ''}`}>
      <Link
        ref={registerControl}
        className={styles.rowLink}
        to={`/app/signals/${encodeURIComponent(item.signal_id)}`}
        state={selectionState}
        aria-current={selected ? 'page' : undefined}
        aria-label={`${company} — ${contract} — ${item.event.headline} — ${item.event.why_now} — ${formattedAmount} — ${formattedDate}`}
      >
        <span className={styles.identity}>{company}</span>
        <span className={styles.contract}>{contract}</span>
        <span className={styles.headline}>{item.event.headline}</span>
        <span className={styles.context}>{item.event.why_now}</span>
        <span className={styles.meta}>
          <span>{formattedDate}</span>
          <strong className={styles.amount}>{formattedAmount}</strong>
        </span>
      </Link>
    </article>
  )
}

function LockedRow({
  item,
  selected,
  onSelect,
  registerControl,
}: {
  item: LockedFeedItem
  selected: boolean
  onSelect?: (item: LockedFeedItem) => void
  registerControl?: (element: HTMLAnchorElement | HTMLButtonElement | null) => void
}) {
  const { t, date } = useI18n()
  const magnitude = item.context.contract_magnitude
    ? t.magnitude[item.context.contract_magnitude]
    : null

  return (
    <article className={`${styles.row} ${styles.locked} ${selected ? styles.selected : ''}`}>
      <button
        ref={registerControl}
        type="button"
        className={styles.rowButton}
        aria-current={selected ? 'page' : undefined}
        aria-label={`${t.workspace.lockedSelection}: ${item.headline} — ${item.event.why_now}`}
        onClick={() => onSelect?.(item)}
      >
        <span className={styles.lockedBadge}>{t.locked.badge}</span>
        <span className={styles.identity}>{item.headline}</span>
        <span className={styles.context}>{item.event.why_now}</span>
        <span className={styles.meta}>
          <span>{date(item.event.date) ?? t.common.notAvailable}</span>
          {magnitude ? (
            <strong className={styles.amount}>
              {magnitude}
              {item.context.currency ? ` ${item.context.currency.toUpperCase()}` : ''}
            </strong>
          ) : null}
        </span>
      </button>
    </article>
  )
}
