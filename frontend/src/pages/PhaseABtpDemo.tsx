import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import {
  Building2,
  CalendarDays,
  ExternalLink,
  FileCheck2,
  LayoutDashboard,
  MapPin,
  SlidersHorizontal,
  Target,
} from 'lucide-react'
import { withRenderableSpaces } from '../i18n'
import { KivouBrand } from '../reference/dashboard/KivouBrand'
import {
  Sidebar,
  SidebarContent,
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
} from '../reference/dashboard/ui/sidebar'
import { ReferenceLink } from '../reference/router/ReferenceLink'
import { SurfaceBoundary } from '../reference/surface/SurfaceBoundary'

type Need = { statement: string; based_on: string }
type Signal = {
  opportunity_key: string
  specialty: string
  official_facts: {
    awardee: string
    buyer: string | null
    object: string
    lot: string | null
    amount: string | null
    date: string
    location: string
    cpv: string
    source_system: string
    source_notice_id: string
    source_url: string
  }
  operational_elements: string[]
  potential_needs_title: string
  potential_needs: Need[]
  fit_reason: string
  recommended_action: string
  contact_roles: string[]
  to_qualify: string[]
  visible_dashboard: boolean
  outbound_ready: boolean
  outbound_reason: string
  age_days: number
  enrichment_level: 'OFFICIAL_SOURCE' | 'DCE_ANALYZED'
}
type Report = {
  evaluated_on: string
  corpus_total: number
  btp_total: number
  exploitable_total: number
  insufficient_total: number
  siret_recovery_candidates: number
  dce_available: number
  outbound_ready_total: number
  freshness: {
    days_0_90: number
    days_91_180: number
    days_181_365: number
    over_one_year: number
  }
  showcase: Signal[]
}

const number = { format: (value: number) => withRenderableSpaces(new Intl.NumberFormat('fr-FR').format(value)) }
const date = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })

function sourceLabel(level: Signal['enrichment_level']) {
  return level === 'DCE_ANALYZED' ? 'DCE analysé' : 'Source officielle'
}

function outboundLabel(signal: Signal) {
  if (signal.outbound_ready) return 'OUTBOUND_READY'
  if (signal.outbound_reason === 'published_execution_not_ongoing') {
    return 'Non outbound : exécution en cours non démontrée'
  }
  return 'Non outbound : fraîcheur insuffisante'
}

const demoNavigation = [
  { label: "Vue d'ensemble", icon: LayoutDashboard, href: '/app/dashboard', active: true },
  { label: 'Signaux', icon: FileCheck2, href: '/app/signals', active: false },
  { label: 'Entreprises', icon: Building2, href: '/app/companies', active: false },
  { label: 'Ciblage', icon: Target, href: '/app/icps', active: false },
  { label: 'Compte', icon: SlidersHorizontal, href: '/app/settings', active: false },
] as const

