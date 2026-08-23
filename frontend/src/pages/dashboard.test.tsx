import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_DETAIL,
  LOCKED_ITEM,
  ME,
  PRO_CANCELLING_OTHER_DATE_STATUS,
  PRO_STATUS,
  RECOVER_STATUS,
  SUPPORT_STATUS,
  UNAUTHENTICATED,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const DASHBOARD_ROUTES = {
  'GET /signals': { body: { items: [], total: 0, limit: 20, offset: 0 } },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
  'GET /notification-preferences': {
    body: {
      email_enabled: true,
      notification_email: 'claire@acme.test',
      updated_at: '2026-08-18T09:00:00+00:00',
    },
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

describe('accès à la fiche entreprise', () => {
  it('charge au plus le détail du premier signal déclaré déverrouillé par le feed', async () => {
    const first = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_first_unlocked',
      company: { ...UNLOCKED_ITEM.company, name: 'Premier serveur SA' },
    }
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_second_unlocked',
      company: { ...UNLOCKED_ITEM.company, name: 'Second serveur SA' },
    }
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([LOCKED_ITEM, first, second]) },
      'GET /signals/sig_first_unlocked': {
        body: {
          ...UNLOCKED_DETAIL,
          signal_id: first.signal_id,
          company: first.company,
          company_key: 'cmp_first_authorized',
        },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByRole('link', { name: 'Consulter la fiche entreprise' })).toHaveAttribute(
      'href',
      '/app/companies/cmp_first_authorized',
    )
    expect(callsTo('/signals/sig_first_unlocked', 'GET')).toHaveLength(1)
    expect(callsTo('/signals/sig_second_unlocked', 'GET')).toHaveLength(0)
    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
  })

  it.each([
    ['un feed vide', []],
    ['des signaux tous verrouillés', [LOCKED_ITEM]],
  ])('ne charge aucun détail avec %s', async (_label, items) => {
    mockApi({ ...DASHBOARD_ROUTES, 'GET /signals': { body: feedPage(items) } })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(1))

    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
    expect(screen.queryByText('Fiche entreprise')).not.toBeInTheDocument()
  })

  it('masque toute action entreprise si le détail répond verrouillé', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: LOCKED_DETAIL },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    await waitFor(() => expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1))

    expect(screen.queryByRole('link', { name: 'Consulter la fiche entreprise' })).not.toBeInTheDocument()
    expect(screen.queryByText('Fiche indisponible')).not.toBeInTheDocument()
  })

  it('dit seulement Fiche indisponible après un détail accessible sans company_key', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: { ...UNLOCKED_DETAIL, company_key: null } },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Fiche indisponible')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Consulter la fiche entreprise' })).not.toBeInTheDocument()
  })

  it('propose une reprise locale si le détail échoue sans annoncer une indisponibilité', async () => {
    const user = userEvent.setup()
    let detailCall = 0
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': () => {
        detailCall += 1
        return detailCall === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: UNLOCKED_DETAIL }
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const retry = await screen.findByRole('button', { name: 'Réessayer la fiche entreprise' })
    expect(screen.queryByText('Fiche indisponible')).not.toBeInTheDocument()
    await user.click(retry)

    expect(await screen.findByRole('link', { name: 'Consulter la fiche entreprise' })).toHaveAttribute(
      'href',
      `/app/companies/${UNLOCKED_DETAIL.company_key}`,
    )
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(2)
  })

  it('rejoue un feed en erreur sans relire les ICP ou alertes et borne les appels dérivés', async () => {
    const user = userEvent.setup()
    let feedCall = 0
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': () => {
        feedCall += 1
        return feedCall === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: feedPage([UNLOCKED_ITEM]) }
      },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    await user.click(await screen.findByRole('button', { name: 'Réessayer les occasions' }))

    expect(await screen.findByRole('link', { name: 'Consulter la fiche entreprise' })).toBeInTheDocument()
    expect(callsTo('/signals', 'GET')).toHaveLength(2)
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(1)
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(1)
  })
})

