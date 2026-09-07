import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import {
  Building2,
  Bell,
  FileCheck2,
  LayoutDashboard,
  LogOut,
  Settings,
  Target,
} from 'lucide-react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { PROFILE_CONFIRMATION_PATH } from '../auth/profileRoute'
import { dashboard } from '../api/endpoints'
import type { DashboardResponse } from '../api/types'
import { useCurrentUser, useSession } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import { KivouBrand } from '../presentation/dashboard/KivouBrand'
import { useResource } from '../presentation/dashboard/resources'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from '../presentation/dashboard/ui/sidebar'
import { ReferenceLink } from '../presentation/router/ReferenceLink'
import { SurfaceBoundary } from '../presentation/surface/SurfaceBoundary'
import { sharedZoneLabels } from '../presentation/dashboard/zoneLabels'

type ActiveView = 'overview' | 'signals' | 'companies' | 'target' | 'alerts' | 'settings'

export interface DashboardOutletContext {
  data: DashboardResponse | null
  loading: boolean
  error: unknown | null
  retry: () => Promise<void>
}

const navigation = [
  { id: 'overview', icon: LayoutDashboard, href: '/' },
  { id: 'signals', icon: FileCheck2, href: '/signals' },
  { id: 'companies', icon: Building2, href: '/companies' },
  { id: 'target', icon: Target, href: '/targeting' },
  { id: 'alerts', icon: Bell, href: '/settings/notifications' },
  { id: 'settings', icon: Settings, href: '/settings' },
] as const

export function AppShell() {
  const me = useCurrentUser()

  if (me.onboarding_status !== 'ready_for_signals' && !me.provisional_profile) {
    return <Outlet />
  }

  return <ReadyAppShell key={me.account_id} me={me} />
}

function ReadyAppShell({ me }: { me: ReturnType<typeof useCurrentUser> }) {
  const { t, locale } = useI18n()
  const location = useLocation()
  const loadDashboard = useCallback(() => dashboard.get(), [])
  const summary = useResource(loadDashboard)
  const current = connectedLocation(location.pathname, locale)
  const profileLabel = summary.data?.profile?.name ?? t.reference.missingValue
  const sectorLabel = summary.data?.profile?.sector_label ?? t.reference.missingValue
  const zoneLabel = sharedZoneLabels(summary.data?.profile).join(', ') || t.reference.missingValue
  const planLabel = summary.loading || summary.error
    ? t.reference.loading
    : summary.data?.plan?.name ?? t.reference.missingValue

  return (
    <SurfaceBoundary surface="dashboard">
      <SidebarProvider
        style={{ '--sidebar-width': '240px' } as CSSProperties}
        className="dashboard-provider"
      >
        <ConnectedShell
          dashboardResource={summary}
          me={me}
          activeView={current.active}
          title={current.title}
          planLabel={planLabel}
          profileLabel={profileLabel}
          sectorLabel={sectorLabel}
          zoneLabel={zoneLabel}
          openedSignals={summary.data?.plan?.opened ?? null}
          signalQuota={summary.data?.plan?.quota ?? null}
          profileError={Boolean(summary.error)}
          planError={Boolean(summary.error)}
          retryProfile={() => void summary.retry()}
          retryPlan={() => void summary.retry()}
        />
      </SidebarProvider>
    </SurfaceBoundary>
  )
}

