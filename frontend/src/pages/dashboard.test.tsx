import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_DETAIL,
  LOCKED_ITEM,
  ME,
  PRO_STATUS,
  RECOVER_STATUS,
  SUPPORT_STATUS,
  UNAUTHENTICATED,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  UNLOCKED_PRESENTATION,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

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
  it('compose Compte comme une identité réelle suivie de ses destinations', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/settings' })

    await screen.findByRole('button', { name: 'Réessayer' })
    expect(screen.getAllByText('L’offre n’a pas pu être chargée.')).not.toHaveLength(0)
    expect(
      screen.getByRole('button', {
        name: 'Réessayer le chargement du profil de ciblage',
      }),
    ).toBeVisible()

    const identity = screen.getByRole('link', { name: 'Ouvrir les paramètres du compte' })
    expect(identity).toHaveTextContent('Acme Solutions')
    expect(identity).toHaveTextContent('claire@acme.test')

    const actions = screen.getByRole('navigation', { name: 'Paramètres du compte' })
    expect(within(actions).getByRole('link', { name: 'Abonnement' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
    expect(within(actions).getByRole('link', { name: 'Notifications' })).toHaveAttribute(
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
    const companyButton = await screen.findByRole('button', { name: /Constructions Bertrand SA/ })
    const directory = document.querySelector('.companies-list') as HTMLElement
    const rows = within(directory).getAllByRole('button')
    expect(rows).toHaveLength(1)
    expect(companyButton).toBe(within(directory).getByRole('button', { name: /Constructions Bertrand SA/ }))
    expect(companyButton).toHaveTextContent('1 marché')
    expect(companyButton).toHaveTextContent('France')
    expect(companyButton).toHaveAttribute('aria-pressed', 'true')
    companyButton.focus()
    expect(companyButton).toHaveFocus()
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
    expect(await screen.findByRole('button', { name: /Actuelle SA/ })).toBeInTheDocument()
    await act(async () => {
      resolveOutdatedFeed?.({ body: feedPage([UNLOCKED_ITEM]) })
      await Promise.resolve()
    })
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(screen.getByRole('button', { name: /Actuelle SA/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Constructions Bertrand SA/ })).not.toBeInTheDocument()
  })

  it('conserve les entreprises chargées et annonce une liste partielle si un détail échoue', async () => {
    const user = userEvent.setup()
    let resolveRefresh: ((value: {
      status: number
      body: { detail: { code: string } }
    }) => void) | undefined
    let rejectedAttempts = 0
    const rejectedItem = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_company_rejected',
      company: { ...UNLOCKED_ITEM.company, name: 'Détail indisponible SA' },
    }
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, rejectedItem]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${rejectedItem.signal_id}`]: () => {
        rejectedAttempts += 1
        if (rejectedAttempts === 1) {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        return new Promise((resolve) => { resolveRefresh = resolve })
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/companies' })

    const companyButton = await screen.findByRole('button', { name: /Constructions Bertrand SA/ })
    const partial = screen.getByText('Liste partielle').closest('[role="alert"]') as HTMLElement
    expect(partial).toHaveTextContent(
      'Certaines entreprises n’ont pas pu être chargées.',
    )
    const retry = within(partial).getByRole('button', { name: 'Réessayer' })
    await user.click(retry)

    await waitFor(() => expect(callsTo(`/signals/${rejectedItem.signal_id}`, 'GET')).toHaveLength(2))
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(companyButton).toBeInTheDocument()
    expect(partial).toBeInTheDocument()
    expect(retry).toBeInTheDocument()
    expect(retry).toBeDisabled()
    expect(retry).toHaveTextContent('Chargement')
    expect(retry).toHaveFocus()

    await act(async () => {
      resolveRefresh?.({
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      })
      await Promise.resolve()
    })

    const refreshError = screen.getByText('Liste partielle').closest('[role="alert"]') as HTMLElement
    expect(within(refreshError).getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
    expect(companyButton).toBeInTheDocument()
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
      await screen.findByRole('heading', { name: 'Définir ce que Kivou doit surveiller' }),
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

const EXACT_OVERVIEW_ROUTES = {
  'GET /signals': { body: feedPage([]) },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

const OVERVIEW_SECOND_ITEM = {
  ...UNLOCKED_ITEM,
  signal_id: 'sig_overview_second',
  company: { ...UNLOCKED_ITEM.company, name: 'Deuxième SA' },
  presentation: {
    ...UNLOCKED_PRESENTATION,
    artifact_id: 'card_presentation_sig_overview_second_v1',
    content: {
      ...UNLOCKED_PRESENTATION.content,
      headline: 'Deuxième SA réalisera un marché de travaux documenté',
      award_summary:
        'Deuxième SA est attributaire d’un second marché public dont les faits essentiels sont documentés.',
    },
  },
  contract: {
    ...UNLOCKED_ITEM.contract,
    title: 'Deuxième marché public',
    dates: { ...UNLOCKED_ITEM.contract.dates, award: '2026-08-03' },
  },
}

function OverviewAccountSwitcher() {
  const { adopt } = useSession()
  return (
    <button
      type="button"
      onClick={() => adopt({ ...ME, account_id: 'acc_2', account_display_name: 'Compte B' })}
    >
      Basculer sur le compte B
    </button>
  )
}

describe('vue d’ensemble exacte connectée', () => {
  it('rend uniquement la composition de référence depuis les API réelles', async () => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, OVERVIEW_SECOND_ITEM, LOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 2, name: '3 attributions documentées' })).toBeVisible()
    expect(document.querySelector('.overview-focus-grid .priority-card')).not.toBeNull()
    expect(document.querySelector('.target-profile-snapshot')).not.toBeNull()
    expect(document.querySelector('.overview-awards-card .recent-list')).not.toBeNull()
    expect(document.querySelector('.workspace-grid')).toBeNull()
    expect(document.body).not.toHaveTextContent('Résumé du compte')
    expect(document.body).not.toHaveTextContent('Alertes activées')
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)

    const priority = document.querySelector('.priority-card') as HTMLElement
    expect(within(priority).getByText(UNLOCKED_PRESENTATION.content.headline)).toBeVisible()
    expect(within(priority).getByText(UNLOCKED_PRESENTATION.content.award_summary)).toBeVisible()
    expect(within(priority).queryByText(UNLOCKED_ITEM.contract.title!)).toBeNull()
    expect(within(priority).getByText('Attribution publiée sur BOAMP')).toBeVisible()
    for (const insight of [
      UNLOCKED_PRESENTATION.content.commercial_importance,
      UNLOCKED_PRESENTATION.content.fit_reason,
      UNLOCKED_PRESENTATION.content.timing,
    ]) {
      expect(within(priority).getByText(insight!)).toBeVisible()
    }
    expect(within(priority).getByText('Début prévu')).toBeVisible()
    expect(within(priority).getByText('Non publié')).toBeVisible()

    const targeting = document.querySelector('.target-profile-snapshot') as HTMLElement
    expect(within(targeting).getByText(ICP.label)).toBeVisible()
    expect(within(targeting).getByText('Matériaux et composants')).toBeVisible()
    expect(within(targeting).getByText('France')).toBeVisible()
    expect(within(targeting).getByRole('link', { name: 'Voir le profil' })).toHaveAttribute(
      'href',
      '/app/icps',
    )
  })

  it('rend les compteurs 0, 1, pluriel et pagination sans inventer un total', async () => {
    mockApi(EXACT_OVERVIEW_ROUTES)
    const empty = renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByRole('heading', { level: 2, name: '0 attributions documentées' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 3, name: '0 marchés à parcourir' })).toBeVisible()
    empty.unmount()

    mockApi({ ...EXACT_OVERVIEW_ROUTES, 'GET /signals': { body: feedPage([UNLOCKED_ITEM]) } })
    const one = renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByRole('heading', { level: 2, name: '1 attribution documentée' })).toBeVisible()
    one.unmount()

    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': {
        body: feedPage([UNLOCKED_ITEM, OVERVIEW_SECOND_ITEM, LOCKED_ITEM], {
          page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
        }),
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByRole('heading', { level: 2, name: '3+ attributions documentées' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 3, name: '2 marchés à parcourir' })).toBeVisible()
  })

  it('choisit le premier signal déverrouillé et garde les autres dans l’ordre serveur', async () => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': {
        body: feedPage([LOCKED_ITEM, OVERVIEW_SECOND_ITEM, UNLOCKED_ITEM]),
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const priority = document.querySelector('.priority-card') as HTMLElement
    expect(
      await within(priority).findByText(OVERVIEW_SECOND_ITEM.presentation.content.headline),
    ).toBeVisible()
    expect(within(priority).getByRole('link', { name: 'Examiner le signal' })).toHaveAttribute(
      'href',
      `/app/signals/${OVERVIEW_SECOND_ITEM.signal_id}`,
    )
    const rows = Array.from(document.querySelectorAll('.recent-list .recent-signal'))
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent(LOCKED_ITEM.headline)
    expect(rows[1]).toHaveTextContent(UNLOCKED_ITEM.company.name!)
    expect(screen.getByRole('link', { name: /Voir tous les signaux/ })).toHaveAttribute(
      'href',
      '/app/signals',
    )
  })

  it('limite la vue d’ensemble à six cartes tout en gardant le lien vers le feed complet', async () => {
    const items = Array.from({ length: 9 }, (_, index) => ({
      ...UNLOCKED_ITEM,
      signal_id: `sig_overview_${index}`,
      company: { ...UNLOCKED_ITEM.company, name: `Entreprise ${index}` },
      presentation: {
        ...UNLOCKED_PRESENTATION,
        artifact_id: `card_presentation_sig_overview_${index}_v1`,
        content: {
          ...UNLOCKED_PRESENTATION.content,
          headline: `Attribution résumée ${index}`,
          award_summary: `Résumé commercial publié ${index}.`,
        },
      },
    }))
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage(items) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Attribution résumée 0')).toBeVisible()
    expect(document.querySelectorAll('.recent-list .recent-signal')).toHaveLength(5)
    expect(screen.queryByText('Résumé commercial publié 6.')).toBeNull()
    expect(screen.getByRole('link', { name: /Voir tous les signaux/ })).toHaveAttribute(
      'href',
      '/app/signals',
    )
  })

  it('n’invente aucun résumé lorsque la présentation publiée est absente', async () => {
    const withoutPresentation = {
      ...UNLOCKED_ITEM,
      presentation: null,
      contract: {
        ...UNLOCKED_ITEM.contract,
        title: 'TITRE BRUT INTERDIT DANS LA VUE D’ENSEMBLE',
      },
    }
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([withoutPresentation]) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Résumé commercial indisponible. Ouvrez le signal pour consulter les faits publiés.')).toBeVisible()
    expect(screen.getByText('Aucune analyse publiée : seuls les faits du marché sont affichés.')).toBeVisible()
    expect(document.body).not.toHaveTextContent('TITRE BRUT INTERDIT')
  })

  it('sélectionne dans le feed le premier signal ouvert reçu sans demander le teaser verrouillé', async () => {
    const secondDetail = {
      ...UNLOCKED_DETAIL,
      ...OVERVIEW_SECOND_ITEM,
      company_key: 'cmp_overview_second',
    }
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': {
        body: feedPage([LOCKED_ITEM, OVERVIEW_SECOND_ITEM, UNLOCKED_ITEM]),
      },
      [`GET /signals/${OVERVIEW_SECOND_ITEM.signal_id}`]: { body: secondDetail },
      [`GET /signals/${OVERVIEW_SECOND_ITEM.signal_id}/note`]: {
        body: { signal_id: OVERVIEW_SECOND_ITEM.signal_id, note: null, updated_at: null },
      },
    })

    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: { pathname: '/app/signals', state: { activationCompleted: true } },
    })

    expect(
      await screen.findByRole('heading', { name: OVERVIEW_SECOND_ITEM.contract.title! }),
    ).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('ne révèle ni ne demande les champs protégés d’un teaser verrouillé malformé', async () => {
    const leakingLocked = {
      ...LOCKED_ITEM,
      company: { name: 'ENTREPRISE SECRÈTE', country: 'FR' },
      company_key: 'cmp_secret',
      contract: { title: 'MARCHÉ SECRET', reference: 'REF-SECRET' },
      analysis: { fit: { label: 'SCORE SECRET' } },
      source: { url: 'https://secret.invalid' },
    }
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([leakingLocked]) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText(LOCKED_ITEM.headline)).toBeVisible()
    const page = document.body.textContent ?? ''
    for (const secret of [
      'ENTREPRISE SECRÈTE',
      'cmp_secret',
      'MARCHÉ SECRET',
      'REF-SECRET',
      'SCORE SECRET',
      'secret.invalid',
    ]) {
      expect(page).not.toContain(secret)
    }
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
  })
})

describe('ressources indépendantes de la vue d’ensemble', () => {
  it('démarre feed, profils et billing en parallèle sans notifications', async () => {
    const pending = () => new Promise<never>(() => undefined)
    mockApi({
      'GET /signals': pending,
      'GET /target-icps': pending,
      'GET /billing/status': pending,
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    await waitFor(() => {
      expect(callsTo('/signals', 'GET')).toHaveLength(1)
      expect(callsTo('/target-icps', 'GET')).toHaveLength(2)
      expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
    })
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(0)
    expect(document.querySelector('.priority-card')).toHaveAttribute('aria-busy', 'true')
  })

  it('reprend uniquement le feed et conserve le profil déjà chargé', async () => {
    const user = userEvent.setup()
    let feedCalls = 0
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': () => {
        feedCalls += 1
        return feedCalls === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: feedPage([UNLOCKED_ITEM]) }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const priority = document.querySelector('.priority-card') as HTMLElement
    await user.click(await within(priority).findByRole('button', { name: 'Réessayer' }))
    expect(await within(priority).findByText(UNLOCKED_PRESENTATION.content.headline)).toBeVisible()
    expect(screen.getByText(ICP.label)).toBeVisible()
    expect(callsTo('/signals', 'GET')).toHaveLength(2)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(2)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
  })

  it('reprend uniquement le profil sans masquer le signal réel', async () => {
    const user = userEvent.setup()
    let profileCalls = 0
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /target-icps': () => {
        profileCalls += 1
        return profileCalls <= 2
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: [ICP] }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText(UNLOCKED_PRESENTATION.content.headline)).toBeVisible()
    const targeting = document.querySelector('.targeting-card') as HTMLElement
    await user.click(await within(targeting).findByRole('button', { name: 'Réessayer' }))
    expect(await within(targeting).findByText(ICP.label)).toBeVisible()
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(3)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
  })

  it('reprend uniquement billing et rend ensuite l’action autoritaire', async () => {
    const user = userEvent.setup()
    let billingCalls = 0
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /billing/status': () => {
        billingCalls += 1
        return billingCalls <= 2
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: RECOVER_STATUS }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const priority = document.querySelector('.priority-card') as HTMLElement
    await user.click(await within(priority).findByRole('button', { name: 'Réessayer' }))
    expect(
      await within(priority).findByRole('link', { name: /Corriger le paiement/ }),
    ).toHaveAttribute('href', '/app/billing')
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo('/target-icps', 'GET')).toHaveLength(2)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(3)
  })

  it('ignore les reprises croisées obsolètes et garde la dernière autorité feed', async () => {
    let feedCalls = 0
    let resolveStale!: (value: { body: ReturnType<typeof feedPage> }) => void
    const currentItem = {
      ...OVERVIEW_SECOND_ITEM,
      signal_id: 'sig_current_overview',
      presentation: {
        ...UNLOCKED_PRESENTATION,
        artifact_id: 'card_presentation_sig_current_overview_v1',
        content: {
          ...UNLOCKED_PRESENTATION.content,
          headline: 'Lecture la plus récente',
          award_summary: 'Résumé publié par la reprise la plus récente.',
        },
      },
      contract: { ...OVERVIEW_SECOND_ITEM.contract, title: 'Lecture la plus récente' },
    }
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': () => {
        feedCalls += 1
        if (feedCalls === 1) {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        if (feedCalls === 2) {
          return new Promise((resolve) => { resolveStale = resolve })
        }
        return { body: feedPage([currentItem]) }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    const retry = await screen.findByRole('button', { name: 'Réessayer' })
    act(() => {
      retry.click()
      retry.click()
    })
    expect(await screen.findByText('Lecture la plus récente')).toBeVisible()
    await act(async () => {
      resolveStale({ body: feedPage([UNLOCKED_ITEM]) })
    })
    expect(screen.getByText('Lecture la plus récente')).toBeVisible()
    expect(screen.queryByText(UNLOCKED_PRESENTATION.content.headline)).toBeNull()
  })

  it('écarte la réponse feed privée du compte précédent après changement de compte', async () => {
    const user = userEvent.setup()
    let feedCalls = 0
    let resolveAccountA!: (value: { body: ReturnType<typeof feedPage> }) => void
    const accountAItem = {
      ...UNLOCKED_ITEM,
      presentation: {
        ...UNLOCKED_PRESENTATION,
        artifact_id: 'card_presentation_account_a_v1',
        content: {
          ...UNLOCKED_PRESENTATION.content,
          headline: 'Attribution privée du compte A',
        },
      },
      contract: { ...UNLOCKED_ITEM.contract, title: 'Marché privé du compte A' },
    }
    const accountBItem = {
      ...OVERVIEW_SECOND_ITEM,
      presentation: {
        ...UNLOCKED_PRESENTATION,
        artifact_id: 'card_presentation_account_b_v1',
        content: {
          ...UNLOCKED_PRESENTATION.content,
          headline: 'Attribution du compte B',
        },
      },
      contract: { ...OVERVIEW_SECOND_ITEM.contract, title: 'Marché du compte B' },
    }
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': () => {
        feedCalls += 1
        return feedCalls === 1
          ? new Promise((resolve) => { resolveAccountA = resolve })
          : { body: feedPage([accountBItem]) }
      },
    })
    renderApp(
      <>
        <AppRoutes />
        <OverviewAccountSwitcher />
      </>,
      { session: AUTHENTICATED, route: '/app/dashboard' },
    )

    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(1))
    await user.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    expect(await screen.findByText('Attribution du compte B')).toBeVisible()
    await act(async () => {
      resolveAccountA({ body: feedPage([accountAItem]) })
    })
    expect(screen.getByText('Attribution du compte B')).toBeVisible()
    expect(screen.queryByText('Attribution privée du compte A')).toBeNull()
  })

  it('ne transforme ni chargement ni erreur feed en faux zéro et ne duplique pas l’alerte', async () => {
    const pending = () => new Promise<never>(() => undefined)
    mockApi({ ...EXACT_OVERVIEW_ROUTES, 'GET /signals': pending })
    const loading = renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findAllByText('Chargement…')).not.toHaveLength(0)
    expect(screen.queryByText(/0 attribution documentée/)).toBeNull()
    expect(screen.queryByText(/0 marché à parcourir/)).toBeNull()
    loading.unmount()

    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { status: 503, body: { detail: { code: 'temporarily_unavailable' } } },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findAllByRole('alert')).toHaveLength(1)
    expect(screen.queryByText(/0 attribution documentée/)).toBeNull()
    expect(screen.queryByText(/0 marché à parcourir/)).toBeNull()
  })
})

describe('autorités, navigation et garde-fous Overview', () => {
  it.each([
    ['choose_plan', DISCOVERY_STATUS, 'Choisir une formule'],
    ['manage_subscription', PRO_STATUS, 'Gérer mon abonnement'],
    ['recover_payment', RECOVER_STATUS, 'Corriger le paiement'],
    ['contact_support', SUPPORT_STATUS, 'Contacter le support'],
  ] as const)('respecte billing_action %s quand aucun signal n’est accessible', async (_action, status, label) => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /billing/status': { body: status },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Aucun signal accessible pour le moment')).toBeVisible()
    expect(screen.getByRole('link', { name: new RegExp(label) })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it('rend le snapshot ICP réel et l’état vide sans profil actif', async () => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
    })
    const real = renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByText(ICP.label)).toBeVisible()
    expect(screen.getByText('Matériaux et composants')).toBeVisible()
    real.unmount()

    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /target-icps': { body: [{ ...ICP, status: 'incomplete' }] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByText('Aucun profil actif publié.')).toBeVisible()
  })

  it('suit le parcours de session expirée sur un 401 feed', async () => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { status: 401, body: { detail: { code: 'not_authenticated' } } },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Votre session a expiré. Reconnectez-vous.')).toBeVisible()
    expect(screen.getByRole('heading', { level: 1, name: 'Retrouver vos signaux' })).toBeVisible()
  })

  it('préserve l’historique Dashboard vers Signaux et retour/avance', async () => {
    const user = userEvent.setup()
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
    })
    renderApp(
      <>
        <AppRoutes />
        <HistoryControls />
      </>,
      { session: AUTHENTICATED, route: '/app/dashboard' },
    )

    await user.click(await screen.findByRole('link', { name: 'Examiner le signal' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: UNLOCKED_ITEM.contract.title! }),
    ).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Historique suivant' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: UNLOCKED_ITEM.contract.title! }),
    ).toBeVisible()
  })

  it('garde la parité anglaise de l’Overview et de ses routes', async () => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/dashboard',
      locale: 'en',
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 2, name: '1 documented award' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Review signal' })).toHaveAttribute(
      'href',
      `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    )
    expect(screen.getByRole('link', { name: /View all signals/ })).toHaveAttribute(
      'href',
      '/app/signals',
    )
  })

  it('ne persiste aucune donnée feed ou clé protégée dans le navigateur', async () => {
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem')
    localStorage.clear()
    sessionStorage.clear()
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText(UNLOCKED_PRESENTATION.content.headline)).toBeVisible()
    expect(storageWrite).not.toHaveBeenCalled()
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
  })

  it('rend un main, un h1 et des actions toutes nommées', async () => {
    mockApi({
      ...EXACT_OVERVIEW_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    })
    const { container } = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/app/dashboard',
    })

    await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })
    expect(container.querySelectorAll('main')).toHaveLength(1)
    expect(container.querySelectorAll('h1')).toHaveLength(1)
    expect(document.querySelector('.overview-main')).not.toBeNull()
    for (const action of container.querySelectorAll('a[href], button')) {
      expect(action).toHaveAccessibleName()
    }
  })
})