describe('occasions et ciblages autoritaires', () => {
  it('rend un extrait du feed dans l’ordre serveur avec le bon CTA de détail', async () => {
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_server_second',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième dans la réponse' },
    }
    const first = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_server_first',
      company: { ...UNLOCKED_ITEM.company, name: 'Premier selon le score serveur' },
    }
    const fourth = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_not_in_excerpt',
      company: { ...UNLOCKED_ITEM.company, name: 'Hors extrait' },
    }
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([second, LOCKED_ITEM, first, fourth]) },
      'GET /signals/sig_server_second': {
        body: { ...UNLOCKED_DETAIL, signal_id: second.signal_id, company: second.company },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const opportunities = (await screen.findByRole('heading', {
      name: 'Prochaines occasions à examiner',
    })).closest('section')
    expect(opportunities).not.toBeNull()

    const cards = within(opportunities!).getAllByRole('article')
    expect(cards.map((card) => within(card).getByRole('heading').textContent)).toEqual([
      'Deuxième dans la réponse',
      LOCKED_ITEM.headline,
      'Premier selon le score serveur',
    ])
    expect(
      within(opportunities!).getAllByRole('link', { name: 'Examiner le signal' }).map((link) =>
        link.getAttribute('href'),
      ),
    ).toEqual(['/app/signals/sig_server_second', '/app/signals/sig_server_first'])
    expect(within(opportunities!).queryByText('Hors extrait')).not.toBeInTheDocument()
    expect(within(opportunities!).getByRole('link', { name: 'Voir tout le feed' })).toHaveAttribute(
      'href',
      '/app/signals',
    )
  })

  it('ne révèle aucun champ protégé même si un objet verrouillé malformé les contient', async () => {
    const leakingLocked = {
      ...LOCKED_ITEM,
      company: { name: 'ENTREPRISE SECRÈTE', country: 'FR', identifier: null },
      company_key: 'cmp_secret',
      contract: {
        title: 'MARCHÉ SECRET',
        reference: 'REF-SECRET',
        buyer: { name: 'ACHETEUR SECRET' },
        amount: { value: '999999', currency: 'EUR' },
      },
      analysis: { fit: { label: 'SCORE SECRET' } },
      source: { url: 'https://secret.invalid' },
    }
    mockApi({ ...DASHBOARD_ROUTES, 'GET /signals': { body: feedPage([leakingLocked]) } })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    await screen.findByText(LOCKED_ITEM.headline)

    const page = document.body.textContent ?? ''
    expect(page).not.toContain('ENTREPRISE SECRÈTE')
    expect(page).not.toContain('MARCHÉ SECRET')
    expect(page).not.toContain('REF-SECRET')
    expect(page).not.toContain('ACHETEUR SECRET')
    expect(page).not.toContain('999999')
    expect(page).not.toContain('SCORE SECRET')
    expect(page).not.toContain('cmp_secret')
    expect(screen.getByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it('affiche tous les ICP actifs dans l’ordre serveur avec résumé, territoires et limites', async () => {
    const first = {
      ...ICP,
      target_icp_id: 'icp_first',
      label: 'Isolation — Suisse et Belgique',
      customer_input: {
        ...ICP.customer_input,
        offer_summary: 'Isolation thermique pour bâtiments publics',
        territories: ['CH', 'BE'],
      },
    }
    const inactive = {
      ...ICP,
      target_icp_id: 'icp_inactive',
      label: 'Profil incomplet à ne pas afficher',
      status: 'incomplete',
    }
    const second = {
      ...ICP,
      target_icp_id: 'icp_second',
      label: 'Matériaux — France',
      plan_limit: { code: 'territory_limit', limit: 1, territory_count: 3 },
    }
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /target-icps': { body: [first, inactive, second] },
      'GET /billing/status': {
        body: { ...DISCOVERY_STATUS, target_icps_over_limit: ['icp_second'] },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const section = (await screen.findByRole('heading', { name: 'Ciblages actifs' })).closest(
      'section',
    )
    expect(section).not.toBeNull()

    const profiles = within(section!).getAllByRole('article')
    expect(profiles.map((profile) => within(profile).getByRole('heading').textContent)).toEqual([
      'Isolation — Suisse et Belgique',
      'Matériaux — France',
    ])
    expect(within(profiles[0]).getByText('Isolation thermique pour bâtiments publics')).toBeInTheDocument()
    expect(within(profiles[0]).getByText('Suisse, Belgique')).toBeInTheDocument()
    expect(within(profiles[1]).getByText('3 territoires configurés · limite de la formule : 1')).toBeInTheDocument()
    expect(within(profiles[1]).getByText('Au-delà de la limite de votre offre')).toBeInTheDocument()
    expect(within(section!).queryByText('Profil incomplet à ne pas afficher')).not.toBeInTheDocument()
    expect(within(section!).getAllByRole('link', { name: 'Gérer mes ciblages' })).toHaveLength(1)
  })

  it('affiche un état honnête et une seule action quand aucun ICP actif n’existe', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /target-icps': { body: [{ ...ICP, status: 'incomplete' }] },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Aucun ciblage actif utilisable.')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Gérer mes ciblages' })).toHaveLength(1)
  })
})

