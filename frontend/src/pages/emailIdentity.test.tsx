import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { AUTHENTICATED, DASHBOARD, DISCOVERY_STATUS, ICP, ME, UNAUTHENTICATED, callsTo, mockApi, recordedCalls, renderApp } from '../test/harness'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const shell = {
  'GET /target-icps': { body: [ICP] },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /dashboard': { body: DASHBOARD },
}

describe('identité email', () => {
  it('garde l’adresse vérifiée et affiche la nouvelle adresse en attente sans enregistrer la langue', async () => {
    mockApi({ ...shell,
      'GET /auth/email': { body: { email: ME.email, verified: true, pending_email: null } },
      'POST /auth/email/request': { body: { status: 'sent' } },
    })
    renderApp(<AppRoutes />, { route: '/app/settings/profile', session: AUTHENTICATED })
    const user = userEvent.setup()
    const email = await screen.findByLabelText('Adresse professionnelle')
    await waitFor(() => expect(screen.getByText(/Adresse vérifiée :/)).toBeVisible())
    await user.clear(email)
    await user.type(email, 'nouveau@example.test')
    await user.click(screen.getByRole('button', { name: 'Envoyer le lien de vérification' }))
    expect(await screen.findByText(/En attente de vérification : nouveau@example.test/)).toBeVisible()
    expect(screen.getByText(/Adresse vérifiée :/)).toHaveTextContent(ME.email)
    expect(callsTo('/auth/email/request')[0].body).toEqual({ email: 'nouveau@example.test' })
    expect(callsTo('/me', 'PATCH')).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Renvoyer le lien de vérification' })).toBeEnabled()
  })

  it.each([
    [422, 'Indiquez une adresse email valide.'],
    [409, 'Cette adresse ne peut pas être utilisée.'],
    [429, 'Un lien vient déjà d’être demandé. Patientez avant de réessayer.'],
    [503, 'Le lien n’a pas pu être envoyé. Réessayez.'],
  ])('affiche une erreur %s sans prétendre que le lien est envoyé', async (status, message) => {
    mockApi({ ...shell,
      'GET /auth/email': { body: { email: ME.email, verified: false, pending_email: null } },
      'POST /auth/email/request': { status: Number(status) },
    })
    renderApp(<AppRoutes />, { route: '/app/settings/profile', session: AUTHENTICATED })
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Envoyer le lien de vérification' })
    await waitFor(() => expect(button).toBeEnabled())
    await user.click(button)
    expect(await screen.findByRole('alert')).toHaveTextContent(String(message))
    expect(screen.getByLabelText('Adresse professionnelle')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByText(/Lien de vérification envoyé/)).not.toBeInTheDocument()
    expect(button).toBeEnabled()
  })

  it('recharge une adresse en attente et permet de la renvoyer', async () => {
    mockApi({ ...shell,
      'GET /auth/email': { body: { email: ME.email, verified: true, pending_email: 'pending@example.test' } },
      'POST /auth/email/request': { body: { status: 'sent' } },
    })
    renderApp(<AppRoutes />, { route: '/app/settings/profile', session: AUTHENTICATED })
    const button = await screen.findByRole('button', { name: 'Renvoyer le lien de vérification' })
    expect(screen.getByLabelText('Adresse professionnelle')).toHaveValue('pending@example.test')
    await userEvent.setup().click(button)
    expect(callsTo('/auth/email/request')[0].body).toEqual({ email: 'pending@example.test' })
  })
})