export function PhaseABtpDashboardDemo() {
  return (
    <SurfaceBoundary surface="dashboard">
      <SidebarProvider
        style={{ '--sidebar-width': '240px' } as CSSProperties}
        className="dashboard-provider"
      >
        <Sidebar collapsible="offcanvas" className="kivou-sidebar" mobileTitle="Navigation" mobileDescription="Navigation principale Kivou" mobileCloseLabel="Fermer la navigation">
          <SidebarHeader className="sidebar-head">
            <ReferenceLink dashboard className="sidebar-brand" href="/app/dashboard" aria-label="Vue d'ensemble Kivou">
              <KivouBrand subtitle="Intelligence commerciale" />
            </ReferenceLink>
          </SidebarHeader>
          <SidebarContent className="sidebar-content">
            <SidebarGroup>
              <SidebarGroupLabel className="sidebar-label">Navigation</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="sidebar-menu">
                  {demoNavigation.map(({ label, icon: Icon, href, active }) => (
                    <SidebarMenuItem key={label}>
                      <SidebarMenuButton asChild isActive={active} className="sidebar-item">
                        <ReferenceLink dashboard href={href} aria-current={active ? 'page' : undefined}>
                          <Icon aria-hidden="true" /><span>{label}</span>
                        </ReferenceLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
        </Sidebar>
        <SidebarInset className="dashboard-workspace phase-a-dashboard-workspace">
          <header className="topbar">
            <div className="topbar-title"><SidebarTrigger className="sidebar-trigger" aria-label="Ouvrir la navigation" /><div><p>Veille commerciale</p><h1>Vue d'ensemble</h1></div></div>
            <span className="demo-mode-badge">Démonstration locale</span>
          </header>
          <PhaseABtpDemo />
        </SidebarInset>
      </SidebarProvider>
    </SurfaceBoundary>
  )
}

export function PhaseABtpDemo() {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch('/local/phase-a-btp-demo.json')
      .then((response) => {
        if (!response.ok) throw new Error('report unavailable')
        return response.json() as Promise<Report>
      })
      .then(setReport)
      .catch(() => setError(true))
  }, [])

  if (error) return <main className="phase-a-demo"><p role="alert">Le rapport local n’est pas disponible.</p></main>
  if (!report) return <main className="phase-a-demo"><p role="status">Chargement du corpus réel…</p></main>

  const metrics = [
    ['Corpus analysé', report.corpus_total],
    ['Attributions BTP', report.btp_total],
    ['Signaux exploitables', report.exploitable_total],
    ['OUTBOUND_READY', report.outbound_ready_total],
    ['Attributions insuffisantes', report.insufficient_total],
    ['DCE disponibles', report.dce_available],
  ] as const
  const buckets = [
    ['0–90 jours', report.freshness.days_0_90, 'Priorité absolue'],
    ['91–180 jours', report.freshness.days_91_180, 'Outbound accepté'],
    ['181–365 jours', report.freshness.days_181_365, 'Seulement si exécution en cours'],
    ['Plus d’un an', report.freshness.over_one_year, 'Seulement si exécution en cours'],
  ] as const

  return (
    <main className="phase-a-demo">
      <header className="phase-a-hero">
        <div>
          <p className="phase-a-eyebrow">Kivou · Phase A France</p>
          <h1>Signaux BTP immédiatement commercialisables</h1>
          <p>Attributions officielles suffisamment précises, sans attendre le DCE. Évaluation au {date.format(new Date(`${report.evaluated_on}T12:00:00Z`))}.</p>
        </div>
        <span className="phase-a-local">Démonstration locale · lecture seule</span>
      </header>

      <section className="phase-a-metrics" aria-label="Volumes du corpus">
        {metrics.map(([label, value]) => <article key={label}><span>{label}</span><strong>{number.format(value)}</strong></article>)}
      </section>

      <section className="phase-a-recovery">
        <Building2 aria-hidden="true" />
        <div><strong>{number.format(report.siret_recovery_candidates)} SIRET à résoudre</strong><p>Recherche d’abord dans les identités Kivou, puis mise en file asynchrone vers une source officielle. Aucun appel réseau pendant l’affichage.</p></div>
      </section>

      <section className="phase-a-freshness" aria-labelledby="freshness-title">
        <div><p className="phase-a-eyebrow">Fraîcheur commerciale</p><h2 id="freshness-title">Répartition des {number.format(report.exploitable_total)} signaux</h2></div>
        <div className="phase-a-buckets">{buckets.map(([label, value, note]) => <article key={label}><strong>{number.format(value)}</strong><span>{label}</span><small>{note}</small></article>)}</div>
      </section>

      <section className="phase-a-feed" aria-labelledby="signals-title">
        <div className="phase-a-section-heading"><div><p className="phase-a-eyebrow">Sélection diversifiée</p><h2 id="signals-title">10 signaux récents et spécifiques</h2></div><p>Un seul lot par avis · deux occurrences maximum par attributaire</p></div>
        {report.showcase.map((signal, index) => (
          <article className="phase-a-signal" key={signal.opportunity_key}>
            <div className="phase-a-signal-head">
              <div className="phase-a-rank">{String(index + 1).padStart(2, '0')}</div>
              <div className="phase-a-title"><div className="phase-a-badges"><span>{sourceLabel(signal.enrichment_level)}</span><span className="visible">VISIBLE_DASHBOARD</span><span className={signal.outbound_ready ? 'outbound' : 'not-outbound'}>{outboundLabel(signal)}</span></div><h3>{signal.official_facts.awardee}</h3><p>{signal.official_facts.object}</p></div>
            </div>
            <div className="phase-a-fact-strip">
              <span><strong>{signal.official_facts.amount ?? 'Montant non publié'}</strong><small>Montant</small></span>
              <span><CalendarDays aria-hidden="true" /><strong>{date.format(new Date(`${signal.official_facts.date}T12:00:00Z`))}</strong><small>{signal.age_days} jour{signal.age_days > 1 ? 's' : ''}</small></span>
              <span><MapPin aria-hidden="true" /><strong>{signal.official_facts.location}</strong><small>Lieu d’exécution</small></span>
              <span><strong>{signal.official_facts.cpv}</strong><small>CPV officiel</small></span>
            </div>
            <div className="phase-a-reading">
              <section><h4>Ce que les données officielles indiquent</h4>{signal.official_facts.lot ? <p><strong>Lot :</strong> {signal.official_facts.lot}</p> : null}<p><strong>Acheteur :</strong> {signal.official_facts.buyer ?? 'Non publié'}</p><ul>{signal.operational_elements.slice(0, 6).map((item) => <li key={item}>{item}</li>)}</ul></section>
              <section className="phase-a-needs"><h4>{signal.potential_needs_title}</h4><ul>{signal.potential_needs.map((need) => <li key={need.statement}><Target aria-hidden="true" /><span>{need.statement}<small>Fondé sur : {need.based_on}</small></span></li>)}</ul><p className="phase-a-fit">{signal.fit_reason}</p></section>
            </div>
            <div className="phase-a-action"><div><span>Action recommandée</span><strong>{signal.recommended_action}</strong></div><div><span>Fonctions à contacter</span><strong>{signal.contact_roles.join(' · ')}</strong></div><a href={signal.official_facts.source_url} target="_blank" rel="noreferrer">Voir la source officielle <ExternalLink aria-hidden="true" /></a></div>
            <details><summary>À qualifier ({signal.to_qualify.length})</summary><ul>{signal.to_qualify.map((item) => <li key={item}>{item}</li>)}</ul></details>
          </article>
        ))}
      </section>
    </main>
  )
}
