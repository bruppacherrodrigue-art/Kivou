import { useCallback, useEffect, useRef, type CSSProperties } from 'react'
import {
  Building2,
  Bell,
  FileCheck2,
  LayoutDashboard,
  Settings,
  Target,
} from 'lucide-react'
import { Outlet, useLocation } from 'react-router-dom'
import { billing, icps } from '../api/endpoints'
import { useCurrentUser } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import { toTargetProfileView } from '../presentation/dashboard/adapters'
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
import { subscribeToTargetIcpChanges } from '../targeting/targetIcpEvents'

type ActiveView = 'overview' | 'signals' | 'companies' | 'target' | 'alerts' | 'settings'

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

  if (me.onboarding_status !== 'ready_for_signals') {
    return <Outlet />
  }

  return <ReadyAppShell key={me.account_id} />
}

function ReadyAppShell() {
  const { t, locale } = useI18n()
  const location = useLocation()
  const loadProfiles = useCallback(() => icps.list(), [])
  const loadBilling = useCallback(() => billing.status(), [])
  const profiles = useResource(loadProfiles)
  const access = useResource(loadBilling)
  const retryProfiles = profiles.retry
  useEffect(() => subscribeToTargetIcpChanges(() => {
    void retryProfiles()
  }), [retryProfiles])
  const current = connectedLocation(location.pathname, locale)
  const activeProfileSource = profiles.data?.find((profile) => profile.status === 'active')
  const activeProfile = activeProfileSource ? toTargetProfileView(activeProfileSource) : undefined
  const profileLabel = activeProfile?.label ?? t.reference.missingValue
  const firstTrade = activeProfileSource?.customer_input.buyer_trades[0]
  const sectorLabel = activeProfileSource?.customer_input.offer_summary
    || (firstTrade ? t.trades[firstTrade] : t.reference.missingValue)
  const zoneLabel = activeProfileSource?.customer_input.territories.join(', ') || t.reference.missingValue
  const planLabel = access.loading || access.error
    ? t.reference.loading
    : access.data
      ? t.reference.plans[access.data.plan_code]
      : t.reference.missingValue

  return (
    <SurfaceBoundary surface="dashboard">
      <SidebarProvider
        style={{ '--sidebar-width': '240px' } as CSSProperties}
        className="dashboard-provider"
      >
        <ConnectedShell
          activeView={current.active}
          title={current.title}
          planLabel={planLabel}
          profileLabel={profileLabel}
          sectorLabel={sectorLabel}
          zoneLabel={zoneLabel}
          openedSignals={access.data ? access.data.discovery.granted_signal_count - access.data.discovery.remaining_slots : null}
          signalQuota={access.data?.discovery.limit ?? null}
          profileError={Boolean(profiles.error)}
          planError={Boolean(access.error)}
          retryProfile={() => void retryProfiles()}
          retryPlan={() => void access.retry()}
        />
      </SidebarProvider>
    </SurfaceBoundary>
  )
}

function ConnectedShell({
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
          <div className="sidebar-plan-summary">
            <strong>Plan {planLabel} · {openedSignals ?? '—'}/{signalQuota ?? '—'} signaux ce mois</strong>
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
          ) : <span className="shell-profile-name">{profileLabel}</span>}
        </header>

        <Outlet />
      </SidebarInset>
    </>
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
