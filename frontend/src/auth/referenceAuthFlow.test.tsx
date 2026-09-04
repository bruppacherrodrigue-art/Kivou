import { useState } from 'react'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { useSession } from './SessionProvider'
import { planFromSearch } from '../billing/planRoute'
import { useI18n } from '../i18n'
import { AuthFlow } from '../presentation/dashboard/AuthFlow'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNAUTHENTICATED,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

function AuthLeaveHarness() {
  const [visible, setVisible] = useState(true)
  const navigate = useNavigate()
  const { state } = useSession()

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setVisible(false)
          navigate('/left')
        }}
      >
        Quitter la surface
      </button>
      {visible ? <AuthFlow mode="login" /> : <p>Surface quittée</p>}
      <output data-testid="session-state">{state.status}</output>
      <LocationProbe />
    </>
  )
}

function LateAccountLocale() {
  const { locale, setLocale } = useI18n()
  const { adopt } = useSession()
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => setLocale('en')}>Résoudre la locale du compte</button>
      <button
        type="button"
        onClick={() => {
          adopt({ ...ME, locale: 'en' })
          navigate('/app/settings')
        }}
      >
        Ouvrir le compte anglais
      </button>
      <output data-testid="locale">{locale}</output>
    </>
  )
}

afterEach(() => vi.restoreAllMocks())

describe('parcours d’entrée de la référence connectée', () => {
  it('connecte avec le formulaire de référence et ouvre la vue d’ensemble', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/login': (request) => {
        expect(request.body).toEqual({
          email: 'test@example.test',
          password: 'correct-password',
        })
        return { body: ME }
      },
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /dashboard': { body: {
        as_of: '2026-09-04', last_seen_at: null, new_since_last_visit: 0,
        strong_matches: 0, top3: [], to_follow_up: [], to_follow_up_truncated: false,
        week: { new: 0, saved: 0, contacted: 0, replied: 0 }, scan_truncated: false,
      } },
      'GET /notification-preferences': {
        body: {
          email_enabled: false,
          notification_email: null,
          updated_at: '2026-08-29T09:00:00+00:00',
        },
      },
    })
    renderApp(<AppRoutes />, { route: '/login', session: UNAUTHENTICATED })

    expect(document.querySelector('.auth-shell')).not.toBeNull()
    const notice = screen.getByRole('note')
    expect(notice).toHaveClass('prototype-notice')
    expect(notice).not.toHaveTextContent(/démonstration|maquette/i)
    await user.type(screen.getByLabelText(/adresse/i), 'test@example.test')
    await user.type(screen.getByLabelText(/^mot de passe$/i), 'correct-password')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Vos premiers signaux' }),
    ).toBeVisible()
  })

  it('verrouille deux soumissions de connexion dans le même tour de boucle', async () => {
    let release!: (value: { body: typeof ME }) => void
    const response = new Promise<{ body: typeof ME }>((resolve) => {
      release = resolve
    })
    mockApi({ 'POST /auth/login': () => response })
    renderApp(<AuthFlow mode="login" />, { route: '/login', session: UNAUTHENTICATED })

    fireEvent.change(screen.getByLabelText(/adresse/i), {
      target: { value: 'test@example.test' },
    })
    fireEvent.change(screen.getByLabelText(/^mot de passe$/i), {
      target: { value: 'correct-password' },
    })
    const form = screen.getByRole('button', { name: /se connecter/i }).closest('form')!
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })

    expect(callsTo('/auth/login')).toHaveLength(1)
    await act(async () => {
      release({ body: ME })
      await response
    })
  })

  it('n’adopte ni ne redirige après avoir quitté la surface pendant la connexion', async () => {
    const user = userEvent.setup()
    let release!: (value: { body: typeof ME }) => void
    const response = new Promise<{ body: typeof ME }>((resolve) => {
      release = resolve
    })
    mockApi({ 'POST /auth/login': () => response })
    renderApp(<AuthLeaveHarness />, { route: '/login', session: UNAUTHENTICATED })

    await user.type(screen.getByLabelText(/adresse/i), 'test@example.test')
    await user.type(screen.getByLabelText(/^mot de passe$/i), 'correct-password')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))
    await waitFor(() => expect(callsTo('/auth/login')).toHaveLength(1))
    await user.click(screen.getByRole('button', { name: 'Quitter la surface' }))

    await act(async () => {
      release({ body: ME })
      await response
    })
    expect(screen.getByTestId('session-state')).toHaveTextContent('unauthenticated')
    expect(screen.getByTestId('location')).toHaveTextContent('/left')
  })

  it('rend le lien de changement de parcours inerte pendant une connexion active', async () => {
    const user = userEvent.setup()
    let release!: (value: { body: typeof ME }) => void
    const response = new Promise<{ body: typeof ME }>((resolve) => {
      release = resolve
    })
    mockApi({ 'POST /auth/login': () => response })
    renderApp(
      <>
        <AuthFlow mode="login" />
        <LocationProbe />
      </>,
      { route: '/login', session: UNAUTHENTICATED },
    )

    await user.type(screen.getByLabelText(/adresse/i), 'test@example.test')
    await user.type(screen.getByLabelText(/^mot de passe$/i), 'correct-password')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))
    const changer = screen.getByRole('link', { name: 'Mot de passe oublié ?' })
    expect(changer).toHaveAttribute('aria-disabled', 'true')
    await user.click(changer)
    expect(screen.getByTestId('location')).toHaveTextContent('/login')

    await act(async () => {
      release({ body: ME })
      await response
    })
  })

  it('inscrit en français sans stockage de démonstration ni sélecteur de langue', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/signup': (request) => {
        expect(request.body).toEqual({
          company_name: 'Entreprise Test',
          email: 'test@example.test',
          password: 'correct-password',
          locale: 'fr',
        })
        return {
          status: 201,
          body: { ...ME, locale: 'fr', onboarding_status: 'account_created' },
        }
      },
    })
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/signup?plan=discovery', session: UNAUTHENTICATED, locale: 'en' },
    )

    expect(screen.queryByLabelText(/langue/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'English' })).not.toBeInTheDocument()
    expect(document.querySelector('.auth-readonly-locale')).toHaveTextContent('Français')
    expect(screen.getByRole('heading', { name: 'Commencer avec un profil cible clair' })).toBeVisible()

    await user.type(screen.getByLabelText('Entreprise'), 'Entreprise Test')
    await user.type(
      screen.getByLabelText('Adresse e-mail professionnelle'),
      'test@example.test',
    )
    await user.type(screen.getByLabelText(/^Mot de passe$/), 'correct-password')
    await user.type(
      screen.getByLabelText('Confirmer le mot de passe'),
      'correct-password',
    )
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /continuer vers le profil cible/i }))

    expect(await screen.findByText('Première configuration')).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent('/onboarding?plan=discovery')
    expect(storage).not.toHaveBeenCalled()
  })

  it('transporte un choix payant du catalogue vers l’onboarding sans stockage', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/signup': {
        status: 201,
        body: { ...ME, onboarding_status: 'account_created' },
      },
    })
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/signup?plan=pro', session: UNAUTHENTICATED },
    )

    await user.type(screen.getByLabelText('Entreprise'), 'Entreprise Test')
    await user.type(
      screen.getByLabelText('Adresse e-mail professionnelle'),
      'test@example.test',
    )
    await user.type(screen.getByLabelText(/^Mot de passe$/), 'correct-password')
    await user.type(
      screen.getByLabelText('Confirmer le mot de passe'),
      'correct-password',
    )
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /continuer vers le profil cible/i }))

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/onboarding?plan=pro'),
    )
    expect(storage).not.toHaveBeenCalled()
  })

  it('maintient la locale française sur l’auth puis applique la locale du compte connecté', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(
      <>
        <AppRoutes />
        <LateAccountLocale />
      </>,
      { route: '/forgot-password', session: UNAUTHENTICATED, locale: 'fr' },
    )

    await user.click(screen.getByRole('button', { name: 'Résoudre la locale du compte' }))
    await waitFor(() => expect(screen.getByTestId('locale')).toHaveTextContent('fr'))
    expect(document.documentElement).toHaveAttribute('lang', 'fr')

    await user.click(screen.getByRole('button', { name: 'Ouvrir le compte anglais' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Account' })).toBeVisible()
    await waitFor(() => expect(screen.getByTestId('locale')).toHaveTextContent('en'))
    expect(document.documentElement).toHaveAttribute('lang', 'en')
  })
})

