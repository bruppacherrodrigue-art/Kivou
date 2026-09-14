import { afterEach, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { AppRoutes } from '../App'
import type { TargetIcp } from '../api/types'
import { ICP, ME, callsTo, mockApi, renderApp, type Routes } from '../test/harness'

const PROFILE: TargetIcp = {
  ...ICP,
  label: 'Bois et charpente',
  provisional: true,
  customer_input: {
    ...ICP.customer_input,
    offer_summary: 'Bois et charpente',
    territories: ['FR'],
    territory_subdivisions: ['FR-38'],
    sector_cpv_prefixes: ['452611'],
  },
}
const OPTIONS = {
  zones: [{ code: 'FR-38', label: 'Isère', country: 'FR' }, { code: 'FR-69', label: 'Rhône', country: 'FR' }],
  sectors: [{ prefix: '45', label: 'Travaux de construction' }],
}
const INCOMPLETE = { ...ME, onboarding_status: 'icp_incomplete' as const, provisional_profile: true }
function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output> }
function setup(profiles: TargetIcp[] = [PROFILE], routes: Routes = {}, search = '') {
  mockApi({
    'GET /target-icps': { body: profiles },
    'GET /target-icps/options': { body: OPTIONS },
    'GET /me': { body: ME },
    ...routes,
  })
  return renderApp(<><AppRoutes /><Location /></>, {
    route: `/app/confirm-profile${search}`,
    session: { status: 'authenticated', me: INCOMPLETE },
  })
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('préremplit le département, la famille et les offres dans une page autonome', async () => {
  setup()
  expect(await screen.findByRole('button', { name: 'Retirer Isère · FR-38' })).toBeInTheDocument()
  expect(screen.getByLabelText('Secteur')).toHaveValue('452611')
  expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('Bois et charpente')
  expect(within(screen.getByRole('list', { name: 'Type d’offre : sélection' })).getAllByRole('button')).not.toHaveLength(0)
  expect(screen.getAllByRole('main')).toHaveLength(1)
  expect(screen.queryByText('Personnalisez vos opportunités avec votre profil commercial.')).not.toBeInTheDocument()
  expect(screen.queryByText('Compte à confirmer')).not.toBeInTheDocument()
})

it('préserve les critères obligatoires et ouvre les signaux après confirmation serveur', async () => {
  setup([PROFILE], { [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...PROFILE, status: 'active', provisional: false } } })
  await userEvent.click(await screen.findByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
  expect(callsTo(`/target-icps/${PROFILE.target_icp_id}`, 'PATCH')[0].body).toEqual({
    label: PROFILE.label,
    customer_input: PROFILE.customer_input,
  })
  expect(callsTo('/target-icps')).toHaveLength(0)
})

it('crée un profil exploitable avec un type d’offre explicitement choisi et sans seuil de montant', async () => {
  setup([], { 'POST /target-icps': { body: { ...ICP, status: 'active' } } })
  await userEvent.selectOptions(await screen.findByLabelText('Zone'), 'FR-38')
  await userEvent.selectOptions(screen.getByLabelText('Secteur'), '45')
  await userEvent.type(screen.getByLabelText('Ce que vous vendez'), 'Composants bois')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  expect(await screen.findByText('Sélectionnez au moins un type d’offre.')).toBeInTheDocument()
  expect(callsTo('/target-icps')).toHaveLength(0)
  await userEvent.selectOptions(screen.getByLabelText('Type d’offre'), 'materials_and_components')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
  expect(callsTo('/target-icps')[0].body).toMatchObject({ customer_input: {
    offers: ['materials_and_components'], territories: ['FR'], territory_subdivisions: ['FR-38'],
    sector_cpv_prefixes: ['45'], minimum_contract_value: { currency: 'EUR', minimum_amount: 0 },
  } })
})

it('répare le brouillon laissé par l’ancien formulaire au lieu de créer un doublon', async () => {
  const draft = { ...PROFILE, provisional: false, status: 'draft', customer_input: { ...PROFILE.customer_input, offers: [], minimum_contract_value: null } }
  setup([draft], { [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...PROFILE, status: 'active' } } })
  await userEvent.selectOptions(await screen.findByLabelText('Type d’offre'), 'materials_and_components')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
  expect(callsTo(`/target-icps/${PROFILE.target_icp_id}`, 'PATCH')).toHaveLength(1)
  expect(callsTo('/target-icps')).toHaveLength(0)
})

