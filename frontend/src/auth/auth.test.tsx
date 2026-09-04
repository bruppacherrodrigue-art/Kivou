import { describe, expect, it, afterEach, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  EXPIRED,
  ME,
  UNAUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

/* SPEC-015 §48 — les sept vérifications d'authentification. */

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function ResetSearchChanger() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate('/reset-password?token=jeton-deux')}>
      Changer le jeton URL
    </button>
  )
}

const APP_ROUTES = {
  'GET /signals': { body: feedPage([]) },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /billing/plans': { body: CATALOGUE },
  'GET /target-icps': { body: [ICP] },
}

describe('protection des routes', () => {
  it('renvoie vers la connexion une route applicative atteinte sans session', async () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', { name: 'Retrouver vos signaux' }),
    ).toBeInTheDocument()
    // Le feed ne doit pas avoir été demandé : la redirection précède l'appel.
    expect(callsTo('/signals', 'GET')).toHaveLength(0)
  })

  it('laisse un utilisateur authentifié atteindre l’application', async () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(await screen.findByRole('heading', { name: 'Signaux' })).toBeInTheDocument()
  })

  it('ramène à la connexion, en le disant, quand la session a expiré', async () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, { session: EXPIRED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', { name: 'Retrouver vos signaux' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/session a expiré/i)).toBeInTheDocument()
  })

  it('ne crée pas de boucle : l’état de chargement ne redirige pas', () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'loading', me: null },
      route: '/app/signals',
    })

    expect(
      screen.queryByRole('heading', { name: 'Retrouver vos signaux' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Chargement…')).toBeInTheDocument()
  })
})

describe('inscription', () => {
  it('conserve les contraintes HTML natives sur le formulaire de référence', () => {
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup' })

    const form = screen.getByRole('button', { name: 'Continuer vers le profil cible' }).closest('form')!
    expect(form).not.toHaveAttribute('novalidate')
    expect(screen.getByLabelText('Entreprise')).toBeRequired()
    expect(screen.getByLabelText(/Adresse e-mail/)).toHaveAttribute('type', 'email')
    expect(screen.getByLabelText(/^Mot de passe$/)).toHaveAttribute('minlength', '12')
  })

  it.each([
    ['une entreprise composée uniquement d’espaces', 'signup', 'company'],
    ['une adresse vide', 'signup', 'empty-email'],
    ['une adresse invalide', 'signup', 'invalid-email'],
    ['un mot de passe vide', 'login', 'empty-password'],
  ] as const)('refuse %s sans appeler l’API', async (_label, mode, invalidField) => {
    const user = userEvent.setup()
    const endpoint = mode === 'signup' ? '/auth/signup' : '/auth/login'
    mockApi({ [`POST ${endpoint}`]: { body: ME } })
    renderApp(<AppRoutes />, {
      session: UNAUTHENTICATED,
      route: mode === 'signup' ? '/signup' : '/login',
    })

    if (mode === 'signup') {
      await user.type(
        screen.getByLabelText('Entreprise'),
        invalidField === 'company' ? '   ' : 'Acme',
      )
    }
    if (invalidField !== 'empty-email') {
      await user.type(
        screen.getByLabelText(/Adresse e-mail/),
        invalidField === 'invalid-email' ? 'adresse-invalide' : 'claire@acme.test',
      )
    }
    if (invalidField !== 'empty-password') {
      await user.type(screen.getByLabelText(/^Mot de passe$/), 'motdepassesolide')
    }
    if (mode === 'signup') {
      await user.type(screen.getByLabelText('Confirmer le mot de passe'), 'motdepassesolide')
      await user.click(screen.getByRole('checkbox'))
    }

    await user.click(
      screen.getByRole('button', {
        name: mode === 'signup' ? 'Continuer vers le profil cible' : 'Se connecter',
      }),
    )

    expect(callsTo(endpoint)).toHaveLength(0)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      invalidField === 'company'
        ? /nom de votre entreprise/i
        : invalidField === 'empty-password'
          ? /mot de passe/i
          : /adresse e-mail valide/i,
    )
  })

  it('affiche la validation du mot de passe sans appeler le serveur', async () => {
    const user = userEvent.setup()
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup' })

    await user.type(screen.getByLabelText('Entreprise'), 'Acme')
    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText(/^Mot de passe$/), 'court')
    await user.type(screen.getByLabelText('Confirmer le mot de passe'), 'court')
    await user.click(screen.getByRole('button', { name: 'Continuer vers le profil cible' }))

    // L'aide RESTE affichée à côté de l'erreur : un message qui remplacerait
    // l'instruction la ferait disparaître au moment où elle sert.
    expect(screen.getByText('12 caractères minimum.')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(/au moins 12 caractères/i)
    expect(screen.getByLabelText(/^Mot de passe$/)).toHaveAttribute('aria-invalid', 'true')
    expect(callsTo('/auth/signup')).toHaveLength(0)
  })

  it('reprend la composition de référence sans ancien parcours de démonstration', () => {
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup' })

    expect(
      screen.getByRole('heading', { name: 'Commencer avec un profil cible clair' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Créez votre accès, puis décrivez simplement ce que vous vendez et à qui.',
      ),
    ).toBeInTheDocument()
    expect(document.querySelector('.auth-shell')).not.toBeNull()
    expect(screen.queryByRole('navigation', { name: 'Votre mise en route' })).not.toBeInTheDocument()
  })

  /* REVUE #1 — la promesse chiffrée ne doit pas revenir.
   *
   * `signupLead` annonçait « Trois signaux réels vous attendent ». Aucun
   * signal ouvert n'existe pourtant à ce stade : le compte n'a pas de profil cible, et
   * c'est `GET /signals` qui attribue. Le nombre était donc une promesse que
   * le serveur n'avait pas produite — et qu'il ne tiendrait pas si moins de
   * trois signaux éligibles existaient.
   *
   * Ce test est négatif à dessein : il ne vérifie pas une formulation, il
   * interdit le retour de celle-là. */
  it('ne promet aucun nombre de signaux avant attribution — FR', async () => {
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup', locale: 'fr' })

    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Trois signaux réels vous attendent')
    expect(page).not.toMatch(/\b3 signaux\b/)
    expect(page).not.toMatch(/\btrois signaux\b/i)
    expect(screen.getByRole('heading', { name: 'Commencer avec un profil cible clair' })).toBeVisible()
  })

  it('reste en français sans sélecteur même si la langue initiale est l’anglais', () => {
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup', locale: 'en' })

    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Three real signals are waiting')
    expect(page).not.toMatch(/\b3 signals\b/)
    expect(page).not.toMatch(/\bthree signals\b/i)
    expect(screen.getByRole('heading', { name: 'Commencer avec un profil cible clair' })).toBeVisible()
    expect(screen.queryByLabelText(/langue/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /English/i })).not.toBeInTheDocument()
    expect(document.documentElement).toHaveAttribute('lang', 'fr')
  })

  it('n’envoie que les champs du contrat backend — jamais d’account_id', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/signup': { status: 201, body: { ...ME, onboarding_status: 'account_created' } },
    })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup', locale: 'en' })

    await user.type(screen.getByLabelText('Entreprise'), 'Acme Solutions')
    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText(/^Mot de passe$/), 'motdepassesolide')
    await user.type(screen.getByLabelText('Confirmer le mot de passe'), 'motdepassesolide')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Continuer vers le profil cible' }))

    await waitFor(() => expect(callsTo('/auth/signup')).toHaveLength(1))
    const sent = callsTo('/auth/signup')[0].body as Record<string, unknown>
    expect(Object.keys(sent).sort()).toEqual(['company_name', 'email', 'locale', 'password'])
    expect(sent).not.toHaveProperty('account_id')
    expect(sent).toEqual({
      company_name: 'Acme Solutions',
      email: 'claire@acme.test',
      locale: 'fr',
      password: 'motdepassesolide',
    })
  })
})