describe('plan porté uniquement dans l’URL', () => {
  it('accepte uniquement les quatre codes routables et échoue fermé', () => {
    expect(planFromSearch('?plan=pro')).toBe('pro')
    expect(planFromSearch('?plan=founding')).toBe('discovery')
    expect(planFromSearch('?plan=unknown')).toBe('discovery')
    expect(planFromSearch('')).toBe('discovery')
  })

  it.each(['essential', 'pro', 'scale'] as const)(
    'préserve le plan %s vers la facturation pour un compte déjà prêt sans démarrer de checkout',
    async (plan) => {
      mockApi({
        'GET /billing/plans': { body: CATALOGUE },
        'GET /billing/status': { body: DISCOVERY_STATUS },
      })
      renderApp(
        <>
          <AppRoutes />
          <LocationProbe />
        </>,
        { route: `/signup?plan=${plan}`, session: AUTHENTICATED },
      )

      await waitFor(() =>
        expect(screen.getByTestId('location')).toHaveTextContent(`/app/billing?plan=${plan}`),
      )
      expect(callsTo('/billing/checkout')).toHaveLength(0)
    },
  )

  it('préserve le plan choisi entre inscription et connexion', () => {
    renderApp(<AppRoutes />, {
      route: '/signup?plan=pro',
      session: UNAUTHENTICATED,
    })

    expect(screen.getByRole('link', { name: 'Se connecter' })).toHaveAttribute(
      'href',
      '/login?plan=pro',
    )
  })

  it('redirige un compte prêt connecté depuis le choix public vers cette offre', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /auth/login': { body: ME },
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/login?plan=scale', session: UNAUTHENTICATED },
    )

    await user.type(screen.getByLabelText(/adresse/i), 'test@example.test')
    await user.type(screen.getByLabelText(/^mot de passe$/i), 'correct-password')
    await user.click(screen.getByRole('button', { name: /se connecter/i }))

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/app/billing?plan=scale'),
    )
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('renvoie Découverte vers la vue d’ensemble pour un compte déjà prêt', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /notification-preferences': {
        body: {
          email_enabled: false,
          notification_email: null,
          updated_at: '2026-08-29T09:00:00+00:00',
        },
      },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/signup?plan=discovery', session: AUTHENTICATED },
    )

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/app/dashboard'),
    )
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
})
