import { act, screen } from '@testing-library/react'
import { useLocation, useNavigationType } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import type { Me } from '../api/types'
import {
  CATALOGUE, DASHBOARD, DISCOVERY_STATUS, ICP, ME, callsTo,
  feedPage, mockApi, recordedCalls, renderApp,
} from '../test/harness'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function LocationProbe() {
  const location = useLocation()
  const navigation = useNavigationType()
  return <><output data-testid="onboarding-location">{location.pathname}{location.search}</output><output data-testid="onboarding-navigation">{navigation}</output></>
}

function renderRoute(route: string, me: Me = { ...ME, onboarding_status: 'account_created', provisional_profile: false }) {
  const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
  mockApi({
    'GET /target-icps': { body: me.provisional_profile || me.onboarding_status === 'ready_for_signals' ? [ICP] : [] },
    'GET /target-icps/options': { body: { zones: [], sectors: [] } },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /billing/plans': { body: CATALOGUE },
    'GET /dashboard': { body: DASHBOARD },
    'GET /signals': { body: feedPage([]) },
    'GET /notification-preferences': { body: { email_enabled: false, notification_email: null, updated_at: '2026-09-14' } },
  })
  renderApp(<><AppRoutes /><LocationProbe /></>, { route, session: { status: 'authenticated', me } })
  return errors
}

const prospectingRoutes = [
  '/app', '/app/', '/app/dashboard', '/app/signals', '/app/signals/signal-key',
  '/app/companies', '/app/companies/company-key', '/app/companies/directory',
  '/app/companies/directory/123456789',
  '/App', '/APP/dashboard', '/app/Signals', '/App/signals',
  '/app/Companies/company-key', '/APP/companies/directory/123456789',
  '/%61pp', '/app/%73ignals', '/%61pp/signals',
  '/app/%73ignals/signal-key', '/app/%63ompanies/directory/123456789',
]

describe.each(['account_created', 'icp_incomplete'] as const)('incomplete %s account without a provisional profile', (status) => {
  it.each(prospectingRoutes)('redirects %s before any prospecting child can render', async (route) => {
    const errors = renderRoute(route, { ...ME, onboarding_status: status, provisional_profile: false })
    await screen.findByLabelText('Ce que vous vendez')
    expect(screen.getByTestId('onboarding-location')).toHaveTextContent(/^\/app\/confirm-profile$/)
    expect(screen.getByTestId('onboarding-navigation')).toHaveTextContent('REPLACE')
    expect(recordedCalls.some(({ url }) => /^\/(?:dashboard|signals|companies)(?:\/|$)/.test(url))).toBe(false)
    expect(document.querySelector('.dashboard-provider')).not.toBeInTheDocument()
    expect(errors).not.toHaveBeenCalled()
  })
})

it.each(['discovery', 'essential', 'pro'])('preserves validated %s plan intent while discarding unrelated query data', async (plan) => {
  const errors = renderRoute(`/app/signals/signal-key?plan=${plan}&target_icp_id=old-profile&return=https://example.invalid`)
  await screen.findByLabelText('Ce que vous vendez')
  expect(screen.getByTestId('onboarding-location')).toHaveTextContent(`/app/confirm-profile?plan=${plan}`)
  expect(screen.getByTestId('onboarding-location')).not.toHaveTextContent('old-profile')
  expect(screen.getByTestId('onboarding-location')).not.toHaveTextContent('return=')
  expect(errors).not.toHaveBeenCalled()
})

it('normalizes invalid plan intent using the existing auth plan rules', async () => {
  const errors = renderRoute('/app/dashboard?plan=not-a-plan')
  await screen.findByLabelText('Ce que vous vendez')
  expect(screen.getByTestId('onboarding-location')).toHaveTextContent('/app/confirm-profile?plan=discovery')
  expect(errors).not.toHaveBeenCalled()
})

it.each([
  ['/app/confirm-profile?plan=pro', 'Quels marchés vous intéressent ?'],
  ['/app/billing?plan=essential', 'Abonnement'],
  ['/app/settings', 'Informations du compte'],
  ['/app/settings/profile', 'Compte'],
  ['/app/settings/security', 'Sécurité'],
])('keeps %s accessible without a prospecting provider', async (route, heading) => {
  const errors = renderRoute(route)
  await screen.findByRole('heading', { name: heading })
  await act(async () => {})
  expect(screen.getByTestId('onboarding-location')).toHaveTextContent(route)
  expect(document.querySelector('.dashboard-provider')).not.toBeInTheDocument()
  expect(callsTo('/dashboard', 'GET')).toHaveLength(0)
  expect(errors).not.toHaveBeenCalled()
})

it.each([
  { ...ME, onboarding_status: 'ready_for_signals' as const, provisional_profile: false },
  { ...ME, onboarding_status: 'icp_incomplete' as const, provisional_profile: true },
])('retains the real provider for ready/provisional access ($onboarding_status/$provisional_profile)', async (me) => {
  const errors = renderRoute('/app/signals', me)
  await screen.findByRole('tab', { name: /^Nouveaux/ })
  await screen.findByRole('heading', { name: 'Nous surveillons Matériaux — Occitanie dans votre département' })
  expect(screen.getByTestId('onboarding-location')).toHaveTextContent('/app/signals')
  expect(document.querySelector('.dashboard-provider')).toBeInTheDocument()
  expect(callsTo('/signals', 'GET').length).toBeGreaterThan(0)
  expect(screen.queryByRole('heading', { name: 'Quels marchés vous intéressent ?' })).not.toBeInTheDocument()
  expect(errors).not.toHaveBeenCalled()
})

it('keeps account creation visible in the app banner and account menu', async () => {
  const errors = renderRoute('/app/signals', {
    ...ME,
    account_display_name: 'Compte à confirmer',
    email: 'landing+abc@landing.kivou.invalid',
    onboarding_status: 'icp_incomplete',
    provisional_profile: true,
    temporary_access: true,
    claim_email: null,
  })
  expect(await screen.findByText('Votre accès est temporaire. Entrez votre e-mail pour retrouver ces signaux.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Créer mon accès' })).toHaveAttribute('href', '/app/create-access')
  expect(screen.queryByRole('link', { name: 'Confirmer mon profil' })).not.toBeInTheDocument()
  expect(screen.queryByText('Personnalisez vos signaux avec votre profil cible.')).not.toBeInTheDocument()
  expect(document.querySelector('.sidebar-account-link')).toHaveAttribute('href', '/app/create-access')
  expect(errors).not.toHaveBeenCalled()
})
