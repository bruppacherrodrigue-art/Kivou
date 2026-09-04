import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { useState } from 'react'
import { describe, expect, it, afterEach, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import type { TargetIcpInput } from '../api/types'
import { useSession } from '../auth/SessionProvider'
import { fr } from '../i18n/fr'
import { withRenderableSpaces } from '../i18n'
import {
  UnknownTargetingToken,
  toTargetIcpPayload,
} from '../presentation/dashboard/targetingInput'
import { OnboardingFlow } from '../presentation/dashboard/OnboardingFlow'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  ME,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

/* SPEC-015 §49 — onboarding et gestion des profils.
 * P0-02 — la mise en route en trois temps, et son moment le plus coûteux :
 * un profil cible enregistré que le client ne sait pas enregistré. */

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const INCOMPLETE_ME = { ...ME, onboarding_status: 'account_created' as const }
const CROSS_ACCOUNT_A = {
  ...INCOMPLETE_ME,
  user_id: 'usr_cross_a',
  email: 'a@cross-account.test',
  account_id: 'acc_cross_a',
  account_display_name: 'Compte A',
}
const CROSS_ACCOUNT_B = {
  ...INCOMPLETE_ME,
  user_id: 'usr_cross_b',
  email: 'b@cross-account.test',
  account_id: 'acc_cross_b',
  account_display_name: 'Compte B',
}
const CROSS_ACCOUNT_B_READY = {
  ...CROSS_ACCOUNT_B,
  onboarding_status: 'ready_for_signals' as const,
}

const REFERENCE_DRAFT = {
  name: 'Matériaux — Occitanie',
  offer: 'Fourniture de matériaux pour les chantiers publics',
  precision: 'Livraison rapide sur les chantiers routiers',
  companies: 'Routes et génie civil',
  territory: 'France',
  terms: 'Matériaux et composants',
  minAmount: '50000',
  currency: 'EUR',
}

describe('adaptation stricte du profil cible de référence', () => {
  it('mappe uniquement les libellés localisés et préserve les deux textes de l’offre', () => {
    expect(toTargetIcpPayload(REFERENCE_DRAFT, fr)).toEqual({
      label: 'Matériaux — Occitanie',
      customer_input: {
        offer_summary:
          'Fourniture de matériaux pour les chantiers publics\n\nLivraison rapide sur les chantiers routiers',
        offers: ['materials_and_components'],
        secondary_offers: [],
        buyer_trades: ['roads_and_civil_works'],
        secondary_buyer_trades: [],
        territories: ['FR'],
        minimum_contract_value: {
          currency: 'EUR',
          minimum_amount: 50000,
          maximum_amount: null,
        },
      },
    })
  })

  it('accepte aussi les codes machine et les libellés anglais sans inférer de prose', () => {
    expect(
      toTargetIcpPayload(
        {
          ...REFERENCE_DRAFT,
          companies: 'roads_and_civil_works',
          territory: 'Germany',
          terms: 'materials_and_components',
          precision: '',
        },
        fr,
      ).customer_input,
    ).toMatchObject({
      offer_summary: 'Fourniture de matériaux pour les chantiers publics',
      offers: ['materials_and_components'],
      buyer_trades: ['roads_and_civil_works'],
      territories: ['DE'],
    })
  })

  it('préserve les champs secondaires et le maximum antérieurs en remplaçant les champs visibles', () => {
    const previous: TargetIcpInput = {
      offer_summary: 'Ancienne offre',
      offers: ['equipment_rental'],
      secondary_offers: ['transport_and_logistics', 'safety_equipment'],
      buyer_trades: ['building_construction'],
      secondary_buyer_trades: ['rail_infrastructure', 'equipment_hire'],
      territories: ['CH'],
      minimum_contract_value: {
        currency: 'EUR',
        minimum_amount: 1000,
        maximum_amount: 900000,
      },
    }

    expect(toTargetIcpPayload(REFERENCE_DRAFT, fr, previous)).toEqual({
      label: 'Matériaux — Occitanie',
      customer_input: {
        offer_summary:
          'Fourniture de matériaux pour les chantiers publics\n\nLivraison rapide sur les chantiers routiers',
        offers: ['materials_and_components'],
        secondary_offers: ['transport_and_logistics', 'safety_equipment'],
        buyer_trades: ['roads_and_civil_works'],
        secondary_buyer_trades: ['rail_infrastructure', 'equipment_hire'],
        territories: ['FR'],
        minimum_contract_value: {
          currency: 'EUR',
          minimum_amount: 50000,
          maximum_amount: 900000,
        },
      },
    })
  })

  it('échoue fermé plutôt que de préserver un maximum exprimé dans une autre devise', () => {
    const previous: TargetIcpInput = {
      offer_summary: 'Ancienne offre',
      offers: ['equipment_rental'],
      secondary_offers: [],
      buyer_trades: ['building_construction'],
      secondary_buyer_trades: [],
      territories: ['CH'],
      minimum_contract_value: {
        currency: 'CHF',
        minimum_amount: 1000,
        maximum_amount: 900000,
      },
    }

    expect(() => toTargetIcpPayload(REFERENCE_DRAFT, fr, previous)).toThrowError(
      expect.objectContaining<Partial<UnknownTargetingToken>>({ field: 'threshold' }),
    )
  })

  it('échoue fermé quand le nouveau minimum dépasse le maximum préservé', () => {
    const previous: TargetIcpInput = {
      offer_summary: 'Ancienne offre',
      offers: ['equipment_rental'],
      secondary_offers: [],
      buyer_trades: ['building_construction'],
      secondary_buyer_trades: [],
      territories: ['CH'],
      minimum_contract_value: {
        currency: 'EUR',
        minimum_amount: 1000,
        maximum_amount: 40000,
      },
    }

    expect(() => toTargetIcpPayload(REFERENCE_DRAFT, fr, previous)).toThrowError(
      expect.objectContaining<Partial<UnknownTargetingToken>>({ field: 'threshold' }),
    )
  })

  it('déduplique les codes résolus après normalisation en préservant leur ordre', () => {
    const payload = toTargetIcpPayload(
      {
        ...REFERENCE_DRAFT,
        terms:
          'Matériaux et composants, materials_and_components, Location de matériel, equipment_rental',
        companies:
          'Routes et génie civil, roads_and_civil_works, Bâtiment, building_construction',
        territory: 'France, FR, Germany, Allemagne, DE',
      },
      fr,
    )

    expect(payload.customer_input.offers).toEqual([
      'materials_and_components',
      'equipment_rental',
    ])
    expect(payload.customer_input.buyer_trades).toEqual([
      'roads_and_civil_works',
      'building_construction',
    ])
    expect(payload.customer_input.territories).toEqual(['FR', 'DE'])
  })

  it.each([
    ['offers', { terms: 'portes sur mesure' }],
    ['buyer_trades', { companies: 'entreprises qui achètent des portes' }],
    ['territories', { territory: 'Bavière' }],
    ['threshold', { minAmount: '-1' }],
    ['threshold', { minAmount: '' }],
    ['threshold', { currency: 'USD' }],
  ] as const)('échoue fermé sur un jeton inconnu de %s', (field, change) => {
    expect(() =>
      toTargetIcpPayload({ ...REFERENCE_DRAFT, ...change }, fr),
    ).toThrowError(expect.objectContaining<Partial<UnknownTargetingToken>>({ field }))
  })
})

type User = ReturnType<typeof userEvent.setup>

const readHexToken = (css: string, name: string): string => {
  const value = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`, 'i'))?.[1]
  if (!value) throw new Error(`Token hexadécimal introuvable : --${name}`)
  return value
}

const relativeLuminance = (hex: string): number => {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    ?.map((channel) => Number.parseInt(channel, 16))
  if (!channels || channels.length !== 3) throw new Error(`Couleur hexadécimale invalide : ${hex}`)

  const [red, green, blue] = channels.map((channel) => {
    const srgb = channel / 255
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

const contrastRatio = (foreground: string, background: string): number => {
  const foregroundLuminance = relativeLuminance(foreground)
  const backgroundLuminance = relativeLuminance(background)
  const lighter = Math.max(foregroundLuminance, backgroundLuminance)
  const darker = Math.min(foregroundLuminance, backgroundLuminance)
  return (lighter + 0.05) / (darker + 0.05)
}

const ACTIVATED_ROUTES = {
  'POST /target-icps': { status: 201, body: ICP },
  'GET /me': { body: ME },
  'GET /signals': { body: feedPage([]) },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

/** Remplit les quatre étapes exactes de la référence et s'arrête sur la reanalyse. */
async function fillTargeting(
  user: User,
  {
    label = 'Matériaux — Occitanie',
    terms = 'Matériaux et composants',
    offer = 'Fourniture de matériaux pour les chantiers publics',
    precision = 'Livraison rapide sur les chantiers routiers',
  }: { label?: string; terms?: string; offer?: string; precision?: string } = {},
) {
  await user.type(
    await screen.findByLabelText('Produits et services proposés'),
    offer,
  )
  await user.type(screen.getByLabelText(/Précision utile/), precision)
  await user.click(screen.getByRole('button', { name: 'Continuer' }))

  await user.type(await screen.findByLabelText('Entreprises recherchées'), 'Routes et génie civil')
  await user.type(screen.getByLabelText('Territoire couvert'), 'France')
  await user.type(screen.getByLabelText('Mots-clés à surveiller'), terms)
  await user.click(screen.getByRole('button', { name: 'Continuer' }))

  await user.type(await screen.findByLabelText('Montant minimum du marché'), '50000')
  await user.selectOptions(screen.getByLabelText('Devise'), 'EUR')
  await user.type(screen.getByLabelText('Nom du profil'), label)
  await user.click(screen.getByRole('button', { name: 'Continuer' }))

  await screen.findByRole('heading', { name: 'Vérifier le profil cible' })
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

function OnboardingLeaveHarness() {
  const [visible, setVisible] = useState(true)
  const navigate = useNavigate()
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setVisible(false)
          navigate('/left')
        }}
      >
        Quitter l’onboarding
      </button>
      {visible ? <OnboardingFlow /> : <p>Onboarding quitté</p>}
      <LocationProbe />
    </>
  )
}

function OnboardingQueryChanger() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/onboarding?plan=pro')}>
        Choisir Pro
      </button>
      <OnboardingFlow />
      <LocationProbe />
    </>
  )
}

function OnboardingRemountHarness() {
  const [visible, setVisible] = useState(true)
  const navigate = useNavigate()
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setVisible((current) => !current)
          navigate(visible ? '/left' : '/onboarding')
        }}
      >
        {visible ? 'Quitter l’onboarding' : 'Reprendre l’onboarding'}
      </button>
      {visible ? <OnboardingFlow /> : <p>Onboarding quitté</p>}
      <LocationProbe />
    </>
  )
}

function OnboardingAccountSwitcher() {
  const { state, refresh } = useSession()
  const accountId = state.status === 'authenticated' ? state.me.account_id : state.status
  return (
    <>
      <button type="button" onClick={() => void refresh()}>
        Relire le compte
      </button>
      <output data-testid="account-id">{accountId}</output>
      <OnboardingFlow />
      <LocationProbe />
    </>
  )
}

describe('onboarding', () => {
  it('confirme le profil provisoire en une page avec les trois champs préremplis', async () => {
    const provisional = {
      ...ICP,
      provisional: true,
      label: 'Travaux de construction de bâtiments scolaires',
      customer_input: {
        ...ICP.customer_input,
        offer_summary: 'Travaux de construction de bâtiments scolaires',
        territories: ['CH'],
        territory_subdivisions: ['CH-LU'],
        sector_cpv_prefixes: ['45'],
      },
    }
    const landingMe = {
      ...INCOMPLETE_ME,
      account_display_name: 'Compte à confirmer',
      onboarding_status: 'icp_incomplete' as const,
    }
    mockApi({
      'GET /target-icps': { body: [provisional] },
      'GET /target-icps/options': { body: {
        zones: [
          { code: 'CH-LU', label: 'Lucerne', country: 'CH' },
          { code: 'CH-VD', label: 'Vaud', country: 'CH' },
        ],
        sectors: [
          { prefix: '45', label: 'Travaux de construction' },
          { prefix: '71', label: 'Services d’architecture' },
        ],
      } },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: { body: { ...provisional, status: 'active' } },
      'GET /me': { body: { ...landingMe, onboarding_status: 'ready_for_signals' } },
      'GET /dashboard': { body: { as_of: '2026-09-04', last_seen_at: null, new_since_last_visit: 1, strong_matches: 1, top3: [UNLOCKED_ITEM], to_follow_up: [], to_follow_up_truncated: false, week: { new: 1, saved: 0, contacted: 0, replied: 0 }, scan_truncated: false, profile: { name: 'Paysage', sector_label: 'Travaux paysagers', zone_labels: ['CH-LU'] }, plan: { name: 'Découverte', opened: 0, quota: 3, period_end: null } } },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: landingMe },
      route: '/onboarding',
    })

    expect((await screen.findByRole('option', { name: 'Lucerne (CH-LU)' }) as HTMLOptionElement).selected).toBe(true)
    expect(screen.getByLabelText('Secteur')).toHaveValue('45')
    expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('Travaux de construction de bâtiments scolaires')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
    await waitFor(() => expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(1))
    expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')[0].body).toMatchObject({
      customer_input: {
        territories: ['CH'],
        territory_subdivisions: ['CH-LU'],
        sector_cpv_prefixes: ['45'],
      },
    })
  })

  it('enregistre les choix contrôlés de zone et de secteur du profil provisoire', async () => {
    const provisional = {
      ...ICP,
      provisional: true,
      customer_input: {
        ...ICP.customer_input,
        offer_summary: 'Conseil en architecture',
        territories: ['CH'],
        territory_subdivisions: ['CH-LU'],
        sector_cpv_prefixes: ['45'],
      },
    }
    const landingMe = { ...INCOMPLETE_ME, onboarding_status: 'icp_incomplete' as const }
    mockApi({
      'GET /target-icps': { body: [provisional] },
      'GET /target-icps/options': { body: {
        zones: [
          { code: 'CH-LU', label: 'Lucerne', country: 'CH' },
          { code: 'CH-VD', label: 'Vaud', country: 'CH' },
        ],
        sectors: [
          { prefix: '45', label: 'Travaux de construction' },
          { prefix: '71', label: 'Services d’architecture' },
        ],
      } },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: { body: { ...provisional, status: 'active' } },
      'GET /me': { body: { ...landingMe, onboarding_status: 'ready_for_signals' } },
      'GET /dashboard': { body: { as_of: '2026-09-04', last_seen_at: null, new_since_last_visit: 1, strong_matches: 1, top3: [UNLOCKED_ITEM], to_follow_up: [], to_follow_up_truncated: false, week: { new: 1, saved: 0, contacted: 0, replied: 0 }, scan_truncated: false, profile: { name: 'Architecture', sector_label: 'Services d’architecture', zone_labels: ['Vaud'] }, plan: { name: 'Découverte', opened: 0, quota: 3, period_end: null } } },
    })
    renderApp(<AppRoutes />, { session: { status: 'authenticated', me: landingMe }, route: '/onboarding' })

    await screen.findByRole('option', { name: 'Vaud (CH-VD)' })
    const user = userEvent.setup()
    await user.deselectOptions(screen.getByLabelText('Zone'), ['CH-LU'])
    await user.selectOptions(screen.getByLabelText('Zone'), ['CH-VD'])
    await user.selectOptions(screen.getByLabelText('Secteur'), '71')
    await user.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))
    await waitFor(() => expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(1))
    expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')[0].body).toMatchObject({
      label: 'Services d’architecture',
      customer_input: { territories: ['CH'], territory_subdivisions: ['CH-VD'], sector_cpv_prefixes: ['71'] },
    })
  })

  it('dirige un compte incomplet vers l’onboarding depuis une route applicative', async () => {
    mockApi({ 'GET /target-icps': { body: [] } })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    expect(
      await screen.findByRole('heading', { name: 'Définir ce que Kivou doit surveiller' }),
    ).toBeInTheDocument()
    const note = screen.getByRole('note')
    expect(note).toHaveClass('prototype-notice')
    expect(note).toHaveTextContent('Le profil cible sera enregistré dans votre compte Kivou')
  })

  it('pose les questions dans les quatre étapes exactes, sous un seul h1', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    // Un seul titre de page ; les étapes sont des sous-titres.
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Que vendez-vous ?' }),
    ).toBeInTheDocument()

    await user.type(screen.getByLabelText('Produits et services proposés'), 'Matériaux')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Quel marché recherchez-vous ?' }),
    ).toBeInTheDocument()

    await user.type(screen.getByLabelText('Entreprises recherchées'), 'Routes et génie civil')
    await user.type(screen.getByLabelText('Territoire couvert'), 'France')
    await user.type(screen.getByLabelText('Mots-clés à surveiller'), 'Matériaux et composants')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Quel seuil mérite votre attention ?' }),
    ).toBeInTheDocument()

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('signale la progression exacte sans rendre les étapes cliquables', async () => {
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    const progress = await screen.findByRole('progressbar')
    expect(progress).toHaveAttribute('aria-valuenow', '25')
    const region = progress.closest('.onboarding-progress') as HTMLElement
    expect(region).toHaveAccessibleName('Étape 1 sur 4')
    expect(region).toHaveTextContent('Votre offre')
    expect(within(region).queryByRole('link')).not.toBeInTheDocument()
    expect(within(region).queryByRole('button')).not.toBeInTheDocument()
  })

  it('laisse le bouton utilisable et explique ce qui manque, sans jargon moteur', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    // Le bouton n'est pas désactivé sans explication (§13) : il répond.
    const next = await screen.findByRole('button', { name: 'Continuer' })
    expect(next).toBeEnabled()
    await user.click(next)

    const notice = await screen.findByRole('alert')
    expect(notice).toHaveTextContent('Décrivez ce que vous proposez')
    // L'étape n'a pas avancé.
    expect(
      screen.getByRole('heading', { level: 2, name: 'Que vendez-vous ?' }),
    ).toBeInTheDocument()

    // L'erreur disparaît dès que la saisie la lève.
    await user.type(screen.getByLabelText('Produits et services proposés'), 'Matériaux')
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())

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

  it('déplace le focus sur le titre de la nouvelle étape, en avant comme en arrière', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await user.type(await screen.findByLabelText('Produits et services proposés'), 'Matériaux')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))

    const second = await screen.findByRole('heading', { level: 2, name: 'Quel marché recherchez-vous ?' })
    await waitFor(() => expect(second).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Retour' }))
    const first = await screen.findByRole('heading', { level: 2, name: 'Que vendez-vous ?' })
    await waitFor(() => expect(first).toHaveFocus())
  })

  it('conserve la devise et le montant quand leur groupe cesse d’être visible', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await user.type(await screen.findByLabelText('Produits et services proposés'), 'Matériaux')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))
    await user.type(await screen.findByLabelText('Entreprises recherchées'), 'Routes et génie civil')
    await user.type(screen.getByLabelText('Territoire couvert'), 'France')
    await user.type(screen.getByLabelText('Mots-clés à surveiller'), 'Matériaux et composants')
    await user.click(screen.getByRole('button', { name: 'Continuer' }))

    // Une devise choisie AVANT le montant n'a encore aucune représentation dans
    // le modèle : c'est exactement la saisie qu'un démontage effacerait.
    await user.selectOptions(await screen.findByLabelText('Devise'), 'CHF')
    await user.type(screen.getByLabelText('Montant minimum du marché'), '75000')

    await user.click(screen.getByRole('button', { name: 'Retour' }))
    await screen.findByRole('heading', { level: 2, name: 'Quel marché recherchez-vous ?' })
    await user.click(screen.getByRole('button', { name: 'Continuer' }))

    await screen.findByRole('heading', { level: 2, name: 'Quel seuil mérite votre attention ?' })
    expect(screen.getByLabelText('Devise')).toHaveValue('CHF')
    expect(screen.getByLabelText('Montant minimum du marché')).toHaveValue(75000)
  })

  it('relit le profil cible dans les mots du client avant de l’enregistrer', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)

    expect(screen.getByText('Matériaux et composants')).toBeInTheDocument()
    const territoryRow = screen.getByText('Territoire').closest('div')!
    expect(territoryRow).toHaveTextContent('France')
    expect(territoryRow).not.toHaveTextContent(/\bFR\b/)
    expect(screen.getByText('Entreprises').closest('div')).toHaveTextContent('Routes et génie civil')
    expect(screen.getByText('Précision').closest('div')).toHaveTextContent(
      'Livraison rapide sur les chantiers routiers',
    )
    expect(screen.queryByLabelText('Montant minimum du marché')).not.toBeInTheDocument()
  })

  it('crée un profil valide et n’envoie jamais d’account_id', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

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
    // Les champs secondaires existent au contrat mais ne sont pas collectés :
    // ils partent vides plutôt qu'inventés.
    expect(sent.customer_input.secondary_offers).toEqual([])
    expect(sent.customer_input.secondary_buyer_trades).toEqual([])
    expect(sent).not.toHaveProperty('account_id')
    expect(sent.customer_input).not.toHaveProperty('account_id')
  })

  it('rejoint le feed exact sans réintroduire la bannière d’activation supprimée', async () => {
    const user = userEvent.setup()
    mockApi({
      ...ACTIVATED_ROUTES,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

    expect(await screen.findByRole('heading', { name: 'Signaux' })).toBeInTheDocument()
    expect(await screen.findByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    expect(screen.queryByText(/signaux sont accessibles avec votre profil/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Voir mon premier signal' })).not.toBeInTheDocument()
  })

  it('aucune requête du frontend ne porte d’account_id', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user, { label: 'Test' })
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    for (const call of recordedCalls) {
      expect(JSON.stringify(call.body ?? {})).not.toContain('account_id')
      expect(call.url).not.toContain('account_id')
      expect(call.search.get('account_id')).toBeNull()
    }
  })

  it('refuse un libellé de profil cible inconnu localement sans appeler l’API', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user, { terms: 'portes sur mesure' })
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '« portes sur mesure » ne correspond à aucun type d’offre proposé',
    )
    expect(screen.getByRole('heading', { name: 'Quel marché recherchez-vous ?' })).toBeVisible()
    expect(callsTo('/target-icps')).toHaveLength(0)
    expect(callsTo('/me')).toHaveLength(0)
  })

  it('porte une offre payante uniquement dans l’URL jusqu’au checkout', async () => {
    const user = userEvent.setup()
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    mockApi({
      ...ACTIVATED_ROUTES,
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      {
        session: { status: 'authenticated', me: INCOMPLETE_ME },
        route: '/onboarding?plan=pro',
      },
    )

    await fillTargeting(user)
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/checkout?plan=pro'),
    )
    expect(storage).not.toHaveBeenCalled()
  })

  it('conserve la création pendant un changement de plan et ne rejoue jamais le POST', async () => {
    const user = userEvent.setup()
    let release!: (value: { status: number; body: typeof ICP }) => void
    const response = new Promise<{ status: number; body: typeof ICP }>((resolve) => {
      release = resolve
    })
    mockApi({
      'POST /target-icps': () => response,
      'GET /me': { body: ME },
    })
    renderApp(<OnboardingQueryChanger />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding?plan=discovery',
    })

    await fillTargeting(user)
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))
    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    await user.click(screen.getByRole('button', { name: 'Choisir Pro' }))
    const repeatedSubmit = screen.getByRole('button', {
      name: 'Enregistrer et voir les signaux',
    })
    expect(repeatedSubmit).toBeDisabled()
    fireEvent.click(repeatedSubmit)
    expect(callsTo('/target-icps')).toHaveLength(1)

    await act(async () => {
      release({ status: 201, body: ICP })
      await response
    })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(1))
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/checkout?plan=pro'),
    )
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(callsTo('/me', 'GET')).toHaveLength(1)
  })

  it('isole le POST du compte B quand le compte change pendant la création du compte A', async () => {
    const user = userEvent.setup()
    let releaseA!: (value: { status: number; body: typeof ICP }) => void
    let releaseB!: (value: { status: number; body: typeof ICP }) => void
    const responseA = new Promise<{ status: number; body: typeof ICP }>((resolve) => {
      releaseA = resolve
    })
    const responseB = new Promise<{ status: number; body: typeof ICP }>((resolve) => {
      releaseB = resolve
    })
    let postCalls = 0
    let meCalls = 0
    mockApi({
      'POST /target-icps': () => {
        postCalls += 1
        return postCalls === 1 ? responseA : responseB
      },
      'GET /me': () => {
        meCalls += 1
        if (meCalls === 1) return { body: CROSS_ACCOUNT_B }
        if (meCalls === 2) {
          return { status: 503, body: { detail: { code: 'billing_error' } } }
        }
        return { body: CROSS_ACCOUNT_B_READY }
      },
    })
    renderApp(<OnboardingAccountSwitcher />, {
      session: { status: 'authenticated', me: CROSS_ACCOUNT_A },
      route: '/onboarding',
    })

    await fillTargeting(user, { label: 'Profil cible du compte A' })
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))
    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: 'Relire le compte' }))
    await waitFor(() => expect(screen.getByTestId('account-id')).toHaveTextContent('acc_cross_b'))
    await fillTargeting(user, { label: 'Profil cible du compte B' })
    const submitB = screen.getByRole('button', { name: 'Enregistrer et voir les signaux' })
    await waitFor(() => expect(submitB).toBeEnabled())
    await user.click(submitB)
    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(2))
    expect(submitB).toBeDisabled()

    await act(async () => {
      releaseA({ status: 201, body: { ...ICP, target_icp_id: 'icp_cross_a' } })
      await responseA
    })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(2))

    expect(submitB).toBeDisabled()
    expect(screen.queryByText(/^Votre profil cible a bien été enregistré/)).not.toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/onboarding')

    await act(async () => {
      releaseB({ status: 201, body: { ...ICP, target_icp_id: 'icp_cross_b' } })
      await responseB
    })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(3))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
    expect(callsTo('/target-icps')).toHaveLength(2)
  })

  it('écarte le profil cible du compte A quand son refresh autoritaire retourne le compte B', async () => {
    const user = userEvent.setup()
    let releaseRefreshA!: (value: { body: typeof CROSS_ACCOUNT_B }) => void
    const refreshA = new Promise<{ body: typeof CROSS_ACCOUNT_B }>((resolve) => {
      releaseRefreshA = resolve
    })
    let postCalls = 0
    let meCalls = 0
    mockApi({
      'POST /target-icps': () => {
        postCalls += 1
        return {
          status: 201,
          body: {
            ...ICP,
            target_icp_id: postCalls === 1 ? 'icp_refresh_a' : 'icp_refresh_b',
          },
        }
      },
      'GET /me': () => {
        meCalls += 1
        return meCalls === 1 ? refreshA : { body: CROSS_ACCOUNT_B_READY }
      },
    })
    renderApp(<OnboardingAccountSwitcher />, {
      session: { status: 'authenticated', me: { ...CROSS_ACCOUNT_A, account_id: 'acc_refresh_a' } },
      route: '/onboarding',
    })

    await fillTargeting(user, { label: 'Profil cible avant refresh' })
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))
    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(1))

    await act(async () => {
      releaseRefreshA({ body: { ...CROSS_ACCOUNT_B, account_id: 'acc_refresh_b' } })
      await refreshA
    })
    await waitFor(() => expect(screen.getByTestId('account-id')).toHaveTextContent('acc_refresh_b'))
    expect(screen.getByTestId('location')).toHaveTextContent('/onboarding')
    expect(screen.queryByText(/^Votre profil cible a bien été enregistré/)).not.toBeInTheDocument()

    await fillTargeting(user, { label: 'Profil cible du compte B après refresh' })
    const submitB = screen.getByRole('button', { name: 'Enregistrer et voir les signaux' })
    await waitFor(() => expect(submitB).toBeEnabled())

    await user.click(submitB)

    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(2))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
    expect(callsTo('/target-icps')).toHaveLength(2)
  })

  it('efface tout le brouillon du compte A avant que le compte B puisse créer le sien', async () => {
    const user = userEvent.setup()
    const accountA = {
      ...CROSS_ACCOUNT_A,
      account_id: 'acc_private_draft_a',
      account_display_name: 'Compte confidentiel A',
    }
    const accountB = {
      ...CROSS_ACCOUNT_B,
      account_id: 'acc_private_draft_b',
      account_display_name: 'Compte privé B',
    }
    const accountBReady = {
      ...accountB,
      onboarding_status: 'ready_for_signals' as const,
    }
    let releaseA!: (value: { status: number; body: typeof ICP }) => void
    const responseA = new Promise<{ status: number; body: typeof ICP }>((resolve) => {
      releaseA = resolve
    })
    let postCalls = 0
    let meCalls = 0
    mockApi({
      'POST /target-icps': () => {
        postCalls += 1
        return postCalls === 1
          ? responseA
          : { status: 201, body: { ...ICP, target_icp_id: 'icp_private_draft_b' } }
      },
      'GET /me': () => {
        meCalls += 1
        if (meCalls === 1) return { body: accountB }
        if (meCalls === 2) {
          return { status: 503, body: { detail: { code: 'billing_error' } } }
        }
        return { body: accountBReady }
      },
    })
    renderApp(<OnboardingAccountSwitcher />, {
      session: { status: 'authenticated', me: accountA },
      route: '/onboarding?plan=discovery',
    })

    await fillTargeting(user, {
      label: 'Profil strictement confidentiel A',
      offer: 'Offre strictement confidentielle du compte A',
      precision: 'Précision confidentielle réservée au compte A',
    })
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))
    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: 'Relire le compte' }))
    await waitFor(() =>
      expect(screen.getByTestId('account-id')).toHaveTextContent('acc_private_draft_b'),
    )

    expect(screen.getByText('Étape 1 sur 4')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Que vendez-vous ?' })).toBeVisible()
    expect(screen.getByLabelText('Produits et services proposés')).toHaveValue('')
    expect(screen.getByLabelText(/Précision utile/)).toHaveValue('')
    expect(screen.queryByText('Profil strictement confidentiel A')).not.toBeInTheDocument()
    expect(screen.queryByText('Offre strictement confidentielle du compte A')).not.toBeInTheDocument()

    await act(async () => {
      releaseA({ status: 201, body: { ...ICP, target_icp_id: 'icp_private_draft_a' } })
      await responseA
    })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(2))

    expect(screen.getByText('Étape 1 sur 4')).toBeVisible()
    expect(screen.getByLabelText('Produits et services proposés')).toHaveValue('')
    expect(screen.queryByText(/^Votre profil cible a bien été enregistré/)).not.toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/onboarding?plan=discovery')

    await user.click(screen.getByRole('button', { name: 'Continuer' }))
    expect(await screen.findByText('Décrivez ce que vous proposez pour continuer.')).toBeVisible()
    expect(callsTo('/target-icps')).toHaveLength(1)

    await fillTargeting(user, {
      label: 'Profil propre au compte B',
      offer: 'Offre propre au compte B',
      precision: 'Précision propre au compte B',
    })
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))

    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(2))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
    const sentByB = callsTo('/target-icps')[1].body
    expect(sentByB).toMatchObject({
      label: 'Profil propre au compte B',
      customer_input: {
        offer_summary: 'Offre propre au compte B\n\nPrécision propre au compte B',
      },
    })
    expect(JSON.stringify(sentByB)).not.toContain('compte A')
    expect(callsTo('/target-icps')).toHaveLength(2)
  })

  it('garde le reset de compte dans un layout effect pré-affichage — jsdom ne modélise pas la peinture', () => {
    // Le scénario précédent couvre le résultat observable. Comme jsdom n'a
    // pas de phase de peinture, ce garde-fou structurel garantit que le reset
    // du brouillon et de l'étape reste synchrone avant le prochain affichage.
    const source = readFileSync(
      join(process.cwd(), 'src/presentation/dashboard/OnboardingFlow.tsx'),
      'utf8',
    )

    expect(source).toMatch(
      /useLayoutEffect\(\(\) => \{[\s\S]*?setDraft\(initialDraft\)[\s\S]*?setStep\(0\)[\s\S]*?\}, \[currentAccountId\]\)/,
    )
  })

  it('réconcilie la session sans rediriger ni mettre à jour la surface quittée', async () => {
    const user = userEvent.setup()
    let release!: (value: { status: number; body: typeof ICP }) => void
    const response = new Promise<{ status: number; body: typeof ICP }>((resolve) => {
      release = resolve
    })
    mockApi({
      'POST /target-icps': () => response,
      'GET /me': { body: ME },
    })
    renderApp(<OnboardingLeaveHarness />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))
    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    await user.click(screen.getByRole('button', { name: 'Quitter l’onboarding' }))

    await act(async () => {
      release({ status: 201, body: ICP })
      await response
    })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(1))
    expect(screen.getByTestId('location')).toHaveTextContent('/left')
    expect(screen.getByText('Onboarding quitté')).toBeVisible()
  })

  it('reste sur la reanalyse et explique une erreur réseau avant toute création réussie', async () => {
    const user = userEvent.setup()
    mockApi({
      ...ACTIVATED_ROUTES,
      'POST /target-icps': { status: 503, body: { detail: { code: 'billing_error' } } },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

    expect(await screen.findByText(/^Une erreur est survenue/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Vérifier le profil cible' })).toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(callsTo('/me')).toHaveLength(0)
  })

  it('reste sur la reanalyse et affiche la limite territoriale fournie par le serveur', async () => {
    const user = userEvent.setup()
    mockApi({
      ...ACTIVATED_ROUTES,
      'POST /target-icps': {
        status: 422,
        body: {
          detail: {
            code: 'territory_limit_exceeded',
            limit: 1,
            territory_count: 2,
            plan_code: 'discovery',
          },
        },
      },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))

    expect(await screen.findByText(/^Limite territoriale atteinte/)).toBeInTheDocument()
    expect(document.body).toHaveTextContent(
      'Votre offre autorise 1 territoire par profil. Réduisez votre sélection pour enregistrer ce profil cible.',
    )
    expect(screen.getByRole('heading', { name: 'Vérifier le profil cible' })).toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(callsTo('/me')).toHaveLength(0)
  })
})

describe('succès partiel — profil cible enregistré, session non relue', () => {
  it('réutilise la création après démontage et échec de réconciliation', async () => {
    const user = userEvent.setup()
    let meCalls = 0
    mockApi({
      'POST /target-icps': { status: 201, body: ICP },
      'GET /me': () => {
        meCalls += 1
        return meCalls === 1
          ? { status: 503, body: { detail: { code: 'billing_error' } } }
          : { body: ME }
      },
    })
    renderApp(<OnboardingRemountHarness />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))
    expect(await screen.findByText(/^Votre profil cible a bien été enregistré/)).toBeVisible()
    expect(callsTo('/target-icps')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Quitter l’onboarding' }))
    await user.click(screen.getByRole('button', { name: 'Reprendre l’onboarding' }))
    await fillTargeting(user)
    await user.click(screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals'))
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(meCalls).toBe(2)
  })

  it('ne rejoue jamais le POST : le retry ne refait que la finalisation', async () => {
    const user = userEvent.setup()
    let meCalls = 0
    mockApi({
      ...ACTIVATED_ROUTES,
      'GET /me': () => {
        meCalls += 1
        // La première reanalyse tombe sur une indisponibilité du serveur.
        return meCalls === 1
          ? { status: 503, body: { detail: { code: 'billing_error' } } }
          : { body: ME }
      },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    await user.click(
      screen.getByRole('button', { name: 'Enregistrer et voir les signaux' }),
    )

    // Le profil cible a bien été enregistré : le dire autrement serait faux, et
    // pousserait le client à recommencer une saisie qui existe déjà.
    const notice = await screen.findByText(/^Votre profil cible a bien été enregistré/)
    expect(notice).toHaveTextContent(/n’a pas pu finaliser/)
    expect(document.body.textContent).not.toMatch(/création du profil cible a échoué/i)
    // La session tient : une panne serveur n'est pas une déconnexion.
    expect(screen.queryByRole('heading', { name: 'Se connecter' })).not.toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Finaliser et voir mes signaux' }))

    expect(await screen.findByRole('heading', { name: 'Signaux' })).toBeInTheDocument()
    // Le point capital : UN seul profil a été créé, malgré deux tentatives.
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(meCalls).toBe(2)
  })

  it('ne crée pas un second profil sur deux envois rapprochés', async () => {
    let releasePost = () => {}
    const gate = new Promise<void>((resolve) => {
      releasePost = resolve
    })
    const seen: string[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        const method = (init?.method ?? 'GET').toUpperCase()
        seen.push(`${method} ${url.pathname}`)

        const json = (body: unknown, status = 200) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { 'Content-Type': 'application/json' },
          })

        if (method === 'POST' && url.pathname === '/target-icps') {
          // La création reste en vol : c'est la fenêtre du double-clic.
          await gate
          return json(ICP, 201)
        }
        if (url.pathname === '/me') return json(ME)
        if (url.pathname === '/signals') return json(feedPage([]))
        if (url.pathname === '/billing/status') return json(DISCOVERY_STATUS)
        if (url.pathname === '/target-icps') return json([ICP])
        return json({ detail: { code: 'signal_not_found' } }, 404)
      }),
    )

    const user = userEvent.setup()
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)
    const submit = screen.getByRole('button', { name: 'Enregistrer et voir les signaux' })

    // Deux clics dans le même tour de boucle, avant tout nouveau rendu.
    act(() => {
      fireEvent.click(submit)
      fireEvent.click(submit)
    })
    await act(async () => {
      releasePost()
      await gate
    })

    expect(await screen.findByRole('heading', { name: 'Signaux' })).toBeInTheDocument()
    expect(seen.filter((call) => call === 'POST /target-icps')).toHaveLength(1)
  })

  it('renvoie au feed plutôt que de rouvrir un formulaire déjà rempli', async () => {
    // Le remontage qui suit un incident : le serveur sait que l'onboarding est
    // terminé, la page ne doit pas proposer d'en créer un second.
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/onboarding' })

    expect(await screen.findByRole('heading', { name: 'Signaux' })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Définir ce que Kivou doit surveiller' }),
    ).not.toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(0)
  })
})

describe('gestion des profils', () => {
  it('garde les aides de dépassement au-dessus du contraste WCAG AA', () => {
    const css = readFileSync(
      join(process.cwd(), 'src/presentation/dashboard/app-shell.css'),
      'utf8',
    )

    expect(css).toMatch(
      /\.target-demo-message\s*\{[^}]*color:\s*var\(--green\)/s,
    )
    expect(
      contrastRatio(
        readHexToken(css, 'green'),
        readHexToken(css, 'surface'),
      ),
    ).toBeGreaterThanOrEqual(4.5)
  })

  it('empile le workspace de référence au breakpoint existant tout en gardant sa grille sur grand écran', () => {
    const css = readFileSync(
      join(process.cwd(), 'src/presentation/dashboard/app-shell.css'),
      'utf8',
    )

    expect(css).toMatch(
      /\.target-profile-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1\.45fr\) minmax\(290px, 0\.7fr\)/s,
    )
    expect(css).toMatch(
      /@media \(max-width: 1279px\)\s*\{[\s\S]*?\.target-profile-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    )
  })

  it('organise les profils en workspace liste + éditeur et focalise le formulaire ouvert', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    expect(await screen.findByRole('heading', { level: 3, name: ICP.label })).toBeVisible()
    expect(document.querySelector('.target-profile-layout .target-definition-card')).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'Modifier le profil' }))
    await waitFor(() => expect(screen.getByLabelText('Nom du profil')).toHaveFocus())
    expect(document.querySelector('form.target-edit-form')).not.toBeNull()
  })

  it('remonte l’éditeur avec les valeurs du profil choisi quand on change de ligne', async () => {
    const user = userEvent.setup()
    const second = { ...ICP, target_icp_id: 'icp_2', label: 'Location — Suisse' }
    mockApi({
      'GET /target-icps': { body: [ICP, second] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    const selector = await screen.findByLabelText('Profil affiché')
    expect(within(selector).getAllByRole('option')).toHaveLength(2)
    await user.selectOptions(selector, second.target_icp_id)
    await user.click(screen.getByRole('button', { name: 'Modifier le profil' }))
    expect(screen.getByLabelText(/Nom du profil/)).toHaveValue(second.label)
  })

  it('rend le focus au bouton Créer après annulation du nouvel éditeur', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.click(screen.getByRole('button', { name: 'Créer un profil' }))
    await user.click(screen.getByRole('button', { name: 'Annuler' }))

    const restoredTrigger = screen.getByRole('button', { name: 'Créer un profil' })
    await waitFor(() => expect(restoredTrigger).toHaveFocus())
  })

  it('rend le focus au bouton Modifier après une sauvegarde réussie', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'PATCH /target-icps/icp_1': { body: ICP },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    const name = screen.getByLabelText(/Nom du profil/)
    await user.clear(name)
    await user.type(name, 'Matériaux — Sud')
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(callsTo('/target-icps/icp_1', 'PATCH')).toHaveLength(1))

    const restoredTrigger = screen.getByRole('button', { name: 'Modifier le profil' })
    await waitFor(() => expect(restoredTrigger).toHaveFocus())
  })

  it('rend le focus au profil créé depuis l’état vide après la sauvegarde', async () => {
    const user = userEvent.setup()
    const created = {
      ...ICP,
      target_icp_id: 'icp_created',
      label: 'Nouveau profil',
      customer_input: {
        offer_summary: 'Granulats livrés sur chantier',
        offers: ['materials_and_components'] as const,
        secondary_offers: [],
        buyer_trades: ['roads_and_civil_works'] as const,
        secondary_buyer_trades: [],
        territories: ['FR'],
        minimum_contract_value: { currency: 'EUR', minimum_amount: 50000, maximum_amount: null },
      },
    }
    mockApi({
      'GET /target-icps': { body: [] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'POST /target-icps': { status: 201, body: created },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Créer un profil' }))
    await user.type(screen.getByLabelText(/Nom du profil/), created.label)
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats livrés sur chantier')
    await user.type(screen.getByLabelText('Entreprises recherchées'), 'Routes et génie civil')
    await user.type(screen.getByLabelText('Territoire commercial'), 'France')
    await user.type(screen.getByLabelText('Mots-clés surveillés'), 'Matériaux et composants')
    await user.type(screen.getByLabelText('Montant minimum du marché'), '50000')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await waitFor(() => expect(callsTo('/target-icps', 'POST')).toHaveLength(1))
    expect(callsTo('/target-icps', 'POST')[0].body).toEqual({
      label: created.label,
      customer_input: created.customer_input,
    })
    const restoredTrigger = await screen.findByRole('button', { name: 'Modifier le profil' })
    await waitFor(() => expect(restoredTrigger).toHaveFocus())
  })

  it('annonce honnêtement le chargement initial des profils', () => {
    const pending = new Promise<never>(() => {})
    mockApi({
      'GET /target-icps': () => pending,
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    const { unmount } = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/app/icps',
    })

    expect(screen.getByRole('status', { name: 'Chargement…' })).toBeInTheDocument()
    unmount()
  })

  it('rend une erreur de chargement relançable sans masquer le titre de page', async () => {
    let profileCalls = 0
    mockApi({
      'GET /target-icps': () => {
        profileCalls += 1
        return profileCalls <= 1
          ? { status: 503, body: { detail: { code: 'billing_error' } } }
          : { body: [ICP] }
      },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    const page = document.querySelector('.target-profile-main') as HTMLElement
    expect(await within(page).findByRole('alert')).toHaveTextContent('Le profil cible n’a pas pu être chargé')
    expect(screen.getByRole('heading', { level: 1, name: 'Profil cible' })).toBeInTheDocument()
    await userEvent.setup().click(within(page).getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByRole('heading', { level: 3, name: ICP.label })).toBeVisible()
    expect(callsTo('/billing/status', 'GET')).toHaveLength(1)
  })

  it('conserve l’éditeur après une erreur de modification et localise l’erreur en anglais', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /signals': { body: feedPage([], { freshness: 'all' }) },
      'PATCH /target-icps/icp_1': {
        status: 503,
        body: { detail: { code: 'billing_error' } },
      },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/icps',
      locale: 'en',
    })

    await user.click(await screen.findByRole('button', { name: 'Edit profile' }))
    await user.type(screen.getByLabelText('What you sell'), 'Real offer')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/The changes could not be saved.*Something went wrong/)).toBeVisible()
    expect(screen.getByLabelText('What you sell')).toHaveValue('Real offer')
    expect(screen.queryByText(/Une erreur|Réessayer|Modifier le profil/)).not.toBeInTheDocument()
  })

  it('localise en anglais la limite territoriale renvoyée à la modification', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /signals': { body: feedPage([], { freshness: 'all' }) },
      'PATCH /target-icps/icp_1': {
        status: 422,
        body: {
          detail: {
            code: 'territory_limit_exceeded',
            limit: 1,
            territory_count: 2,
            plan_code: 'discovery',
          },
        },
      },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/icps',
      locale: 'en',
    })

    await user.click(await screen.findByRole('button', { name: 'Edit profile' }))
    await user.type(screen.getByLabelText('What you sell'), 'Real offer')
    await user.clear(screen.getByLabelText('Sales territory'))
    await user.type(screen.getByLabelText('Sales territory'), 'France, Germany')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/Territory limit reached/)).toBeVisible()
    expect(document.body).toHaveTextContent(
      'Your plan allows 1 territory per profile. Reduce your selection to save this target profile.',
    )
    expect(screen.queryByText(/Limite|Votre offre|territoire par profil/)).not.toBeInTheDocument()
  })

  it('localise les territoires, formate le seuil et affiche la description enregistrée', async () => {
    const described = {
      ...ICP,
      customer_input: {
        ...ICP.customer_input,
        offer_summary: 'Composants bois livrés sur chantier.',
        territories: ['CH', 'ZZ'],
        minimum_contract_value: {
          currency: 'CHF',
          minimum_amount: 75000,
          maximum_amount: null,
        },
      },
    }
    mockApi({
      'GET /target-icps': { body: [described] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await screen.findByRole('heading', { level: 3, name: 'Matériaux — Occitanie' })
    const card = document.querySelector('.target-definition-card') as HTMLElement
    const territories = within(card).getByText('Territoire commercial').closest('div')!
    expect(territories).toHaveTextContent('Suisse, ZZ')
    expect(territories).not.toHaveTextContent(/\bCH\b/)
    const threshold = within(card).getByText('Montant minimum').closest('div')!
    expect(threshold.querySelector('dd')?.textContent).toBe(
      withRenderableSpaces(new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: 'CHF',
        maximumFractionDigits: 0,
      }).format(75000)),
    )
    expect(within(card).getByText('Ce que vous vendez').closest('div')).toHaveTextContent(
      'Composants bois livrés sur chantier.',
    )
  })

  it('rend le même résumé métier en anglais, sans texte français', async () => {
    const described = {
      ...ICP,
      customer_input: {
        ...ICP.customer_input,
        offer_summary: 'Timber components delivered to site.',
        territories: ['CH', 'DE'],
      },
    }
    mockApi({
      'GET /target-icps': { body: [described] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/icps',
      locale: 'en',
    })

    await screen.findByRole('heading', { level: 3, name: 'Matériaux — Occitanie' })
    const card = document.querySelector('.target-definition-card') as HTMLElement
    expect(within(card).getByText('Sales territory').closest('div')).toHaveTextContent(
      'Switzerland, Germany',
    )
    const threshold = within(card).getByText('Minimum amount').closest('div')!
    expect(threshold.querySelector('dd')?.textContent).toBe(
      withRenderableSpaces(new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
      }).format(50000)),
    )
    expect(within(card).getByText('What you sell').closest('div')).toHaveTextContent(
      'Timber components delivered to site.',
    )
    expect(card).not.toHaveTextContent(/Territoire commercial|Montant minimum|Ce que vous vendez/)
  })

  it('masque la description facultative lorsqu’elle est vide', async () => {
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await screen.findByRole('heading', { level: 3, name: 'Matériaux — Occitanie' })
    expect(screen.queryByText('Précision')).not.toBeInTheDocument()
  })

  it('permet de modifier un profil existant', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'PATCH /target-icps/icp_1': { body: { ...ICP, label: 'Matériaux — Sud' } },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    const field = await screen.findByLabelText(/Nom du profil/)
    await user.clear(field)
    await user.type(field, 'Matériaux — Sud')
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await waitFor(() =>
      expect(callsTo('/target-icps/icp_1', 'PATCH')).toHaveLength(1),
    )
  })

  /* P0-02 §16 — la non-régression explicite.
   *
   * L'onboarding et `/app/icps` partagent désormais UN seul composant de
   * champs. Le risque de ce partage est connu : un groupe qui ne serait rendu
   * que pour l'assistant disparaîtrait silencieusement de l'écran d'édition.
   * Ces deux vérifications tiennent la promesse « sans `sections`, le
   * formulaire complet ». */
  it('rend le formulaire ICP complet en édition, sans le transformer en assistant', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    const editor = document.querySelector('form.target-edit-form') as HTMLElement

    // Les champs du profil exact, présents ensemble sur le MÊME écran.
    expect(within(editor).getByLabelText(/Nom du profil/)).toBeInTheDocument()
    expect(within(editor).getByLabelText('Ce que vous vendez')).toBeInTheDocument()
    expect(within(editor).getByLabelText(/Précision utile/)).toBeInTheDocument()
    expect(within(editor).getByLabelText('Entreprises recherchées')).toBeInTheDocument()
    expect(within(editor).getByLabelText('Territoire commercial')).toBeInTheDocument()
    expect(within(editor).getByLabelText('Mots-clés surveillés')).toBeInTheDocument()
    expect(within(editor).getByLabelText('Devise')).toBeInTheDocument()
    expect(within(editor).getByLabelText('Montant minimum du marché')).toBeInTheDocument()

    // Les valeurs existantes sont rendues, pas réinitialisées.
    expect(within(editor).getByLabelText(/Nom du profil/)).toHaveValue('Matériaux — Occitanie')
    expect(within(editor).getByLabelText('Entreprises recherchées')).toHaveValue('Routes et génie civil')
    expect(within(editor).getByLabelText('Territoire commercial')).toHaveValue('France')
    expect(within(editor).getByLabelText('Mots-clés surveillés')).toHaveValue('Matériaux et composants')
    expect(within(editor).getByLabelText('Montant minimum du marché')).toHaveValue(50000)

    // `/app/icps` n'est pas un assistant.
    expect(screen.queryByRole('button', { name: 'Suivant' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Votre mise en route' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Enregistrer' })).toBeInTheDocument()
  })

  it('rend le formulaire complet aussi à la création depuis /app/icps', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await user.click(await screen.findByRole('button', { name: 'Créer un profil' }))

    expect(await screen.findByLabelText(/Nom du profil/)).toBeInTheDocument()
    expect(screen.getByLabelText('Ce que vous vendez')).toBeInTheDocument()
    expect(screen.getByLabelText(/Précision utile/)).toBeInTheDocument()
    expect(screen.getByLabelText('Entreprises recherchées')).toBeInTheDocument()
    expect(screen.getByLabelText('Territoire commercial')).toBeInTheDocument()
    expect(screen.getByLabelText('Mots-clés surveillés')).toBeInTheDocument()
    expect(screen.getByLabelText('Devise')).toBeInTheDocument()
    expect(screen.getByLabelText('Montant minimum du marché')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Suivant' })).not.toBeInTheDocument()
  })

  it('affiche la limite de profils du plan sans supprimer aucun profil', async () => {
    const second = { ...ICP, target_icp_id: 'icp_2', label: 'Location — Suisse' }
    mockApi({
      'GET /target-icps': { body: [ICP, second] },
      'GET /billing/status': {
        body: { ...DISCOVERY_STATUS, target_icps_over_limit: ['icp_2'] },
      },
      'GET /signals': { body: feedPage([], { freshness: 'all' }) },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    const selector = await screen.findByLabelText('Profil affiché')
    expect(within(selector).getAllByRole('option')).toHaveLength(2)
    await userEvent.setup().selectOptions(selector, second.target_icp_id)
    expect(screen.getByRole('heading', { level: 3, name: second.label })).toBeVisible()
    expect(screen.getByText(/Ce profil est conservé mais n’alimente plus votre flux/)).toBeVisible()

    // Aucune action destructive n'est proposée : le backend n'expose pas de DELETE.
    expect(screen.queryByRole('button', { name: /supprimer/i })).not.toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Modifier le profil' })).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/désactivez|supprimez/i)
  })

  it('signale un profil limité territorialement sans tronquer sa saisie', async () => {
    const limited = {
      ...ICP,
      customer_input: {
        ...ICP.customer_input,
        territories: ['CH', 'FR'],
      },
      plan_limit: {
        code: 'territory_limit_exceeded',
        limit: 1,
        territory_count: 2,
      },
    }
    mockApi({
      'GET /target-icps': { body: [limited] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /signals': { body: feedPage([], { freshness: 'all' }) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await screen.findByRole('heading', { level: 3, name: 'Matériaux — Occitanie' })
    const card = document.querySelector('.target-definition-card') as HTMLElement
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Ce profil conserve ses territoires, mais il n’alimente pas votre flux. Sélectionnez au maximum 1 territoire pour le réactiver.',
    )
    expect(within(card).getByText('Territoire commercial').closest('div')).toHaveTextContent('Suisse, France')
    expect(within(card).queryByRole('button', { name: /supprimer/i })).not.toBeInTheDocument()
  })
})
