import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import type { UnlockedFeedItem } from '../api/types'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

/* L'écran « Signaux » : un tableau dense, une ligne de filtres, un tiroir.
 *
 * Ces tests interrogent ce que la page ENVOIE (les paramètres de requête) et
 * ce qu'elle MONTRE — jamais son état interne. Un filtre qui n'atteint pas le
 * serveur n'est pas un filtre, et un compteur qui n'apparaît pas n'existe pas.
 */

const NOW = new Date('2026-09-03T12:00:00Z')

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function isoDaysAgo(days: number): string {
  return new Date(NOW.getTime() - days * 86_400_000).toISOString().slice(0, 10)
}

const BASE = {
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /billing/plans': { body: CATALOGUE },
  'GET /target-icps': { body: [ICP] },
  [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
}

function feedWith(items: unknown[], overrides = {}) {
  return {
    ...BASE,
    'GET /signals': { body: feedPage(items as never[], overrides) },
  }
}

/** Un signal débloqué dérivé de la fixture, pour varier une seule chose. */
function item(
  signalId: string,
  patch: {
    name?: string | null
    title?: string
    amount?: string | null
    date?: string
    subdivision?: string
    locality?: string | null
    status?: UnlockedFeedItem['status']
  } = {},
): UnlockedFeedItem {
  return {
    ...UNLOCKED_ITEM,
    signal_id: signalId,
    status: patch.status ?? UNLOCKED_ITEM.status,
    company: { ...UNLOCKED_ITEM.company, name: patch.name ?? UNLOCKED_ITEM.company.name },
    factual_display: {
      ...UNLOCKED_ITEM.factual_display,
      date: { ...UNLOCKED_ITEM.factual_display.date, value: patch.date ?? '2026-08-04' },
    },
    contract: {
      ...UNLOCKED_ITEM.contract,
      lot_title: patch.title ?? UNLOCKED_ITEM.contract.lot_title,
      amount: patch.amount === undefined
        ? UNLOCKED_ITEM.contract.amount
        : patch.amount === null
          ? null
          : { value: patch.amount, currency: 'EUR' },
      location: {
        ...UNLOCKED_ITEM.contract.location!,
        locality: patch.locality === undefined ? 'Villeneuve' : patch.locality,
        subdivision_code: patch.subdivision ?? 'FR-31',
      },
    },
  }
}

async function table(): Promise<HTMLElement> {
  return screen.findByRole('table')
}

function lastFeedCall() {
  const calls = callsTo('/signals', 'GET')
  return calls[calls.length - 1]
}

function normalise(text: string): string {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

describe('écran Signaux — tableau dense', () => {
  it('rend un tableau et ses six colonnes, une ligne par signal', async () => {
    mockApi(feedWith([item('sig_a'), item('sig_b', { name: 'Amiaud SARL' }), item('sig_c', { name: 'ID Verde' })]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    const headers = within(grid).getAllByRole('columnheader').map((cell) => cell.textContent)
    expect(headers).toEqual(['Date', 'Titulaire', 'Objet', 'Montant', 'Lieu', 'Match'])
    expect(within(grid).getAllByRole('row')).toHaveLength(4)
    expect(within(grid).getByText('Amiaud SARL')).toBeInTheDocument()
    expect(within(grid).getByText('ID Verde')).toBeInTheDocument()
  })

  it('tronque l’objet à 60 caractères et conserve le texte complet en infobulle', async () => {
    const long = 'Réfection complète de la voirie communale et des réseaux enterrés du centre-bourg'
    mockApi(feedWith([item('sig_a', { title: long })]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    const cell = within(grid).getByTitle(long)
    expect(cell.textContent).toBe(`${long.slice(0, 60)}…`)
    expect(cell.textContent).not.toBe(long)
  })

  it('affiche le lieu en clair et jamais un code de subdivision', async () => {
    mockApi(feedWith([item('sig_a', { locality: 'Nice', subdivision: 'FR-06' })]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    expect(within(grid).getByText('Nice')).toBeInTheDocument()
    expect(grid.textContent).not.toContain('FR-06')
  })

  it('rend un signal verrouillé en ligne neutre et renvoie vers la facturation', async () => {
    mockApi(feedWith([LOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    const row = within(grid).getAllByRole('row')[1]
    expect(row.textContent).toContain('—')
    expect(row.textContent).toContain('Votre accès actuel conserve cet aperçu')

    await userEvent.click(within(row).getByRole('button'))
    await waitFor(() => expect(callsTo('/billing/plans', 'GET').length).toBeGreaterThan(0))
  })
})

describe('écran Signaux — filtres', () => {
  it('porte les compteurs sur le segment et répète status= dans la requête', async () => {
    mockApi(feedWith([item('sig_a')], { counts: { new: 12, saved: 5, contacted: 3, ignored: 7 } }))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await table()
    expect(lastFeedCall().search.getAll('status')).toEqual(['new'])
    expect(screen.getByRole('button', { name: /Nouveaux\s+12/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sauvés\s+5/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Contactés\s+3/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ignorés' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tous' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Sauvés/ }))
    await waitFor(() => expect(lastFeedCall().search.getAll('status')).toEqual(['saved']))

    await userEvent.click(screen.getByRole('button', { name: 'Tous' }))
    await waitFor(() =>
      expect(lastFeedCall().search.getAll('status')).toEqual(['new', 'saved', 'contacted', 'ignored']))
  })

  it('garde les derniers compteurs connus quand le serveur ne les fournit plus', async () => {
    let calls = 0
    mockApi({
      ...BASE,
      'GET /signals': () => {
        calls += 1
        return {
          body: feedPage([item('sig_a')], calls === 1
            ? { counts: { new: 12, saved: 5, contacted: 3, ignored: 0 } }
            : { counts_available: false, counts: { new: 0, saved: 0, contacted: 0, ignored: 0 } }),
        }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByRole('button', { name: /Nouveaux\s+12/ })
    await userEvent.click(screen.getByRole('button', { name: /Sauvés/ }))
    await waitFor(() => expect(lastFeedCall().search.getAll('status')).toEqual(['saved']))
    expect(screen.getByRole('button', { name: /Nouveaux\s+12/ })).toBeInTheDocument()
  })

  it('désactive le filtre secteur et l’explique quand l’accès l’interdit', async () => {
    mockApi(feedWith([item('sig_a')]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await table()
    const sector = screen.getByLabelText('Secteur')
    expect(sector).toBeDisabled()
    const describedBy = sector.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy!)?.textContent)
      .toContain('Ce filtre n’est pas inclus dans votre accès actuel.')
  })

  it('envoie le préfixe CPV quand le filtre secteur est ouvert', async () => {
    mockApi(feedWith([item('sig_a')], {
      filter_access: { date_range: true, country: true, subdivision: true, status: true, sector: true },
    }))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await table()
    await userEvent.type(screen.getByLabelText('Secteur'), '4523')
    await waitFor(() => expect(lastFeedCall().search.get('cpv_prefix')).toBe('4523'))
  })

  it('traduit la période choisie en date_from', async () => {
    mockApi(feedWith([item('sig_a')]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await table()
    expect(lastFeedCall().search.get('date_from')).toBe(isoDaysAgo(30))

    await userEvent.selectOptions(screen.getByLabelText('Période'), '7')
    await waitFor(() => expect(lastFeedCall().search.get('date_from')).toBe(isoDaysAgo(7)))

    await userEvent.selectOptions(screen.getByLabelText('Période'), 'all')
    await waitFor(() => expect(lastFeedCall().search.get('date_from')).toBeNull())
  })

  it('envoie la zone en subdivision_code', async () => {
    mockApi(feedWith([item('sig_a')]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await table()
    await userEvent.type(screen.getByLabelText('Zone'), 'FR-06')
    await waitFor(() => expect(lastFeedCall().search.get('subdivision_code')).toBe('FR-06'))
  })

  it('filtre côté client sur le montant minimum, sans nouvel appel', async () => {
    mockApi(feedWith([
      item('sig_a', { name: 'Grand chantier SA', amount: '1240000' }),
      item('sig_b', { name: 'Petit lot SARL', amount: '90000' }),
    ]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    expect(within(grid).getAllByRole('row')).toHaveLength(3)
    const before = callsTo('/signals', 'GET').length

    await userEvent.type(screen.getByLabelText('Montant minimum'), '100000')
    await waitFor(() => expect(within(grid).getAllByRole('row')).toHaveLength(2))
    expect(within(grid).queryByText('Petit lot SARL')).toBeNull()
    expect(callsTo('/signals', 'GET')).toHaveLength(before)
  })

  it('filtre côté client sur la recherche, sans accent ni casse', async () => {
    mockApi(feedWith([
      item('sig_a', { name: 'Éolienne Sud SARL' }),
      item('sig_b', { name: 'Amiaud SARL' }),
    ]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    const before = callsTo('/signals', 'GET').length

    await userEvent.type(screen.getByLabelText(/Rechercher/), 'eolienne')
    await waitFor(() => expect(within(grid).getAllByRole('row')).toHaveLength(2))
    expect(within(grid).getByText('Éolienne Sud SARL')).toBeInTheDocument()
    expect(callsTo('/signals', 'GET')).toHaveLength(before)
  })
})

describe('écran Signaux — pagination et compteur', () => {
  it('annonce le nombre de signaux chargés, avec « + » quand il en reste', async () => {
    mockApi(feedWith([item('sig_a'), item('sig_b'), item('sig_c')], {
      page: { limit: 20, offset: 0, has_more: true, scan_truncated: false, next_cursor: 'cur1' },
    }))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await table()
    expect(await screen.findByText('3+ signaux')).toBeInTheDocument()
  })

  it('« Charger plus » enchaîne le curseur et fusionne sans doublon', async () => {
    mockApi({
      ...BASE,
      'GET /signals': (request) => {
        if (request.search.get('cursor') === 'cur1') {
          return {
            body: feedPage([item('sig_a'), item('sig_b', { name: 'Amiaud SARL' })], {
              page: { limit: 20, offset: 0, has_more: false, scan_truncated: false, next_cursor: null },
            }),
          }
        }
        return {
          body: feedPage([item('sig_a')], {
            page: { limit: 20, offset: 0, has_more: true, scan_truncated: false, next_cursor: 'cur1' },
          }),
        }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const grid = await table()
    expect(within(grid).getAllByRole('row')).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: 'Charger plus' }))
    await waitFor(() => expect(within(grid).getAllByRole('row')).toHaveLength(3))
    expect(lastFeedCall().search.get('cursor')).toBe('cur1')
    expect(within(grid).getAllByText('Constructions Bertrand SA')).toHaveLength(1)
    expect(screen.getByText('2 signaux')).toBeInTheDocument()
  })
})

describe('écran Signaux — tiroir', () => {
  it('ouvre le tiroir au clic sur une ligne et écrit la clé dans l’URL', async () => {
    mockApi(feedWith([item(UNLOCKED_ITEM.signal_id)]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals?zone=FR-31' })

    const grid = await table()
    await userEvent.click(within(grid).getByRole('button', { name: 'Constructions Bertrand SA' }))

    const drawer = await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    const panel = drawer.closest('aside')!
    expect(within(panel).getByText('Nouveau')).toBeInTheDocument()
    expect(within(panel).getByLabelText(/Correspondance \d\/4/)).toBeInTheDocument()
    expect(within(panel).getByText('Acheteur')).toBeInTheDocument()
    expect(within(panel).getByText('Commune de Villeneuve')).toBeInTheDocument()
    expect(within(panel).getByText('Attribué le')).toBeInTheDocument()
    expect(within(panel).getByText('CPV')).toBeInTheDocument()
    expect(within(panel).getByText('45233120')).toBeInTheDocument()
    expect(within(panel).getByText('Pourquoi ça vous concerne')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: /Source : BOAMP 26-104412/ })).toBeInTheDocument()
    // La ligne sélectionnée reste marquée, et les filtres survivent.
    expect(within(grid).getAllByRole('row')[1]).toHaveAttribute('aria-current', 'true')
    expect(screen.getByLabelText('Zone')).toHaveValue('FR-31')
  })

  it('résout un lien profond par signals.detail quand la ligne n’est pas chargée', async () => {
    mockApi(feedWith([]))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
  })

  it('Échap referme le tiroir en conservant les filtres', async () => {
    mockApi(feedWith([item(UNLOCKED_ITEM.signal_id)]))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}?zone=FR-31`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    await userEvent.keyboard('{Escape}')

    await waitFor(() => expect(screen.getByText('Sélectionnez un signal')).toBeInTheDocument())
    expect(screen.getByLabelText('Zone')).toHaveValue('FR-31')
  })
})

describe('écran Signaux — actions', () => {
  const COUNTS = { new: 4, saved: 1, contacted: 0, ignored: 0 }

  function openedFeed(routes: Record<string, unknown> = {}) {
    return {
      ...feedWith([item(UNLOCKED_ITEM.signal_id)], { counts: COUNTS }),
      ...routes,
    }
  }

  it('« Marquer contacté » bascule la ligne, le tiroir et les compteurs', async () => {
    mockApi(openedFeed({
      [`POST /signals/${UNLOCKED_ITEM.signal_id}/contacted`]: { body: { recorded: true } },
    }))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    await userEvent.click(screen.getByRole('button', { name: 'Marquer contacté' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Contacté ✓' })).toBeInTheDocument())
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/contacted`, 'POST')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Nouveaux\s+3/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Contactés\s+1/ })).toBeInTheDocument()
    // Le tiroir lit la LIGNE chargée, pas une copie : son état prouve que la
    // ligne du tableau a bien changé de statut.
    expect(within(await table()).getAllByRole('row')).toHaveLength(2)
  })

  it('« Sauver » écrit une pertinence positive', async () => {
    mockApi(openedFeed({
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/feedback`]: { body: { relevance: 'relevant' } },
    }))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    await userEvent.click(screen.getByRole('button', { name: 'Sauver' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sauvé ✓' })).toBeInTheDocument())
    const call = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/feedback`, 'PUT')[0]
    expect(call.body).toMatchObject({ relevance: 'relevant' })
    expect(screen.getByRole('button', { name: /Sauvés\s+2/ })).toBeInTheDocument()
  })

  it('« Ignorer » écrit une pertinence négative motivée', async () => {
    mockApi(openedFeed({
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/feedback`]: { body: { relevance: 'not_relevant' } },
    }))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    await userEvent.click(screen.getByRole('button', { name: 'Ignorer' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Ignoré ✓' })).toBeInTheDocument())
    const call = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/feedback`, 'PUT')[0]
    expect(call.body).toMatchObject({ relevance: 'not_relevant', reason: 'other' })
    // La ligne ne quitte pas l'écran : elle ne correspond plus au segment,
    // mais la faire disparaître sous le curseur serait une trahison.
    expect(within(await table()).getAllByRole('row')).toHaveLength(2)
  })

  it('restaure l’état et annonce l’erreur quand l’action échoue', async () => {
    mockApi(openedFeed({
      [`POST /signals/${UNLOCKED_ITEM.signal_id}/contacted`]: { status: 500, body: { detail: 'boom' } },
    }))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    await userEvent.click(screen.getByRole('button', { name: 'Marquer contacté' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Marquer contacté' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Contacté ✓' })).toBeNull()
    expect(screen.getByRole('button', { name: /Nouveaux\s+4/ })).toBeInTheDocument()
  })
})

describe('écran Signaux — mobile et copy', () => {
  it('sous 900 px, la colonne Lieu disparaît et le tiroir devient une feuille', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query === '(max-width: 899px)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    }))
    mockApi(feedWith([item(UNLOCKED_ITEM.signal_id)]))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    // La feuille est modale : Radix masque le reste du document à
    // l'accessibilité, le tableau se lit donc par le DOM.
    const grid = await waitFor(() => {
      const found = document.querySelector('table')
      if (!found) throw new Error('tableau absent')
      return found
    })
    const headers = [...grid.querySelectorAll('thead th')].map((cell) => cell.textContent)
    expect(headers).toEqual(['Date', 'Titulaire', 'Objet', 'Montant', 'Match'])
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(within(screen.getByRole('dialog')).getByRole('heading', { level: 2, name: 'Voirie' }))
      .toBeInTheDocument()
  })

  it('n’emploie aucun mot du copy interdit', async () => {
    mockApi(feedWith([item(UNLOCKED_ITEM.signal_id), LOCKED_ITEM]))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    const text = normalise(document.body.textContent ?? '')
    for (const forbidden of [
      'documente',
      'non publie',
      'resolution incomplete',
      'faits publies',
      'contact non confirme',
    ]) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('n’emploie pas le vocabulaire de l’ancienne page dans la surface Signaux', async () => {
    mockApi(feedWith([item(UNLOCKED_ITEM.signal_id), LOCKED_ITEM]))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    // La coque (barre du haut, navigation) garde son propre vocabulaire ; c'est
    // la SURFACE de la page qui est sous contrat.
    const page = document.querySelector('[data-page="signals"]')
    expect(page).not.toBeNull()
    const text = normalise(page!.textContent ?? '')
    for (const forbidden of ['occasion', 'ciblage', 'attribution', 'deblocage', 'lecture']) {
      expect(text).not.toContain(forbidden)
    }
  })
})
