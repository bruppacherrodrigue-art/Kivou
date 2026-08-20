import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { useI18n, LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { KivouLogo } from '../components/KivouLogo'
import { ButtonLink } from '../components/Button'
import { CloseIcon, MenuIcon } from '../assets/Icons'
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
  const location = useLocation()
  const authenticated = state.status === 'authenticated'
  const [menuOpen, setMenuOpen] = useState(false)

  // Naviguer referme le menu : laissé ouvert, il masquerait la page atteinte.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname, location.hash])

  // Échap referme. Sans cela, un utilisateur au clavier reste prisonnier de la
  // couche modale qui recouvre la page.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

  // Les mêmes liens servent le bandeau large et le tiroir : deux listes
  // séparées finiraient par diverger, et l'une des deux deviendrait fausse.
  // Les actions d'authentification vivent dans le bandeau en large, et dans le
  // tiroir en étroit. Une seule définition : deux copies finiraient par
  // diverger, et l'une des deux deviendrait fausse.
  const authActions = authenticated ? (
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
  )

  const links = (
    <nav className={styles.nav} aria-label={t.nav.mainNavigation}>
      <Link to="/exemple-de-signal" className={styles.navLink}>
        {t.publicDemo.navLabel}
      </Link>
      <Link to="/#comment" className={styles.navLink}>
        {t.nav.howItWorks}
      </Link>
      <Link to="/#tarifs" className={styles.navLink}>
        {t.nav.pricing}
      </Link>
    </nav>
  )

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

          <div className={styles.headerNav}>{links}</div>

          <div className={styles.headerActions}>
            <LocaleSwitch locale={locale} onChange={setLocale} label={t.common.language} />
            {/* Sous 900 px, les actions passent dans le tiroir : le bandeau ne
                peut pas porter logo, langue, deux boutons et l'ouverture du
                menu sans déborder — mesuré à 506 px pour 390 disponibles. */}
            <div className={styles.headerAuth}>{authActions}</div>
            <button
              type="button"
              className={styles.menuToggle}
              aria-expanded={menuOpen}
              aria-controls="kivou-public-menu"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <MenuIcon />
              <span className="kivou-visually-hidden">
                {menuOpen ? t.nav.closeMenu : t.nav.openMenu}
              </span>
            </button>
          </div>
        </div>
      </header>

      {menuOpen ? (
        <div className={styles.menuLayer}>
          <button
            type="button"
            className={styles.scrim}
            aria-label={t.nav.closeMenu}
            onClick={() => setMenuOpen(false)}
          />
          <div className={styles.menu} id="kivou-public-menu" role="dialog" aria-modal="true">
            <div className={styles.menuHead}>
              <KivouLogo size="sm" />
              <button
                type="button"
                className={styles.menuToggle}
                onClick={() => setMenuOpen(false)}
              >
                <CloseIcon />
                <span className="kivou-visually-hidden">{t.nav.closeMenu}</span>
              </button>
            </div>
            {links}
            <div className={styles.menuAuth}>{authActions}</div>
          </div>
        </div>
      ) : null}

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
