import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { useLayoutEffect } from 'react'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import type { FeedPage } from '../api/types'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const FEED: FeedPage = {
  items: [UNLOCKED_ITEM, LOCKED_ITEM],
  total_returned: 2,
  page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
  excluded: { without_display_name: 0, by_freshness: 0 },
  read_at: '2026-08-18',
  freshness: 'new',
  language: 'fr',
  plan_code: 'discovery',
  policy: { feed: 'customer-feed-v0.1', recency: 'v1', paywall: 'kivou-paywall-v0.1' },
}

const ROUTES = {
  'GET /signals': { body: FEED },
  'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

const UNLOCKED_ROW_NAME = /^Constructions Bertrand SA — Réfection de la voirie communale/

function DetailCommitProbe({ onCommit }: { onCommit: (content: string) => void }) {
  const { pathname } = useLocation()

  useLayoutEffect(() => {
    if (!pathname.endsWith('/sig_unlocked_2')) return
    const panel = document.querySelector('[aria-label="Détail du signal sélectionné"]')
    onCommit(panel?.textContent ?? '')
  }, [onCommit, pathname])

  return null
}

function LocationProbe() {
  const { pathname, state } = useLocation()
  return (
    <div>
      <p data-testid="location-path">{pathname}</p>
      <pre data-testid="location-state">{JSON.stringify(state)}</pre>
    </div>
  )
}

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Historique précédent
    </button>
  )
}