it('affiche une erreur si le serveur conserve un profil incomplet, sans retour en boucle', async () => {
  setup([PROFILE], { [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...PROFILE, status: 'draft' } } })
  await userEvent.click(await screen.findByRole('button', { name: 'Recevoir mes signaux' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('il reste incomplet')
  expect(screen.getByTestId('location')).toHaveTextContent('/app/confirm-profile')
  expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('Bois et charpente')
})

it('vérifie aussi que la session est activée avant de naviguer', async () => {
  setup([PROFILE], {
    [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...PROFILE, status: 'active' } },
    'GET /me': { body: INCOMPLETE },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Recevoir mes signaux' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Son activation n’a pas abouti')
  expect(screen.getByTestId('location')).toHaveTextContent('/app/confirm-profile')
})

it('reprend après une panne de session sans répéter la création du profil et conserve le plan choisi', async () => {
  let reads = 0
  setup([], {
    'POST /target-icps': { body: { ...ICP, status: 'active' } },
    [`PATCH /target-icps/${ICP.target_icp_id}`]: { body: { ...ICP, status: 'active' } },
    'GET /me': () => ++reads === 1 ? { status: 503 } : { body: ME },
  }, '?plan=pro')
  await userEvent.selectOptions(await screen.findByLabelText('Zone'), 'FR-38')
  await userEvent.selectOptions(screen.getByLabelText('Secteur'), '45')
  await userEvent.selectOptions(screen.getByLabelText('Type d’offre'), 'materials_and_components')
  await userEvent.type(screen.getByLabelText('Ce que vous vendez'), 'Composants bois')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Votre profil est enregistré')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/billing?plan=pro'))
  expect(callsTo('/target-icps')).toHaveLength(1)
  expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(1)
})

it('permet de réessayer le chargement sans présenter de formulaire vide', async () => {
  let reads = 0
  setup([PROFILE], { 'GET /target-icps/options': () => ++reads === 1 ? { status: 503 } : { body: OPTIONS } })
  expect(await screen.findByRole('alert')).toHaveTextContent('Votre profil n’a pas pu être chargé')
  expect(screen.queryByRole('button', { name: 'Recevoir mes signaux' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Réessayer' }))
  expect(await screen.findByRole('button', { name: 'Recevoir mes signaux' })).toBeInTheDocument()
})

it('conserve les autres secteurs existants quand le secteur affiché ne change pas', async () => {
  const multi = { ...PROFILE, customer_input: { ...PROFILE.customer_input, sector_cpv_prefixes: ['452611', '44'] } }
  setup([multi], { [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...multi, status: 'active' } } })
  await userEvent.click(await screen.findByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(callsTo(`/target-icps/${PROFILE.target_icp_id}`, 'PATCH')).toHaveLength(1))
  expect(callsTo(`/target-icps/${PROFILE.target_icp_id}`, 'PATCH')[0].body).toMatchObject({ customer_input: { sector_cpv_prefixes: ['452611', '44'] } })
})

it('remplace la couverture nationale par le département sélectionné et permet de revenir au pays entier', async () => {
  setup([{ ...PROFILE, customer_input: { ...PROFILE.customer_input, territory_subdivisions: [] } }])
  expect(await screen.findByRole('button', { name: 'Retirer France entière' })).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Zone'), 'FR-38')
  expect(screen.queryByRole('button', { name: 'Retirer France entière' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Retirer Isère · FR-38' })).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Zone'), 'FR')
  expect(screen.getByRole('button', { name: 'Retirer France entière' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retirer Isère · FR-38' })).not.toBeInTheDocument()
})

it('permet de compléter un ancien brouillon ayant seulement des corps de métier secondaires', async () => {
  setup([{ ...PROFILE, status: 'draft', customer_input: { ...PROFILE.customer_input, buyer_trades: [], secondary_buyer_trades: ['building_construction'] } }], {
    [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...PROFILE, status: 'active' } },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Recevoir mes signaux' }))
  expect(await screen.findByText('Sélectionnez au moins un corps de métier principal.')).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Corps de métier principaux'), 'building_construction')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
})

it('préserve un pays entier associé à une subdivision d’un autre pays', async () => {
  const mixed = { ...PROFILE, customer_input: { ...PROFILE.customer_input, territories: ['FR', 'CH'], territory_subdivisions: ['CH-VD'] } }
  setup([mixed], { [`PATCH /target-icps/${PROFILE.target_icp_id}`]: { body: { ...mixed, status: 'active' } } })
  expect(await screen.findByRole('button', { name: 'Retirer France entière' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Retirer CH-VD' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
  await waitFor(() => expect(callsTo(`/target-icps/${PROFILE.target_icp_id}`, 'PATCH')).toHaveLength(1))
  expect(callsTo(`/target-icps/${PROFILE.target_icp_id}`, 'PATCH')[0].body).toMatchObject({ customer_input: { territories: ['CH', 'FR'], territory_subdivisions: ['CH-VD'] } })
})
