import { useCallback, useEffect, type CSSProperties } from 'react'
import {
  Building2,
  ChevronRight,
  FileCheck2,
  LayoutDashboard,
  SlidersHorizontal,
  Target,
} from 'lucide-react'
import { Outlet, useLocation } from 'react-router-dom'
import { billing, icps } from '../api/endpoints'
import { useCurrentUser } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import { toTargetProfileView } from '../reference/dashboard/adapters'
import { KivouBrand } from '../reference/dashboard/KivouBrand'
import { useResource } from '../reference/dashboard/resources'
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
} from '../reference/dashboard/ui/sidebar'
import { ReferenceLink } from '../reference/router/ReferenceLink'
import { SurfaceBoundary } from '../reference/surface/SurfaceBoundary'

type ActiveView = 'overview' | 'signals' | 'companies' | 'target' | 'settings'

const navigation = [
  { id: 'overview', icon: LayoutDashboard, href: '/' },
  { id: 'signals', icon: FileCheck2, href: '/signals' },
  { id: 'companies', icon: Building2, href: '/companies' },
  { id: 'target', icon: Target, href: '/targeting' },
  { id: 'settings', icon: SlidersHorizontal, href: '/settings' },
] as const

export function AppShell() {
  const me = useCurrentUser()

  if (me.onboarding_status !== 'ready_for_signals') {
    return <Outlet />
  }

  return <ReadyAppShell key={me.account_id} />
}

function ReadyAppShell() {
  const { t } = useI18n()
  const location = useLocation()
  const me = useCurrentUser()
  const loadProfiles = useCallback(() => icps.list(), [])
  const loadBilling = useCallback(() => billing.status(), [])
  const profiles = useResource(loadProfiles)
  const access = useResource(loadBilling)
  const current = connectedLocation(location.pathname, t)
  const activeProfile = profiles.data
    ?.map(toTargetProfileView)
    .find((profile) => profile.active)
  const profileLabel = activeProfile
    ? activeProfile.firstTerritory
      ? `${activeProfile.label} · ${activeProfile.firstTerritory}`
      : activeProfile.label
    : profiles.loading
      ? t.reference.loading
      : t.reference.missingValue
  const planLabel = access.data
    ? t.reference.plans[access.data.plan_code]
    : access.loading
      ? t.reference.loading
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
          accountName={me.account_display_name}
          accountEmail={me.email}
          accountInitials={initials(me.account_display_name)}
          planLabel={planLabel}
          profileLabel={profileLabel}
        />
      </SidebarProvider>
    </SurfaceBoundary>
  )
}

function ConnectedShell({
  activeView,
  title,
  accountName,
  accountEmail,
  accountInitials,
  planLabel,
  profileLabel,
}: {
  activeView: ActiveView
  title: string
  accountName: string
  accountEmail: string
  accountInitials: string
  planLabel: string
  profileLabel: string
}) {
  const { t } = useI18n()
  const { pathname } = useLocation()
  const { setOpenMobile } = useSidebar()
  const labels = {
    overview: t.reference.overview,
    signals: t.reference.signals,
    companies: t.reference.companies,
    target: t.reference.targeting,
    settings: t.reference.account,
  } satisfies Record<ActiveView, string>

  useEffect(() => {
    setOpenMobile(false)
  }, [pathname, setOpenMobile])

  return (
    <>
      <Sidebar collapsible="offcanvas" className="kivou-sidebar">
        <SidebarHeader className="sidebar-head">
          <ReferenceLink
            dashboard
            className="sidebar-brand"
            href="/"
            aria-label={t.reference.brandOverview}
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
          <ReferenceLink
            dashboard
            className="demo-account"
            href="/settings"
            aria-label={t.reference.openAccountSettings}
          >
            <span className="account-avatar">{accountInitials}</span>
            <div>
              <strong>{accountName}</strong>
              <small>{accountEmail}</small>
            </div>
          </ReferenceLink>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="dashboard-workspace">
        <header className="topbar">
          <div className="topbar-title">
            <SidebarTrigger
              className="sidebar-trigger"
              aria-label={t.reference.openNavigation}
            />
            <div>
              <p>{t.reference.monitoring}</p>
              <h1>{title}</h1>
            </div>
          </div>
          <span className="demo-mode-badge">{planLabel}</span>
          {activeView !== 'target' ? (
            <div className="topbar-tools">
              <ReferenceLink
                dashboard
                href="/targeting"
                aria-label={t.reference.openTargetProfile}
              >
                <span>{t.reference.targetingShort}</span>
                <strong>{profileLabel}</strong>
                <ChevronRight aria-hidden="true" />
              </ReferenceLink>
            </div>
          ) : null}
        </header>

        <Outlet />
      </SidebarInset>
    </>
  )
}

function connectedLocation(
  pathname: string,
  t: ReturnType<typeof useI18n>['t'],
): { active: ActiveView; title: string } {
  if (pathname === '/app/dashboard') {
    return { active: 'overview', title: t.reference.overview }
  }
  if (pathname.startsWith('/app/signals')) {
    return { active: 'signals', title: t.reference.signals }
  }
  if (pathname.startsWith('/app/companies')) {
    return { active: 'companies', title: t.reference.companies }
  }
  if (pathname.startsWith('/app/icps')) {
    return { active: 'target', title: t.reference.targeting }
  }
  return { active: 'settings', title: t.reference.account }
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '—'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts.at(-1)?.[0] ?? ''}`.toUpperCase()
}