describe('workspace partagé des signaux', () => {
  it('sélectionne un signal débloqué dans le workspace master-detail', async () => {
    const user = userEvent.setup()
    mockApi(ROUTES)
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    const signalLink = await within(workspace).findByRole('link', {
      name: UNLOCKED_ROW_NAME,
    })
    expect(signalLink).toHaveAttribute('href', '/app/signals/sig_unlocked_1')

    await user.click(signalLink)

    expect(screen.getByTestId('location-state')).toHaveTextContent(
      '"signalSelection":{"kind":"feed","key":"sig_unlocked_1"',
    )

    expect(
      await within(workspace).findByRole('list', { name: 'Liste des signaux' }),
    ).toBeInTheDocument()
    expect(
      within(workspace).getByRole('link', { name: UNLOCKED_ROW_NAME }),
    ).toHaveAttribute('aria-current', 'page')
    const detail = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(within(detail).getByText('Commune de Villeneuve')).toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
  })

  it('sélectionne un signal verrouillé sans demander son détail protégé', async () => {
    const user = userEvent.setup()
    mockApi(ROUTES)
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
        <HistoryControls />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    const lockedButton = await within(workspace).findByRole('button', {
      name: /signal verrouillé/i,
    })
    expect(lockedButton).toHaveAccessibleName(
      expect.stringContaining(LOCKED_ITEM.event.why_now),
    )
    await user.click(lockedButton)

    expect(screen.getByTestId('location-path')).toHaveTextContent(
      /^\/app\/signals\/sig_locked_1$/,
    )
    expect(screen.getByTestId('location-state')).toHaveTextContent(
      '"signalSelection":{"kind":"feed","key":"sig_locked_1"',
    )

    const detail = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(
      within(detail).getByRole('heading', { level: 2, name: LOCKED_ITEM.headline }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Signaux' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(within(detail).getByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    await waitFor(() => expect(lockedButton).toHaveFocus())
  })

  it('ouvre directement un signal débloqué dans le workspace partagé', async () => {
    mockApi(ROUTES)
    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_unlocked_1',
      session: AUTHENTICATED,
    })

    const workspace = await screen.findByTestId('signal-workspace')
    expect(
      await within(workspace).findByRole('list', { name: 'Liste des signaux' }),
    ).toBeInTheDocument()
    expect(
      await within(workspace).findByRole('region', { name: 'Détail du signal sélectionné' }),
    ).toBeInTheDocument()
    const signalLink = within(workspace).getByRole('link', {
      name: UNLOCKED_ROW_NAME,
    })
    expect(signalLink).toHaveAttribute('href', '/app/signals/sig_unlocked_1')
    expect(signalLink).toHaveAttribute('aria-current', 'page')
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
  })

  it('ignore une ancienne réponse détail après une nouvelle sélection', async () => {
    const user = userEvent.setup()
    const secondItem = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_unlocked_2',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième SA' },
      contract: {
        ...UNLOCKED_ITEM.contract,
        title: 'Deuxième marché public',
        buyer: { ...UNLOCKED_ITEM.contract.buyer!, name: 'Acheteur Deux' },
      },
    }
    const secondDetail = {
      ...UNLOCKED_DETAIL,
      ...secondItem,
      company_key: 'cmp_second_opaque',
    }
    let resolveFirst!: (value: { body: unknown }) => void
    let resolveSecond!: (value: { body: unknown }) => void
    mockApi({
      ...ROUTES,
      'GET /signals': { body: { ...FEED, items: [UNLOCKED_ITEM, secondItem] } },
      'GET /signals/sig_unlocked_1': () =>
        new Promise((resolve) => {
          resolveFirst = resolve
        }),
      'GET /signals/sig_unlocked_2': () =>
        new Promise((resolve) => {
          resolveSecond = resolve
        }),
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('link', { name: UNLOCKED_ROW_NAME }),
    )
    await waitFor(() => expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1))
    await user.click(within(workspace).getByRole('link', { name: /Deuxième SA/ }))
    await waitFor(() => expect(callsTo('/signals/sig_unlocked_2', 'GET')).toHaveLength(1))

    resolveSecond({ body: secondDetail })
    const panel = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect((await within(panel).findAllByText('Deuxième SA')).length).toBeGreaterThan(0)
    expect(within(panel).getByText('Acheteur Deux')).toBeInTheDocument()

    resolveFirst({ body: UNLOCKED_DETAIL })
    await waitFor(() => {
      expect(within(panel).getAllByText('Deuxième SA').length).toBeGreaterThan(0)
      expect(within(panel).queryByText('Commune de Villeneuve')).not.toBeInTheDocument()
    })
  })

  it('retire immédiatement le détail précédent quand la route sélectionne une nouvelle clé', async () => {
    const user = userEvent.setup()
    const onCommit = vi.fn()
    const secondItem = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_unlocked_2',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième SA' },
      contract: {
        ...UNLOCKED_ITEM.contract,
        title: 'Deuxième marché public',
        buyer: { ...UNLOCKED_ITEM.contract.buyer!, name: 'Acheteur Deux' },
      },
    }
    const secondDetail = {
      ...UNLOCKED_DETAIL,
      ...secondItem,
      company_key: 'cmp_second_opaque',
    }
    let resolveSecond!: (value: { body: unknown }) => void
    mockApi({
      ...ROUTES,
      'GET /signals': { body: { ...FEED, items: [UNLOCKED_ITEM, secondItem] } },
      'GET /signals/sig_unlocked_2': () =>
        new Promise((resolve) => {
          resolveSecond = resolve
        }),
    })
    renderApp(
      <>
        <AppRoutes />
        <DetailCommitProbe onCommit={onCommit} />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('link', { name: UNLOCKED_ROW_NAME }),
    )
    const panel = within(workspace).getByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(await within(panel).findByText('Commune de Villeneuve')).toBeInTheDocument()

    await user.click(within(workspace).getByRole('link', { name: /Deuxième SA/ }))

    expect(onCommit).toHaveBeenCalled()
    expect(onCommit.mock.lastCall?.[0]).not.toContain('Commune de Villeneuve')
    expect(within(panel).queryByText('Commune de Villeneuve')).not.toBeInTheDocument()
    expect(within(panel).getByRole('heading', { level: 2, name: 'Chargement…' })).toBeInTheDocument()

    await act(async () => {
      resolveSecond({ body: secondDetail })
    })
    expect(await within(panel).findByText('Acheteur Deux')).toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_2', 'GET')).toHaveLength(1)
  })

  it('focalise le détail à l’ouverture puis restaure la ligne au retour', async () => {
    const user = userEvent.setup()
    mockApi(ROUTES)
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const workspace = await screen.findByTestId('signal-workspace')
    const signalLink = await within(workspace).findByRole('link', {
      name: UNLOCKED_ROW_NAME,
    })
    await user.click(signalLink)

    const panel = within(workspace).getByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    await waitFor(() => expect(panel).toHaveFocus())

    await user.click(within(panel).getByRole('button', { name: 'Retour à la liste' }))
    await waitFor(() => expect(signalLink).toHaveFocus())
  })

  it('efface une sélection unlocked issue du feed quand le filtre suivant l’exclut', async () => {
    const user = userEvent.setup()
    const replacement = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_filter_replacement',
      company: { ...UNLOCKED_ITEM.company, name: 'Remplacement filtre SA' },
    }
    mockApi({
      ...ROUTES,
      'GET /signals': (request) =>
        request.search.get('freshness') === 'all'
          ? { body: { ...FEED, items: [replacement], total_returned: 1, freshness: 'all' } }
          : { body: { ...FEED, items: [UNLOCKED_ITEM], total_returned: 1 } },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('link', { name: UNLOCKED_ROW_NAME }),
    )
    const panel = within(workspace).getByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(await within(panel).findByText('Commune de Villeneuve')).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'Tout l’historique' }))

    expect(await screen.findByText('Remplacement filtre SA')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    expect(within(panel).queryByText('Commune de Villeneuve')).not.toBeInTheDocument()
    expect(panel).toHaveTextContent(
      'Sélectionnez un signal pour examiner ses faits et son analyse.',
    )
    expect(workspace.querySelector('[aria-current="page"]')).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
  })

  it('efface la sélection quand une nouvelle génération du filtre d’origine l’exclut', async () => {
    const user = userEvent.setup()
    let newFeedCalls = 0
    mockApi({
      ...ROUTES,
      'GET /signals': (request) => {
        const selectedFreshness = request.search.get('freshness')
        if (selectedFreshness === 'new') {
          newFeedCalls += 1
          return {
            body: {
              ...FEED,
              items: newFeedCalls === 1 ? [UNLOCKED_ITEM] : [],
              total_returned: newFeedCalls === 1 ? 1 : 0,
            },
          }
        }
        return {
          body: {
            ...FEED,
            items: [UNLOCKED_ITEM],
            total_returned: 1,
            freshness: 'recent_or_aging',
          },
        }
      },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('link', { name: UNLOCKED_ROW_NAME }),
    )
    const panel = within(workspace).getByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(await within(panel).findByText('Commune de Villeneuve')).toBeInTheDocument()
    expect(screen.getByTestId('location-state')).toHaveTextContent('"feedGeneration":1')

    await user.click(screen.getByRole('radio', { name: 'Récents et plus anciens' }))
    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(2))
    expect(
      await within(workspace).findByRole('link', { name: UNLOCKED_ROW_NAME }),
    ).toHaveAttribute('aria-current', 'page')

    await user.click(screen.getByRole('radio', { name: 'Nouveautés' }))

    expect(await screen.findByText('Aucun signal pertinent pour le moment')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    expect(within(panel).queryByText('Commune de Villeneuve')).not.toBeInTheDocument()
    expect(panel).toHaveTextContent(
      'Sélectionnez un signal pour examiner ses faits et son analyse.',
    )
    expect(workspace.querySelector('[aria-current="page"]')).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
  })

  it('reprend la génération portée par une entrée feed restaurée', async () => {
    mockApi({
      ...ROUTES,
      'GET /signals': { body: { ...FEED, items: [], total_returned: 0 } },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      {
        route: {
          pathname: '/app/signals/sig_unlocked_1',
          state: {
            signalSelection: {
              kind: 'feed',
              key: 'sig_unlocked_1',
              feedGeneration: 7,
              query: { freshness: 'new', targetIcpId: '' },
            },
          },
        },
        session: AUTHENTICATED,
      },
    )

    expect(await screen.findByText('Aucun signal pertinent pour le moment')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(0)
  })

  it('efface une sélection locked route-backed quand le filtre suivant l’exclut', async () => {
    const user = userEvent.setup()
    mockApi({
      ...ROUTES,
      'GET /signals': (request) =>
        request.search.get('freshness') === 'all'
          ? { body: { ...FEED, items: [UNLOCKED_ITEM], total_returned: 1, freshness: 'all' } }
          : { body: { ...FEED, items: [LOCKED_ITEM], total_returned: 1 } },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('button', { name: /signal verrouillé/i }),
    )
    const panel = within(workspace).getByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(within(panel).getByText(LOCKED_ITEM.headline)).toBeInTheDocument()
    expect(screen.getByTestId('location-path')).toHaveTextContent(
      /^\/app\/signals\/sig_locked_1$/,
    )

    await user.click(screen.getByRole('radio', { name: 'Tout l’historique' }))

    expect(await screen.findByText('Constructions Bertrand SA')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    expect(within(panel).queryByText(LOCKED_ITEM.headline)).not.toBeInTheDocument()
    expect(panel).toHaveTextContent(
      'Sélectionnez un signal pour examiner ses faits et son analyse.',
    )
    expect(workspace.querySelector('[aria-current="page"]')).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
  })

  it('restaure la provenance de chaque entrée historique avant d’évaluer un filtre', async () => {
    const user = userEvent.setup()
    const secondLocked = {
      ...LOCKED_ITEM,
      signal_id: 'sig_locked_2',
      headline: 'Un second marché public vient d’être attribué.',
      event: {
        ...LOCKED_ITEM.event,
        why_now: 'Le second marché exige une prise de contact immédiate.',
      },
    }
    mockApi({
      ...ROUTES,
      'GET /signals': (request) =>
        request.search.get('freshness') === 'all'
          ? { body: { ...FEED, items: [secondLocked], total_returned: 1, freshness: 'all' } }
          : { body: { ...FEED, items: [LOCKED_ITEM, secondLocked], total_returned: 2 } },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
        <HistoryControls />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('button', { name: new RegExp(LOCKED_ITEM.headline) }),
    )
    expect(screen.getByTestId('location-state')).toHaveTextContent('"key":"sig_locked_1"')

    await user.click(
      within(workspace).getByRole('button', { name: new RegExp(secondLocked.headline) }),
    )
    expect(screen.getByTestId('location-state')).toHaveTextContent('"key":"sig_locked_2"')

    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(
        /^\/app\/signals\/sig_locked_1$/,
      ),
    )
    expect(screen.getByTestId('location-state')).toHaveTextContent('"key":"sig_locked_1"')

    await user.click(screen.getByRole('radio', { name: 'Tout l’historique' }))

    expect(await screen.findByText(secondLocked.headline)).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    expect(
      within(workspace).getByText(
        'Sélectionnez un signal pour examiner ses faits et son analyse.',
      ),
    ).toBeInTheDocument()
    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
    expect(callsTo('/signals/sig_locked_2', 'GET')).toHaveLength(0)
  })

  it('conserve un deep link absent du premier feed et laisse le backend détail décider', async () => {
    const user = userEvent.setup()
    const deepDetail = {
      ...UNLOCKED_DETAIL,
      signal_id: 'sig_deep_unknown',
      company: { ...UNLOCKED_DETAIL.company, name: 'Deep Link SA' },
    }
    mockApi({
      ...ROUTES,
      'GET /signals': { body: { ...FEED, items: [UNLOCKED_ITEM], total_returned: 1 } },
      'GET /signals/sig_deep_unknown': { body: deepDetail },
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/app/signals/sig_deep_unknown', session: AUTHENTICATED },
    )

    const workspace = await screen.findByTestId('signal-workspace')
    const panel = within(workspace).getByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect((await within(panel).findAllByText('Deep Link SA')).length).toBeGreaterThan(0)
    expect(screen.getByTestId('location-path')).toHaveTextContent(
      '/app/signals/sig_deep_unknown',
    )
    expect(callsTo('/signals/sig_deep_unknown', 'GET')).toHaveLength(1)

    await user.click(within(panel).getByRole('button', { name: 'Retour à la liste' }))
    await waitFor(() =>
      expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/),
    )
    expect(callsTo('/signals/sig_deep_unknown', 'GET')).toHaveLength(1)
  })

  it('garde à 1024 px une colonne détail flexible sans minimum combiné débordant', () => {
    const css = readFileSync(join(process.cwd(), 'src/pages/SignalsFeed.module.css'), 'utf8')
    expect(css).toContain(
      'grid-template-columns: minmax(16rem, 0.82fr) minmax(0, 1.48fr);',
    )
    expect(css).not.toContain(
      'grid-template-columns: minmax(18rem, 0.82fr) minmax(28rem, 1.48fr);',
    )
  })

  it('garde la liste visible et réessaie localement un détail en erreur', async () => {
    const user = userEvent.setup()
    let detailCalls = 0
    mockApi({
      ...ROUTES,
      'GET /signals/sig_unlocked_1': () => {
        detailCalls += 1
        return detailCalls === 1
          ? { status: 503, body: { detail: { code: 'signal_unavailable' } } }
          : { body: UNLOCKED_DETAIL }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('link', { name: UNLOCKED_ROW_NAME }),
    )

    const list = within(workspace).getByRole('list', { name: 'Liste des signaux' })
    expect(within(list).getByText('Constructions Bertrand SA')).toBeInTheDocument()
    const panel = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    await user.click(await within(panel).findByRole('button', { name: 'Réessayer' }))

    expect(await within(panel).findByText('Commune de Villeneuve')).toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(2)
    expect(within(list).getByText('Constructions Bertrand SA')).toBeInTheDocument()
  })

  it('compose une ligne dense avec le panneau sans dupliquer les longues preuves', async () => {
    mockApi({
      ...ROUTES,
      'GET /signals': { body: { ...FEED, items: [UNLOCKED_ITEM], total_returned: 1 } },
    })
    renderApp(<AppRoutes />, { route: '/app/signals/sig_unlocked_1', session: AUTHENTICATED })

    const workspace = await screen.findByTestId('signal-workspace')
    const list = within(workspace).getByRole('list', { name: 'Liste des signaux' })
    const row = within(list).getByRole('article')
    expect(row).toHaveTextContent('Constructions Bertrand SA')
    expect(row).toHaveTextContent('Réfection de la voirie communale — lot 2')
    expect(row.textContent?.replace(/\u202f|\u00a0/g, ' ')).toContain('1 240 000')
    expect(row).toHaveTextContent('4 août 2026')
    expect(row).not.toHaveTextContent('Preuves des faits publiés')
    expect(
      within(workspace).getByRole('region', { name: 'Détail du signal sélectionné' }),
    ).toBeInTheDocument()
  })
})