function ConnectedShell({
  dashboardResource,
  me,
  activeView,
  title,
  planLabel,
  profileLabel,
  sectorLabel,
  zoneLabel,
  openedSignals,
  signalQuota,
  profileError,
  planError,
  retryProfile,
  retryPlan,
}: {
  dashboardResource: DashboardOutletContext
  me: ReturnType<typeof useCurrentUser>
  activeView: ActiveView
  title: string | null
  planLabel: string
  profileLabel: string
  sectorLabel: string
  zoneLabel: string
  openedSignals: number | null
  signalQuota: number | null
  profileError: boolean
  planError: boolean
  retryProfile: () => void
  retryPlan: () => void
}) {
  const { t, locale } = useI18n()
  const { pathname } = useLocation()
  const { openMobile, setOpenMobile } = useSidebar()
  const mobileTrigger = useRef<HTMLButtonElement>(null)
  const mobileWasOpen = useRef(openMobile)
  const closeMobileNavigation = useCallback(() => {
    setOpenMobile(false)
  }, [setOpenMobile])
  const labels = {
    overview: locale === 'fr' ? 'Aujourd’hui' : 'Today',
    signals: t.reference.signals,
    companies: t.reference.companies,
    target: locale === 'fr' ? 'Profil cible' : 'Target profile',
    alerts: locale === 'fr' ? 'Alertes' : 'Alerts',
    settings: locale === 'fr' ? 'Réglages' : 'Settings',
  } satisfies Record<ActiveView, string>

  useEffect(() => {
    setOpenMobile(false)
  }, [pathname, setOpenMobile])

  useEffect(() => {
    if (mobileWasOpen.current && !openMobile) {
      mobileTrigger.current?.focus()
    }
    mobileWasOpen.current = openMobile
  }, [openMobile])

  return (
    <>
      <Sidebar
        collapsible="offcanvas"
        className="kivou-sidebar"
        mobileTitle={t.reference.navigation}
        mobileDescription={t.reference.navigationDescription}
        mobileCloseLabel={t.reference.closeNavigation}
      >
        <SidebarHeader className="sidebar-head">
          <ReferenceLink
            dashboard
            className="sidebar-brand"
            href="/"
            aria-label={t.reference.brandOverview}
            onClick={closeMobileNavigation}
          >
            <KivouBrand subtitle={t.reference.brandSubtitle} />
          </ReferenceLink>
        </SidebarHeader>

        <SidebarContent className="sidebar-content">
          <SidebarGroup>
            <SidebarGroupLabel className="sidebar-label">
              {t.reference.navigation}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="sidebar-menu">
                {navigation.map(({ id, icon: Icon, href }) => {
                  const active = id === activeView

                  return (
                    <SidebarMenuItem key={id}>
                      <SidebarMenuButton
                        asChild
                        isActive={active}
                        className="sidebar-item"
                      >
                        <ReferenceLink
                          dashboard
                          href={href}
                          aria-current={active ? 'page' : undefined}
                          onClick={closeMobileNavigation}
                        >
                          <Icon aria-hidden="true" />
                          <span>{labels[id]}</span>
                        </ReferenceLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter className="sidebar-footer">
          <AccountBlock me={me} />
          <div className="sidebar-plan-summary">
            {me.provisional_profile ? <Link to={PROFILE_CONFIRMATION_PATH}><strong>Découverte · profil provisoire</strong></Link> : null}
            <strong>{signalQuota === null && openedSignals !== null ? `${openedSignals} signaux ouverts ce mois` : `Plan ${planLabel} · ${openedSignals ?? 0}/${signalQuota ?? '∞'} signaux ce mois`}</strong>
            <small>{sectorLabel} · {zoneLabel}</small>
          </div>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className={`dashboard-workspace${activeView === 'companies' || activeView === 'signals'
        ? ' dashboard-workspace-contained'
        : ''}`}>
        <header className="topbar">
          <SidebarTrigger ref={mobileTrigger} className="sidebar-trigger" aria-label={t.reference.openNavigation} />
          {title ? <h1 className="shell-page-title">{title}</h1> : null}
          {profileError || planError ? (
            <button type="button" className="shell-resource-retry" onClick={profileError ? retryProfile : retryPlan}>
              {profileError ? t.reference.messages.profileLoadError : t.reference.messages.billingLoadError}
            </button>
          ) : <>
            <span className="shell-profile-name">{profileLabel}</span>
            <span className="shell-profile-mobile">
              <strong>{sectorLabel === t.reference.missingValue ? '' : sectorLabel}</strong>
              <span data-profile-zones>{zoneLabel === t.reference.missingValue ? '' : zoneLabel}</span>
            </span>
          </>}
        </header>

        <Outlet context={dashboardResource} />
      </SidebarInset>
    </>
  )
}

function AccountBlock({ me }: { me: ReturnType<typeof useCurrentUser> }) {
  const { signOut } = useSession()
  const navigate = useNavigate()
  const [signingOut, setSigningOut] = useState(false)
  const pending = useRef(false)
  const displayName = me.account_display_name || me.email
  const initials = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || '?'

  async function leaveAccount() {
    if (pending.current) return
    pending.current = true
    setSigningOut(true)
    try {
      await signOut()
      navigate('/login', { replace: true })
    } finally {
      pending.current = false
      setSigningOut(false)
    }
  }

  return (
    <div className="sidebar-account">
      <Link className="sidebar-account-link" to={me.provisional_profile ? PROFILE_CONFIRMATION_PATH : '/app/settings'}>
        <span className="sidebar-account-avatar" aria-hidden="true">{initials}</span>
        <span className="sidebar-account-copy">
          <strong>{displayName}</strong>
          {me.company_name ? <small>{me.company_name}</small> : null}
        </span>
      </Link>
      <button
        type="button"
        className="sidebar-account-logout"
        aria-label="Se déconnecter"
        disabled={signingOut}
        onClick={() => void leaveAccount()}
      >
        <LogOut aria-hidden="true" />
      </button>
    </div>
  )
}

function connectedLocation(pathname: string, locale: 'fr' | 'en'): { active: ActiveView; title: string | null } {
  if (pathname === '/app' || pathname === '/app/dashboard') {
    return { active: 'overview', title: null }
  }
  if (pathname.startsWith('/app/signals')) {
    return { active: 'signals', title: null }
  }
  if (pathname.startsWith('/app/companies')) {
    return { active: 'companies', title: null }
  }
  if (pathname.startsWith('/app/icps')) {
    return { active: 'target', title: locale === 'fr' ? 'Profil cible' : 'Target profile' }
  }
  if (pathname.startsWith('/app/settings/security')) {
    return { active: 'settings', title: locale === 'fr' ? 'Sécurité' : 'Security' }
  }
  if (pathname.startsWith('/app/notifications')) {
    return { active: 'alerts', title: locale === 'fr' ? 'Alertes' : 'Alerts' }
  }
  if (pathname.startsWith('/app/billing')) {
    return { active: 'settings', title: locale === 'fr' ? 'Abonnement' : 'Subscription' }
  }
  return { active: 'settings', title: locale === 'fr' ? 'Compte' : 'Account' }
}
