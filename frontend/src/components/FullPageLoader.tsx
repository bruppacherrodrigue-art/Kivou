import { useI18n } from '../i18n'
import { KivouMark } from './KivouLogo'
import styles from './FullPageLoader.module.css'

/** L'attente initiale — la seule de l'application qui ne connaît pas encore la
 *  structure à venir, donc la seule qui ne peut pas être un squelette. */
export function FullPageLoader() {
  const { t } = useI18n()
  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <KivouMark size={40} />
      <p className={styles.label}>{t.common.loading}</p>
    </div>
  )
}
