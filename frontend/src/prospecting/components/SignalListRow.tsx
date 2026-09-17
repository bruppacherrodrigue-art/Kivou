import { Bookmark, Check, LockKeyhole, RotateCcw, X } from 'lucide-react'
import type { FeedItem, UnifiedStatus } from '../../api/types'
import { useI18n } from '../../i18n'
import { frenchDepartmentPhrase, visiblePlaceName } from '../../presentation/locationText'
import { formatAmount, initials, signalClock, signalPlace, signalTitle } from '../adapters'
import { useSignalActions } from '../useSignalActions'
import styles from '../Prospecting.module.css'

export function statusLabel(status: UnifiedStatus, fr: boolean) {
  return (fr ? { new: 'Nouveau', saved: 'Sauvegardé', contacted: 'Contacté', ignored: 'Ignoré' } : { new: 'New', saved: 'Saved', contacted: 'Contacted', ignored: 'Ignored' })[status]
}
export function SignalListRow({ item, onOpen }: { item: FeedItem; onOpen: () => void }) {
  const { locale, shortDate } = useI18n()
  const fr = locale === 'fr'
  const actions = useSignalActions(item.locked ? null : item)
  const status = actions.status ?? item.status
  const title = item.locked ? item.headline : signalTitle(item)
  const money = item.locked ? item.teaser.amount?.currency ? { value: item.teaser.amount.value, currency: item.teaser.amount.currency } : null : item.contract.amount
  const clock = item.locked ? {
    label: item.teaser.date_kind === 'award'
      ? (fr ? 'Attribué le' : 'Awarded on')
      : (fr ? 'Publié le' : 'Published on'),
    value: item.teaser.date,
  } : signalClock(item, locale)
  const lockedDepartment = item.locked ? visiblePlaceName(item.teaser.department) : null
  const act = (next: UnifiedStatus) => { void actions.setStatus(next).catch(() => {}) }
  return <article className={styles.signalRow} data-signal-id={item.signal_id}>
    <span className={styles.avatar} aria-hidden="true">{item.locked ? <LockKeyhole /> : initials(item.company.name || title)}</span>
    <div className={styles.rowMain}>
      <div className={styles.rowTop}><span className={styles.tag} data-status={status}>{statusLabel(status, fr)}</span>{clock.value && <span>{clock.label} {shortDate(clock.value)}</span>}</div>
      <button className={styles.rowTitle} onClick={onOpen} aria-label={`${fr ? 'Ouvrir' : 'Open'} : ${title}`}>{title}</button>
      <div className={styles.rowMeta}>{item.locked && <strong className={styles.tag}>{item.holder_label}</strong>}{!item.locked && item.company.name && <strong>{item.company.name}</strong>}{!item.locked && item.company.consortium && <span className={styles.tag}>{fr ? 'Groupement' : 'Consortium'}</span>}<span>{item.locked ? (fr ? frenchDepartmentPhrase(lockedDepartment) : lockedDepartment) : signalPlace(item, locale)}</span></div>
      {item.locked && <p className={styles.caption}>{item.landing_example_holder
        ? (fr
          ? `Comme pour ${item.landing_example_holder} : dirigeant, téléphone, e-mail, historique des marchés.`
          : `As with ${item.landing_example_holder}: director, phone, email and contract history.`)
        : (fr ? 'Découvrez les possibilités d’accès à ce signal.' : 'Explore access to this signal.')}</p>}
      {actions.error != null && <p className={styles.error} role="alert">{actions.conflict ? (fr ? 'Ce signal a été modifié dans une autre fenêtre.' : 'This signal changed in another window.') : (fr ? 'L’action n’a pas été enregistrée.' : 'The action was not saved.')} <button className={styles.textButton} onClick={actions.reload}>{fr ? 'Actualiser' : 'Refresh'}</button></p>}
    </div>
    <div className={styles.rowAside}>
      {money && <span className={styles.money}>{formatAmount(money, locale, true)}</span>}
      {!item.locked && <div className={styles.actions}>
        <button className={styles.iconButton} disabled={actions.pending} aria-label={status === 'saved' ? (fr ? 'Rétablir comme nouveau' : 'Mark as new') : (fr ? 'Sauvegarder le signal' : 'Save signal')} aria-pressed={status === 'saved'} onClick={() => act(status === 'saved' ? 'new' : 'saved')}><Bookmark aria-hidden="true" fill={status === 'saved' ? 'currentColor' : 'none'} /></button>
        <button className={styles.iconButton} disabled={actions.pending} aria-label={status === 'contacted' || status === 'ignored' ? (fr ? 'Rétablir le signal' : 'Restore signal') : (fr ? 'Ignorer le signal' : 'Ignore signal')} onClick={() => act(status === 'contacted' || status === 'ignored' ? 'new' : 'ignored')}>{status === 'contacted' ? <Check aria-hidden="true" /> : status === 'ignored' ? <RotateCcw aria-hidden="true" /> : <X aria-hidden="true" />}</button>
      </div>}
    </div>
  </article>
}
