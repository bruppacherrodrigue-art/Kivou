import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  PRO_STATUS,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'
import type { BillingStatus } from '../api/types'

/* P0-02 §8, §9, §11 — le moment d'activation, sur le feed.
 *
 * Trois pièges y sont vérifiés, et chacun produirait un mensonge :
 *   — annoncer zéro signal parce que le compteur a été lu AVANT l'appel qui
 *     attribue les déblocages ;
 *   — laisser « votre ciblage est prêt » revenir à chaque rechargement ;
 *   — fabriquer un « premier signal » que le serveur n'a pas ouvert.
 */

afterEach(() => vi.unstubAllGlobals())

const ACTIVATION_ROUTE = {
  pathname: '/app/signals',
  state: { activationCompleted: true },
}

function discovery(granted: number): BillingStatus {
  return {
    ...DISCOVERY_STATUS,
    discovery: { granted_signal_count: granted, remaining_slots: 3 - granted, limit: 3 },
  }
}

/* Un compte payant n'a AUCUN déblocage Découverte : `_grant_discovery` sort
 * immédiatement dès que le plan est payé. Le compteur vaut donc zéro, et les
 * signaux sont pourtant ouverts par les droits du plan. */
const PAID_WITHOUT_GRANTS: BillingStatus = {
  ...PRO_STATUS,
  discovery: { granted_signal_count: 0, remaining_slots: 0, limit: 3 },
}

/** Le second signal débloqué, plus ancien : un reclassement le remonterait. */
const SECOND_UNLOCKED = {
  ...UNLOCKED_ITEM,
  signal_id: 'sig_unlocked_2',
  company: { ...UNLOCKED_ITEM.company, name: 'Charpentes Morel SA' },
  event: { ...UNLOCKED_ITEM.event, date: '2026-07-02', age_days: 47 },
}

function routesFor(items: unknown[], granted: number) {
  return {
    'GET /signals': { body: feedPage(items as never[]) },
    'GET /billing/status': { body: discovery(granted) },
    'GET /target-icps': { body: [ICP] },
  }
}

/** Le bandeau d'activation, isolé de tout ce qui l'entoure. */
function activationSection(): HTMLElement {
  return screen.getByRole('heading', { name: 'Votre ciblage est prêt' }).closest('section')!
}

