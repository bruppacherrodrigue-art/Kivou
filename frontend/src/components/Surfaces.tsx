import type { ReactNode } from 'react'
import styles from './Surfaces.module.css'

/* Cards, badges, callouts, états vides et squelettes.
 *
 * Une card est définie par sa SURFACE, sa bordure et son espacement — l'ombre
 * est optionnelle et très légère (directive §7.5, §9). Aucun effet glass.
 */

export function Card({
  children,
  padding = 'md',
  className = '',
  as: Tag = 'div',
  elevated = false,
  ariaLabelledBy,
}: {
  children: ReactNode
  padding?: 'none' | 'sm' | 'md' | 'lg'
  className?: string
  as?: 'div' | 'section' | 'article' | 'aside' | 'li'
  elevated?: boolean
  ariaLabelledBy?: string
}) {
  return (
    <Tag
      aria-labelledby={ariaLabelledBy}
      className={[
        styles.card,
        styles[`padding-${padding}`],
        elevated ? styles.elevated : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </Tag>
  )
}

/* Les tonalités de badge sont volontairement peu nombreuses : beige, vert
 * doux, terracotta doux et neutres. « Un badge doit répondre à une question ;
 * si tout devient badge, rien n'est prioritaire. » */
export type BadgeTone = 'neutral' | 'positive' | 'warm' | 'muted' | 'brand'

export function Badge({
  children,
  tone = 'neutral',
  icon,
}: {
  children: ReactNode
  tone?: BadgeTone
  icon?: ReactNode
}) {
  return (
    <span className={`${styles.badge} ${styles[`badge-${tone}`]}`}>
      {icon ? (
        <span className={styles.badgeIcon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </span>
  )
}

export type CalloutTone = 'info' | 'warning' | 'danger' | 'success'

/** Un message de contexte. `role="alert"` seulement quand il annonce un
 *  changement que l'utilisateur n'a pas provoqué en le lisant. */
export function Callout({
  title,
  children,
  tone = 'info',
  action,
  live = false,
}: {
  title?: string
  children?: ReactNode
  tone?: CalloutTone
  action?: ReactNode
  live?: boolean
}) {
  return (
    <div
      className={`${styles.callout} ${styles[`callout-${tone}`]}`}
      role={live ? 'alert' : undefined}
    >
      <div className={styles.calloutBody}>
        {title ? <p className={styles.calloutTitle}>{title}</p> : null}
        {children ? <div className={styles.calloutText}>{children}</div> : null}
      </div>
      {action ? <div className={styles.calloutAction}>{action}</div> : null}
    </div>
  )
}

export function EmptyState({
  illustration,
  title,
  body,
  action,
}: {
  illustration?: ReactNode
  title: string
  body?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={styles.empty}>
      {illustration ? <div className={styles.emptyIllustration}>{illustration}</div> : null}
      <h2 className={styles.emptyTitle}>{title}</h2>
      {body ? <p className={styles.emptyBody}>{body}</p> : null}
      {action ? <div className={styles.emptyAction}>{action}</div> : null}
    </div>
  )
}

/** Un squelette qui reprend la STRUCTURE finale, pas un rond qui tourne
 *  (docx §Overlays). */
export function Skeleton({
  width = '100%',
  height = '1rem',
  radius = 'var(--kivou-radius-sm)',
}: {
  width?: string
  height?: string
  radius?: string
}) {
  return (
    <span className={styles.skeleton} style={{ width, height, borderRadius: radius }} aria-hidden="true" />
  )
}

export function SectionHeading({
  eyebrow,
  title,
  lead,
  id,
  level = 2,
  hideTitle = false,
}: {
  eyebrow?: string
  title: string
  lead?: ReactNode
  id?: string
  /** Le titre de PAGE est un `h1`. Une application dont chaque écran commence
   *  en `h2` laisse un document sans racine, et la navigation par titres d'un
   *  lecteur d'écran n'a plus de point de départ. */
  level?: 1 | 2 | 3
  /** Le shell connecte porte deja le titre de page dans sa topbar. Cette
   *  option conserve alors le texte d'introduction sans dupliquer le titre. */
  hideTitle?: boolean
}) {
  const Tag = level === 1 ? 'h1' : level === 2 ? 'h2' : 'h3'
  return (
    <div className={styles.sectionHeading}>
      {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
      {hideTitle ? null : (
        <Tag className={level === 3 ? styles.subsectionTitle : styles.sectionTitle} id={id}>
          {title}
        </Tag>
      )}
      {lead ? <p className={styles.sectionLead}>{lead}</p> : null}
    </div>
  )
}

/** Une paire libellé / valeur. `dl` plutôt que `div` : c'est une liste de
 *  définitions, et un lecteur d'écran l'annonce comme telle. */
export function DataList({ children }: { children: ReactNode }) {
  return <dl className={styles.dataList}>{children}</dl>
}

export function DataRow({
  label,
  children,
  tabular = false,
}: {
  label: string
  children: ReactNode
  tabular?: boolean
}) {
  return (
    <div className={styles.dataRow}>
      <dt className={styles.dataLabel}>{label}</dt>
      <dd className={`${styles.dataValue} ${tabular ? 'kivou-tabular' : ''}`}>{children}</dd>
    </div>
  )
}
