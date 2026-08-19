import { useState } from 'react'
import { useI18n, plural, interpolate } from '../i18n'
import { Callout } from '../components/Surfaces'
import { ChevronDownIcon, DocumentIcon, ExternalIcon } from '../assets/Icons'
import type { Evidence, EvidenceItem } from '../api/types'
import styles from './EvidenceGroup.module.css'

/* La preuve documentaire — lisible, jamais un vidage de débogage.
 *
 * Le groupement vient de l'API : `public_facts` regroupe par FAIT établi,
 * `analysis_inputs` par besoin plausible étayé. Les deux ne se mélangent pas,
 * et la note qui accompagne `analysis_inputs` dit ce que ces pièces prouvent
 * réellement — c'est-à-dire pas l'achat.
 *
 * Ce qui n'est jamais rendu : `path`. L'API le nettoie déjà des chemins locaux,
 * des fixtures et des artefacts de recherche, mais un chemin de dépôt n'a de
 * toute façon aucun sens pour un client, et les identifiants de règle moteur
 * n'entrent pas dans cette réponse.
 */

export function EvidencePanel({ evidence }: { evidence: Evidence }) {
  const { t } = useI18n()
  const hasPublic = evidence.public_facts.length > 0
  const hasInputs = evidence.analysis_inputs.groups.length > 0

  if (!hasPublic && !hasInputs) {
    return <Callout tone="warning" title={t.evidence.empty}>{t.evidence.emptyBody}</Callout>
  }

  return (
    <div className={styles.panel}>
      {hasPublic ? (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>{t.evidence.publicFacts}</h3>
          <ul className={styles.groups}>
            {evidence.public_facts.map((group) => (
              <li key={group.fact}>
                <EvidenceGroup label={group.label} items={group.items} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {hasInputs ? (
        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>{t.evidence.analysisInputs}</h3>
          {/* La mise en garde de l'API : ces pièces documentent une hypothèse,
              elles ne la démontrent pas. */}
          <p className={styles.note}>{evidence.analysis_inputs.note}</p>
          <ul className={styles.groups}>
            {evidence.analysis_inputs.groups.map((group) => (
              <li key={group.plausible_need}>
                <EvidenceGroup label={group.label} items={group.items} inferred />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}

export function EvidenceGroup({
  label,
  items,
  inferred = false,
}: {
  label: string
  items: EvidenceItem[]
  inferred?: boolean
}) {
  const { t, date } = useI18n()
  const [open, setOpen] = useState(false)
  const count = items.length

  return (
    <div className={`${styles.group} ${inferred ? styles.groupInferred : ''}`}>
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <DocumentIcon className={styles.triggerIcon} />
        <span className={styles.triggerLabel}>{label}</span>
        <span className={styles.triggerCount}>
          {interpolate(plural(count, t.evidence.itemCountOne, t.evidence.itemCountOther), {
            count,
          })}
        </span>
        <ChevronDownIcon className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`} />
        <span className="kivou-visually-hidden">
          {open ? t.evidence.collapse : t.evidence.expand}
        </span>
      </button>

      {open ? (
        <ul className={styles.items}>
          {items.map((item, index) => (
            <li key={`${item.notice_id ?? 'item'}-${index}`} className={styles.item}>
              {item.excerpt ? (
                <blockquote className={styles.excerpt}>
                  <span className="kivou-visually-hidden">{t.evidence.excerpt} : </span>
                  {item.excerpt}
                </blockquote>
              ) : null}

              <div className={styles.itemMeta}>
                {item.source_system ? (
                  <span className={styles.itemSource}>{item.source_system}</span>
                ) : null}
                {item.notice_id ? (
                  <span className="kivou-tabular">{item.notice_id}</span>
                ) : null}
                {item.retrieved_at ? (
                  <span className="kivou-tabular">
                    {t.evidence.retrievedAt} {date(item.retrieved_at)}
                  </span>
                ) : null}
              </div>

              {item.url ? (
                <a
                  className={styles.sourceLink}
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t.evidence.openSource}
                  <ExternalIcon className={styles.linkIcon} />
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
