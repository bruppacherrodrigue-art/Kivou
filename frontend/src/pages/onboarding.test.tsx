import { describe, expect, it, afterEach, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
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
 * un ciblage enregistré que le client ne sait pas enregistré. */

afterEach(() => vi.unstubAllGlobals())

const INCOMPLETE_ME = { ...ME, onboarding_status: 'account_created' as const }

type User = ReturnType<typeof userEvent.setup>

const ACTIVATED_ROUTES = {
  'POST /target-icps': { status: 201, body: ICP },
  'GET /me': { body: ME },
  'GET /signals': { body: feedPage([]) },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

/** Remplit les trois temps du ciblage et s'arrête sur la relecture. */
async function fillTargeting(user: User, { label = 'Matériaux — Occitanie' } = {}) {
  // A — ce que vous vendez
  await user.click(await screen.findByLabelText('Matériaux et composants'))
  await user.click(screen.getByRole('button', { name: 'Suivant' }))

  // B — à qui et où
  await user.click(await screen.findByLabelText('France'))
  await user.click(screen.getByRole('button', { name: 'Suivant' }))

  // C — à partir de quel montant
  await user.type(await screen.findByLabelText('Montant minimum'), '50000')
  await user.type(screen.getByLabelText(/Nom du profil/), label)
  await user.click(screen.getByRole('button', { name: 'Suivant' }))

  await screen.findByRole('heading', { name: 'Vérifier votre ciblage' })
}

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

  it('pose les questions en trois temps, sous un seul h1', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    // Un seul titre de page ; les étapes sont des sous-titres.
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Ce que vous vendez' }),
    ).toBeInTheDocument()

    await user.click(screen.getByLabelText('Matériaux et composants'))
    await user.click(screen.getByRole('button', { name: 'Suivant' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: 'À qui et où vous vendez' }),
    ).toBeInTheDocument()

    await user.click(screen.getByLabelText('France'))
    await user.click(screen.getByRole('button', { name: 'Suivant' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: 'À partir de quel montant' }),
    ).toBeInTheDocument()

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('signale la progression sans compter les questions', async () => {
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    const progress = await screen.findByRole('navigation', { name: 'Votre mise en route' })
    const steps = within(progress).getAllByRole('listitem')
    expect(steps).toHaveLength(3)
    expect(steps[0]).toHaveTextContent('Compte')
    expect(steps[1]).toHaveTextContent('Ciblage')
    expect(steps[2]).toHaveTextContent('Signaux')

    // L'étape courante est portée par ARIA, pas seulement par une couleur.
    expect(steps[1]).toHaveAttribute('aria-current', 'step')
    expect(steps[0]).not.toHaveAttribute('aria-current')
    expect(steps[2]).not.toHaveAttribute('aria-current')
    // Rien n'y est cliquable : le ciblage ne se saute pas.
    expect(within(progress).queryByRole('link')).not.toBeInTheDocument()
    expect(within(progress).queryByRole('button')).not.toBeInTheDocument()
  })

  it('laisse le bouton utilisable et explique ce qui manque, sans jargon moteur', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    // Le bouton n'est pas désactivé sans explication (§13) : il répond.
    const next = await screen.findByRole('button', { name: 'Suivant' })
    expect(next).toBeEnabled()
    await user.click(next)

    const notice = await screen.findByText(/Il manque encore/)
    expect(notice.closest('div')).toHaveTextContent('ce que vous vendez')
    // L'étape n'a pas avancé.
    expect(
      screen.getByRole('heading', { level: 2, name: 'Ce que vous vendez' }),
    ).toBeInTheDocument()

    // L'erreur disparaît dès que la saisie la lève.
    await user.click(screen.getByLabelText('Matériaux et composants'))
    await waitFor(() => expect(screen.queryByText(/Il manque encore/)).not.toBeInTheDocument())

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

    await user.click(await screen.findByLabelText('Matériaux et composants'))
    await user.click(screen.getByRole('button', { name: 'Suivant' }))

    const second = await screen.findByRole('heading', { level: 2, name: 'À qui et où vous vendez' })
    await waitFor(() => expect(second).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Retour' }))
    const first = await screen.findByRole('heading', { level: 2, name: 'Ce que vous vendez' })
    await waitFor(() => expect(first).toHaveFocus())
  })

  it('conserve la devise et le montant quand leur groupe cesse d’être visible', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await user.click(await screen.findByLabelText('Matériaux et composants'))
    await user.click(screen.getByRole('button', { name: 'Suivant' }))
    await user.click(await screen.findByLabelText('France'))
    await user.click(screen.getByRole('button', { name: 'Suivant' }))

    // Une devise choisie AVANT le montant n'a encore aucune représentation dans
    // le modèle : c'est exactement la saisie qu'un démontage effacerait.
    await user.selectOptions(await screen.findByLabelText('Devise'), 'CHF')
    await user.type(screen.getByLabelText('Montant minimum'), '75000')

    await user.click(screen.getByRole('button', { name: 'Retour' }))
    await screen.findByRole('heading', { level: 2, name: 'À qui et où vous vendez' })
    await user.click(screen.getByRole('button', { name: 'Suivant' }))

    await screen.findByRole('heading', { level: 2, name: 'À partir de quel montant' })
    expect(screen.getByLabelText('Devise')).toHaveValue('CHF')
    expect(screen.getByLabelText('Montant minimum')).toHaveValue(75000)
  })

  it('relit le ciblage dans les mots du client avant de l’enregistrer', async () => {
    const user = userEvent.setup()
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: INCOMPLETE_ME },
      route: '/onboarding',
    })

    await fillTargeting(user)

    expect(screen.getByText('Matériaux et composants')).toBeInTheDocument()
    // Le territoire est nommé, jamais rendu par son code ISO brut.
    const territoryRow = screen.getByText('Territoires').closest('div')!
    expect(territoryRow).toHaveTextContent('France')
    expect(territoryRow).not.toHaveTextContent(/\bFR\b/)
    // Sans corps de métier choisi, la relecture le dit plutôt que de laisser un vide.
    expect(screen.getByText('Corps de métier visés').closest('div')).toHaveTextContent(
      'Tous corps de métier',
    )
    expect(screen.getByText('Prêt pour les signaux')).toBeInTheDocument()
    // Aucun champ de saisie n'est proposé sur la relecture.
    expect(screen.queryByLabelText('Montant minimum')).not.toBeInTheDocument()
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
      screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }),
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

  it('rejoint le feed en annonçant les signaux réellement ouverts', async () => {
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
      screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }),
    )

    expect(await screen.findByRole('heading', { name: 'Occasions commerciales' })).toBeInTheDocument()
    // Le compte vient du serveur, et il n'est annoncé qu'une fois les
    // déblocages réellement attribués.
    expect(
      await screen.findByText('3 signaux sont accessibles avec votre profil.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Voir mon premier signal' })).toHaveAttribute(
      'href',
      '/app/signals/sig_unlocked_1',
    )
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
      screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }),
    )

    await waitFor(() => expect(callsTo('/target-icps')).toHaveLength(1))
    for (const call of recordedCalls) {
      expect(JSON.stringify(call.body ?? {})).not.toContain('account_id')
      expect(call.url).not.toContain('account_id')
      expect(call.search.get('account_id')).toBeNull()
    }
  })

  it('reste sur la relecture et explique une erreur réseau avant toute création réussie', async () => {
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
      screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }),
    )

    expect(await screen.findByText('Une erreur est survenue')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Vérifier votre ciblage' })).toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(callsTo('/me')).toHaveLength(0)
  })

  it('reste sur la relecture et affiche la limite territoriale fournie par le serveur', async () => {
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
    await user.click(screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }))

    expect(await screen.findByText('Limite territoriale atteinte')).toBeInTheDocument()
    expect(document.body).toHaveTextContent(
      'Votre offre autorise 1 territoire par profil. Réduisez votre sélection pour enregistrer ce ciblage.',
    )
    expect(screen.getByRole('heading', { name: 'Vérifier votre ciblage' })).toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(1)
    expect(callsTo('/me')).toHaveLength(0)
  })
})

