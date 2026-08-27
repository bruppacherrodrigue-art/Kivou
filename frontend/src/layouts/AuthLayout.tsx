import type { ReactNode } from 'react'
import styles from './AuthLayout.module.css'

/* Les routes d'authentification vivent déjà dans PublicLayout.
 * AuthLayout reste donc une composition de formulaire, sans second logo,
 * second skip-link ni second <main>.
 */
export function AuthLayout({
  title,
  lead,
  children,
  footer,
}: {
  title: string
  lead?: string
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <section className={styles.page} aria-labelledby="kivou-auth-title">
      <div className={styles.formPanel}>
        <div className={styles.formInner}>
          <div className={styles.heading}>
            <h1 className={styles.title} id="kivou-auth-title">{title}</h1>
            {lead ? <p className={styles.lead}>{lead}</p> : null}
          </div>
          {children}
          {footer ? <div className={styles.footer}>{footer}</div> : null}
        </div>
      </div>
    </section>
  )
}
