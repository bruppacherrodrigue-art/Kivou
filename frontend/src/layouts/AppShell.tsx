import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { KivouLogo } from '../components/KivouLogo'
import { Button } from '../components/Button'
import {
  BillingIcon,
  BuildingIcon,
  CloseIcon,
  DashboardIcon,
  LogoutIcon,
  MenuIcon,
  SignalsIcon,
  TargetIcon,
} from '../assets/Icons'
import styles from './AppShell.module.css'

/* Le shell du SaaS client.
 *
 * La géométrie vient de la référence 04 : sidebar de 248 px, logo en haut,
 * items icône + libellé, séparateur, carte de compte en bas. Ce que la
 * référence montre aussi Entreprises : cette entrée est maintenant alimentée
 * uniquement par les fiches reliées aux signaux accessibles. Marchés, Veille
 * et Notes restent absents tant qu'aucun point d'entrée client ne les sert.
 *
 * Ce qui n'y figure jamais (§14, §40) : Acquisition Engine, Apollo, Instantly,
 * mailboxes, campagnes, séquences et délivrabilité. Ce sont
 * les systèmes internes de Kivou, pas des fonctionnalités du produit client.
 */

const NAV_ITEMS = [
  { to: '/app/dashboard', key: 'dashboard', Icon: DashboardIcon },
  { to: '/app/signals', key: 'signals', Icon: SignalsIcon },
  { to: '/app/companies', key: 'companies', Icon: BuildingIcon },
  { to: '/app/icps', key: 'icps', Icon: TargetIcon },
  { to: '/app/settings', key: 'settings', Icon: BillingIcon },
] as const