describe('connexion', () => {
  it('accepte un mot de passe historique d’un caractère et appelle la connexion une seule fois', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/login': { body: ME },
      ...APP_ROUTES,
    })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/login' })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    const password = screen.getByLabelText('Mot de passe')
    expect(password).toHaveAttribute('minlength', '1')
    await user.type(password, 'x')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))

    await waitFor(() => expect(callsTo('/auth/login')).toHaveLength(1))
    expect(callsTo('/auth/login')[0].body).toEqual({
      email: 'claire@acme.test',
      password: 'x',
    })
  })

  it('affiche un échec générique qui ne révèle pas l’existence du compte', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/login': {
        status: 401,
        body: { detail: { code: 'invalid_credentials', message: 'identifiants invalides' } },
      },
    })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/login' })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'inconnu@acme.test')
    await user.type(screen.getByLabelText('Mot de passe'), 'motdepassesolide')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Adresse e-mail ou mot de passe incorrect.')
    // Aucune formulation ne doit distinguer « compte inconnu » de « mot de passe faux ».
    expect(alert.textContent).not.toMatch(/inexistant|inconnu|introuvable/i)
  })

  it('conduit un compte incomplet vers l’onboarding plutôt que vers le feed', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/login': { body: { ...ME, onboarding_status: 'account_created' } },
      ...APP_ROUTES,
    })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/login' })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText('Mot de passe'), 'motdepassesolide')
    await user.click(screen.getByRole('button', { name: 'Se connecter' }))

    expect(
      await screen.findByRole('heading', { name: 'Définir ce que Kivou doit surveiller' }),
    ).toBeInTheDocument()
  })
})