describe('facturation et alertes exactes', () => {
  it('affiche les compteurs Discovery exacts et l’action décidée par billing_action', async () => {
    mockApi(DASHBOARD_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const billing = (await screen.findByRole('heading', { name: 'Formule et accès' })).closest(
      'section',
    )
    expect(billing).not.toBeNull()
    expect(within(billing!).getByText('Découverte')).toBeInTheDocument()
    expect(within(billing!).getByText('3 déblocages utilisés')).toBeInTheDocument()
    expect(within(billing!).getByText('0 déblocages restants')).toBeInTheDocument()
    expect(within(billing!).getByText('Limite : 3')).toBeInTheDocument()
    expect(within(billing!).getByRole('link', { name: 'Choisir une formule' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it.each([
    [PRO_STATUS, 'Gérer mon abonnement'],
    [RECOVER_STATUS, 'Corriger le paiement'],
    [SUPPORT_STATUS, 'Contacter le support'],
  ])('rend le plan et le CTA sans rejouer la décision serveur %#', async (status, action) => {
    mockApi({ ...DASHBOARD_ROUTES, 'GET /billing/status': { body: status } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText(status.plan_code === 'pro' ? 'Pro' : 'Découverte')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: action })).toHaveAttribute('href', '/app/billing')
    expect(callsTo('/billing/plans', 'GET')).toHaveLength(0)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
    expect(document.body.textContent).not.toMatch(/price_id|CHF\s*\/|EUR\s*\//i)
  })

  it('affiche uniquement scheduled_cancellation_at sans emprunter current_period_end', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /billing/status': { body: PRO_CANCELLING_OTHER_DATE_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Résiliation programmée le 30 novembre 2026')).toBeInTheDocument()
    expect(screen.queryByText(/18 septembre 2026/)).not.toBeInTheDocument()
  })

  it.each([
    [true, 'Alertes activées · Cadence quotidienne'],
    [false, 'Alertes désactivées · Votre formule permet une cadence quotidienne'],
  ])('sépare le choix utilisateur de la cadence du plan — email_enabled=%s', async (enabled, copy) => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /notification-preferences': {
        body: {
          email_enabled: enabled,
          notification_email: 'claire@acme.test',
          updated_at: '2026-08-18T09:00:00+00:00',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText(copy)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Gérer mes alertes' })).toHaveAttribute(
      'href',
      '/app/notifications',
    )
  })

  it('montre la cadence disponible mais ne prétend rien sur l’activation si les préférences échouent', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /billing/status': {
        body: {
          ...PRO_STATUS,
          entitlements: { ...PRO_STATUS.entitlements, alert_cadence: 'priority' },
        },
      },
      'GET /notification-preferences': {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Cadence disponible : prioritaire')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/alertes (activées|désactivées)/i)
    expect(document.body.textContent).not.toMatch(/temps réel/i)
    expect(screen.getByRole('button', { name: 'Réessayer les alertes' })).toBeInTheDocument()
  })

  it('conserve le plan déjà chargé si la relecture post-feed échoue', async () => {
    let resolveFeed: ((value: { body: ReturnType<typeof feedPage> }) => void) | undefined
    let billingCall = 0
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': () =>
        new Promise((resolve) => {
          resolveFeed = resolve
        }),
      'GET /billing/status': () => {
        billingCall += 1
        return billingCall === 1
          ? { body: PRO_STATUS }
          : { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Pro')).toBeInTheDocument()
    await act(async () => {
      resolveFeed?.({ body: feedPage([]) })
    })
    expect(screen.getByRole('button', { name: 'Réessayer la facturation' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Prochaines occasions à examiner' })).toBeInTheDocument()
  })

  it('reprend localement les alertes sans masquer les ICP déjà chargés', async () => {
    const user = userEvent.setup()
    let preferenceCall = 0
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /notification-preferences': () => {
        preferenceCall += 1
        return preferenceCall === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : {
              body: {
                email_enabled: true,
                notification_email: 'claire@acme.test',
                updated_at: '2026-08-18T09:00:00+00:00',
              },
            }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText(ICP.label)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Réessayer les alertes' }))
    expect(await screen.findByText('Alertes activées · Cadence quotidienne')).toBeInTheDocument()
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(2)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(1)
  })
})
