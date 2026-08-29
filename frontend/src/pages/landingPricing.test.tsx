import { readFileSync } from 'node:fs'
import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import type { CataloguePlan, PlanCatalogue } from '../api/types'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, mockApi, renderApp } from '../test/harness'

function catalogueWithEssentialPrice(amount: number): PlanCatalogue {
  return {
    ...CATALOGUE,
    plans: CATALOGUE.plans.map((plan) => plan.plan_code === 'essential'
      ? { ...plan, monthly_price: { chf: { amount_minor_units: amount, currency: 'chf' }, eur: { amount_minor_units: amount, currency: 'eur' } } }
      : plan),
  }
}

const AGGREGATE_DOWNGRADES: Array<[
  string,
  {
    essential?: Partial<CataloguePlan['entitlements']>
    pro?: Partial<CataloguePlan['entitlements']>
  },
]> = [
  ['le nombre de profils est inférieur', { essential: { max_active_icps: 4 } }],
  ['l’historique est inférieur', { essential: { history_scope: 'all_available', history_days: null } }],
  ['le mode territorial est inférieur', { essential: { territory_mode: 'expanded', max_territories_per_icp: null } }],
  ['la limite territoriale est inférieure', {
    essential: { territory_mode: 'single', max_territories_per_icp: 2 },
    pro: { territory_mode: 'single', max_territories_per_icp: 1 },
  }],
  ['le flux est retiré', { pro: { feed_access: false } }],
  ['le détail est retiré', { pro: { detail_access: false } }],
  ['la source est retirée', { pro: { evidence_access: false } }],
  ['la cadence est inférieure', { essential: { alert_cadence: 'priority' } }],
  ['le niveau de filtre est inférieur', { essential: { filter_level: 'advanced' } }],
  ['le niveau d’export est inférieur', { essential: { export_level: 'scheduled' } }],
  ['les signaux attribués sont inférieurs', { essential: { granted_signals: 1 } }],
]

