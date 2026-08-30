import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, UNAUTHENTICATED, callsTo, mockApi, renderApp } from '../test/harness'

describe('port exact de la référence publique', () => {
  it('renders the exact public reference shell without a locale switch', () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const view = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const nav = screen.getByRole('navigation', { name: 'Navigation principale' })
    const primaryLinks = Array.from(nav.querySelectorAll(':scope > .brand, :scope > .nav-links a, :scope > .nav-actions > a'))
    expect(primaryLinks.map((link) => link.textContent)).toEqual([
      expect.stringContaining('KIVOU'),
      'Accueil',
      'Comment ça marche',
      'Exemple de signal',
      'Tarifs',
      'Contact',
      'Se connecter',
      'Essayer gratuitement',
    ])
    expect(document.querySelector('.site-header .site-nav.container')).not.toBeNull()
    expect(screen.queryByText(/^FR$|^EN$/)).not.toBeInTheDocument()
    expect(nav.querySelector('.nav-actions > a')).toHaveAttribute('href', '/login')
    view.unmount()
  })

  it.each(['/produit', '/tarifs', '/exemple-de-signal', '/contact', '/informations-legales'])(
    'keeps the reference header and footer on %s',
    (route) => {
      mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
      const view = renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
      expect(document.querySelector('header.site-header')).not.toBeNull()
      expect(screen.getByRole('contentinfo')).toHaveClass('site-footer')
      expect(screen.getAllByRole('main')).toHaveLength(1)
      view.unmount()
    },
  )

  it.each(['/contact', '/informations-legales'])(
    'does not load the catalogue on non-packaging page %s',
    (route) => {
      mockApi({})
      renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
      expect(screen.getByRole('main')).toBeInTheDocument()
      expect(callsTo('/billing/plans', 'GET')).toHaveLength(0)
    },
  )

  it('uses catalogue prices in the exact reference pricing cards and table', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) => ({
        ...plan,
        monthly_price:
          plan.plan_code === 'essential'
            ? { chf: { amount_minor_units: 5700, currency: 'chf' as const } }
            : plan.plan_code === 'pro'
              ? { chf: { amount_minor_units: 11300, currency: 'chf' as const } }
              : plan.monthly_price,
      })),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/tarifs', session: UNAUTHENTICATED })
    await screen.findByText('57')
    const essential = screen.getByRole('heading', { name: 'Essentiel' }).closest('article')!
    expect(within(essential).getByText('CHF')).toBeInTheDocument()
    expect(within(essential).getByText('57')).toBeInTheDocument()
    expect(within(essential).queryByText('49')).not.toBeInTheDocument()
    const pro = screen.getByRole('heading', { name: 'Pro' }).closest('article')!
    expect(within(pro).getByText('113')).toBeInTheDocument()
    expect(document.querySelectorAll('.pricing-grid .price-card')).toHaveLength(4)
  })

  it('shows an honest same-geometry error when the catalogue is unavailable', async () => {
    mockApi({
      'GET /billing/plans': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
    })
    renderApp(<AppRoutes />, { route: '/tarifs', session: UNAUTHENTICATED })
    expect(await screen.findByRole('alert')).toHaveTextContent('tarifs')
    expect(document.querySelector('.pricing-grid')).not.toBeNull()
    expect(screen.queryByText(/CHF 49|CHF 99|CHF 199/)).not.toBeInTheDocument()
  })

  it('uses the same catalogue authority in the home offer matrix', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) => ({
        ...plan,
        monthly_price: plan.plan_code === 'essential'
          ? { chf: { amount_minor_units: 5700, currency: 'chf' as const } }
          : plan.monthly_price,
      })),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    expect(await screen.findByText(/CHF\s+57/)).toBeInTheDocument()
    expect(screen.queryByText('CHF 49')).not.toBeInTheDocument()
  })

  it('does not promise a weekly Discovery signal when the catalogue cadence is none', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    await screen.findByText(/3 signaux gratuits/)
    expect(container).not.toHaveTextContent(/1 nouveau signal par semaine|1 par semaine|1\/semaine/i)
    expect(container).toHaveTextContent(/sans (?:envoi|alerte) récurrent/i)
  })

  it.each([
    {
      route: '/',
      readyText: 'Voir mon premier signal',
      expected: ['1 signal gratuit', '1 signal complet, sans alerte récurrente'],
    },
    {
      route: '/tarifs',
      readyText: 'Choisir Essentiel',
      expected: ['1 signal gratuit', '1 signal complet dès l’inscription'],
    },
    {
      route: '/produit',
      readyText: 'Le premier est accessible gratuitement, sans alerte récurrente.',
      expected: ['Le premier est accessible gratuitement'],
    },
    {
      route: '/exemple-de-signal',
      readyText: 'Le premier est accessible dès l’inscription, sans alerte récurrente.',
      expected: ['Le premier est accessible dès l’inscription'],
    },
  ])(
    'accorde le quota Découverte au singulier sur $route',
    async ({ route, readyText, expected }) => {
      const catalogue = {
        ...CATALOGUE,
        plans: CATALOGUE.plans.map((plan) => plan.plan_code === 'discovery'
          ? { ...plan, entitlements: { ...plan.entitlements, granted_signals: 1 } }
          : plan),
      }
      mockApi({ 'GET /billing/plans': { body: catalogue } })
      const view = renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })

      await screen.findByText(readyText)
      expect(view.container).not.toHaveTextContent(/\b1 signaux\b/)
      for (const fragment of expected) expect(view.container).toHaveTextContent(fragment)
    },
  )

  it('does not reconstruct user or five-country quotas absent from the catalogue', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, {
      route: '/tarifs',
      session: UNAUTHENTICATED,
    })
    await screen.findByRole('heading', { name: 'Pro' })
    expect(container).not.toHaveTextContent(/1 utilisateur|jusqu’à 5 pays/i)
    expect(container).toHaveTextContent('Plusieurs territoires par profil')
  })

  it('keeps all four public slots honest when a catalogue plan is absent', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.filter((plan) => plan.plan_code !== 'scale'),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/tarifs', session: UNAUTHENTICATED })
    await screen.findByRole('link', { name: 'Choisir Essentiel' })
    expect(document.querySelectorAll('.pricing-grid .price-card')).toHaveLength(4)
    const scale = screen.getByRole('heading', { name: 'Scale' }).closest('article')!
    expect(scale).toHaveTextContent('Indisponible')
    expect(within(scale).queryByRole('link')).not.toBeInTheDocument()
  })

  it('keeps the landing Discovery CTA grammatical and explained while loading', () => {
    let release!: () => void
    const pendingCatalogue = new Promise<{ body: typeof CATALOGUE }>((resolve) => {
      release = () => resolve({ body: CATALOGUE })
    })
    mockApi({ 'GET /billing/plans': () => pendingCatalogue })

    const view = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const cta = screen.getByText('Voir mes premiers signaux')
    expect(cta).toHaveAttribute('aria-disabled', 'true')
    expect(cta).toHaveAttribute('aria-describedby', 'landing-discovery-status')
    expect(screen.getByRole('status')).toHaveTextContent('Chargement des offres')
    expect(document.body).not.toHaveTextContent('Voir mes  premiers signaux')

    view.unmount()
    release()
  })

  it('keeps the landing Discovery CTA grammatical and locally alerted on error', async () => {
    mockApi({
      'GET /billing/plans': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
    })
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveAttribute('id', 'landing-discovery-status')
    expect(alert).toHaveTextContent('Les offres sont momentanément indisponibles')
    expect(screen.getByText('Voir mes premiers signaux')).toHaveAttribute('aria-disabled', 'true')
    expect(document.body).not.toHaveTextContent('Voir mes  premiers signaux')
  })

  it('keeps the landing Discovery CTA grammatical when that plan is absent', async () => {
    mockApi({
      'GET /billing/plans': {
        body: {
          ...CATALOGUE,
          plans: CATALOGUE.plans.filter((plan) => plan.plan_code !== 'discovery'),
        },
      },
    })
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    expect(await screen.findByText('L’offre Découverte est absente du catalogue.')).toHaveAttribute(
      'id',
      'landing-discovery-status',
    )
    expect(screen.getByText('Voir mes premiers signaux')).toHaveAttribute('aria-disabled', 'true')
    expect(document.body).not.toHaveTextContent('Voir mes  premiers signaux')
  })

  it('preserves each page-specific Discovery sentence', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const product = renderApp(<AppRoutes />, { route: '/produit', session: UNAUTHENTICATED })
    expect(await screen.findByText('Les trois premiers sont accessibles gratuitement, sans alerte récurrente.')).toBeInTheDocument()
    product.unmount()

    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const signal = renderApp(<AppRoutes />, { route: '/exemple-de-signal', session: UNAUTHENTICATED })
    expect(await screen.findByText('Les trois premiers sont accessibles dès l’inscription, sans alerte récurrente.')).toBeInTheDocument()
    signal.unmount()

    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/tarifs', session: UNAUTHENTICATED })
    const finalCta = document.querySelector<HTMLElement>('.pricing-page .final-cta')!
    expect(await within(finalCta).findByText('Commencez sans carte bancaire, sans alerte récurrente.')).toBeInTheDocument()
  })

  it.each(['/produit', '/exemple-de-signal'])(
    'keeps one status paragraph in the final CTA while %s pricing loads',
    (route) => {
      let release!: () => void
      const pendingCatalogue = new Promise<{ body: typeof CATALOGUE }>((resolve) => {
        release = () => resolve({ body: CATALOGUE })
      })
      mockApi({ 'GET /billing/plans': () => pendingCatalogue })

      const view = renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
      const copy = view.container.querySelector<HTMLElement>('.final-cta-grid > div:first-child')!
      expect(copy.querySelectorAll(':scope > p')).toHaveLength(1)
      expect(within(copy).getByRole('status')).toHaveTextContent('Chargement de l’offre Découverte')

      view.unmount()
      release()
    },
  )

  it.each(['/produit', '/exemple-de-signal'])(
    'keeps one alert paragraph in the final CTA when %s pricing fails',
    async (route) => {
      mockApi({
        'GET /billing/plans': {
          status: 503,
          body: { detail: { code: 'billing_unavailable' } },
        },
      })
      const view = renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
      const copy = view.container.querySelector<HTMLElement>('.final-cta-grid > div:first-child')!
      const alert = await within(copy).findByRole('alert')
      expect(alert).toHaveTextContent('Les tarifs sont momentanément indisponibles')
      expect(copy.querySelectorAll(':scope > p')).toHaveLength(1)
    },
  )

  it.each(['/', '/produit', '/tarifs', '/exemple-de-signal'])(
    'retries the failed authoritative catalogue locally on %s',
    async (route) => {
      const user = userEvent.setup()
      let attempt = 0
      mockApi({
        'GET /billing/plans': () => {
          attempt += 1
          return attempt === 1
            ? { status: 503, body: { detail: { code: 'billing_unavailable' } } }
            : { body: CATALOGUE }
        },
      })
      renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })

      await user.click(await screen.findByRole('button', {
        name: 'Réessayer le chargement des tarifs',
      }))

      await waitFor(() => expect(callsTo('/billing/plans', 'GET')).toHaveLength(2))
      await waitFor(() => expect(screen.queryByRole('button', {
        name: 'Réessayer le chargement des tarifs',
      })).not.toBeInTheDocument())
    },
  )
})
