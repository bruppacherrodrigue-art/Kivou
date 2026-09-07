import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { DASHBOARD, ICP, ME, UNLOCKED_ITEM, callsTo, feedPage, mockApi, renderApp, type Routes } from '../test/harness'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const provisionalMe = { ...ME, provisional_profile: true, onboarding_status: 'icp_incomplete' as const }
const profile = { ...ICP, provisional: true, label: 'bardage métallique · Loir-et-Cher', customer_input: {
  ...ICP.customer_input, offer_summary: 'bardage métallique', territories: ['FR'],
  territory_subdivisions: ['FR-41'], sector_cpv_prefixes: ['45'],
  minimum_contract_value: { currency: 'EUR', minimum_amount: 0, maximum_amount: null },
} }
const options = { zones: [{ code: 'FR-41', label: 'Loir-et-Cher', country: 'FR' }],
  sectors: [{ prefix: '45', label: 'Travaux de construction' }] }
const updatePath = `/target-icps/${profile.target_icp_id}`

function mount(overrides: Routes = {}, route = '/app/confirm-profile') {
  mockApi({
    'GET /target-icps': { body: [profile] },
    'GET /target-icps/options': { body: options },
    [`PATCH ${updatePath}`]: { body: { ...profile, provisional: false } },
    'GET /me': { body: { ...ME, provisional_profile: false } },
    'GET /dashboard': { body: { ...DASHBOARD, top3: [UNLOCKED_ITEM] } },
    'GET /signals': { body: feedPage([UNLOCKED_ITEM], { provisional_profile: true }) },
    ...overrides,
  })
  return renderApp(<AppRoutes />, { route, session: { status: 'authenticated', me: provisionalMe } })
}

describe('B2 confirmation du profil depuis un jeton QA', () => {
  it('relie le bandeau, le compte et le profil provisoire au formulaire PR5', async () => {
    mount({}, '/app/signals')
    expect(await screen.findByRole('link', { name: 'Confirmer mon profil' })).toHaveAttribute('href', '/app/confirm-profile')
    expect(screen.getByText('Découverte · profil provisoire').closest('a')).toHaveAttribute('href', '/app/confirm-profile')
    expect(document.querySelector('.sidebar-account-link')).toHaveAttribute('href', '/app/confirm-profile')
  })

  it('préremplit les trois champs et confirme le même profil vers un accueil non vide', async () => {
    mount()
    const user = userEvent.setup()
    expect(await screen.findByLabelText('Zone')).toHaveValue(['FR-41'])
    expect(screen.getByLabelText('Secteur')).toHaveValue('45')
    expect(within(screen.getByLabelText('Secteur')).getByRole('option', { selected: true })).toHaveTextContent('bardage métallique')
    expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('bardage métallique')
    expect(document.querySelectorAll('input, select, textarea')).toHaveLength(3)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Ce que vous vendez'))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Panneaux métalliques et accessoires sur mesure')
    await user.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
    await waitFor(() => expect(callsTo(updatePath, 'PATCH')).toHaveLength(1))
    expect(callsTo(updatePath, 'PATCH')[0].body).toMatchObject({ customer_input: {
      offer_summary: 'Panneaux métalliques et accessoires sur mesure', territories: ['FR'],
      territory_subdivisions: ['FR-41'], sector_cpv_prefixes: ['45'],
    } })
    expect(callsTo('/target-icps', 'POST')).toHaveLength(0)
    expect(await screen.findByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Recevoir mes signaux' })).not.toBeInTheDocument()
  })

  it('ne revient jamais à l’ancien assistant si le chargement du profil échoue', async () => {
    mount({ 'GET /target-icps': { status: 503 } }, '/onboarding')
    expect(await screen.findByRole('alert')).toHaveTextContent(/profil/i)
    expect(screen.queryByRole('button', { name: 'Continuer' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeEnabled()
  })

  it('place chaque erreur locale près du champ sans changement de page', async () => {
    mount()
    const user = userEvent.setup()
    await user.deselectOptions(await screen.findByLabelText('Zone'), ['FR-41'])
    fireEvent.change(screen.getByLabelText('Secteur'), { target: { value: '' } })
    await user.clear(screen.getByLabelText('Ce que vous vendez'))
    await user.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
    for (const label of ['Zone', 'Secteur', 'Ce que vous vendez']) {
      const field = screen.getByLabelText(label)
      expect(field).toHaveAttribute('aria-invalid', 'true')
      expect(within(field.closest('.form-field')!).getByRole('alert')).not.toHaveTextContent(/^$/)
    }
    expect(callsTo(updatePath, 'PATCH')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: 'Continuer' })).not.toBeInTheDocument()
  })

  it('conserve les erreurs 422 de texte et de listes près des trois champs', async () => {
    mount({ [`PATCH ${updatePath}`]: { status: 422, body: { detail: [
      { loc: ['body', 'customer_input', 'offer_summary'], msg: 'Description trop longue' },
      { loc: ['body', 'customer_input', 'territory_subdivisions', 0], msg: 'Département invalide' },
      { loc: ['body', 'customer_input', 'sector_cpv_prefixes', 0], msg: 'Secteur invalide' },
    ] } } })
    await screen.findByLabelText('Zone')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
    for (const [label, message] of [['Zone', 'Département invalide'], ['Secteur', 'Secteur invalide'], ['Ce que vous vendez', 'Description trop longue']]) {
      await waitFor(() => expect(within(screen.getByLabelText(label).closest('.form-field')!).getByRole('alert')).toHaveTextContent(message))
    }
    expect(screen.queryByRole('button', { name: 'Continuer' })).not.toBeInTheDocument()
  })

  it('affiche les échecs réseau et permet de réessayer sans vider le formulaire', async () => {
    mount({ [`PATCH ${updatePath}`]: { status: 503 } })
    await screen.findByLabelText('Zone')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
    expect(await screen.findByRole('alert')).not.toHaveTextContent(/^$/)
    expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('bardage métallique')
    expect(screen.getByRole('button', { name: 'Recevoir mes signaux' })).toBeEnabled()
  })

  it('sélectionne EUR, pas CHF, pour le parcours classique français', async () => {
    mockApi({ 'GET /target-icps': { body: [] } })
    renderApp(<AppRoutes />, { route: '/onboarding', session: { status: 'authenticated', me: { ...ME, onboarding_status: 'account_created' } } })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Produits et services proposés'), 'Bardage')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))
    await user.type(screen.getByLabelText('Entreprises recherchées'), 'Routes et génie civil')
    await user.type(screen.getByLabelText('Territoire couvert'), 'France')
    await user.type(screen.getByLabelText('Mots-clés à surveiller'), 'Matériaux et composants')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))
    expect(screen.getByLabelText('Devise')).toHaveValue('EUR')
    expect(within(screen.getByLabelText('Devise')).queryByRole('option', { name: 'CHF' })).not.toBeInTheDocument()
  })
})