describe('tarifs publics exacts et autoritaires', () => {
  it('rend les quatre cartes et montants exclusivement depuis le catalogue API', async () => {
    mockApi({ 'GET /billing/plans': { body: catalogueWithEssentialPrice(1234) } })
    const { container } = renderApp(<AppRoutes />, { route: '/tarifs' })
    await screen.findAllByText(/12[,.]34/)
    const grid = container.querySelector('.pricing-grid')!
    expect(grid.querySelectorAll('.price-card')).toHaveLength(4)
    const essential = screen.getByRole('heading', { level: 2, name: 'Essentiel' }).closest('article')!
    expect(essential.textContent).toMatch(/12[,.]34/)
    expect(within(essential).getByRole('link', { name: 'Choisir Essentiel' })).toHaveAttribute('href', '/signup?plan=essential')
    expect(container.querySelector('.table-wrap table')).not.toBeNull()
  })

  it('n’écrit aucun prix de production dans les composants publics', () => {
    const sources = [
      '../reference/public/PricingResource.tsx',
      './Landing.tsx',
      './PublicPricing.tsx',
    ].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'))
    for (const source of sources) {
      expect(source).not.toMatch(/(?:CHF|EUR|€)\s*(?:49|99|199)\b/)
      expect(source).not.toMatch(/amount_minor_units\s*:\s*(?:4900|9900|19900)\b/)
    }
  })

  it('suit exclusivement le plan recommandé fourni par l’API', async () => {
    const catalogue = { ...CATALOGUE, plans: CATALOGUE.plans.map((plan) => ({ ...plan, recommended: plan.plan_code === 'essential' })) }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    const { container } = renderApp(<AppRoutes />, { route: '/tarifs' })
    const ribbon = await screen.findByText('Recommandé')
    expect(within(ribbon.closest('article')!).getByRole('heading', { name: 'Essentiel' })).toBeInTheDocument()
    expect(screen.getAllByText('Recommandé')).toHaveLength(1)

    const table = container.querySelector<HTMLElement>('.table-wrap table')!
    const headers = within(table).getAllByRole('columnheader')
    expect(headers.find((header) => header.textContent === 'Essentiel')).toHaveClass('pro-col')
    expect(headers.find((header) => header.textContent === 'Pro')).not.toHaveClass('pro-col')
    for (const row of within(table).getAllByRole('row').slice(1)) {
      const cells = within(row).getAllByRole('cell')
      expect(cells[1]).toHaveClass('pro-col')
      expect(cells[2]).not.toHaveClass('pro-col')
    }
  })

  it('conserve quatre cartes de cinq lignes pendant le chargement', () => {
    let release!: () => void
    const pendingCatalogue = new Promise<{ body: PlanCatalogue }>((resolve) => {
      release = () => resolve({ body: CATALOGUE })
    })
    mockApi({ 'GET /billing/plans': () => pendingCatalogue })

    const view = renderApp(<AppRoutes />, { route: '/tarifs' })
    const grid = view.container.querySelector('.pricing-grid')!
    expect(grid).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByRole('status')).toHaveClass('hero-facts')
    expect(screen.getByRole('status')).toHaveTextContent('Chargement des offres')
    expect(grid.children).toHaveLength(4)
    const cards = Array.from(grid.querySelectorAll('.price-card'))
    expect(cards).toHaveLength(4)
    for (const card of cards) {
      expect(card.querySelector('.plan-intro')).toHaveTextContent('Informations')
      expect(Array.from(card.querySelectorAll('ul > li'), (item) => item.textContent)).toEqual([
        'Chargement du contenu de l’offre…',
        'Chargement de la couverture…',
        'Chargement des accès…',
        'Chargement des alertes…',
        'Chargement de l’historique…',
      ])
    }

    view.unmount()
    release()
  })

  it('affiche la géométrie source et un état honnête quand le catalogue échoue', async () => {
    mockApi({ 'GET /billing/plans': { status: 503, body: { detail: { code: 'billing_unavailable' } } } })
    const { container } = renderApp(<AppRoutes />, { route: '/tarifs' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveClass('hero-facts')
    expect(alert).toHaveTextContent('Les tarifs sont momentanément indisponibles')
    expect(container.querySelector('.pricing-grid')?.children).toHaveLength(4)
    const cards = Array.from(container.querySelectorAll('.pricing-grid .price-card'))
    expect(cards).toHaveLength(4)
    for (const card of cards) {
      expect(card).toHaveTextContent('Catalogue indisponible')
      expect(card.querySelector('.plan-intro')).toHaveTextContent('Informations')
      expect(Array.from(card.querySelectorAll('ul > li'), (item) => item.textContent)).toEqual([
        'Contenu indisponible',
        'Couverture indisponible',
        'Accès indisponibles',
        'Alertes indisponibles',
        'Historique indisponible',
      ])
    }
    expect(document.body.textContent).not.toMatch(/CHF\s?49|CHF\s?99|CHF\s?199/)
    expect(screen.queryByRole('link', { name: 'Choisir Essentiel' })).not.toBeInTheDocument()
  })

  it('préserve les cinq fragments de chaque offre sans inventer de droit', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, { route: '/tarifs' })
    await screen.findByRole('link', { name: 'Choisir Essentiel' })

    const features = (name: string) => Array.from(
      screen.getByRole('heading', { name }).closest('article')!.querySelectorAll('ul > li'),
      (item) => item.textContent,
    )
    expect(features('Découverte')).toEqual([
      '3 signaux complets dès l’inscription',
      'Sans alerte récurrente',
      '1 profil cible · 1 territoire',
      'Entreprise, marché, besoin possible et calendrier',
      'Source officielle associée',
    ])
    expect(features('Essentiel')).toEqual([
      'Tous les signaux correspondant à votre cible',
      '1 profil cible · 1 territoire',
      'Contexte, calendrier et source',
      'Alerte hebdomadaire',
      '30 jours d’historique à l’activation',
    ])
    expect(features('Pro')).toEqual([
      'Tout Essentiel',
      '3 profils cibles · Plusieurs territoires par profil',
      'Alertes quotidiennes',
      '365 jours d’historique',
      'Contexte, calendrier et source',
    ])
    expect(features('Scale')).toEqual([
      'Tout Pro',
      '10 profils cibles',
      'Couverture territoriale étendue',
      'Alertes prioritaires après détection',
      'Tout l’historique conservé',
    ])
    expect(screen.getByRole('heading', { name: 'Essentiel' }).closest('article')).not.toHaveTextContent('1 utilisateur')
    expect(container).not.toHaveTextContent(/Priorisation par pertinence et calendrier|Filtrage (?:essentiel|minimum)/)
  })

  it.each(AGGREGATE_DOWNGRADES)(
    'retire Tout Essentiel quand %s',
    async (_label, changes) => {
      const catalogue = {
        ...CATALOGUE,
        plans: CATALOGUE.plans.map((plan) => {
          if (plan.plan_code === 'essential' && changes.essential) {
            return { ...plan, entitlements: { ...plan.entitlements, ...changes.essential } }
          }
          if (plan.plan_code === 'pro' && changes.pro) {
            return { ...plan, entitlements: { ...plan.entitlements, ...changes.pro } }
          }
          return plan
        }),
      }
      mockApi({ 'GET /billing/plans': { body: catalogue } })
      renderApp(<AppRoutes />, { route: '/tarifs' })

      await screen.findByRole('link', { name: 'Choisir Essentiel' })
      const pro = screen.getByRole('heading', { name: 'Pro' }).closest('article')!
      expect(pro).not.toHaveTextContent('Tout Essentiel')
      expect(pro).toHaveTextContent(/flux (?:inclus|non inclus)/)
    },
  )

  it('retire les agrégats quand le plan de référence est absent', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans
        .filter((plan) => plan.plan_code !== 'essential' && plan.plan_code !== 'pro')
        .map((plan) => plan.plan_code === 'scale'
          ? { ...plan, entitlements: { ...plan.entitlements, filter_level: 'advanced' as const } }
          : plan),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/tarifs' })

    await screen.findByRole('link', { name: 'Choisir Scale' })
    const scale = screen.getByRole('heading', { name: 'Scale' }).closest('article')!
    expect(scale).not.toHaveTextContent('Tout Pro')
    expect(scale).toHaveTextContent('flux inclus · contexte inclus · source incluse')
  })

  it('contacte Kivou pour un plan non achetable même sans prix et bloque seulement le checkout sans prix', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) => {
        if (plan.plan_code === 'essential') {
          return { ...plan, purchasable: false, monthly_price: {} }
        }
        if (plan.plan_code === 'pro') return { ...plan, purchasable: true, monthly_price: {} }
        return plan
      }),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/tarifs' })
    await screen.findByRole('link', { name: 'Choisir Scale' })

    const essential = screen.getByRole('heading', { name: 'Essentiel' }).closest('article')!
    expect(within(essential).getByRole('link', { name: 'Choisir Essentiel' })).toHaveAttribute('href', '/contact')
    const pro = screen.getByRole('heading', { name: 'Pro' }).closest('article')!
    expect(within(pro).queryByRole('link', { name: 'Choisir Pro' })).not.toBeInTheDocument()
    expect(within(pro).getByText('Choisir Pro')).toHaveAttribute('aria-disabled', 'true')
  })

  it('conserve cinq lignes et distingue une offre absente du catalogue', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.filter((plan) => plan.plan_code !== 'scale'),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/tarifs' })
    await screen.findByRole('link', { name: 'Choisir Essentiel' })

    const scale = screen.getByRole('heading', { name: 'Scale' }).closest('article')!
    expect(scale).toHaveTextContent('Offre absente du catalogue')
    expect(scale.querySelector('.plan-intro')).toHaveTextContent('Informations')
    expect(Array.from(scale.querySelectorAll('ul > li'), (item) => item.textContent)).toEqual([
      'Contenu non publié',
      'Couverture non publiée',
      'Accès non publiés',
      'Alertes non publiées',
      'Historique non publié',
    ])
    expect(within(scale).queryByRole('link')).not.toBeInTheDocument()
  })

  it('préserve les actions de facturation serveur dans le dashboard', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })
    expect(await screen.findByRole('button', { name: 'Choisir Essentiel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choisir Pro' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choisir Scale' })).toBeInTheDocument()
  })
})
