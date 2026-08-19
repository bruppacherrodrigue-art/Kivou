import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import { KivouLogo } from '../components/KivouLogo'
import { ArchitecturalHero } from '../assets/Illustrations'
import styles from './AuthLayout.module.css'

/* Les écrans d'authentification.
 *
 * Le design fourni n'en montre aucun. La composition est donc extrapolée du
 * SEUL motif approuvé qui lui ressemble : le checkout (référence 06), qui pose
 * un panneau de marque à gauche et le formulaire à droite. Aucune couleur,
 * aucun rayon, aucune famille typographique nouvelle n'est introduit.
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
  const { t } = useI18n()

  return (
    <div className={styles.page}>
      <a className="kivou-skip-link" href="#kivou-main">
        {t.common.skipToContent}
      </a>

      <aside className={styles.brandPanel}>
        <Link to="/" className={styles.logoLink}>
          <KivouLogo size="lg" baseline={t.brand.baseline} />
        </Link>
        <p className={styles.promise}>{t.brand.promise}</p>
        <ArchitecturalHero className={styles.material} />
      </aside>

      <main className={styles.formPanel} id="kivou-main">
        <div className={styles.formInner}>
          <Link to="/" className={styles.mobileLogo}>
            <KivouLogo size="md" />
          </Link>
          <div className={styles.heading}>
            <h1 className={styles.title}>{title}</h1>
            {lead ? <p className={styles.lead}>{lead}</p> : null}
          </div>
          {children}
          {footer ? <div className={styles.footer}>{footer}</div> : null}
        </div>
      </main>
    </div>
  )
}