describe('déconnexion', () => {
  it('efface la session côté interface et ramène à une surface publique', async () => {
    const user = userEvent.setup()
    mockApi({ ...APP_ROUTES, 'POST /auth/logout': { status: 204 } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByRole('heading', { name: 'Signaux' })
    await user.click(screen.getByRole('link', { name: 'Réglages' }))
    await screen.findByRole('heading', { level: 1, name: 'Compte' })
    const security = screen.getAllByRole('link', { name: 'Sécurité' }).find(
      (link) => link.getAttribute('href') === '/app/settings/security',
    )
    expect(security).toBeDefined()
    await user.click(security as HTMLElement)
    await screen.findByRole('heading', { level: 1, name: 'Sécurité' })
    await user.click(screen.getByRole('button', { name: 'Se déconnecter' }))

    await waitFor(() => expect(callsTo('/auth/logout')).toHaveLength(1))
    expect(
      await screen.findByRole('heading', { name: 'Retrouver vos signaux' }),
    ).toBeInTheDocument()
  })

  it('verrouille un double clic et ignore une réponse tardive après démontage', async () => {
    let release: ((response: { status: number }) => void) | undefined
    mockApi({
      ...APP_ROUTES,
      'POST /auth/logout': () =>
        new Promise((resolve) => {
          release = resolve
        }),
    })
    const view = renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/settings' })

    await screen.findByText(ICP.label)
    const user = userEvent.setup()
    const security = screen.getAllByRole('link', { name: 'Sécurité' }).find(
      (link) => link.getAttribute('href') === '/app/settings/security',
    )
    expect(security).toBeDefined()
    await user.click(security as HTMLElement)
    const logout = screen.getByRole('button', { name: 'Se déconnecter' })
    act(() => {
      fireEvent.click(logout)
      fireEvent.click(logout)
    })
    await waitFor(() => expect(callsTo('/auth/logout')).toHaveLength(1))

    view.unmount()
    await act(async () => {
      release?.({ status: 204 })
    })
    expect(callsTo('/auth/logout')).toHaveLength(1)
  })
})

describe('mot de passe oublié', () => {
  it('affiche une confirmation générique, sans dire si le compte existe', async () => {
    const user = userEvent.setup()
    mockApi({ 'POST /auth/password-reset/request': { status: 202, body: { status: 'accepted' } } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/forgot-password' })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'peut-etre@acme.test')
    await user.click(screen.getByRole('button', { name: 'Demander un lien' }))

    const confirmation = await screen.findByRole('status')
    expect(confirmation).toHaveTextContent('Si un compte correspond à cette adresse')
    expect(callsTo('/auth/password-reset/request')[0].body).toEqual({
      email: 'peut-etre@acme.test',
    })
  })

  it('confirme le nouveau mot de passe avec le jeton de l’URL', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/password-reset/confirm': { status: 204 },
    })
    renderApp(<AppRoutes />, {
      session: UNAUTHENTICATED,
      route: '/reset-password?token=jeton-test',
    })

    await user.type(screen.getByLabelText('Nouveau mot de passe'), 'nouveaumotdepasse')
    await user.type(
      screen.getByLabelText('Confirmer le nouveau mot de passe'),
      'nouveaumotdepasse',
    )
    await user.click(screen.getByRole('button', { name: 'Valider le nouveau mot de passe' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Mot de passe remplacé')
    expect(callsTo('/auth/password-reset/confirm')[0].body).toEqual({
      reset_token: 'jeton-test',
      new_password: 'nouveaumotdepasse',
    })
  })

  it('traite un jeton URL vide ou composé d’espaces comme absent', () => {
    mockApi({})
    renderApp(<AppRoutes />, {
      session: UNAUTHENTICATED,
      route: '/reset-password?token=%20%20%20',
    })

    expect(screen.getByLabelText('Jeton de réinitialisation')).toBeRequired()
  })

  it('resynchronise le jeton quand la recherche change sans remonter la page', async () => {
    const user = userEvent.setup()
    mockApi({ 'POST /auth/password-reset/confirm': { status: 204 } })
    renderApp(
      <>
        <AppRoutes />
        <ResetSearchChanger />
      </>,
      { session: UNAUTHENTICATED, route: '/reset-password?token=jeton-un' },
    )

    await user.click(screen.getByRole('button', { name: 'Changer le jeton URL' }))
    await user.type(screen.getByLabelText('Nouveau mot de passe'), 'nouveaumotdepasse')
    await user.type(
      screen.getByLabelText('Confirmer le nouveau mot de passe'),
      'nouveaumotdepasse',
    )
    await user.click(screen.getByRole('button', { name: 'Valider le nouveau mot de passe' }))

    await waitFor(() => expect(callsTo('/auth/password-reset/confirm')).toHaveLength(1))
    expect(callsTo('/auth/password-reset/confirm')[0].body).toMatchObject({
      reset_token: 'jeton-deux',
    })
  })

  it('annule la redirection différée du reset quand la surface est démontée', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    mockApi({ 'POST /auth/password-reset/confirm': { status: 204 } })
    const view = renderApp(<AppRoutes />, {
      session: UNAUTHENTICATED,
      route: '/reset-password?token=jeton-test',
    })

    await user.type(screen.getByLabelText('Nouveau mot de passe'), 'nouveaumotdepasse')
    await user.type(
      screen.getByLabelText('Confirmer le nouveau mot de passe'),
      'nouveaumotdepasse',
    )
    await user.click(screen.getByRole('button', { name: 'Valider le nouveau mot de passe' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Mot de passe remplacé')
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    view.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
