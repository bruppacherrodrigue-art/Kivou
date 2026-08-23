import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  ME,
  PRO_STATUS,
  UNAUTHENTICATED,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const DASHBOARD_ROUTES = {
  'GET /signals': { body: { items: [], total: 0, limit: 20, offset: 0 } },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
  'GET /notification-preferences': {
    body: { email_enabled: true, notification_email: 'claire@acme.test' },
  },
}

describe('accueil connecté', () => {
  it('fait de /app/dashboard la destination de /app pour un compte prêt', async () => {
    mockApi(DASHBOARD_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app' })

    expect(await screen.findByRole('heading', { level: 1, name: 'Tableau de bord' })).toBeInTheDocument()
  })

  it('rend le dashboard accessible dans la navigation authentifiée en FR et EN', async () => {
    mockApi(DASHBOARD_ROUTES)
    const { unmount } = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/app/dashboard',
      locale: 'fr',
    })

    expect(await screen.findByRole('link', { name: 'Accueil' })).toHaveAttribute(
      'href',
      '/app/dashboard',
    )

    unmount()
    mockApi(DASHBOARD_ROUTES)
    renderApp(<AppRoutes />, {
      session: {
        status: 'authenticated',
        me: { ...ME, locale: 'en' },
      },
      route: '/app/dashboard',
      locale: 'en',
    })

    expect(await screen.findByRole('link', { name: 'Dashboard' })).toHaveAttribute(
      'href',
      '/app/dashboard',
    )
  })

  it('redirige un compte incomplet avant tout appel aux API du dashboard', async () => {
    mockApi(DASHBOARD_ROUTES)
    renderApp(<AppRoutes />, {
      session: {
        status: 'authenticated',
        me: { ...ME, onboarding_status: 'account_created' },
      },
      route: '/app/dashboard',
    })

    expect(
      await screen.findByRole('heading', { name: 'Configurer votre profil de ciblage' }),
    ).toBeInTheDocument()
    expect(callsTo('/signals', 'GET')).toHaveLength(0)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(0)
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(0)
  })

  it('envoie un login prêt vers le dashboard mais conserve une destination profonde demandée', async () => {
    const user = userEvent.setup()
    mockApi({
      ...DASHBOARD_ROUTES,
      'POST /auth/login': { body: ME },
    })
    const first = renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/login' })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText('Mot de passe'), 'motdepassesolide')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Tableau de bord' })).toBeInTheDocument()

    first.unmount()
    mockApi({
      ...DASHBOARD_ROUTES,
      'POST /auth/login': { body: ME },
    })
    renderApp(<AppRoutes />, {
      session: UNAUTHENTICATED,
      route: { pathname: '/login', state: { from: '/app/icps' } },
    })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText('Mot de passe'), 'motdepassesolide')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))
    expect(await screen.findByRole('link', { name: 'Profils de ciblage' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})

describe('chargements indépendants', () => {
  it('démarre le feed, le billing, les ICP et les préférences sans attendre une autre source', async () => {
    const pending = () => new Promise<never>(() => undefined)
    mockApi({
      'GET /signals': pending,
      'GET /billing/status': pending,
      'GET /target-icps': pending,
      'GET /notification-preferences': pending,
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    await waitFor(() => {
      expect(callsTo('/signals', 'GET')).toHaveLength(1)
      expect(callsTo('/billing/status', 'GET')).toHaveLength(1)
      expect(callsTo('/target-icps', 'GET')).toHaveLength(1)
      expect(callsTo('/notification-preferences', 'GET')).toHaveLength(1)
    })
  })

  it('relit billing exactement une fois après le feed et ignore la première réponse devenue ancienne', async () => {
    let resolveInitial: ((value: { body: typeof DISCOVERY_STATUS }) => void) | undefined
    let resolveRefresh: ((value: { body: typeof PRO_STATUS }) => void) | undefined
    let billingCall = 0

    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /billing/status': () => {
        billingCall += 1
        if (billingCall === 1) {
          return new Promise((resolve) => {
            resolveInitial = resolve
          })
        }
        return new Promise((resolve) => {
          resolveRefresh = resolve
        })
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    await waitFor(() => expect(callsTo('/billing/status', 'GET')).toHaveLength(2))

    await act(async () => {
      resolveRefresh?.({ body: PRO_STATUS })
    })
    expect(await screen.findByText('Pro')).toBeInTheDocument()

    await act(async () => {
      resolveInitial?.({ body: DISCOVERY_STATUS })
    })
    await waitFor(() => expect(screen.getByText('Pro')).toBeInTheDocument())
    expect(screen.queryByText('Découverte')).not.toBeInTheDocument()
    expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
  })
})