describe('moment d’activation — compteur', () => {
  it('relit le compteur APRÈS le feed, qui est l’appel qui attribue les déblocages', async () => {
    let feedCalls = 0
    mockApi({
      'GET /signals': () => {
        feedCalls += 1
        return { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) }
      },
      // Avant le feed, le compte n'a encore RIEN : c'est `_grant_discovery`,
      // déclenché par `GET /signals`, qui commite les trois déblocages.
      'GET /billing/status': () => ({ body: discovery(feedCalls > 0 ? 3 : 0) }),
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(
      await screen.findByText('3 signaux sont accessibles avec votre profil.'),
    ).toBeInTheDocument()

    const paths = recordedCalls.map((call) => `${call.method} ${call.url}`)
    expect(paths.indexOf('GET /signals')).toBeGreaterThanOrEqual(0)
    expect(paths.indexOf('GET /billing/status')).toBeGreaterThan(paths.indexOf('GET /signals'))
    // Aucun zéro passager n'a été affiché.
    expect(document.body.textContent).not.toContain(
      'Aucun signal correspondant n’est disponible pour le moment.',
    )
  })

  it('lit le compteur du serveur, jamais le nombre de cartes déverrouillées', async () => {
    // Deux cartes ouvertes dans la page, trois déblocages acquis : c'est le
    // serveur qui a raison, la page n'est qu'une fenêtre paginée.
    mockApi(routesFor([UNLOCKED_ITEM, SECOND_UNLOCKED, LOCKED_ITEM], 3))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(
      await screen.findByText('3 signaux sont accessibles avec votre profil.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/2 signaux sont accessibles/)).not.toBeInTheDocument()
  })

  it('accorde le singulier à un seul déblocage', async () => {
    mockApi(routesFor([UNLOCKED_ITEM], 1))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(
      await screen.findByText('1 signal est accessible avec votre profil.'),
    ).toBeInTheDocument()
  })

  it('annonce deux déblocages quand le serveur n’en a attribué que deux', async () => {
    mockApi(routesFor([UNLOCKED_ITEM, SECOND_UNLOCKED], 2))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(
      await screen.findByText('2 signaux sont accessibles avec votre profil.'),
    ).toBeInTheDocument()
  })

  it('dit clairement l’absence de signal, sans appel à l’action', async () => {
    mockApi(routesFor([], 0))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(
      await screen.findByText('Aucun signal correspondant n’est disponible pour le moment.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Kivou continuera à surveiller les nouvelles attributions compatibles avec votre profil.',
      ),
    ).toBeInTheDocument()
    // Aucun premier signal n'existe : aucun lien ne doit prétendre le contraire.
    expect(screen.queryByRole('link', { name: 'Voir mon premier signal' })).not.toBeInTheDocument()
    // Ni faux compte, ni chiffre inventé.
    expect(document.body.textContent).not.toMatch(/0 signal/)
  })
})

describe('moment d’activation — premier signal', () => {
  it('ouvre le PREMIER signal accessible dans l’ordre reçu de l’API', async () => {
    // Le premier déverrouillé de la page est le plus ANCIEN : reclasser par
    // fraîcheur proposerait l'autre, que le serveur n'a pas mis en tête.
    mockApi(routesFor([LOCKED_ITEM, SECOND_UNLOCKED, UNLOCKED_ITEM], 3))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    const cta = await screen.findByRole('link', { name: 'Voir mon premier signal' })
    expect(cta).toHaveAttribute('href', '/app/signals/sig_unlocked_2')
  })

  it('n’invente aucun appel à l’action quand la page ne contient rien de déverrouillé', async () => {
    // Cas incohérent mais possible : le compte a des déblocages, la page rendue
    // n'en montre aucun (une fraîcheur restrictive suffit). Le nombre du
    // serveur reste affiché ; le lien, lui, n'a rien à pointer.
    mockApi(routesFor([LOCKED_ITEM], 3))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(
      await screen.findByText('3 signaux sont accessibles avec votre profil.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Voir mon premier signal' })).not.toBeInTheDocument()
  })
})

describe('moment d’activation — plan payant', () => {
  /* REVUE #2 — le compteur Découverte ne décrit QUE Découverte.
   *
   * Un compte peut payer avant d'avoir terminé son ciblage : il atteint
   * `/app/billing`, souscrit, puis revient finir l'onboarding. `GET /signals`
   * n'attribue alors aucun déblocage — le plan payé court-circuite
   * `_grant_discovery` — et `granted_signal_count` reste à zéro pendant que
   * les signaux, eux, sont ouverts.
   *
   * Lire ce compteur sans regarder le plan annonçait « aucun signal
   * correspondant » à un client qui venait d'en payer l'accès, avec les
   * signaux ouverts juste en dessous. */
  it('ne fabrique aucun faux zéro pour un compte payant', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /billing/status': { body: PAID_WITHOUT_GRANTS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    // Une confirmation positive, sans chiffre.
    expect(await screen.findByText('Vos signaux sont disponibles ci-dessous.')).toBeInTheDocument()
    expect(
      screen.queryByText('Aucun signal correspondant n’est disponible pour le moment.'),
    ).not.toBeInTheDocument()
    // Aucun compteur Découverte n'est emprunté.
    expect(screen.queryByText(/signaux sont accessibles avec votre profil/)).not.toBeInTheDocument()
    expect(screen.queryByText(/signal est accessible avec votre profil/)).not.toBeInTheDocument()

    // Le premier signal ouvert reste proposé.
    expect(screen.getByRole('link', { name: 'Voir mon premier signal' })).toHaveAttribute(
      'href',
      '/app/signals/sig_unlocked_1',
    )
  })

  it('n’invente pas de CTA payant quand la page ne contient rien de déverrouillé', async () => {
    mockApi({
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /billing/status': { body: PAID_WITHOUT_GRANTS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    expect(await screen.findByText('Vos signaux sont disponibles ci-dessous.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Voir mon premier signal' })).not.toBeInTheDocument()
  })

  it('n’affiche pas le panneau Découverte à un compte payant', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      'GET /billing/status': { body: PRO_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    await screen.findByText('Vos signaux sont disponibles ci-dessous.')
    // `PRO_STATUS` porte pourtant `granted_signal_count: 3` — un reliquat que
    // le bandeau ne doit pas relayer.
    expect(screen.queryByText(/3 signaux sont accessibles/)).not.toBeInTheDocument()
    expect(screen.queryByText('Votre découverte')).not.toBeInTheDocument()
  })
})

describe('moment d’activation — portée et durée', () => {
  it('reste un moment ponctuel : le bandeau ne redit pas le plan', async () => {
    mockApi(routesFor([UNLOCKED_ITEM, LOCKED_ITEM], 3))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    await screen.findByText('3 signaux sont accessibles avec votre profil.')
    const banner = activationSection()

    // L'explication durable appartient au panneau Découverte, pas ici.
    expect(banner.textContent).not.toMatch(/déblocage/i)
    expect(banner.textContent).not.toMatch(/offre|tarif|verrouill/i)
    expect(within(banner).queryByRole('link', { name: 'Voir les offres' })).not.toBeInTheDocument()

    // Et il précède le panneau Découverte, qui reste présent.
    const panel = screen.getByText('Votre découverte').closest('aside')!
    expect(banner.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('clôt la progression sur les signaux', async () => {
    mockApi(routesFor([UNLOCKED_ITEM], 3))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: ACTIVATION_ROUTE })

    await screen.findByText('3 signaux sont accessibles avec votre profil.')
    const progress = screen.getByRole('navigation', { name: 'Votre mise en route' })
    const steps = within(progress).getAllByRole('listitem')
    expect(steps[2]).toHaveAttribute('aria-current', 'step')
    expect(steps[0]).not.toHaveAttribute('aria-current')
  })

  it('consomme l’état de navigation et l’efface de l’historique', async () => {
    mockApi(routesFor([UNLOCKED_ITEM], 3))
    renderApp(
      <>
        <AppRoutes />
        <LocationStateProbe />
      </>,
      { session: AUTHENTICATED, route: ACTIVATION_ROUTE },
    )

    // Visible pour CE montage…
    expect(
      await screen.findByText('3 signaux sont accessibles avec votre profil.'),
    ).toBeInTheDocument()

    // …mais l'entrée d'historique ne le porte plus. Un rechargement de la page
    // repartirait donc d'un état vide, et le bandeau ne reviendrait pas.
    await waitFor(() => expect(screen.getByTestId('nav-state')).toHaveTextContent('null'))
  })

  it('n’affiche rien sur une arrivée ordinaire au feed', async () => {
    mockApi(routesFor([UNLOCKED_ITEM], 3))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByRole('heading', { name: 'Signaux récents' })
    await screen.findByText('Votre découverte')

    expect(screen.queryByText('Votre ciblage est prêt')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Voir mon premier signal' })).not.toBeInTheDocument()
    // Hors activation, rien n'ordonne les deux lectures.
    expect(recordedCalls.some((call) => call.url === '/billing/status')).toBe(true)
  })
})

/** Rend l'état de navigation courant, pour vérifier qu'il a bien été effacé. */
function LocationStateProbe() {
  const location = useLocation()
  return <p data-testid="nav-state">{JSON.stringify(location.state ?? null)}</p>
}
