import type { UnifiedStatus } from '../../api/types'
import { useI18n } from '../../i18n'
import styles from './signals.module.css'

/* La pastille de statut unifié.
 *
 * Le statut vient du backend (`unified_status`) et n'est jamais recalculé ici :
 * le composant ne fait que lui donner un libellé et une couleur. */
export function StatusPill({ status }: { status: UnifiedStatus }) {
  const { t } = useI18n()

  return (
    <span
      className={`${styles.statusPill} status-pill status-pill--${status}`}
      data-status={status}
    >
      {t.signalsTable.status[status]}
    </span>
  )
}
