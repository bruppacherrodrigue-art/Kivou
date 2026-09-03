import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { notifyTargetIcpChanged } from '../targeting/targetIcpEvents'
import {
  AUTHENTICATED,
  ICP,
  LOCKED_ITEM,
  PRO_STATUS,
  STALE_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  factualFallbackPresentation,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const PUBLISHED_HEADLINE = 'Attribution documentée pour le lot communal de voirie'
const PUBLISHED_AWARD_SUMMARY = 'La source officielle documente l’attribution de ce lot communal.'

const PUBLISHED_UNLOCKED_ITEM = {
  ...UNLOCKED_ITEM,
  presentation: factualFallbackPresentation({
    artifactId: '1'.repeat(64),
    headline: PUBLISHED_HEADLINE,
    awardSummary: PUBLISHED_AWARD_SUMMARY,
    headlineEvidenceRefs: ['source:notice:26-104412:headline'],
    awardSummaryEvidenceRefs: ['source:notice:26-104412:award-summary'],
  }),
}

describe('états indépendants des vues de référence', () => {
  it('conserve les signaux réels et annonce localement une panne de facturation', async () => {
    mockApi({
      'GET /signals': { body: feedPage([PUBLISHED_UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(
      await screen.findByText(PUBLISHED_UNLOCKED_ITEM.presentation.content.headline),
    ).toBeVisible()
    const priority = document.querySelector('.priority-card') as HTMLElement
    expect(within(priority).getAllByRole('alert')).toHaveLength(1)
    expect(within(priority).getByRole('alert')).toHaveTextContent(/offre/i)
    expect(within(priority).getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('explique la panne de facturation même quand aucun signal n’est accessible', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    const heading = await screen.findByRole('heading', {
      name: 'Aucun signal accessible pour le moment',
    })
    const priority = heading.closest('.priority-card') as HTMLElement
    expect(within(priority).getByRole('alert')).toHaveTextContent(/offre/i)
    expect(within(priority).getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  /* Sur la page Signaux, un signal déjà présent dans le feed chargé n'est
   * JAMAIS relu au clic (le tiroir se sert directement de la ligne) : seul un
   * signal ABSENT du feed déclenche `GET /signals/{key}`, et peut donc échouer
   * indépendamment de la liste. */
  it('conserve la liste utilisable quand le détail sélectionné échoue', async () => {
    mockApi({
      'GET /signals': { body: feedPage([STALE_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    const table = await screen.findByRole('table')
    expect(within(table).getByText(STALE_ITEM.company.name!)).toBeVisible()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Le signal n’a pas pu être chargé.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('conserve le contexte de facturation quand le feed échoue', async () => {
    mockApi({
      'GET /signals': {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(await screen.findByText('Pro', { selector: '.demo-mode-badge' })).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/informations.*chargées/i)
  })

  it('conserve le shell du compte quand les notifications échouent', async () => {
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
      'GET /notification-preferences': {
        status: 503,
        body: { detail: { code: 'notification_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { level: 1, name: 'Notifications' })).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/préférences/i)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('conserve la liste pendant une nouvelle lecture locale du détail', async () => {
    const user = userEvent.setup()
    let detailReads = 0
    let rejectRetry!: (reason: unknown) => void
    mockApi({
      'GET /signals': { body: feedPage([STALE_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => {
        detailReads += 1
        if (detailReads === 1) return { status: 503, body: { detail: { code: 'signal_unavailable' } } }
        return new Promise((_resolve, reject) => { rejectRetry = reject })
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Le signal n’a pas pu être chargé.')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))

    expect(await screen.findByRole('status', { name: 'Chargement du signal' })).toBeVisible()
    expect(screen.getByText(STALE_ITEM.company.name!)).toBeVisible()
    await act(async () => rejectRetry(new Error('detail retry failed')))
    expect(await screen.findByRole('alert')).toHaveTextContent('Le signal n’a pas pu être chargé.')
    expect(screen.getByText(STALE_ITEM.company.name!)).toBeVisible()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  /* Sur la page Signaux, le feed (le tableau) et le détail (le tiroir) sont
   * deux ressources indépendantes : une panne du feed ne bloque ni n'annonce
   * deux fois la même chose. Ici le feed échoue mais le signal demandé par la
   * route profonde reste lisible directement — une seule alerte, dans le
   * tableau, et le tiroir affiche normalement son contenu. */
  it('n’annonce qu’une fois une panne initiale du feed sur une route profonde', async () => {
    mockApi({
      'GET /signals': {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { level: 2, name: 'Voirie' })).toBeVisible()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Les informations n’ont pas pu être chargées.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  it('ne présente jamais un profil retenu comme actuel pendant ou après un refresh échoué', async () => {
    let reads = 0
    let rejectRefresh!: (reason: unknown) => void
    mockApi({
      'GET /target-icps': () => {
        reads += 1
        if (reads === 1) return { body: [ICP] }
        return new Promise((_resolve, reject) => { rejectRefresh = reject })
      },
      'GET /billing/status': { body: PRO_STATUS },
      'GET /me': { body: AUTHENTICATED.me },
    })

    renderApp(<AppRoutes />, { route: '/app/settings/profile', session: AUTHENTICATED })
    const profileLabel = `${ICP.label} · FR`
    expect(await screen.findByText(profileLabel)).toBeVisible()

    act(() => notifyTargetIcpChanged())
    expect(await screen.findByText('Chargement…', { selector: '.topbar-tools strong' })).toBeVisible()
    expect(screen.queryByText(profileLabel)).toBeNull()

    await act(async () => rejectRefresh(new Error('refresh failed')))
    expect(
      await screen.findByRole('button', { name: 'Réessayer le chargement du profil de ciblage' }),
    ).toBeVisible()
    expect(screen.queryByText(profileLabel)).toBeNull()
  })
})
