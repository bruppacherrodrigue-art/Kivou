import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  COMPANY_PROFILE,
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
  'GET /signals': { body: feedPage([]) },
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

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <div>
      <button type="button" onClick={() => navigate(-1)}>
        Historique précédent
      </button>
      <button type="button" onClick={() => navigate(1)}>
        Historique suivant
      </button>
    </div>
  )
}

describe('accueil connecté', () => {
  it('compose Compte comme une identité réelle suivie de ses destinations', () => {
    mockApi({})
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/settings' })

    const identity = screen.getByRole('region', { name: 'Acme Solutions' })
    expect(identity).toHaveTextContent('claire@acme.test')

    const actions = screen.getByRole('navigation', { name: 'Actions du compte' })
    expect(within(actions).getByRole('link', { name: 'Voir la facturation' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
    expect(within(actions).getByRole('link', { name: 'Gérer les notifications' })).toHaveAttribute(
      'href',
      '/app/notifications',
    )
  })

  it('fait de /app/dashboard la destination de /app pour un compte prêt', async () => {
    mockApi(DASHBOARD_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app' })

    expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeInTheDocument()
  })

  it('rend le dashboard accessible dans la navigation authentifiée en FR et EN', async () => {
    mockApi(DASHBOARD_ROUTES)
    const { unmount } = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/app/dashboard',
      locale: 'fr',
    })

    expect(await screen.findByRole('link', { name: 'Vue d’ensemble' })).toHaveAttribute(
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

    expect(await screen.findByRole('link', { name: 'Overview' })).toHaveAttribute(
      'href',
      '/app/dashboard',
    )
  })

  it('rend une seule ligne entreprise depuis le détail déverrouillé sans demander le détail verrouillé', async () => {
    const protectedIdentity = 'ENTREPRISE PROTÉGÉE'
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${LOCKED_ITEM.signal_id}`]: {
        body: {
          ...LOCKED_DETAIL,
          company: { name: protectedIdentity, country: 'CH', identifier: null },
          company_key: 'cmp_protected',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/companies' })

    expect(await screen.findByRole('heading', { level: 1, name: 'Entreprises' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Entreprises' })).toHaveAttribute('href', '/app/companies')
    const directory = await screen.findByRole('list', { name: 'Entreprises' })
    const rows = within(directory).getAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(within(rows[0]).getAllByRole('link')).toHaveLength(1)
    expect(within(rows[0]).getByText('Signaux liés · 1')).toBeInTheDocument()
    expect(within(rows[0]).getByText('FR')).toBeInTheDocument()
    const companyLink = within(rows[0]).getByRole('link', { name: /Constructions Bertrand SA/ })
    expect(companyLink).toHaveAttribute(
      'href',
      `/app/companies/${UNLOCKED_DETAIL.company_key}`,
    )
    companyLink.focus()
    expect(companyLink).toHaveFocus()
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain(protectedIdentity)
    expect(document.body.textContent).not.toContain('cmp_protected')
    expect(screen.queryByText('Ouvrir la fiche')).not.toBeInTheDocument()
  })

  it('ignore une réponse ancienne lorsque deux reprises locales Entreprises se chevauchent', async () => {
    let feedCall = 0
    let resolveOutdatedFeed: ((value: { body: ReturnType<typeof feedPage> }) => void) | undefined
    const secondItem = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_current_company',
      company: { ...UNLOCKED_ITEM.company, name: 'Actuelle SA' },
    }
    const secondDetail = {
      ...UNLOCKED_DETAIL,
      signal_id: secondItem.signal_id,
      company: secondItem.company,
      company_key: 'cmp_current_company',
    }
    mockApi({
      'GET /signals': () => {
        feedCall += 1
        if (feedCall === 1) {
          return {
            status: 503,
            body: { detail: { code: 'temporarily_unavailable' } },
          }
        }
        if (feedCall === 2) {
          return new Promise((resolve) => {
            resolveOutdatedFeed = resolve
          })
        }
        return { body: feedPage([secondItem]) }
      },
      [`GET /signals/${secondItem.signal_id}`]: { body: secondDetail },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/companies' })

    const retry = await screen.findByRole('button', { name: 'Réessayer' })
    act(() => {
      retry.click()
      retry.click()
    })
    await waitFor(() => expect(feedCall).toBe(3))
    expect(await screen.findByRole('link', { name: /Actuelle SA/ })).toBeInTheDocument()
    await act(async () => {
      resolveOutdatedFeed?.({ body: feedPage([UNLOCKED_ITEM]) })
      await Promise.resolve()
    })
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(screen.getByRole('link', { name: /Actuelle SA/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Constructions Bertrand SA/ })).not.toBeInTheDocument()
  })

  it('conserve les entreprises chargées et annonce une liste partielle si un détail échoue', async () => {
    const user = userEvent.setup()
    let feedCall = 0
    let resolveRefresh: ((value: {
      status: number
      body: { detail: { code: string } }
    }) => void) | undefined
    const rejectedItem = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_company_rejected',
      company: { ...UNLOCKED_ITEM.company, name: 'Détail indisponible SA' },
    }
    mockApi({
      'GET /signals': () => {
        feedCall += 1
        if (feedCall === 1) return { body: feedPage([UNLOCKED_ITEM, rejectedItem]) }
        return new Promise((resolve) => {
          resolveRefresh = resolve
        })
      },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${rejectedItem.signal_id}`]: {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/companies' })

    const companyLink = await screen.findByRole('link', { name: /Constructions Bertrand SA/ })
    const partial = screen.getByRole('region', { name: 'Liste partielle' })
    expect(within(partial).getByRole('alert')).toHaveTextContent(
      'Certaines entreprises n’ont pas pu être chargées.',
    )
    const retry = within(partial).getByRole('button', { name: 'Réessayer' })
    await user.click(retry)

    await waitFor(() => expect(feedCall).toBe(2))
    expect(companyLink).toBeInTheDocument()
    expect(partial).toBeInTheDocument()
    expect(retry).toBeInTheDocument()
    expect(retry).toHaveAttribute('aria-busy', 'true')
    expect(retry).toHaveFocus()

    await act(async () => {
      resolveRefresh?.({
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      })
      await Promise.resolve()
    })

    const refreshError = await screen.findByRole('region', {
      name: 'Les entreprises n’ont pas pu être chargées.',
    })
    expect(within(refreshError).getByRole('alert')).toBeInTheDocument()
    expect(within(refreshError).getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
    expect(companyLink).toBeInTheDocument()
    expect(partial).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('temporarily_unavailable')
  })

  it('rend une erreur réessayable plutôt qu’un faux vide si tous les détails échouent', async () => {
    const secondItem = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_company_rejected_too',
      company: { ...UNLOCKED_ITEM.company, name: 'Autre détail indisponible SA' },
    }
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, secondItem]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
      [`GET /signals/${secondItem.signal_id}`]: {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/companies' })

    const error = await screen.findByRole('alert')
    expect(error).toHaveTextContent('Les entreprises n’ont pas pu être chargées.')
    expect(within(error).getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
    expect(screen.queryByText('Aucune entreprise accessible pour le moment.')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('temporarily_unavailable')
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
    expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeInTheDocument()

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
    expect(await screen.findByRole('link', { name: 'Profil de ciblage' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})

describe('chargements indépendants', () => {
  it('résume honnêtement une lecture vide depuis la fixture dashboard commune', async () => {
    mockApi(DASHBOARD_ROUTES)

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const summary = await screen.findByRole('list', { name: 'Résumé du compte' })
    expect(within(summary).getByText('0 signaux dans cette lecture')).toBeInTheDocument()
  })

  it('accorde au pluriel une lecture de plusieurs signaux', async () => {
    const secondLocked = {
      ...LOCKED_ITEM,
      signal_id: 'sig_locked_2',
      headline: 'Deuxième signal verrouillé',
    }
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([LOCKED_ITEM, secondLocked]) },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const summary = await screen.findByRole('list', { name: 'Résumé du compte' })
    expect(within(summary).getByText('2 signaux dans cette lecture')).toBeInTheDocument()
  })

  it('résume uniquement les ressources réelles de cette lecture', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const summary = await screen.findByRole('list', { name: 'Résumé du compte' })
    expect(within(summary).getByText('1 signal dans cette lecture')).toBeInTheDocument()
    expect(within(summary).getByText('1 profil actif')).toBeInTheDocument()
    expect(within(summary).getByText('Pro')).toBeInTheDocument()
    expect(within(summary).getByText('Alertes activées · Cadence quotidienne')).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/32 signaux|82\s*%|12[\s\u00a0]*540/i)
  })

  it('isole une panne billing dans sa métrique et son retry', async () => {
    const user = userEvent.setup()
    let billingCall = 0
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
      'GET /billing/status': () => {
        billingCall += 1
        return billingCall < 3
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: PRO_STATUS }
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const summary = await screen.findByRole('list', { name: 'Résumé du compte' })
    expect(within(summary).getByText('1 signal dans cette lecture')).toBeInTheDocument()
    expect(within(summary).getByText('1 profil actif')).toBeInTheDocument()
    expect(within(summary).getByText('Alertes activées')).toBeInTheDocument()
    const accessMetric = within(summary).getByText('Accès actuel').closest('li')
    expect(accessMetric).not.toBeNull()
    expect(within(accessMetric!).getByRole('alert')).toHaveTextContent(
      'La facturation n’a pas pu être chargée.',
    )
    expect(within(summary).getAllByRole('alert')).toHaveLength(1)
    await user.click(within(summary).getByRole('button', { name: 'Réessayer la facturation' }))

    expect(await within(summary).findByText('Pro')).toBeInTheDocument()
    expect(callsTo('/billing/status', 'GET')).toHaveLength(3)
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(1)
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(1)
  })

  it('isole une panne notifications dans sa métrique et son retry', async () => {
    const user = userEvent.setup()
    let preferenceCall = 0
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
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

    const summary = await screen.findByRole('list', { name: 'Résumé du compte' })
    expect(within(summary).getByText('1 signal dans cette lecture')).toBeInTheDocument()
    expect(within(summary).getByText('1 profil actif')).toBeInTheDocument()
    expect(within(summary).getByText('Pro')).toBeInTheDocument()
    await user.click(within(summary).getByRole('button', { name: 'Réessayer les alertes' }))

    expect(
      await within(summary).findByText('Alertes activées · Cadence quotidienne'),
    ).toBeInTheDocument()
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(2)
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(1)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
  })

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

  it('annonce explicitement les loaders du feed et du contexte', async () => {
    const pending = () => new Promise<never>(() => undefined)
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': pending,
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const summary = await screen.findByRole('list', { name: 'Résumé du compte' })
    expect(
      within(summary).getByRole('status', { name: 'Signaux — Chargement…' }),
    ).toBeInTheDocument()
    const opportunities = screen.getByRole('region', { name: 'Signaux à examiner' })
    expect(
      within(opportunities).getByRole('status', {
        name: 'Signaux à examiner — Chargement…',
      }),
    ).toBeInTheDocument()
    const company = screen.getByRole('complementary', { name: 'Fiche entreprise' })
    expect(
      within(company).getByRole('status', { name: 'Fiche entreprise — Chargement…' }),
    ).toBeInTheDocument()
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
    expect(screen.getByRole('complementary', { name: 'Fiche entreprise' })).toHaveTextContent(
      'Aucun signal déverrouillé dans cette lecture',
    )
    expect(screen.queryByRole('link', { name: 'Consulter la fiche entreprise' })).not.toBeInTheDocument()
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
    expect(
      within(screen.getByRole('complementary', { name: 'Fiche entreprise' })).getByRole('alert'),
    ).toHaveTextContent('La fiche entreprise n’a pas pu être vérifiée.')
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
      name: 'Signaux à examiner',
    })).closest('section')
    expect(opportunities).not.toBeNull()

    const rows = within(opportunities!).getAllByRole('article')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('Deuxième dans la réponse')).toBeInTheDocument()
    expect(within(rows[1]).getByText(LOCKED_ITEM.headline)).toBeInTheDocument()
    expect(within(rows[2]).getByText('Premier selon le score serveur')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('link')).toHaveAttribute(
      'href',
      '/app/signals/sig_server_second',
    )
    expect(within(rows[1]).getByRole('button')).toHaveAccessibleName(
      new RegExp(LOCKED_ITEM.headline),
    )
    expect(within(rows[2]).getByRole('link')).toHaveAttribute(
      'href',
      '/app/signals/sig_server_first',
    )
    expect(within(opportunities!).queryByText('Hors extrait')).not.toBeInTheDocument()
    expect(within(opportunities!).getByRole('link', { name: 'Voir tous les signaux' })).toHaveAttribute(
      'href',
      '/app/signals',
    )
  })

  it('ne révèle aucun champ protégé même si un objet verrouillé malformé les contient', async () => {
    const user = userEvent.setup()
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
    await user.click(
      screen.getByRole('button', {
        name: new RegExp(`Examiner l’aperçu du signal verrouillé: ${LOCKED_ITEM.headline}`),
      }),
    )
    expect(await screen.findByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
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
    expect(
      within(screen.getByRole('list', { name: 'Résumé du compte' })).getByText('Découverte'),
    ).toBeInTheDocument()
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

  it.each([
    ['weekly', true, 'Alertes activées · Cadence hebdomadaire'],
    ['none', false, 'Alertes désactivées · Votre formule ne prévoit aucune cadence'],
  ] as const)('rend aussi exactement la cadence %s', async (cadence, enabled, copy) => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /billing/status': {
        body: {
          ...PRO_STATUS,
          entitlements: { ...PRO_STATUS.entitlements, alert_cadence: cadence },
        },
      },
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

    expect(await screen.findByRole('button', { name: 'Réessayer les alertes' })).toBeInTheDocument()
    expect(screen.queryByText('Cadence disponible : prioritaire')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/alertes (activées|désactivées)/i)
    expect(document.body.textContent).not.toMatch(/temps réel/i)
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
    expect(screen.getByRole('heading', { name: 'Signaux à examiner' })).toBeInTheDocument()
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

describe('navigation et garde-fous du dashboard', () => {
  it('suit le parcours existant de session expirée après un 401 local', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': {
        status: 401,
        body: { detail: { code: 'not_authenticated' } },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(
      await screen.findByText('Votre session a expiré. Connectez-vous à nouveau.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Se connecter' })).toBeInTheDocument()
  })

  it('rend les blocs et actions structurants avec une parité anglaise', async () => {
    mockApi({ ...DASHBOARD_ROUTES, 'GET /billing/status': { body: PRO_STATUS } })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/dashboard',
      locale: 'en',
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Signals to review' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Active targeting profiles' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Plan and access' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alerts' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage my targeting' })).toHaveAttribute(
      'href',
      '/app/icps',
    )
    expect(screen.getByRole('link', { name: 'Manage my subscription' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
    expect(screen.getByRole('link', { name: 'Manage my alerts' })).toHaveAttribute(
      'href',
      '/app/notifications',
    )
  })

  it('préserve les blocs chargés quand la facturation échoue', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
      'GET /billing/status': {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findAllByText(UNLOCKED_ITEM.company.name!)).not.toHaveLength(0)
    expect(screen.getByText(ICP.label)).toBeInTheDocument()
    expect(screen.getByText('Alertes activées')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer la facturation' })).toBeInTheDocument()
  })

  it('restaure dashboard, détail et fiche entreprise avec précédent et suivant', async () => {
    const user = userEvent.setup()
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
      [`GET /companies/${UNLOCKED_DETAIL.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(
      <>
        <AppRoutes />
        <HistoryControls />
      </>,
      { session: AUTHENTICATED, route: '/app/dashboard' },
    )

    await screen.findByRole('link', { name: 'Consulter la fiche entreprise' })
    await user.click(
      screen.getByRole('link', {
        name: new RegExp(`${UNLOCKED_ITEM.company.name} — ${UNLOCKED_ITEM.contract.title}`),
      }),
    )
    expect(
      await screen.findByRole('heading', { level: 1, name: UNLOCKED_DETAIL.contract.title! }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' }),
    ).toBeInTheDocument()
    await user.click(await screen.findByRole('link', { name: 'Consulter la fiche entreprise' }))
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: COMPANY_PROFILE.official_identity.name,
      }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Historique suivant' }))
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: COMPANY_PROFILE.official_identity.name,
      }),
    ).toBeInTheDocument()
  })

  it('ne stocke aucune donnée entreprise ni company_key dans le navigateur', async () => {
    localStorage.clear()
    sessionStorage.clear()
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    await screen.findByRole('link', { name: 'Consulter la fiche entreprise' })

    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
    expect(JSON.stringify(localStorage)).not.toContain(UNLOCKED_ITEM.company.name)
    expect(JSON.stringify(sessionStorage)).not.toContain(UNLOCKED_DETAIL.company_key)
  })

  it('rend un seul main, un seul h1 et des actions nommées', async () => {
    mockApi({
      ...DASHBOARD_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
    })

    const { container } = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/app/dashboard',
    })
    await screen.findByRole('link', { name: 'Consulter la fiche entreprise' })

    expect(container.querySelectorAll('main')).toHaveLength(1)
    expect(container.querySelectorAll('h1')).toHaveLength(1)
    expect(
      screen.getByRole('list', { name: 'Signaux à examiner' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Ciblages actifs' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Ciblages actifs' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Formule et accès' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Alertes' })).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Fiche entreprise' })).toBeInTheDocument()
    for (const action of container.querySelectorAll('a[href], button')) {
      expect(action).toHaveAccessibleName()
    }
  })
})
