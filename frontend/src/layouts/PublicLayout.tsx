import { Link, Outlet } from 'react-router-dom'
import { useI18n, LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { KivouLogo } from '../components/KivouLogo'
import { ButtonLink } from '../components/Button'
import styles from './PublicLayout.module.css'

/* Le shell public : header horizontal, contenu, footer.
 *
 * Le sélecteur FR/EN n'existe QUE sur les surfaces publiques. Une fois connecté,
 * `account.locale` fait autorité — l'API renvoie déjà ses libellés dans cette
 * langue, et laisser le navigateur en choisir une autre ferait cohabiter deux
 * langues sur le même écran.
 */
export function PublicLayout() {
  const { t, locale, setLocale } = useI18n()
  const { state } = useSession()
  const authenticated = state.status === 'authenticated'

  return (
    <div className={styles.page}>
      <a className="kivou-skip-link" href="#kivou-main">
        {t.common.skipToContent}
      </a>

      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.logoLink} aria-label={t.brand.name}>
            <KivouLogo size="md" />
          </Link>

          <div className={styles.headerActions}>
            <LocaleSwitch locale={locale} onChange={setLocale} label={t.common.language} />
            {authenticated ? (
              <ButtonLink to="/app/signals" variant="primary">
                {t.nav.signals}
              </ButtonLink>
            ) : (
              <>
                <ButtonLink to="/login" variant="quiet">
                  {t.nav.login}
                </ButtonLink>
                <ButtonLink to="/signup" variant="primary">
                  {t.nav.signup}
                </ButtonLink>
              </>
            )}
          </div>
        </div>
      </header>

      <main id="kivou-main">
        <Outlet />
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <KivouLogo size="sm" baseline={t.brand.baseline} />
            <p className={styles.footerTagline}>{t.landing.footerTagline}</p>
          </div>
          <p className={styles.footerLegal}>
            © {new Date().getFullYear()} {t.brand.name} — {t.landing.footerRights}
          </p>
        </div>
      </footer>
    </div>
  )
}

function LocaleSwitch({
  locale,
  onChange,
  label,
}: {
  locale: Locale
  onChange: (next: Locale) => void
  label: string
}) {
  return (
    <div className={styles.localeSwitch} role="group" aria-label={label}>
      {LOCALES.map((option) => (
        <button
          key={option}
          type="button"
          className={`${styles.localeButton} ${option === locale ? styles.localeActive : ''}`}
          // L'état sélectionné est porté par `aria-pressed`, pas par la seule
          // couleur de fond.
          aria-pressed={option === locale}
          onClick={() => onChange(option)}
        >
          {option.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
