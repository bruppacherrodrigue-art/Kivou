import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { KivouLogo } from '../components/KivouLogo'
import { Button } from '../components/Button'
import {
  BillingIcon,
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
 * La géométrie vient de la référence 04 : sidebar de 240 px, logo en haut,
 * items icône + libellé, séparateur, carte de compte en bas. Ce que la
 * référence montre en plus — Entreprises, Marchés, Veille, Notes — n'a AUCUN
 * point d'entrée dans `src/signals/api/`. Ces entrées ne sont donc pas rendues,
 * même désactivées : afficher une navigation vers une fonctionnalité
 * inexistante la promettrait.
 *
 * Ce qui n'y figure jamais (§14, §40) : Acquisition Engine, Apollo, Instantly,
 * mailboxes, campagnes, séquences et délivrabilité. Ce sont
 * les systèmes internes de Kivou, pas des fonctionnalités du produit client.
 */

const NAV_ITEMS = [
  { to: '/app/dashboard', key: 'dashboard', Icon: DashboardIcon },
  { to: '/app/signals', key: 'signals', Icon: SignalsIcon },
  { to: '/app/icps', key: 'icps', Icon: TargetIcon },
  { to: '/app/settings', key: 'settings', Icon: BillingIcon },
] as const

const INTERNAL_NAV_ITEM = {
  to: '/app/internal/cockpit',
  key: 'cockpit',
  Icon: SignalsIcon,
} as const

export function AppShell() {
  const { t } = useI18n()
  const { state, signOut } = useSession()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [signingOut, setSigningOut] = useState(false)

  // La navigation ferme le tiroir : sur mobile, un tiroir resté ouvert
  // masquerait la page qu'on vient d'atteindre.
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  // Échap ferme le tiroir. Sans cela, un utilisateur au clavier n'a aucun moyen
  // de sortir de la couche modale qui recouvre la page.
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  const me = state.status === 'authenticated' ? state.me : null
  const items = me?.capabilities.commercial_cockpit
    ? [...NAV_ITEMS, INTERNAL_NAV_ITEM]
    : NAV_ITEMS

  const navigation = (
    <nav className={styles.nav} aria-label={t.nav.mainNavigation}>
      <ul className={styles.navList}>
        {items.map(({ to, key, Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
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
      <a className="kivou-skip-link" href="#kivou-main">
        {t.common.skipToContent}
      </a>

      {/* Barre mobile : le tiroir remplace la sidebar sous 1024px (§20). */}
      <header className={styles.mobileBar}>
        <Link to="/app/dashboard" className={styles.logoLink}>
          <KivouLogo size="sm" />
        </Link>
        <button
          type="button"
          className={styles.drawerToggle}
          aria-expanded={drawerOpen}
          aria-controls="kivou-app-drawer"
          onClick={() => setDrawerOpen((open) => !open)}
        >
          {drawerOpen ? <MenuIcon /> : <MenuIcon />}
          <span className="kivou-visually-hidden">
            {drawerOpen ? t.nav.closeMenu : t.nav.openMenu}
          </span>
        </button>
      </header>

      <aside className={styles.sidebar}>
        <Link to="/app/dashboard" className={styles.logoLink}>
          <KivouLogo size="md" tone="inverse" />
        </Link>
        {navigation}
        <div className={styles.sidebarFooter}>{accountPanel}</div>
      </aside>

      {drawerOpen ? (
        <div className={styles.drawerLayer}>
          <button
            type="button"
            className={styles.scrim}
            aria-label={t.nav.closeMenu}
            onClick={() => setDrawerOpen(false)}
          />
          <div className={styles.drawer} id="kivou-app-drawer" role="dialog" aria-modal="true">
            <div className={styles.drawerHead}>
              <KivouLogo size="sm" tone="inverse" />
              <button
                type="button"
                className={styles.drawerToggle}
                onClick={() => setDrawerOpen(false)}
              >
                <CloseIcon />
                <span className="kivou-visually-hidden">{t.nav.closeMenu}</span>
              </button>
            </div>
            {navigation}
            <div className={styles.sidebarFooter}>{accountPanel}</div>
          </div>
        </div>
      ) : null}

      <main className={styles.main} id="kivou-main">
        <Outlet />
      </main>
    </div>
  )
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '—'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
