import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  STALE_ITEM,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

/* SPEC-015 §50 — les huit vérifications du feed. */

afterEach(() => vi.unstubAllGlobals())

const BASE = {
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

function feedWith(items: unknown[], overrides = {}) {
  return {
    ...BASE,
    'GET /signals': { body: feedPage(items as never[], overrides) },
  }
}

describe('feed de signaux', () => {
  it('rend l’entreprise gagnante sur un signal débloqué', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(await screen.findByText('Constructions Bertrand SA')).toBeInTheDocument()
    expect(screen.getByText('Réfection de la voirie communale — lot 2')).toBeInTheDocument()
  })

  it('ne rend JAMAIS l’identité du gagnant sur un aperçu verrouillé', async () => {
    mockApi(feedWith([LOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByText('Un marché public vient d’être attribué.')

    const page = document.body.textContent ?? ''
    // Ni le nom, ni l'identifiant, ni l'intitulé du marché, ni l'URL source.
    expect(page).not.toContain('Constructions Bertrand')
    expect(page).not.toContain('12345678900011')
    expect(page).not.toContain('Réfection de la voirie')
    expect(page).not.toContain('boamp.fr')
    expect(page).not.toContain('26-104412')
    // Le montant exact est remplacé par un ordre de grandeur.
    expect(page).not.toContain('1240000')
    expect(page).toContain('250 k à 1 M')
  })

  it('affiche l’appel à l’action d’un signal verrouillé', async () => {
    mockApi(feedWith([LOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const cta = await screen.findByRole('link', { name: /Déverrouiller Kivou/ })
    expect(cta).toHaveAttribute('href', '/app/billing')
    expect(screen.getByText('Verrouillé')).toBeInTheDocument()
    // Jamais une formulation d'extraction de données cachées.
    expect(document.body.textContent).not.toMatch(/révéler|reveal|données cachées/i)
  })

  it('ne dit jamais qu’un signal ancien vient d’être remporté', async () => {
    mockApi(feedWith([STALE_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByText('Travaux Delmas SARL')
    const page = document.body.textContent ?? ''
    // La phrase vient de `recency.claim` ; le frontend ne la reformule pas.
    expect(page).toContain('a remporté un marché public en novembre 2025.')
    expect(page).not.toMatch(/vient de remporter/)
    expect(page).not.toMatch(/nouveau contrat/i)
  })

  it('rend un état vide utile plutôt qu’une liste blanche', async () => {
    mockApi(feedWith([]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', { name: 'Aucun signal pertinent pour le moment' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Kivou continue de surveiller/)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Voir aussi les signaux plus anciens' }),
    ).toBeInTheDocument()
  })

  it('ne duplique aucune carte lorsque la pagination recouvre la page précédente', async () => {
    const second = { ...UNLOCKED_ITEM, signal_id: 'sig_unlocked_2' }
    let call = 0
    mockApi({
      ...BASE,
      'GET /signals': () => {
        call += 1
        return call === 1
          ? {
              body: feedPage([UNLOCKED_ITEM, second], {
                page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              }),
            }
          : {
              // La seconde page RENVOIE le même premier signal : la fraîcheur a
              // été réévaluée entre les deux appels.
              body: feedPage([second, { ...UNLOCKED_ITEM, signal_id: 'sig_unlocked_3' }], {
                page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
              }),
            }
      },
    })
    const user = userEvent.setup()
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByRole('list', { name: 'Liste des signaux' })
    await user.click(screen.getByRole('button', { name: 'Voir plus de signaux' }))

    // On compte les CARTES (`<article>`), pas les `<li>` : la ligne de méta
    // d'une carte est elle-même une liste, et compter les `listitem`
    // additionnerait les deux niveaux.
    await waitFor(() => {
      const list = screen.getByRole('list', { name: 'Liste des signaux' })
      expect(within(list).getAllByRole('article')).toHaveLength(3)
    })

    const ids = screen
      .getByRole('list', { name: 'Liste des signaux' })
      .querySelectorAll('article')
    expect(ids).toHaveLength(3)
  })

  it('formate les montants dans la locale du compte, pas dans celle du navigateur', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals', locale: 'fr' })

    await screen.findByText('Constructions Bertrand SA')
    const page = document.body.textContent ?? ''
    // 1 240 000 € en français : espaces insécables, symbole après le nombre.
    // La forme anglaise « 1,240,000 » serait une fuite de la locale du poste.
    expect(page).not.toContain('1,240,000')
    expect(page.replace(/\u202f|\u00a0/g, ' ')).toContain('1 240 000')
  })

  it('n’affiche aucune preuve documentaire sur une carte de feed', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByText('Constructions Bertrand SA')
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Preuve documentaire')
    expect(page).not.toContain('Le marché est attribué à')
    expect(screen.queryByRole('link', { name: /Ouvrir la source/ })).not.toBeInTheDocument()
  })

  it('n’expose aucun vocabulaire interne ni système d’acquisition', async () => {
    mockApi(feedWith([UNLOCKED_ITEM, LOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByText('Constructions Bertrand SA')
    const page = (document.body.textContent ?? '').toLowerCase()

    for (const forbidden of [
      'acquisition engine',
      'apollo',
      'instantly',
      'mailbox',
      'délivrabilité',
      'campagne',
      'séquence',
      'mrr',
      'churn',
      'need graph',
      'benchmark',
      'opportunity_key',
      'materialized',
      'signal_key',
      'scan_truncated',
    ]) {
      expect(page).not.toContain(forbidden)
    }
  })

  it('explique l’état Découverte sans promettre un renouvellement', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByText(/3 signaux réels débloqués/)
    expect(screen.getByText(/acquis définitivement/)).toBeInTheDocument()

    // La copie NIE explicitement le renouvellement ; ce qui est interdit, c'est
    // de le promettre. L'assertion vise donc l'affirmation, pas le mot.
    const page = (document.body.textContent ?? '').toLowerCase()
    expect(page).toContain('ne se renouvellent pas')
    expect(page).not.toMatch(/renouvel\w+ (chaque|tous les|automatiquement)/)
    expect(page).not.toMatch(/3 signaux (gratuits )?(par|chaque) (jour|mois|semaine)/)
  })

  it('affiche le nombre RÉEL de déblocages quand il est inférieur à trois', async () => {
    mockApi({
      ...feedWith([UNLOCKED_ITEM]),
      'GET /billing/status': {
        body: {
          ...DISCOVERY_STATUS,
          discovery: { granted_signal_count: 1, remaining_slots: 2, limit: 3 },
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(await screen.findByText('1 signal réel débloqué')).toBeInTheDocument()
    expect(screen.getByText(/il reste 2 déblocages/)).toBeInTheDocument()
  })

  it('propose de configurer un profil quand aucun n’est actif', async () => {
    mockApi({
      ...BASE,
      'GET /target-icps': { body: [{ ...ICP, status: 'draft' }] },
      'GET /signals': { body: feedPage([]) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', { name: 'Aucun profil de ciblage actif' }),
    ).toBeInTheDocument()
  })

  it('rend l’erreur de chargement comme un état produit, jamais comme une trace', async () => {
    mockApi({
      ...BASE,
      'GET /signals': { status: 500, body: { detail: 'Traceback: sqlalchemy.exc.OperationalError' } },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const alert = await screen.findByRole('alert')
    expect(alert).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('Traceback')
    expect(document.body.textContent).not.toContain('sqlalchemy')
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
  })
})