const DESKTOP_RAIL_QUERY = '(min-width: 1024px)'
const DRAWER_CONTROLS =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function AppShell() {
  const { t } = useI18n()
  const { state, signOut } = useSession()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [signingOut, setSigningOut] = useState(false)
  const drawerTriggerRef = useRef<HTMLButtonElement>(null)
  const drawerRef = useRef<HTMLDivElement>(null)
  const drawerCloseRef = useRef<HTMLButtonElement>(null)
  const restoreDrawerFocus = useRef(false)

  const closeDrawer = useCallback((restoreFocus: boolean) => {
    restoreDrawerFocus.current = restoreFocus
    setDrawerOpen(false)
  }, [])

  const openDrawer = useCallback(() => {
    restoreDrawerFocus.current = false
    setDrawerOpen(true)
  }, [])

  // La navigation ferme le tiroir : sur mobile, un tiroir resté ouvert
  // masquerait la page qu'on vient d'atteindre.
  useEffect(() => {
    closeDrawer(false)
  }, [closeDrawer, location.pathname])

  // Une ouverture modale commence sur son contrôle de fermeture. Après une
  // fermeture locale, le focus revient au déclencheur une fois `inert` retiré.
  useEffect(() => {
    if (drawerOpen) {
      drawerCloseRef.current?.focus()
      return
    }
    if (!restoreDrawerFocus.current) return
    restoreDrawerFocus.current = false
    drawerTriggerRef.current?.focus()
  }, [drawerOpen])

  // Échap ferme le tiroir. Sans cela, un utilisateur au clavier n'a aucun moyen
  // de sortir de la couche modale qui recouvre la page.
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDrawer(true)
        return
      }
      if (event.key !== 'Tab') return

      const drawer = drawerRef.current
      if (!drawer) return
      const controls = Array.from(drawer.querySelectorAll<HTMLElement>(DRAWER_CONTROLS)).filter(
        (control) => control.tabIndex >= 0,
      )
      const first = controls.at(0)
      const last = controls.at(-1)
      if (!first || !last) return

      const active = document.activeElement
      if (event.shiftKey && (active === first || !drawer.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !drawer.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [closeDrawer, drawerOpen])

  // Si la media query active le rail fixe, le drawer mobile n'a plus de
  // surface visible : il doit disparaître avec son état modal.
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const desktop = window.matchMedia(DESKTOP_RAIL_QUERY)
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) closeDrawer(false)
    }
    desktop.addEventListener('change', onChange)
    return () => desktop.removeEventListener('change', onChange)
  }, [closeDrawer])

  const me = state.status === 'authenticated' ? state.me : null
  const items = NAV_ITEMS
  const pageTitle = titleForPath(location.pathname, t)
  const contentOwnsPageHeading = pageOwnsHeading(location.pathname)
  const eyebrow = me?.locale === 'en' ? 'Awarded contract monitoring' : 'Veille des marchés attribués'

  const navigation = (onNavigate?: () => void) => (
    <nav className={styles.nav} aria-label={t.nav.mainNavigation}>
      <p className={styles.sidebarLabel}>Navigation</p>
      <ul className={styles.navList}>
        {items.map(({ to, key, Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              onClick={onNavigate}
              className={({ isActive }) =>
                `${styles.navItem} ${isActive ? styles.navItemActive : ''}`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon className={styles.navIcon} />
                  <span>{t.nav[key]}</span>
                  {/* L'état actif ne repose pas sur la seule couleur : il est
                      aussi porté par `aria-current` et par un liseré. */}
                  {isActive ? <span className={styles.navMarker} aria-hidden="true" /> : null}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )

  const accountPanel = me ? (
    <div className={styles.account}>
      <div className={styles.accountIdentity}>
        <span className={styles.accountAvatar} aria-hidden="true">
          {initials(me.account_display_name)}
        </span>
        <span className={styles.accountText}>
          <span className={styles.accountName}>{me.account_display_name}</span>
          <span className={styles.accountEmail}>{me.email}</span>
        </span>
      </div>
      <Button
        variant="secondary"
        fullWidth
        icon={<LogoutIcon />}
        loading={signingOut}
        onClick={() => {
          setSigningOut(true)
          void signOut().finally(() => setSigningOut(false))
        }}
      >
        {t.nav.logout}
      </Button>
    </div>
  ) : null

  return (
    <div className={styles.shell}>
      <a
        className="kivou-skip-link"
        href="#kivou-main"
        inert={drawerOpen ? true : undefined}
      >
        {t.common.skipToContent}
      </a>

      {/* Barre mobile : le tiroir remplace la sidebar sous 1024px (§20). */}
      <header className={styles.mobileBar} inert={drawerOpen ? true : undefined}>
        <button
          ref={drawerTriggerRef}
          type="button"
          className={styles.drawerToggle}
          aria-expanded={drawerOpen}
          aria-controls="kivou-app-drawer"
          onClick={openDrawer}
        >
          <MenuIcon />
          <span className="kivou-visually-hidden">{t.nav.openMenu}</span>
        </button>
        <div className={styles.mobileTitle}>
          <strong aria-hidden="true">{pageTitle}</strong>
        </div>
      </header>

      <aside className={styles.sidebar}>
        <Link to="/app/dashboard" className={styles.logoLink}>
          <KivouLogo size="md" />
        </Link>
        {navigation()}
        <div className={styles.sidebarFooter}>{accountPanel}</div>
      </aside>

      {drawerOpen ? (
        <div className={styles.drawerLayer}>
          <button
            type="button"
            className={styles.scrim}
            aria-label={t.nav.dismissMenu}
            onClick={() => closeDrawer(true)}
          />
          <div
            ref={drawerRef}
            className={styles.drawer}
            id="kivou-app-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={t.nav.mainNavigation}
          >
            <div className={styles.drawerHead}>
              <KivouLogo size="sm" />
              <button
                ref={drawerCloseRef}
                type="button"
                className={styles.drawerToggle}
                onClick={() => closeDrawer(true)}
              >
                <CloseIcon />
                <span className="kivou-visually-hidden">{t.nav.closeMenu}</span>
              </button>
            </div>
            {navigation(() => closeDrawer(false))}
            <div className={styles.sidebarFooter}>{accountPanel}</div>
          </div>
        </div>
      ) : null}

      <div className={styles.workspace} inert={drawerOpen ? true : undefined}>
        <header className={styles.topbar}>
          <div className={styles.topbarTitle}>
            <p>{eyebrow}</p>
            {contentOwnsPageHeading ? (
              <strong className={styles.topbarPageTitle}>{pageTitle}</strong>
            ) : (
              <h1>{pageTitle}</h1>
            )}
          </div>
        </header>
        <main className={styles.main} id="kivou-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function pageOwnsHeading(pathname: string): boolean {
  return /^\/app\/companies\/[^/]+$/.test(pathname)
}

function titleForPath(pathname: string, t: ReturnType<typeof useI18n>['t']): string {
  if (pathname.startsWith('/app/signals')) return t.nav.signals
  if (pathname.startsWith('/app/companies')) return t.nav.companies
  if (pathname.startsWith('/app/icps')) return t.nav.icps
  if (pathname === '/app/billing') return t.billing.title
  if (pathname === '/app/notifications') return t.notifications.title
  if (pathname.startsWith('/app/settings')) return t.nav.settings
  return t.nav.dashboard
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '—'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
