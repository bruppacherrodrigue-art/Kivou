import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { useI18n } from '../../i18n'
import styles from '../Prospecting.module.css'

export function DetailFrame({ title, badge, children, footer, onClose, compact = false, commercial = false, planCount }: {
  title: string; badge?: ReactNode; children: ReactNode; footer?: ReactNode; onClose: () => void; compact?: boolean; commercial?: boolean; planCount?: number
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  const { locale } = useI18n()
  useEffect(() => {
    const dialog = ref.current
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (dialog && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    }
    if (commercial) dialog?.querySelector<HTMLButtonElement>('button')?.focus()
    return () => {
      if (dialog?.open && typeof dialog.close === 'function') dialog.close()
      if (previous?.isConnected) previous.focus()
    }
  }, [commercial])
  return <dialog ref={ref} aria-modal="true" aria-labelledby={id} className={commercial ? styles.commercialDialog : compact ? styles.dialog : styles.detail}
    data-plan-count={planCount}
    onCancel={(event) => { event.preventDefault(); onClose() }}>
    <div className={styles.detailInner}>
      <header className={styles.detailHead}>
        <div>{badge ?? <span className={styles.kicker}>{title}</span>}<span id={id} className={styles.srOnly}>{title}</span></div>
        <button type="button" className={styles.iconButton} onClick={onClose} aria-label={locale === 'fr' ? 'Fermer' : 'Close'}><X aria-hidden="true" /></button>
      </header>
      <div className={styles.detailBody}>{children}</div>
      {footer && <footer className={styles.detailFooter}>{footer}</footer>}
    </div>
  </dialog>
}
