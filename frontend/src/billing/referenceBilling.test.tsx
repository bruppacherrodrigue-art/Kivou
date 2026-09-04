import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  PRO_CANCELLING_STATUS,
  PRO_STATUS,
  RECOVER_STATUS,
  SUPPORT_STATUS,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'
import type { BillingStatus } from '../api/types'

const assign = vi.fn()

beforeEach(() => {
  assign.mockClear()
  vi.stubGlobal('location', { ...window.location, assign })
})

afterEach(() => vi.unstubAllGlobals())

const shell = {
  'GET /target-icps': { body: [ICP] },
  'GET /billing/plans': { body: CATALOGUE },
}

function routes(status: BillingStatus) {
  return {
    ...shell,
    'GET /billing/status': { body: status },
  }
}

function exactBillingPanel() {
  return document.querySelector('.settings-form-card.billing-settings-card') as HTMLElement
}

describe('facturation exacte sous autorité backend', () => {
  it.each([
    [PRO_STATUS, /gérer ma facturation/i],
    [RECOVER_STATUS, /ouvrir le portail de facturation/i],
  ] as const)('utilise le portail uniquement pour l’action backend %s', async (status, label) => {
    const user = userEvent.setup()
    mockApi({
      ...routes(status),
      'POST /billing/portal': {
        body: { portal_url: 'https://billing.stripe.test/session' },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: label }))
    expect(exactBillingPanel()).not.toBeNull()
    expect(callsTo('/billing/portal')).toHaveLength(1)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('ouvre un checkout seulement pour choose_plan et un plan explicite du catalogue', async () => {
    const user = userEvent.setup()
    mockApi({
      ...routes(DISCOVERY_STATUS),
      'POST /billing/checkout': (request) => ({
        body: {
          checkout_url: 'https://checkout.stripe.test/session',
          ...(request.body as object),
        },
      }),
    })
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    expect(callsTo('/billing/checkout')).toHaveLength(0)
    await user.click(await screen.findByRole('button', { name: /choisir essentiel/i }))
    expect(exactBillingPanel()).not.toBeNull()
    expect(callsTo('/billing/checkout')[0].body).toEqual({ plan: 'essential', currency: 'chf' })
  })

  it.each([
    ['essential', 'Essentiel'],
    ['pro', 'Pro'],
    ['scale', 'Scale'],
  ] as const)(
    'honore le choix public %s dans le sélecteur et le payload checkout',
    async (planCode, planName) => {
      const user = userEvent.setup()
      mockApi({
        ...routes(DISCOVERY_STATUS),
        'POST /billing/checkout': (request) => ({
          body: {
            checkout_url: 'https://checkout.stripe.test/session',
            ...(request.body as object),
          },
        }),
      })
      renderApp(<AppRoutes />, {
        route: `/app/billing?plan=${planCode}`,
        session: AUTHENTICATED,
      })

      const selector = await screen.findByLabelText('Offre')
      expect(selector).toHaveValue(planCode)
      await user.click(screen.getByRole('button', { name: new RegExp(`choisir ${planName}`, 'i') }))
      expect(callsTo('/billing/checkout')[0].body).toEqual({ plan: planCode, currency: 'chf' })
    },
  )

  it('affiche uniquement les prix et droits fournis par le catalogue réel', async () => {
    mockApi(routes(DISCOVERY_STATUS))
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    const panel = await waitFor(() => {
      const element = exactBillingPanel()
      expect(element).not.toBeNull()
      return element
    })
    const plan = within(panel).getByLabelText('Offre')
    expect(within(plan).getByRole('option', { name: /Essentiel · 49/ })).toBeVisible()
    expect(within(plan).getByRole('option', { name: /Pro · 99/ })).toBeVisible()
    expect(within(plan).getByRole('option', { name: /Scale · 199/ })).toBeVisible()
    expect(document.body).not.toHaveTextContent(/29[.,]00|59[.,]00|129[.,]00/)
  })

  it('conserve Découverte et le badge recommandé dans le sélecteur sans rendre Découverte achetable', async () => {
    const user = userEvent.setup()
    mockApi(routes(DISCOVERY_STATUS))
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    const selector = await screen.findByLabelText('Offre')
    expect(within(selector).getByRole('option', { name: /Découverte · Gratuit/ })).toBeVisible()
    expect(within(selector).getByRole('option', { name: /Pro · 99.*Recommandé/ })).toBeVisible()

    await user.selectOptions(selector, 'discovery')
    expect(screen.getByRole('link', { name: /voir les signaux accessibles/i })).toHaveAttribute(
      'href',
      '/app/signals',
    )
    expect(screen.queryByRole('button', { name: /choisir découverte/i })).not.toBeInTheDocument()
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('sépare clairement l’offre sélectionnée de l’offre actuelle et rend cinq droits réels', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) => plan.plan_code === 'essential'
        ? {
            ...plan,
            entitlements: {
              ...plan.entitlements,
              granted_signals: 7,
              evidence_access: false,
            },
          }
        : plan),
    }
    mockApi({
      ...routes(DISCOVERY_STATUS),
      'GET /billing/plans': { body: catalogue },
    })
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    await screen.findByLabelText('Offre')
    const panel = exactBillingPanel()
    expect(within(panel).getByText('Offre sélectionnée')).toBeVisible()
    expect(within(panel).getByRole('heading', { level: 3 })).toHaveTextContent(/Essentiel · 49/)
    expect(panel.querySelector(':scope > .billing-plan-selector.form-field')).not.toBeNull()
    expect(panel.querySelectorAll('.billing-entitlements > div')).toHaveLength(5)
    expect(within(panel).getByText(/7 signaux réels débloqués/)).toBeVisible()
    expect(within(panel).getByText(/preuve documentaire non incluse/i)).toBeVisible()
  })

  it('ne présente jamais un prix catalogue comme le prix facturé de l’abonnement actuel', async () => {
    const founding = { ...PRO_STATUS, offer_code: 'founding', currency: null }
    mockApi(routes(founding))
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    const panel = await waitFor(() => exactBillingPanel())
    expect(within(panel).getByText('Offre actuelle')).toBeVisible()
    expect(within(panel).getByRole('heading', { level: 3 })).toHaveTextContent(/^Pro$/)
    expect(within(panel).queryByText(/99|CHF|EUR/)).not.toBeInTheDocument()
    expect(within(panel).getByText(tManageLeadFr())).toBeVisible()
  })

  it('ne transforme pas zéro signal ouvert Discovery en absence de flux pour une offre payée', async () => {
    mockApi(routes(PRO_STATUS))
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    const panel = await screen.findByText(tManageLeadFr()).then(() => exactBillingPanel())
    expect(within(panel).queryByText(/0 signaux réels débloqués/)).not.toBeInTheDocument()
    expect(within(panel).getByText(/accès au flux et aux détails/i)).toBeVisible()
    expect(within(panel).getByText(/preuve documentaire complète/i)).toBeVisible()
  })

  it('rend le support humain sans aucune mutation Stripe', async () => {
    mockApi(routes(SUPPORT_STATUS))
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    expect(await screen.findByRole('link', { name: /contact@kivou\.eu/i })).toHaveAttribute(
      'href',
      'mailto:contact@kivou.eu',
    )
    expect(exactBillingPanel()).not.toBeNull()
    expect(callsTo('/billing/portal')).toHaveLength(0)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('rend la date de résiliation fournie par le serveur dans la carte exacte', async () => {
    mockApi(routes(PRO_CANCELLING_STATUS))
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    expect(await screen.findByText(/18 septembre 2026/)).toBeVisible()
    expect(exactBillingPanel()).not.toBeNull()
    expect(document.body).not.toHaveTextContent(PRO_CANCELLING_STATUS.scheduled_cancellation_at!)
  })

  it('garde le portail disponible si le catalogue tombe, sans ouvrir de checkout', async () => {
    const user = userEvent.setup()
    mockApi({
      ...routes(PRO_STATUS),
      'GET /billing/plans': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
      'POST /billing/portal': {
        body: { portal_url: 'https://billing.stripe.test/session' },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: /gérer ma facturation/i }))
    expect(callsTo('/billing/portal')).toHaveLength(1)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('ne présente jamais comme gratuit un prix absent dans la devise sélectionnée', async () => {
    const user = userEvent.setup()
    const missingChf = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) =>
        plan.plan_code === 'essential'
          ? { ...plan, monthly_price: { eur: plan.monthly_price.eur } }
          : plan,
      ),
    }
    mockApi({
      ...routes(DISCOVERY_STATUS),
      'GET /billing/plans': { body: missingChf },
    })
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    const selector = await screen.findByLabelText('Offre')
    await user.selectOptions(selector, 'essential')
    const panel = exactBillingPanel()
    const liveSelector = panel.querySelector('.billing-plan-selector') as HTMLElement
    expect(within(liveSelector).getByText('—')).toBeVisible()
    expect(within(liveSelector).queryByText('Gratuit')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /choisir essentiel/i })).toBeDisabled()
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('refuse une destination non HTTPS renvoyée par le backend', async () => {
    const user = userEvent.setup()
    mockApi({
      ...routes(DISCOVERY_STATUS),
      'POST /billing/checkout': {
        body: {
          checkout_url: 'http://checkout.stripe.test/session',
          plan: 'essential',
          currency: 'chf',
        },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: /choisir essentiel/i }))
    expect(await screen.findByRole('alert')).toBeVisible()
    expect(assign).not.toHaveBeenCalled()
  })

  it('ignore une réponse Stripe tardive après démontage et verrouille les doubles clics', async () => {
    const user = userEvent.setup()
    let release!: () => void
    mockApi({
      ...routes(DISCOVERY_STATUS),
      'POST /billing/checkout': () => new Promise((resolve) => {
        release = () => resolve({
          body: {
            checkout_url: 'https://checkout.stripe.test/session',
            plan: 'essential',
            currency: 'chf',
          },
        })
      }),
    })
    const app = renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    const choose = await screen.findByRole('button', { name: /choisir essentiel/i })
    await user.click(choose)
    await user.click(choose)
    expect(callsTo('/billing/checkout')).toHaveLength(1)
    app.unmount()
    release()
    await waitFor(() => expect(assign).not.toHaveBeenCalled())
  })
})

function tManageLeadFr() {
  return 'Moyen de paiement, factures et résiliation sont gérés dans votre portail de facturation.'
}
