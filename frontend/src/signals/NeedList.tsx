import { useI18n } from '../i18n'
import { Badge } from '../components/Surfaces'
import { CheckIcon, ClockIcon } from '../assets/Icons'
import type { PlausibleNeed } from '../api/types'
import styles from './NeedList.module.css'

/* Les besoins plausibles — et le mot « plausible » reste visible.
 *
 * La note qui coiffe la liste vient de l'API (`plausible_needs.note`) : c'est
 * elle qui dit que ces besoins sont des hypothèses. Elle n'est pas
 * reformulée ici, et elle n'est jamais masquée : sans elle, une liste de
 * besoins se lit comme une liste de commandes à venir.
 *
 * Aucun besoin n'est fabriqué pour que la carte paraisse complète : une liste
 * vide reste une liste vide, et le dit.
 */
export function NeedList({
  needs,
  note,
  showReasoning = false,
}: {
  needs: PlausibleNeed[]
  note: string
  showReasoning?: boolean
}) {
  const { t } = useI18n()

  if (needs.length === 0) {
    return <p className={styles.empty}>{t.detail.needsEmpty}</p>
  }

  return (
    <div className={styles.wrap}>
      <p className={styles.note}>{note}</p>
      <ol className={styles.list}>
        {needs.map((need, index) => (
          <li key={`${need.category ?? 'need'}-${index}`} className={styles.item}>
            <span className={styles.rank} aria-hidden="true">
              {index + 1}
            </span>

            <div className={styles.content}>
              <div className={styles.header}>
                <h4 className={styles.label}>{need.label ?? need.category}</h4>
                {need.targeted_by_your_profile ? (
                  <Badge tone="positive" icon={<CheckIcon />}>
                    {t.detail.needTargeted}
                  </Badge>
                ) : null}
              </div>

              {/* `statement` est validé côté domaine : aucune formulation de
                  certitude d'achat ne peut y figurer. */}
              {need.statement ? <p className={styles.statement}>{need.statement}</p> : null}

              <div className={styles.meta}>
                {need.timing_label ? (
                  <span className={styles.timing}>
                    <ClockIcon className={styles.metaIcon} />
                    <span className={styles.metaLabel}>{t.detail.needTiming} :</span>{' '}
                    {need.timing_label}
                  </span>
                ) : null}
              </div>

              {showReasoning && need.reasoning ? (
                <div className={styles.reasoning}>
                  <p className={styles.reasoningLabel}>{t.detail.needReasoning}</p>
                  <p className={styles.reasoningText}>{need.reasoning}</p>
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
