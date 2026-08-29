import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import type { TargetIcp } from '../api/types'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const PRESERVED_PROFILE: TargetIcp = {
  ...ICP,
  customer_input: {
    ...ICP.customer_input,
    offer_summary: 'Ancienne offre\n\nAncienne précision',
    secondary_offers: ['transport_and_logistics', 'safety_equipment'],
    secondary_buyer_trades: ['rail_infrastructure', 'equipment_hire'],
    minimum_contract_value: {
      currency: 'EUR',
      minimum_amount: 50000,
      maximum_amount: 900000,
    },
  },
}

const shell = {
  'GET /target-icps': { body: [ICP] },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM], { freshness: 'all' }) },
}

describe('profil de ciblage exact connecté au contrat ICP', () => {
  it('rend la composition exacte avec le profil API réel et aucune donnée de démonstration', async () => {
    const storageGet = vi.spyOn(Storage.prototype, 'getItem')
    const storageSet = vi.spyOn(Storage.prototype, 'setItem')
    mockApi(shell)

    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { level: 3, name: ICP.label })).toBeVisible()
    expect(document.querySelector('.target-profile-main .target-profile-layout')).not.toBeNull()
    expect(screen.getByText('Matériaux et composants')).toBeVisible()
    expect(screen.getByText('Routes et génie civil')).toBeVisible()
    expect(screen.getByText('France')).toBeVisible()
    expect(document.querySelector('.target-impact-card .target-example-list')).not.toBeNull()
    expect(await screen.findByText(
      'Très bon pour votre profil, pour un projet situé à Villeneuve, 31270, France.',
    )).toBeVisible()
    expect(document.body.textContent).not.toContain('H. Hüther GmbH')
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(storageGet).not.toHaveBeenCalled()
    expect(storageSet).not.toHaveBeenCalled()
  })

  it('mappe uniquement les tokens explicites et préserve secondaires et maximum au PATCH', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [PRESERVED_PROFILE] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: (request) => ({
        body: {
          ...PRESERVED_PROFILE,
          ...(request.body as object),
        },
      }),
    })

    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.clear(screen.getByLabelText('Ce que vous vendez'))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats et enrobés')
    await user.clear(screen.getByLabelText(/Précision utile/))
    await user.type(screen.getByLabelText(/Précision utile/), 'Livraison rapide')
    await user.clear(screen.getByLabelText('Entreprises recherchées'))
    await user.type(screen.getByLabelText('Entreprises recherchées'), 'roads_and_civil_works')
    await user.clear(screen.getByLabelText('Territoire commercial'))
    await user.type(screen.getByLabelText('Territoire commercial'), 'FR')
    await user.clear(screen.getByLabelText('Mots-clés surveillés'))
    await user.type(screen.getByLabelText('Mots-clés surveillés'), 'materials_and_components')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await waitFor(() => expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(1))
    expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')[0].body).toEqual({
      label: ICP.label,
      customer_input: {
        offer_summary: 'Granulats et enrobés\n\nLivraison rapide',
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
    expect(await screen.findByText('Profil enregistré.')).toBeVisible()
  })

  it('rejette un terme libre inconnu sans appeler le backend', async () => {
    const user = userEvent.setup()
    mockApi(shell)

    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Offre réelle')
    await user.clear(screen.getByLabelText('Mots-clés surveillés'))
    await user.type(screen.getByLabelText('Mots-clés surveillés'), 'catégorie inventée')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('catégorie inventée')
    expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(0)
  })

  it('conserve le brouillon après une panne PATCH et réessaie la valeur courante', async () => {
    const user = userEvent.setup()
    let attempts = 0
    mockApi({
      ...shell,
      [`PATCH /target-icps/${ICP.target_icp_id}`]: (request) => {
        attempts += 1
        return attempts === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: { ...ICP, ...(request.body as object) } }
      },
    })

    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.clear(screen.getByLabelText('Ce que vous vendez'))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Offre conservée')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/enregistr/i)
    expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('Offre conservée')

    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(2))
    expect(await screen.findByText(/^Profil enregistré\.$/)).toBeVisible()
  })

  it('rend le même écran connecté en anglais avec des actions localisées', async () => {
    mockApi(shell)
    renderApp(<AppRoutes />, {
      route: '/app/icps',
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      locale: 'fr',
    })

    expect(await screen.findByRole('heading', { level: 2, name: 'Target profile' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Edit profile' })).toBeVisible()
    expect(screen.getByText('Materials and components')).toBeVisible()
    expect(document.querySelector('.target-profile-main')).not.toBeNull()
  })

  it('crée un profil vide avec le payload strict réel puis actualise les droits', async () => {
    const user = userEvent.setup()
    let billingCalls = 0
    mockApi({
      'GET /target-icps': { body: [] },
      'GET /billing/status': () => {
        billingCalls += 1
        return { body: DISCOVERY_STATUS }
      },
      'GET /signals': { body: feedPage([], { freshness: 'all' }) },
      'POST /target-icps': (request) => ({
        status: 201,
        body: { ...ICP, target_icp_id: 'icp_created', ...(request.body as object) },
      }),
    })

    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await user.click(await screen.findByRole('button', { name: 'Créer un profil' }))
    await fillProfileForm(user, 'Profil créé')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await waitFor(() => expect(callsTo('/target-icps', 'POST')).toHaveLength(1))
    expect(callsTo('/target-icps', 'POST')[0].body).toEqual({
      label: 'Profil créé',
      customer_input: {
        offer_summary: 'Granulats livrés sur chantier',
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
    expect(await screen.findByText(/^Profil enregistré\.$/)).toBeVisible()
    await waitFor(() => expect(billingCalls).toBeGreaterThan(2))
  })

  it('garde le nominal mono-profil exact et expose une création honnête seulement depuis l’édition', async () => {
    const user = userEvent.setup()
    mockApi(shell)
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    const edit = await screen.findByRole('button', { name: 'Modifier le profil' })
    expect(edit.parentElement).toHaveClass('target-profile-intro')
    expect(screen.queryByRole('button', { name: 'Créer un profil' })).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/Profils actifs\s*:/)

    await user.click(edit)
    const create = screen.getByRole('button', { name: 'Créer un profil' })
    await user.click(create)
    expect(screen.getByRole('heading', { level: 3, name: 'Nouveau profil' })).toBeVisible()
    expect(screen.getByText('Informations manquantes')).toBeVisible()
    expect(screen.queryByText('Profil actif')).not.toBeInTheDocument()
    expect(document.querySelectorAll('.target-example-list .is-included')).toHaveLength(0)
    expect(callsTo('/signals', 'GET')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(screen.getByLabelText('Nom du profil')).toHaveValue(ICP.label)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Créer un profil' })).toHaveFocus())
  })

  it('sélectionne explicitement un profil secondaire avant de l’éditer', async () => {
    const user = userEvent.setup()
    const second: TargetIcp = {
      ...PRESERVED_PROFILE,
      target_icp_id: 'icp_secondary',
      label: 'Location — Suisse',
      customer_input: { ...PRESERVED_PROFILE.customer_input, territories: ['CH'] },
    }
    mockApi({ ...shell, 'GET /target-icps': { body: [PRESERVED_PROFILE, second] } })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.selectOptions(await screen.findByLabelText('Profil affiché'), second.target_icp_id)
    await user.click(screen.getByRole('button', { name: 'Modifier le profil' }))
    expect(screen.getByLabelText('Nom du profil')).toHaveValue(second.label)
    expect(screen.getByLabelText('Territoire commercial')).toHaveValue('Suisse')
  })

  it('empêche un double POST tant que la création est en vol', async () => {
    const user = userEvent.setup()
    let resolvePost!: (value: { status: number; body: TargetIcp }) => void
    mockApi({
      ...shell,
      'GET /target-icps': { body: [] },
      'POST /target-icps': () => new Promise((resolve) => { resolvePost = resolve }),
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await user.click(await screen.findByRole('button', { name: 'Créer un profil' }))
    await fillProfileForm(user, 'Profil unique')

    const submit = screen.getByRole('button', { name: 'Enregistrer' })
    act(() => {
      fireEvent.click(submit)
      fireEvent.click(submit)
    })
    await waitFor(() => expect(callsTo('/target-icps', 'POST')).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Annuler' })).toBeDisabled()
    await act(async () => {
      resolvePost({ status: 201, body: { ...ICP, target_icp_id: 'icp_unique', label: 'Profil unique' } })
      await Promise.resolve()
    })
    expect(await screen.findByText(/^Profil enregistré\.$/)).toBeVisible()
  })

  it('gèle tous les contrôles pendant un PATCH pour ne perdre aucune saisie tardive', async () => {
    const user = userEvent.setup()
    let resolvePatch!: (value: { body: TargetIcp }) => void
    mockApi({
      ...shell,
      [`PATCH /target-icps/${ICP.target_icp_id}`]: () => new Promise((resolve) => {
        resolvePatch = resolve
      }),
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    const offer = screen.getByLabelText('Ce que vous vendez')
    await user.type(offer, 'Offre figée')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(1))

    const form = document.getElementById('target-profile-form') as HTMLElement
    for (const control of form.querySelectorAll('input, textarea, select')) {
      expect(control).toBeDisabled()
    }
    await user.type(offer, ' ignorée')
    expect(offer).toHaveValue('Offre figée')

    await act(async () => {
      resolvePatch({ body: { ...ICP, customer_input: { ...ICP.customer_input, offer_summary: 'Offre figée' } } })
      await Promise.resolve()
    })
    expect(await screen.findByText(/^Profil enregistré\.$/)).toBeVisible()
  })

  it('pagine les exemples jusqu’à un signal accessible sans demander de détail verrouillé', async () => {
    const pageTwo = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_example_page_two',
      company: { ...UNLOCKED_ITEM.company, name: 'Entreprise page deux' },
    }
    mockApi({
      ...shell,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? {
            body: feedPage([pageTwo], {
              freshness: 'all',
              page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
            }),
          }
        : {
            body: feedPage([LOCKED_ITEM], {
              freshness: 'all',
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            }),
          },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    expect(await screen.findByText('Entreprise page deux')).toBeVisible()
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('annonce une pagination d’exemples partielle et la relance localement', async () => {
    const user = userEvent.setup()
    let firstPageAttempts = 0
    mockApi({
      ...shell,
      'GET /signals': (request) => {
        if (request.search.get('offset') === '20') {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        firstPageAttempts += 1
        return firstPageAttempts === 1
          ? {
              body: feedPage([LOCKED_ITEM], {
                freshness: 'all',
                page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              }),
            }
          : { body: feedPage([UNLOCKED_ITEM], { freshness: 'all' }) }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const examples = document.querySelector('.target-example-list') as HTMLElement
    expect(await within(examples).findByRole('alert')).toHaveTextContent(/incomplète|chargement/i)
    await user.click(within(examples).getByRole('button', { name: 'Réessayer' }))
    expect(await within(examples).findByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20', '0'])
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('annonce une troncature des exemples et effectue une vraie relance locale', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      'GET /signals': {
        body: feedPage([UNLOCKED_ITEM], {
          freshness: 'all',
          page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
        }),
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const examples = document.querySelector('.target-example-list') as HTMLElement
    expect(await within(examples).findByRole('alert')).toHaveTextContent('La lecture des exemples est incomplète')
    await user.click(within(examples).getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(2))
    expect(within(examples).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
  })

  it('conserve un exemple acquis pendant la reprise d’une page suivante', async () => {
    const user = userEvent.setup()
    let pageTwoAttempts = 0
    let resolvePageTwo!: (value: { body: ReturnType<typeof feedPage> }) => void
    mockApi({
      ...shell,
      'GET /signals': (request) => {
        if (request.search.get('offset') !== '20') {
          return {
            body: feedPage([UNLOCKED_ITEM], {
              freshness: 'all',
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            }),
          }
        }
        pageTwoAttempts += 1
        if (pageTwoAttempts === 1) {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        return new Promise((resolve) => { resolvePageTwo = resolve })
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const examples = document.querySelector('.target-example-list') as HTMLElement
    expect(await within(examples).findByRole('alert')).toBeVisible()
    expect(within(examples).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    await user.click(within(examples).getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(resolvePageTwo).toBeTypeOf('function'))
    expect(within(examples).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()

    await act(async () => {
      resolvePageTwo({
        body: feedPage([], {
          freshness: 'all',
          page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
        }),
      })
      await Promise.resolve()
    })
    expect(await within(examples).findByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
  })

  it('conserve un exemple acquis si la reprise échoue dès la première page', async () => {
    const user = userEvent.setup()
    let pageZeroAttempts = 0
    let resolveRetry!: (value: {
      status: number
      body: { detail: { code: string } }
    }) => void
    mockApi({
      ...shell,
      'GET /signals': (request) => {
        if (request.search.get('offset') === '20') {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        pageZeroAttempts += 1
        if (pageZeroAttempts === 1) {
          return {
            body: feedPage([UNLOCKED_ITEM], {
              freshness: 'all',
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            }),
          }
        }
        return new Promise((resolve) => { resolveRetry = resolve })
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    const examples = (await screen.findByText(UNLOCKED_ITEM.company.name!))
      .closest('.target-example-list') as HTMLElement
    await within(examples).findByRole('alert')
    await user.click(within(examples).getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(resolveRetry).toBeTypeOf('function'))
    expect(within(examples).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    const loadingStatus = within(examples).getByRole('status')
    expect(loadingStatus).toHaveTextContent('Chargement')
    expect(loadingStatus.closest('article')).toHaveAttribute('aria-busy', 'true')

    await act(async () => {
      resolveRetry({ status: 503, body: { detail: { code: 'temporarily_unavailable' } } })
      await Promise.resolve()
    })
    expect(await within(examples).findByRole('alert')).toBeVisible()
    expect(within(examples).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
  })

  it('retire un ancien exemple si une reprise réussie ne l’autorise plus', async () => {
    const user = userEvent.setup()
    let pageZeroAttempts = 0
    mockApi({
      ...shell,
      'GET /signals': (request) => {
        if (request.search.get('offset') === '20') {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        pageZeroAttempts += 1
        return pageZeroAttempts === 1
          ? {
              body: feedPage([UNLOCKED_ITEM], {
                freshness: 'all',
                page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              }),
            }
          : { body: feedPage([], { freshness: 'all' }) }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    const examples = (await screen.findByText(UNLOCKED_ITEM.company.name!))
      .closest('.target-example-list') as HTMLElement
    await within(examples).findByRole('alert')
    await user.click(within(examples).getByRole('button', { name: 'Réessayer' }))

    await within(examples).findByRole('status')
    expect(within(examples).queryByText(UNLOCKED_ITEM.company.name!)).not.toBeInTheDocument()
    expect(within(examples).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('interrompt honnêtement une pagination dont l’offset ne progresse plus', async () => {
    mockApi({
      ...shell,
      'GET /signals': (request) => ({
        body: feedPage([LOCKED_ITEM], {
          freshness: 'all',
          page: {
            limit: 20,
            offset: request.search.get('offset') === '20'
              ? 0
              : Number(request.search.get('offset') ?? 0),
            has_more: true,
            scan_truncated: false,
          },
        }),
      }),
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    expect(await screen.findByRole('alert')).toHaveTextContent('La lecture des exemples est incomplète')
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('borne une pagination d’exemples qui annonce toujours une suite', async () => {
    mockApi({
      ...shell,
      'GET /signals': (request) => ({
        body: feedPage([LOCKED_ITEM], {
          freshness: 'all',
          page: {
            limit: 20,
            offset: Number(request.search.get('offset') ?? 0),
            has_more: true,
            scan_truncated: false,
          },
        }),
      }),
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    expect(await screen.findByRole('alert')).toHaveTextContent('La lecture des exemples est incomplète')
    expect(callsTo('/signals', 'GET')).toHaveLength(25)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('localise le pays d’un exemple sans localité dans la langue du compte', async () => {
    const germanSignal = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_germany',
      contract: {
        ...UNLOCKED_ITEM.contract,
        location: { country: 'DE', locality: null, postal_code: null, subdivision_code: null },
      },
      analysis: {
        ...UNLOCKED_ITEM.analysis,
        fit: { ...UNLOCKED_ITEM.analysis.fit, label: 'Strong match for your profile' },
      },
    }
    mockApi({ ...shell, 'GET /signals': { body: feedPage([germanSignal], { freshness: 'all' }) } })
    renderApp(<AppRoutes />, {
      route: '/app/icps',
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      locale: 'en',
    })

    expect(await screen.findByText('Strong match for your profile, for a project located in Germany.')).toBeVisible()
    expect(document.body).not.toHaveTextContent('located in DE')
  })

  it('rafraîchit le profil autoritaire du shell après une mutation avant la navigation', async () => {
    const user = userEvent.setup()
    let listCalls = 0
    const updated = { ...ICP, label: 'Matériaux — Sud' }
    mockApi({
      ...shell,
      'GET /target-icps': () => {
        listCalls += 1
        return { body: [listCalls <= 2 ? ICP : updated] }
      },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: { body: updated },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    const name = screen.getByLabelText('Nom du profil')
    await user.clear(name)
    await user.type(name, updated.label)
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats livrés sur chantier')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await waitFor(() => expect(callsTo(`/target-icps/${ICP.target_icp_id}`, 'PATCH')).toHaveLength(1))
    expect(await screen.findByText(/^Profil enregistré\.$/)).toBeVisible()
    await waitFor(() => expect(listCalls).toBeGreaterThanOrEqual(3))
    await user.click(screen.getByRole('link', { name: 'Vue d’ensemble' }))
    expect(await screen.findByRole('link', { name: 'Ouvrir le profil de ciblage' })).toHaveTextContent(updated.label)
  })

  it('masque la valeur shell périmée pendant le refresh autoritaire', async () => {
    const user = userEvent.setup()
    const updated = { ...ICP, label: 'Matériaux — Sud' }
    let listCalls = 0
    let resolveRefresh!: (value: { body: TargetIcp[] }) => void
    mockApi({
      ...shell,
      'GET /target-icps': () => {
        listCalls += 1
        if (listCalls <= 2) return { body: [ICP] }
        if (listCalls === 3) {
          return new Promise((resolve) => { resolveRefresh = resolve })
        }
        return { body: [updated] }
      },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: { body: updated },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.clear(screen.getByLabelText('Nom du profil'))
    await user.type(screen.getByLabelText('Nom du profil'), updated.label)
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats livrés sur chantier')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(listCalls).toBe(3))
    await user.click(screen.getByRole('link', { name: 'Vue d’ensemble' }))

    const profileLink = await screen.findByRole('link', { name: 'Ouvrir le profil de ciblage' })
    expect(profileLink).toHaveTextContent('Chargement')
    expect(profileLink).not.toHaveTextContent(ICP.label)

    await act(async () => {
      resolveRefresh({ body: [updated] })
      await Promise.resolve()
    })
    await waitFor(() => expect(profileLink).toHaveTextContent(updated.label))
  })

  it('rend l’échec du refresh shell relançable sans réafficher l’ancien profil', async () => {
    const user = userEvent.setup()
    const updated = { ...ICP, label: 'Matériaux — Sud' }
    let listCalls = 0
    let billingCalls = 0
    mockApi({
      ...shell,
      'GET /target-icps': () => {
        listCalls += 1
        if (listCalls <= 2) return { body: [ICP] }
        if (listCalls === 3) {
          return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        }
        return { body: [updated] }
      },
      'GET /billing/status': () => {
        billingCalls += 1
        return { body: DISCOVERY_STATUS }
      },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: { body: updated },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.clear(screen.getByLabelText('Nom du profil'))
    await user.type(screen.getByLabelText('Nom du profil'), updated.label)
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats livrés sur chantier')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(listCalls).toBe(3))
    await user.click(screen.getByRole('link', { name: 'Vue d’ensemble' }))

    const retry = await screen.findByRole('button', {
      name: 'Réessayer le chargement du profil de ciblage',
    })
    expect(retry).not.toHaveTextContent(ICP.label)
    const profileCallsBeforeRetry = listCalls
    const billingCallsBeforeRetry = billingCalls
    await user.click(retry)

    expect(await screen.findByRole('link', { name: 'Ouvrir le profil de ciblage' })).toHaveTextContent(updated.label)
    expect(listCalls).toBe(profileCallsBeforeRetry + 1)
    expect(billingCalls).toBe(billingCallsBeforeRetry)
  })

  it('ne revendique un profil actif qu’après l’autorité billing et expose les limites', async () => {
    let billingCalls = 0
    const resolveAccess: Array<(value: { status: number; body: unknown }) => void> = []
    mockApi({
      ...shell,
      'GET /billing/status': () => {
        billingCalls += 1
        if (billingCalls <= 2) {
          return new Promise((resolve) => { resolveAccess.push(resolve) })
        }
        return {
          body: { ...DISCOVERY_STATUS, target_icps_over_limit: [ICP.target_icp_id] },
        }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const status = document.querySelector('.target-active-status') as HTMLElement
    expect(status).toHaveTextContent('Chargement')
    expect(status).not.toHaveTextContent('Profil actif')

    await act(async () => {
      resolveAccess.forEach((resolve) => resolve({
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      }))
      await Promise.resolve()
    })
    await screen.findByRole('button', { name: 'Réessayer' })
    expect(status).toHaveTextContent('Non publié')
    expect(status).not.toHaveTextContent('Profil actif')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(status).toHaveTextContent('Au-delà de la limite de votre offre'))
    expect(status).not.toHaveTextContent('Profil actif')
  })

  it('affiche la limite territoriale du profil avant toute autorité billing', async () => {
    const limited: TargetIcp = {
      ...ICP,
      plan_limit: {
        code: 'territory_limit_exceeded',
        limit: 1,
        territory_count: 2,
      },
    }
    mockApi({
      ...shell,
      'GET /target-icps': { body: [limited] },
      'GET /billing/status': (() => {
        let call = 0
        return () => {
          call += 1
          return call === 1
            ? { body: DISCOVERY_STATUS }
            : new Promise(() => undefined)
        }
      })(),
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const status = document.querySelector('.target-active-status') as HTMLElement
    expect(status).toHaveTextContent('Limité par votre offre')
    expect(status).not.toHaveTextContent('Profil actif')
  })

  it('n’affiche jamais undefined quand une erreur PATCH ne fournit pas de body', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      [`PATCH /target-icps/${ICP.target_icp_id}`]: {
        status: 404,
        body: { detail: { code: 'target_icp_not_found' } },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Offre conservée')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/enregistr/i)
    expect(alert).not.toHaveTextContent('undefined')
    expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('Offre conservée')
  })

  it('redirige un 401 du chargement ICP vers la connexion', async () => {
    mockApi({
      ...shell,
      'GET /target-icps': { status: 401, body: { detail: { code: 'not_authenticated' } } },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Retrouver vos signaux' })).toBeVisible()
  })

  it('redirige un 401 du PATCH sans annoncer un profil enregistré', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      [`PATCH /target-icps/${ICP.target_icp_id}`]: {
        status: 401,
        body: { detail: { code: 'not_authenticated' } },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Offre réelle')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    expect(await screen.findByRole('heading', { name: 'Retrouver vos signaux' })).toBeVisible()
    expect(screen.queryByText('Profil enregistré')).not.toBeInTheDocument()
  })

  it('ignore une sauvegarde tardive quand le compte change', async () => {
    const user = userEvent.setup()
    const accountBProfile: TargetIcp = {
      ...ICP,
      target_icp_id: 'icp_account_b',
      label: 'Profil du compte B',
    }
    let listCalls = 0
    let resolvePatch!: (value: { body: TargetIcp }) => void
    mockApi({
      ...shell,
      'GET /target-icps': () => {
        listCalls += 1
        return { body: listCalls <= 2 ? [ICP] : [accountBProfile] }
      },
      [`PATCH /target-icps/${ICP.target_icp_id}`]: () => new Promise((resolve) => {
        resolvePatch = resolve
      }),
    })
    renderApp(<><AppRoutes /><AdoptTargetingAccountB /></>, {
      route: '/app/icps',
      session: AUTHENTICATED,
    })

    await user.click(await screen.findByRole('button', { name: 'Modifier le profil' }))
    await user.type(screen.getByLabelText('Ce que vous vendez'), 'Secret compte A')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(resolvePatch).toBeTypeOf('function'))
    await user.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    expect(await screen.findByRole('heading', { level: 3, name: accountBProfile.label })).toBeVisible()

    await act(async () => {
      resolvePatch({
        body: {
          ...ICP,
          label: 'Profil privé A tardif',
          customer_input: { ...ICP.customer_input, offer_summary: 'Secret compte A' },
        },
      })
      await Promise.resolve()
    })
    expect(screen.getByRole('heading', { level: 3, name: accountBProfile.label })).toBeVisible()
    expect(document.body).not.toHaveTextContent('Profil privé A tardif')
    expect(document.body).not.toHaveTextContent('Secret compte A')
  })

  it('rend le chargement, la panne et le vide des exemples comme trois états distincts', async () => {
    const user = userEvent.setup()
    let attempts = 0
    let resolveSignals!: (value: { body: ReturnType<typeof feedPage> }) => void
    mockApi({
      ...shell,
      'GET /signals': () => {
        attempts += 1
        if (attempts === 1) return new Promise((resolve) => { resolveSignals = resolve })
        if (attempts === 2) return { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        return { body: feedPage([], { freshness: 'all' }) }
      },
    })
    const { unmount } = renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const list = document.querySelector('.target-example-list') as HTMLElement
    expect(within(list).getByRole('status')).toHaveTextContent('Chargement')
    expect(list.querySelectorAll('article')).toHaveLength(3)
    expect(list.querySelectorAll('.is-included')).toHaveLength(0)
    await waitFor(() => expect(resolveSignals).toBeTypeOf('function'))

    await act(async () => {
      resolveSignals({ body: feedPage([], { freshness: 'all' }) })
      await Promise.resolve()
    })
    await waitFor(() => expect(within(list).getByRole('status')).toHaveTextContent(
      'Aucun signal accessible n’est publié dans cet emplacement.',
    ))
    expect(within(list).getAllByRole('status')).toHaveLength(1)
    expect(within(list).getByRole('status')).not.toHaveTextContent('Chargement')
    expect(within(list).getAllByText('Aucun signal accessible n’est publié dans cet emplacement.')).toHaveLength(2)
    unmount()

    mockApi({
      ...shell,
      'GET /signals': () => {
        attempts += 1
        return attempts === 2
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: feedPage([], { freshness: 'all' }) }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/icps', session: AUTHENTICATED })
    await screen.findByRole('heading', { level: 3, name: ICP.label })
    const errorList = document.querySelector('.target-example-list') as HTMLElement
    expect(await within(errorList).findByRole('alert')).toHaveTextContent('La lecture des exemples est incomplète')
    await user.click(within(errorList).getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(within(errorList).queryByRole('alert')).not.toBeInTheDocument())
    expect(errorList.querySelectorAll('.is-included')).toHaveLength(0)
  })
})

async function fillProfileForm(user: ReturnType<typeof userEvent.setup>, label: string) {
  await user.type(screen.getByLabelText('Nom du profil'), label)
  await user.type(screen.getByLabelText('Ce que vous vendez'), 'Granulats livrés sur chantier')
  await user.type(screen.getByLabelText('Entreprises recherchées'), 'Routes et génie civil')
  await user.type(screen.getByLabelText('Territoire commercial'), 'France')
  await user.type(screen.getByLabelText('Mots-clés surveillés'), 'Matériaux et composants')
  await user.type(screen.getByLabelText('Montant minimum du marché'), '50000')
}

function AdoptTargetingAccountB() {
  const { adopt } = useSession()
  return (
    <button
      type="button"
      onClick={() => adopt({ ...ME, account_id: 'acc_target_b', account_display_name: 'Compte B' })}
    >
      Basculer sur le compte B
    </button>
  )
}
