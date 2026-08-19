import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  ME,
  callsTo,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

/* SPEC-015 §49 — onboarding et gestion des profils. */

afterEach(() => vi.unstubAllGlobals())

const INCOMPLETE_ME = { ...ME, onboarding_status: 'account_created' as const }

describe('onboarding', () => {
  it('dirige un compte incomplet vers l’onboarding depuis une route applicative', async () => {
    mockApi({ 'GET /target-icps': { body: [] } })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    expect(
      await screen.findByRole('heading', { name: 'Configurer votre profil de ciblage' }),
    ).toBeInTheDocument()
  })

  it('identifie visiblement ce qui manque encore, sans jargon moteur', async () => {
    mockApi({})
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    const notice = await screen.findByText(/Il manque encore/)
    const wrapper = notice.closest('div')!
    expect(wrapper).toHaveTextContent('ce que vous vendez')
    expect(wrapper).toHaveTextContent('où vous pouvez intervenir')
    expect(wrapper).toHaveTextContent('le montant minimum')

    // Aucun vocabulaire moteur ne doit fuiter dans l'interface client.
    const page = document.body.textContent ?? ''
    for (const forbidden of [
      'NeedCategory',
      'TradeDomain',
      'geography_basis',
      'unknown_value_policy',
      'source_modes_allowed',
      'need_graph',
      'materials_or_components',
    ]) {
      expect(page).not.toContain(forbidden)
    }
  })

  it('crée un profil valide et n’envoie jamais d’account_id', async () => {
    const user = userEvent.setup()
    mockApi({
      'POST /target-icps': { status: 201, body: ICP },
      'GET /me': { body: ME },
      'GET /signals': { body: feedPage([]) },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await user.type(await screen.findByLabelText(/Nom du profil/), 'Matériaux — Occitanie')
    await user.click(screen.getByLabelText('Matériaux et composants'))
    await user.click(screen.getByLabelText('France'))
    await user.type(screen.getByLabelText('Montant minimum'), '50000')

    const submit = screen.getByRole('button', {
      name: 'Créer mon profil et voir mes signaux',
    })
    await waitFor(() => expect(submit).toBeEnabled())
    await user.click(submit)

    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    const sent = callsTo('/target-icps')[0].body as {
      label: string
      customer_input: Record<string, unknown>
    }
    expect(sent.label).toBe('Matériaux — Occitanie')
    expect(sent.customer_input.offers).toEqual(['materials_and_components'])
    expect(sent.customer_input.territories).toEqual(['FR'])
    expect(sent.customer_input.minimum_contract_value).toEqual({
      currency: 'EUR',
      minimum_amount: 50000,
      maximum_amount: null,
    })
    expect(sent).not.toHaveProperty('account_id')
    expect(sent.customer_input).not.toHaveProperty('account_id')
  })

  it('aucune requête du frontend ne porte d’account_id', async () => {
    const user = userEvent.setup()
    mockApi({ 'POST /target-icps': { status: 201, body: ICP }, 'GET /me': { body: ME } })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await user.type(await screen.findByLabelText(/Nom du profil/), 'Test')
    await user.click(screen.getByLabelText('Matériaux et composants'))
    await user.click(screen.getByLabelText('France'))
    await user.type(screen.getByLabelText('Montant minimum'), '1000')
    await user.click(screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }))

    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    for (const call of recordedCalls) {
      expect(JSON.stringify(call.body ?? {})).not.toContain('account_id')
      expect(call.url).not.toContain('account_id')
      expect(call.search.get('account_id')).toBeNull()
    }
  })
})

describe('gestion des profils', () => {
  it('permet de modifier un profil existant', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'PATCH /target-icps/icp_1': { body: { ...ICP, label: 'Matériaux — Sud' } },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Modifier' }))
    const field = await screen.findByLabelText(/Nom du profil/)
    await user.clear(field)
    await user.type(field, 'Matériaux — Sud')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await waitFor(() =>
      expect(callsTo('/target-icps/icp_1', 'PATCH')).toHaveLength(1),
    )
  })

  it('affiche la limite de profils du plan sans supprimer aucun profil', async () => {
    const second = { ...ICP, target_icp_id: 'icp_2', label: 'Location — Suisse' }
    mockApi({
      'GET /target-icps': { body: [ICP, second] },
      'GET /billing/status': {
        body: { ...DISCOVERY_STATUS, target_icps_over_limit: ['icp_2'] },
      },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    // Les deux profils restent affichés : rien n'est masqué ni supprimé.
    expect(await screen.findByText('Matériaux — Occitanie')).toBeInTheDocument()
    expect(screen.getByText('Location — Suisse')).toBeInTheDocument()

    const warnings = screen.getAllByText('Au-delà de la limite de votre offre')
    expect(warnings.length).toBeGreaterThan(0)
    expect(screen.getByText(/Profils actifs/)).toBeInTheDocument()

    // Aucune action destructive n'est proposée : le backend n'expose pas de DELETE.
    expect(screen.queryByRole('button', { name: /supprimer/i })).not.toBeInTheDocument()

    const list = screen.getByText('Location — Suisse').closest('article')!
    expect(within(list).getByRole('button', { name: 'Modifier' })).toBeInTheDocument()
  })
})
