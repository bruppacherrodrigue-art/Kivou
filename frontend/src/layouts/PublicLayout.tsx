import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { useI18n, LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { KivouLogo } from '../components/KivouLogo'
import { ButtonLink } from '../components/Button'
import { CloseIcon, MenuIcon } from '../assets/Icons'
import { HashTarget } from './HashTarget'
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
  const footerLinkLabel = (label: string) => `${label} — ${t.publicFooter.linkContext}`
  const [menuOpen, setMenuOpen] = useState(false)
  const toggleRef = useRef<HTMLButtonElement>(null)

  // Refermer rend le focus au bouton qui a ouvert. Sans cela, la fermeture
  // renvoie le focus au début du document et l'utilisateur au clavier doit
  // retraverser toute la page pour revenir où il était.
  const closeMenu = () => {
    setMenuOpen(false)
    toggleRef.current?.focus()
  }

  // Naviguer referme le menu : laissé ouvert, il masquerait la page atteinte.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname, location.hash])

  // Échap referme. Sans cela, un utilisateur au clavier reste prisonnier de la
  // couche modale qui recouvre la page.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu()
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
              ref={toggleRef}
              type="button"
              className={styles.menuToggle}
              aria-expanded={menuOpen}
              aria-controls="kivou-public-menu"
              onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
            >
              <MenuIcon />
              <span className="kivou-visually-hidden">
                {menuOpen ? t.nav.closeMenu : t.nav.openMenu}
              </span>
            </button>
          </div>
        </div>
      </header>

      {/* Panneau NON MODAL, délibérément.
       *
       * `role="dialog"` avec `aria-modal="true"` promet un piège de focus : le
       * lecteur d'écran annonce que le reste de la page est inerte, et il ne
       * l'était pas. Mieux vaut un panneau honnête — `aria-expanded` et
       * `aria-controls` sur le bouton, `Échap` pour sortir, et le focus rendu
       * au bouton — qu'une modale qui ment sur son propre comportement. */}
      {menuOpen ? (
        <div className={styles.menuLayer}>
          <button
            type="button"
            className={styles.scrim}
            // Nom DISTINCT de celui du bouton de fermeture : deux commandes
            // homonymes rendent la liste des contrôles illisible au lecteur
            // d'écran.
            aria-label={t.nav.dismissMenu}
            onClick={closeMenu}
          />
          <div className={styles.menu} id="kivou-public-menu">
            <div className={styles.menuHead}>
              <KivouLogo size="sm" />
              <button type="button" className={styles.menuToggle} onClick={closeMenu}>
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
        {/* Remonter la cible quand la langue change relance le mécanisme de
            focus sans modifier l'URL : l'ancre reste active et le lecteur
            reprend au même endroit dans la nouvelle langue. */}
        <HashTarget key={locale} />
        <Outlet />
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <KivouLogo size="sm" baseline={t.brand.baseline} tone="inverse" />
            <p className={styles.footerTagline}>{t.landing.footerTagline}</p>
          </div>

          <nav className={styles.footerColumn} aria-label={t.publicFooter.product}>
            <p className={styles.footerHeading}>{t.publicFooter.product}</p>
            <Link to="/" aria-label={footerLinkLabel(t.publicFooter.home)}>
              {t.publicFooter.home}
            </Link>
            <Link
              to="/exemple-de-signal"
              aria-label={footerLinkLabel(t.publicFooter.signalExample)}
            >
              {t.publicFooter.signalExample}
            </Link>
            <Link to="/#comment" aria-label={footerLinkLabel(t.nav.howItWorks)}>
              {t.nav.howItWorks}
            </Link>
            <Link to="/#tarifs" aria-label={footerLinkLabel(t.nav.pricing)}>
              {t.nav.pricing}
            </Link>
          </nav>

          <nav className={styles.footerColumn} aria-label={t.publicFooter.account}>
            <p className={styles.footerHeading}>{t.publicFooter.account}</p>
            {authenticated ? (
              <ButtonLink
                to="/app/signals"
                variant="primary"
                aria-label={footerLinkLabel(t.nav.signals)}
              >
                {t.nav.signals}
              </ButtonLink>
            ) : (
              <>
                <ButtonLink
                  to="/signup"
                  variant="primary"
                  aria-label={footerLinkLabel(t.publicFooter.firstSignals)}
                >
                  {t.publicFooter.firstSignals}
                </ButtonLink>
                <Link to="/login" aria-label={footerLinkLabel(t.nav.login)}>
                  {t.nav.login}
                </Link>
              </>
            )}
          </nav>

          <nav className={styles.footerColumn} aria-label={t.publicFooter.helpAndLegal}>
            <p className={styles.footerHeading}>{t.publicFooter.helpAndLegal}</p>
            <ButtonLink
              to="/contact"
              variant="secondary"
              aria-label={footerLinkLabel(t.publicFooter.contact)}
            >
              {t.publicFooter.contact}
            </ButtonLink>
            <Link
              to="/informations-legales#mentions-legales"
              aria-label={footerLinkLabel(t.publicFooter.legalNotice)}
            >
              {t.publicFooter.legalNotice}
            </Link>
            <Link
              to="/informations-legales#confidentialite"
              aria-label={footerLinkLabel(t.publicFooter.privacy)}
            >
              {t.publicFooter.privacy}
            </Link>
            <Link
              to="/informations-legales#cgu"
              aria-label={footerLinkLabel(t.publicFooter.terms)}
            >
              {t.publicFooter.terms}
            </Link>
          </nav>

          <div className={styles.footerBottom}>
            <p className={styles.footerLegal}>
              © {new Date().getFullYear()} {t.brand.name} — {t.landing.footerRights}
            </p>
            <LocaleSwitch
              locale={locale}
              onChange={setLocale}
              label={t.publicFooter.language}
              optionContext={t.publicFooter.linkContext}
            />
          </div>
        </div>
      </footer>
    </div>
  )
}

function LocaleSwitch({
  locale,
  onChange,
  label,
  optionContext,
}: {
  locale: Locale
  onChange: (next: Locale) => void
  label: string
  optionContext?: string
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
          aria-label={optionContext ? `${option.toUpperCase()} — ${optionContext}` : undefined}
          onClick={() => onChange(option)}
        >
          {option.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
