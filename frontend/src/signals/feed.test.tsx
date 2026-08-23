import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  STALE_ITEM,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
  recordedCalls,
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

  it('hiérarchise l’entreprise, le montant puis le marché avant l’analyse', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const company = await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    const card = company.closest('article')!
    const publishedAmount = within(card).getByText('Montant publié').parentElement!
    expect(publishedAmount.textContent?.replace(/\u202f|\u00a0/g, ' ')).toContain('1 240 000 €')
    const contract = within(card).getByText('Réfection de la voirie communale — lot 2')
    const analysis = within(card).getByRole('region', { name: 'Besoin plausible' })

    expect(company.compareDocumentPosition(publishedAmount) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(publishedAmount.compareDocumentPosition(contract) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(contract.compareDocumentPosition(analysis) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('sépare le fait public, le besoin plausible et la correspondance ICP', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const card = (await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })).closest(
      'article',
    )!
    expect(within(card).getByRole('region', { name: 'Fait public' })).toHaveTextContent(
      UNLOCKED_ITEM.event.headline,
    )
    expect(within(card).getByRole('region', { name: 'Besoin plausible' })).toHaveTextContent(
      UNLOCKED_ITEM.analysis.plausible_needs.items[0].statement!,
    )
    expect(
      within(card).getByRole('region', { name: 'Correspondance avec votre profil' }),
    ).toHaveTextContent(UNLOCKED_ITEM.analysis.fit.reasons[0])
  })

  it('rend la date et le timing fournis par le serveur sans les recalculer', async () => {
    const serverItem = {
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        date: '2026-02-03',
        age_days: 999,
        why_now: 'CALENDRIER SERVEUR — décision commerciale à examiner.',
      },
    }
    mockApi(feedWith([serverItem]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(await screen.findByText('3 février 2026')).toBeInTheDocument()
    expect(screen.getByText('CALENDRIER SERVEUR — décision commerciale à examiner.')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('999 jours')
  })

  it('conserve strictement l’ordre des signaux renvoyé par le serveur', async () => {
    const first = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_server_first',
      company: { ...UNLOCKED_ITEM.company, name: 'Première selon le serveur SA' },
      event: { ...UNLOCKED_ITEM.event, date: '2025-01-01', age_days: 600 },
    }
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_server_second',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième selon le serveur SA' },
      event: { ...UNLOCKED_ITEM.event, date: '2026-08-17', age_days: 1 },
    }
    mockApi(feedWith([first, second]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const cards = within(await screen.findByRole('list', { name: 'Liste des signaux' })).getAllByRole(
      'article',
    )
    expect(cards[0]).toHaveTextContent('Première selon le serveur SA')
    expect(cards[1]).toHaveTextContent('Deuxième selon le serveur SA')
  })

  it('envoie uniquement les filtres de fraîcheur et de profil disponibles', async () => {
    const otherIcp = { ...ICP, target_icp_id: 'icp_2', label: 'Location — Suisse' }
    mockApi({
      ...BASE,
      'GET /target-icps': { body: [ICP, otherIcp] },
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    })
    const user = userEvent.setup()
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })
    await screen.findByText('Constructions Bertrand SA')

    await user.click(screen.getByRole('radio', { name: 'Tout l’historique' }))
    await user.selectOptions(screen.getByLabelText('Profil actif'), 'icp_2')

    await waitFor(() => {
      const lastFeedCall = recordedCalls.filter((call) => call.url === '/signals').at(-1)!
      expect(lastFeedCall.search.get('freshness')).toBe('all')
      expect(lastFeedCall.search.get('target_icp_id')).toBe('icp_2')
      expect(lastFeedCall.search.get('winner')).toBeNull()
      expect(lastFeedCall.search.get('country')).toBeNull()
    })
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

    const cta = await screen.findByRole('link', { name: 'Gérer mon accès' })
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

  it('conserve les cartes et propose un réessai local si la page suivante échoue', async () => {
    let call = 0
    mockApi({
      ...BASE,
      'GET /signals': () => {
        call += 1
        return call === 1
          ? {
              body: feedPage([UNLOCKED_ITEM], {
                page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              }),
            }
          : { status: 503, body: { detail: { code: 'feed_unavailable' } } }
      },
    })
    const user = userEvent.setup()
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await user.click(await screen.findByRole('button', { name: 'Voir plus de signaux' }))

    expect(await screen.findByText('Constructions Bertrand SA')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Les signaux suivants n’ont pas pu être chargés',
    )
    expect(screen.getByRole('button', { name: 'Réessayer la page suivante' })).toBeInTheDocument()
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

  it('présente une occasion accessible avant les limites du plan Découverte', async () => {
    mockApi(feedWith([UNLOCKED_ITEM, LOCKED_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const opportunity = await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    const discoveryPanel = screen.getByText('Votre découverte').closest('aside')!
    expect(
      opportunity.compareDocumentPosition(discoveryPanel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
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

  it('conserve la même hiérarchie commerciale et le même niveau de certitude en anglais', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/signals',
      locale: 'en',
    })

    const company = await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    const card = company.closest('article')!
    expect(within(card).getByRole('region', { name: 'Public fact' })).toBeInTheDocument()
    expect(within(card).getByRole('region', { name: 'Plausible need' })).toBeInTheDocument()
    expect(within(card).getByRole('region', { name: 'Fit with your profile' })).toBeInTheDocument()
    expect(within(card).getByText(UNLOCKED_ITEM.event.why_now)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Sales opportunities' })).toBeInTheDocument()
  })
})