describe('vérification explicite du fragment', () => {
  it('ne vérifie rien au chargement, puis adopte la session émise après le clic', async () => {
    mockApi({ 'POST /auth/email/verify': { body: { status: 'verified' } }, 'GET /me': { body: ME } })
    renderApp(<AppRoutes />, { route: '/verify-email#opaque-token', session: UNAUTHENTICATED })
    const button = await screen.findByRole('button', { name: 'Vérifier mon adresse email' })
    expect(callsTo('/auth/email/verify')).toHaveLength(0)
    expect(callsTo('/auth/email/verify', 'GET')).toHaveLength(0)
    await userEvent.setup().click(button)
    expect(await screen.findByText('Votre adresse email est vérifiée.')).toBeVisible()
    expect(callsTo('/auth/email/verify')[0].body).toEqual({ token: 'opaque-token' })
    expect(callsTo('/me', 'GET')).toHaveLength(1)
    expect(screen.getByRole('link', { name: 'Voir mes signaux' })).toHaveAttribute('href', '/app/dashboard')
    expect(recordedCalls.every((call) => !call.url.includes('opaque-token') && !call.search.toString().includes('opaque-token'))).toBe(true)
  })

  it('affiche un lien expiré après un 400', async () => {
    mockApi({ 'POST /auth/email/verify': { status: 400 } })
    renderApp(<AppRoutes />, { route: '/verify-email#expired-token', session: UNAUTHENTICATED })
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Vérifier mon adresse email' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien est invalide ou expiré.')
    expect(callsTo('/me', 'GET')).toHaveLength(0)
  })

  it('ne soumet pas un jeton absent', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/verify-email', session: UNAUTHENTICATED })
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien est invalide ou expiré.')
    expect(callsTo('/auth/email/verify')).toHaveLength(0)
  })

  it('réessaie uniquement la session après une vérification réussie suivie d’une panne', async () => {
    let reads = 0
    mockApi({ 'POST /auth/email/verify': { body: { status: 'verified' } }, 'GET /me': () => ++reads === 1 ? { status: 503 } : { body: ME } })
    renderApp(<AppRoutes />, { route: '/verify-email#opaque-token', session: UNAUTHENTICATED })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Vérifier mon adresse email' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/session/)
    await user.click(screen.getByRole('button', { name: 'Réessayer la connexion' }))
    expect(await screen.findByRole('link', { name: 'Voir mes signaux' })).toBeVisible()
    expect(callsTo('/auth/email/verify')).toHaveLength(1)
  })
})

describe('aperçu public pour une adresse de compte existant', () => {
  it('affiche les seuls faits publics sans session ni appels privés', async () => {
    mockApi({ 'POST /auth/attribution/preview': { body: {
      recipient_email: 'destinataire@example.test',
      signal: { object: 'Rénovation de la mairie', holder: 'Entreprise Martin', buyer: 'Commune de Blois', amount: '120000', currency: 'EUR', location: 'Loir-et-Cher', date: '2026-09-01', date_label: 'Attribué le', for_you_sentence: 'Votre bardage répond aux besoins de ce chantier.' },
    } } })
    renderApp(<AppRoutes />, { route: '/public-signal#opaque-public-token', session: UNAUTHENTICATED })
    expect(await screen.findByRole('heading', { name: 'Rénovation de la mairie' })).toBeVisible()
    expect(screen.getByText('Ce signal a été envoyé à destinataire@example.test — connectez-vous pour l’ouvrir')).toBeVisible()
    expect(screen.getByText('Entreprise Martin')).toBeVisible()
    expect(screen.getByText('Commune de Blois')).toBeVisible()
    expect(screen.getByText('Votre bardage répond aux besoins de ce chantier.')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Se connecter' })).toHaveAttribute('href', '/login')
    expect(callsTo('/auth/attribution/preview')[0].body).toEqual({ token: 'opaque-public-token' })
    expect(recordedCalls.every((call) => call.url === '/auth/attribution/preview')).toBe(true)
    expect(screen.queryByRole('button', { name: /Sauver|Ignorer|Contacter/ })).not.toBeInTheDocument()
  })

  it('affiche une erreur de jeton sans tenter de charger un signal privé', async () => {
    mockApi({ 'POST /auth/attribution/preview': { status: 400 } })
    renderApp(<AppRoutes />, { route: '/public-signal#expired', session: UNAUTHENTICATED })
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce lien est invalide ou expiré.')
    expect(recordedCalls).toHaveLength(1)
  })
})