describe('succès partiel — ciblage enregistré, session non relue', () => {
  it('ne rejoue jamais le POST : le retry ne refait que la finalisation', async () => {
    const user = userEvent.setup()
    let meCalls = 0
    mockApi({
      ...ACTIVATED_ROUTES,
      'GET /me': () => {
        meCalls += 1
        // La première relecture tombe sur une indisponibilité du serveur.
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
      screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' }),
    )

    // Le ciblage a bien été enregistré : le dire autrement serait faux, et
    // pousserait le client à recommencer une saisie qui existe déjà.
    const notice = await screen.findByText('Votre ciblage a bien été enregistré')
    expect(notice.closest('div')).toHaveTextContent(/n’a pas pu finaliser/)
    expect(document.body.textContent).not.toMatch(/création du ciblage a échoué/i)
    // La session tient : une panne serveur n'est pas une déconnexion.
    expect(screen.queryByRole('heading', { name: 'Se connecter' })).not.toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Finaliser et voir mes signaux' }))

    expect(await screen.findByRole('heading', { name: 'Occasions commerciales' })).toBeInTheDocument()
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
    const submit = screen.getByRole('button', { name: 'Créer mon profil et voir mes signaux' })

    // Deux clics dans le même tour de boucle, avant tout nouveau rendu.
    act(() => {
      fireEvent.click(submit)
      fireEvent.click(submit)
    })
    await act(async () => {
      releasePost()
      await gate
    })

    expect(await screen.findByRole('heading', { name: 'Occasions commerciales' })).toBeInTheDocument()
    expect(seen.filter((call) => call === 'POST /target-icps')).toHaveLength(1)
  })

  it('renvoie au feed plutôt que de rouvrir un formulaire déjà rempli', async () => {
    // Le remontage qui suit un incident : le serveur sait que l'onboarding est
    // terminé, la page ne doit pas proposer d'en créer un second.
    mockApi(ACTIVATED_ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/onboarding' })

    expect(await screen.findByRole('heading', { name: 'Occasions commerciales' })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Configurer votre profil de ciblage' }),
    ).not.toBeInTheDocument()
    expect(callsTo('/target-icps')).toHaveLength(0)
  })
})

describe('gestion des profils', () => {
  it('rend une erreur de chargement relançable sans masquer le titre de page', async () => {
    mockApi({
      'GET /target-icps': { status: 503, body: { detail: { code: 'billing_error' } } },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    expect(await screen.findByText('Une erreur est survenue')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Profils de ciblage' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
  })

  it('conserve l’éditeur après une erreur de modification et localise l’erreur en anglais', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
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

    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Edit profile' })).toBeInTheDocument()
    expect(screen.queryByText(/Une erreur|Réessayer|Modifier le profil/)).not.toBeInTheDocument()
  })

  it('localise en anglais la limite territoriale renvoyée à la modification', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
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

    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Territory limit reached')).toBeInTheDocument()
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

    const card = (await screen.findByText('Matériaux — Occitanie')).closest('article')!
    const territories = within(card).getByText('Territoires').closest('div')!
    expect(territories).toHaveTextContent('Suisse, ZZ')
    expect(territories).not.toHaveTextContent(/\bCH\b/)
    const threshold = within(card).getByText('Montant minimum').closest('div')!
    expect(threshold.querySelector('dd')?.textContent).toBe(
      new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: 'CHF',
        maximumFractionDigits: 0,
      }).format(75000),
    )
    expect(within(card).getByText('Votre offre en une phrase').closest('div')).toHaveTextContent(
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

    const card = (await screen.findByText('Matériaux — Occitanie')).closest('article')!
    expect(within(card).getByText('Territories').closest('div')).toHaveTextContent(
      'Switzerland, Germany',
    )
    const threshold = within(card).getByText('Minimum amount').closest('div')!
    expect(threshold.querySelector('dd')?.textContent).toBe(
      new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
      }).format(50000),
    )
    expect(within(card).getByText('Your offer in one sentence').closest('div')).toHaveTextContent(
      'Timber components delivered to site.',
    )
    expect(card).not.toHaveTextContent(/Territoires|Montant minimum|Votre offre/)
  })

  it('masque la description facultative lorsqu’elle est vide', async () => {
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    await screen.findByText('Matériaux — Occitanie')
    expect(screen.queryByText('Votre offre en une phrase')).not.toBeInTheDocument()
  })

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

    await user.click(await screen.findByRole('button', { name: 'Modifier' }))
    const editor = (await screen.findByRole('heading', { name: 'Modifier le profil' })).closest(
      'section',
    )!

    // Les six groupes, présents ensemble sur le MÊME écran.
    expect(within(editor).getByLabelText(/Nom du profil/)).toBeInTheDocument()
    expect(within(editor).getByText('Que vendez-vous ?')).toBeInTheDocument()
    expect(within(editor).getByText('À quels corps de métier vendez-vous ?')).toBeInTheDocument()
    expect(within(editor).getByText('Où pouvez-vous livrer ou intervenir ?')).toBeInTheDocument()
    expect(
      within(editor).getByText('À partir de quel montant un marché vous intéresse-t-il ?'),
    ).toBeInTheDocument()
    expect(within(editor).getByLabelText('Devise')).toBeInTheDocument()
    expect(within(editor).getByLabelText('Montant minimum')).toBeInTheDocument()
    expect(
      within(editor).getByLabelText(/Décrivez votre offre en une phrase/),
    ).toBeInTheDocument()

    // Les valeurs existantes sont rendues, pas réinitialisées.
    expect(within(editor).getByLabelText(/Nom du profil/)).toHaveValue('Matériaux — Occitanie')
    expect(within(editor).getByLabelText('Matériaux et composants')).toBeChecked()
    expect(within(editor).getByLabelText('France')).toBeChecked()
    expect(within(editor).getByLabelText('Montant minimum')).toHaveValue(50000)

    // `/app/icps` n'est pas un assistant.
    expect(screen.queryByRole('button', { name: 'Suivant' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Votre mise en route' })).not.toBeInTheDocument()
    expect(within(editor).getByRole('button', { name: 'Enregistrer' })).toBeInTheDocument()
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
    expect(screen.getByText('Que vendez-vous ?')).toBeInTheDocument()
    expect(screen.getByText('À quels corps de métier vendez-vous ?')).toBeInTheDocument()
    expect(screen.getByText('Où pouvez-vous livrer ou intervenir ?')).toBeInTheDocument()
    expect(screen.getByLabelText('Devise')).toBeInTheDocument()
    expect(screen.getByLabelText(/Décrivez votre offre en une phrase/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Suivant' })).not.toBeInTheDocument()
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
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/icps' })

    const card = (await screen.findByText('Matériaux — Occitanie')).closest('article')!
    expect(within(card).getByText('Limité par votre offre')).toBeInTheDocument()
    expect(within(card).getByText('Territoires').closest('div')).toHaveTextContent('Suisse, France')
    expect(card).toHaveTextContent(
      'Ce profil conserve ses territoires, mais il n’alimente pas votre flux. Sélectionnez au maximum 1 territoire pour le réactiver.',
    )
    expect(within(card).queryByRole('button', { name: /supprimer/i })).not.toBeInTheDocument()
  })
})
