import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

afterEach(() => vi.unstubAllGlobals())

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

    expect(await screen.findByRole('heading', { name: 'Se connecter' })).toBeInTheDocument()
    // Le feed ne doit pas avoir été demandé : la redirection précède l'appel.
    expect(callsTo('/signals', 'GET')).toHaveLength(0)
  })

  it('laisse un utilisateur authentifié atteindre l’application', async () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(await screen.findByRole('heading', { name: 'Signaux récents' })).toBeInTheDocument()
  })

  it('ramène à la connexion, en le disant, quand la session a expiré', async () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, { session: EXPIRED, route: '/app/signals' })

    expect(await screen.findByRole('heading', { name: 'Se connecter' })).toBeInTheDocument()
    expect(screen.getByText(/session a expiré/i)).toBeInTheDocument()
  })

  it('ne crée pas de boucle : l’état de chargement ne redirige pas', () => {
    mockApi(APP_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'loading', me: null },
      route: '/app/signals',
    })

    expect(screen.queryByRole('heading', { name: 'Se connecter' })).not.toBeInTheDocument()
    expect(screen.getByText('Chargement…')).toBeInTheDocument()
  })
})

describe('inscription', () => {
  it('affiche la validation du mot de passe sans appeler le serveur', async () => {
    const user = userEvent.setup()
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup' })

    await user.type(screen.getByLabelText(/Nom de votre entreprise/), 'Acme')
    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText('Mot de passe'), 'court')
    await user.click(screen.getByRole('button', { name: 'Créer mon compte' }))

    // L'aide RESTE affichée à côté de l'erreur : un message qui remplacerait
    // l'instruction la ferait disparaître au moment où elle sert.
    expect(await screen.findAllByText(/Au moins 12 caractères/)).toHaveLength(2)
    expect(screen.getByLabelText('Mot de passe')).toHaveAttribute('aria-invalid', 'true')
    expect(callsTo('/auth/signup')).toHaveLength(0)
  })

  /* P0-02 §4 — ce que l'inscription annonce, et ce qu'elle se garde d'annoncer.
   *
   * La suite du parcours est dite pour que le client sache pourquoi on lui
   * demandera son métier juste après. Le NOMBRE de signaux, lui, n'appartient
   * pas à cet écran : aucun déblocage n'existe tant qu'aucun ciblage n'a été
   * enregistré, et l'annoncer ici promettrait un résultat que le serveur n'a
   * pas produit. */
  it('annonce la suite du parcours et l’absence de carte bancaire', async () => {
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup' })

    expect(
      screen.getByText(
        'Ensuite, indiquez ce que vous vendez et où vous intervenez. Kivou préparera vos premiers signaux.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Aucune carte bancaire n’est nécessaire pour découvrir vos premiers signaux.',
      ),
    ).toBeInTheDocument()

    // La mise en route est située, et l'inscription en est le premier jalon.
    const progress = screen.getByRole('navigation', { name: 'Votre mise en route' })
    const steps = within(progress).getAllByRole('listitem')
    expect(steps[0]).toHaveAttribute('aria-current', 'step')
    expect(steps[0]).toHaveTextContent('Compte')
  })

  /* REVUE #1 — la promesse chiffrée ne doit pas revenir.
   *
   * `signupLead` annonçait « Trois signaux réels vous attendent ». Aucun
   * déblocage n'existe pourtant à ce stade : le compte n'a pas de ciblage, et
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
    // La valeur reste dite, sans chiffre.
    expect(screen.getByText(/Vos premiers signaux réels/)).toBeInTheDocument()
  })

  it('ne promet aucun nombre de signaux avant attribution — EN', async () => {
    mockApi({ 'POST /auth/signup': { body: ME } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup', locale: 'en' })

    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Three real signals are waiting')
    expect(page).not.toMatch(/\b3 signals\b/)
    expect(page).not.toMatch(/\bthree signals\b/i)
    expect(screen.getByText(/Your first real signals/)).toBeInTheDocument()
  })

  it('n’envoie que les champs du contrat backend — jamais d’account_id', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/signup': { status: 201, body: { ...ME, onboarding_status: 'account_created' } },
    })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/signup' })

    await user.type(screen.getByLabelText(/Nom de votre entreprise/), 'Acme Solutions')
    await user.type(screen.getByLabelText(/Adresse e-mail/), 'claire@acme.test')
    await user.type(screen.getByLabelText('Mot de passe'), 'motdepassesolide')
    await user.click(screen.getByRole('button', { name: 'Créer mon compte' }))

    await waitFor(() => expect(callsTo('/auth/signup')).toHaveLength(1))
    const sent = callsTo('/auth/signup')[0].body as Record<string, unknown>
    expect(Object.keys(sent).sort()).toEqual(['company_name', 'email', 'locale', 'password'])
    expect(sent).not.toHaveProperty('account_id')
  })
})

describe('connexion', () => {
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
      await screen.findByRole('heading', { name: 'Configurer votre profil de ciblage' }),
    ).toBeInTheDocument()
  })
})

describe('déconnexion', () => {
  it('efface la session côté interface et ramène à une surface publique', async () => {
    const user = userEvent.setup()
    mockApi({ ...APP_ROUTES, 'POST /auth/logout': { status: 204 } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByRole('heading', { name: 'Signaux récents' })
    await user.click(screen.getByRole('button', { name: 'Se déconnecter' }))

    await waitFor(() => expect(callsTo('/auth/logout')).toHaveLength(1))
    expect(await screen.findByRole('heading', { name: 'Se connecter' })).toBeInTheDocument()
  })
})

describe('mot de passe oublié', () => {
  it('affiche une confirmation générique, sans dire si le compte existe', async () => {
    const user = userEvent.setup()
    mockApi({ 'POST /auth/password-reset/request': { status: 202, body: { status: 'accepted' } } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/forgot-password' })

    await user.type(screen.getByLabelText(/Adresse e-mail/), 'peut-etre@acme.test')
    await user.click(screen.getByRole('button', { name: 'Envoyer le lien' }))

    const confirmation = await screen.findByRole('alert')
    expect(confirmation).toHaveTextContent('Si un compte existe pour cette adresse')
  })
})
