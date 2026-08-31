import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import type { CompanyProfile, UnlockedDetail, UnlockedFeedItem } from '../api/types'
import {
  AUTHENTICATED,
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNLOCKED_DETAIL as BASE_DETAIL,
  UNLOCKED_ITEM as BASE_ITEM,
  callsTo,
  factualFallbackPresentation,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const FIRST_PRESENTATION = factualFallbackPresentation({
  artifactId: 'a'.repeat(64),
  headline: 'Attribution documentée à Constructions Bertrand SA',
  awardSummary: 'La commune a attribué des travaux documentés à Constructions Bertrand SA.',
  headlineEvidenceRefs: ['source:first-headline'],
  awardSummaryEvidenceRefs: ['source:first-award-summary'],
})
const FIRST_ITEM: UnlockedFeedItem = {
  ...BASE_ITEM,
  company_key: COMPANY_PROFILE.company_key,
  presentation: FIRST_PRESENTATION,
  contract: { ...BASE_ITEM.contract, title: 'TITRE ADMINISTRATIF BRUT INTERDIT' },
  event: {
    ...BASE_ITEM.event,
    headline: 'HEADLINE EVENT INTERDITE',
    why_now: 'URGENCE EVENT INTERDITE',
  },
  analysis: {
    ...BASE_ITEM.analysis,
    fit: { ...BASE_ITEM.analysis.fit, reasons: ['RAISON ANALYSIS INTERDITE'] },
    contract_reading: {
      note: 'NOTE ANALYSIS INTERDITE',
      summary: 'RÉSUMÉ ANALYSIS INTERDIT',
      contract_type: 'TYPE ANALYSIS INTERDIT',
      sector: 'SECTEUR ANALYSIS INTERDIT',
    },
  },
}
const FIRST_DETAIL: UnlockedDetail = {
  ...BASE_DETAIL,
  ...FIRST_ITEM,
  presentation: FIRST_PRESENTATION,
}

const SECOND_PRESENTATION = factualFallbackPresentation({
  artifactId: 'c'.repeat(64),
  headline: 'Attribution documentée à Atelier Alpha SA',
  awardSummary: 'Un acheteur public a attribué des travaux documentés à Atelier Alpha SA.',
  headlineEvidenceRefs: ['source:second-headline'],
  awardSummaryEvidenceRefs: ['source:second-award-summary'],
})
const SECOND_ITEM: UnlockedFeedItem = {
  ...FIRST_ITEM,
  signal_id: 'sig_company_second',
  company_key: 'cmp_company_second',
  company: { ...FIRST_ITEM.company, name: 'Atelier Alpha SA' },
  contract: { ...FIRST_ITEM.contract, title: 'Second marché documenté' },
  presentation: SECOND_PRESENTATION,
  event: {
    ...FIRST_ITEM.event,
    headline: 'Atelier Alpha SA a remporté un marché public.',
  },
}
const SECOND_DETAIL: UnlockedDetail = {
  ...FIRST_DETAIL,
  ...SECOND_ITEM,
  company_key: 'cmp_company_second',
  presentation: SECOND_PRESENTATION,
}
const SAME_COMPANY_PRESENTATION = factualFallbackPresentation({
  artifactId: 'd'.repeat(64),
  headline: 'Deuxième attribution documentée à Constructions Bertrand SA',
  awardSummary: 'Une deuxième attribution documentée concerne Constructions Bertrand SA.',
  headlineEvidenceRefs: ['source:same-company-headline'],
  awardSummaryEvidenceRefs: ['source:same-company-award-summary'],
})
const SAME_COMPANY_ITEM: UnlockedFeedItem = {
  ...SECOND_ITEM,
  company_key: COMPANY_PROFILE.company_key,
  company: FIRST_ITEM.company,
  presentation: SAME_COMPANY_PRESENTATION,
}
const SECOND_PROFILE: CompanyProfile = {
  ...COMPANY_PROFILE,
  company_key: SECOND_DETAIL.company_key!,
  official_identity: {
    ...COMPANY_PROFILE.official_identity,
    name: SECOND_ITEM.company.name!,
    address: '2 rue Alpha, 69000 Lyon',
  },
  related_signals: COMPANY_PROFILE.related_signals.map((signal) => ({
    ...signal,
    signal_id: SECOND_ITEM.signal_id,
    contract_title: SECOND_ITEM.contract.title,
  })),
}

const shellRoutes = {
  'GET /target-icps': { body: [ICP] },
  'GET /billing/status': { body: DISCOVERY_STATUS },
}

const FIRST_PATH = `/app/companies/${COMPANY_PROFILE.company_key}?signal=${FIRST_ITEM.signal_id}`
const SECOND_PATH = `/app/companies/${SECOND_PROFILE.company_key}?signal=${SECOND_ITEM.signal_id}`
const FIRST_SUMMARY = FIRST_PRESENTATION.content.award_summary
const SECOND_SUMMARY = SECOND_PRESENTATION.content.award_summary
const SAME_COMPANY_SUMMARY = SAME_COMPANY_PRESENTATION.content.award_summary

describe('workspace Entreprises exact et borné par les signaux accessibles', () => {
  it('résout les entreprises depuis le feed sans N+1 de détails', async () => {
    mockApi({
      'GET /signals': { body: feedPage([FIRST_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findAllByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    expect(document.querySelector('.companies-workspace .companies-panel + .company-detail')).not.toBeNull()
    expect(document.querySelector('.companies-panel')).toHaveAttribute(
      'data-master-detail-pane',
      'list',
    )
    expect(document.querySelector('.company-detail')).toHaveAttribute(
      'data-master-detail-pane',
      'detail',
    )
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
    expect(screen.getByRole('heading', { name: 'Sélectionnez une attribution pour afficher son contexte' })).toBeVisible()
    for (const forbidden of [
      FIRST_ITEM.contract.title,
      FIRST_ITEM.event.headline,
      FIRST_ITEM.event.why_now,
      FIRST_ITEM.analysis.contract_reading?.summary,
      FIRST_ITEM.analysis.fit.reasons[0],
    ]) {
      expect(document.body).not.toHaveTextContent(forbidden!)
    }
  })

  it.each([
    ['aucun artefact feed', { ...FIRST_ITEM, presentation: null }],
    ['artefact feed invalide', {
      ...FIRST_ITEM,
      presentation: { ...FIRST_PRESENTATION, status: 'PASS', content: {
        ...FIRST_PRESENTATION.content,
        variant: 'FACTUAL_FALLBACK',
      } },
    } as unknown as UnlockedFeedItem],
  ] as const)(
    'échoue fermé face à %s sans reconstruire depuis les champs bruts',
    async (_case, feedItem) => {
      mockApi({
        ...shellRoutes,
        'GET /signals': { body: feedPage([feedItem], { freshness: 'all' }) },
      })

      renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

      const row = await screen.findByRole('link', {
        name: new RegExp(COMPANY_PROFILE.official_identity.name),
      })
      expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
      expect(row).toHaveTextContent('Résumé de l’attribution non publié')
      expect(row).not.toHaveTextContent(FIRST_ITEM.contract.title!)
      expect(row).not.toHaveTextContent(FIRST_ITEM.event.headline)
    },
  )

  it('canonise une route entreprise autorisée avec le signal explicite', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<><AppRoutes /><LocationProbe /></>, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: FIRST_SUMMARY })).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent(FIRST_PATH)
  })

  it('préserve le scroll de la liste et restaure son focus avec l’historique mobile', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('matchMedia', mobileMatchMedia())
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<><AppRoutes /><LocationProbe /><HistoryControls /></>, {
      route: '/app/companies',
      session: AUTHENTICATED,
    })

    const row = await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    const list = document.querySelector<HTMLElement>('.companies-panel')
    expect(list).not.toBeNull()
    if (list) list.scrollTop = 280
    expect(row).toHaveAttribute('href', FIRST_PATH)

    await user.click(row)
    await waitFor(() => expect(screen.getByRole('heading', { name: FIRST_SUMMARY })).toHaveFocus())
    expect(row).toHaveAttribute('aria-current', 'true')
    expect(screen.getByTestId('location')).toHaveTextContent(FIRST_PATH)
    expect(list?.scrollTop).toBe(280)

    await user.click(screen.getByRole('button', { name: 'Retour aux attributions' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/companies'))
    await waitFor(() => expect(row).toHaveFocus())
    expect(list?.scrollTop).toBe(280)

    await user.click(screen.getByRole('button', { name: 'Historique suivant' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(FIRST_PATH))
    await waitFor(() => expect(screen.getByRole('heading', { name: FIRST_SUMMARY })).toHaveFocus())
  })

  it('remonte le détail sans déplacer la liste lors d’un changement d’attribution', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM, SAME_COMPANY_ITEM], { freshness: 'all' }) },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: FIRST_PATH, session: AUTHENTICATED })

    await screen.findByText(COMPANY_PROFILE.official_identity.address!)
    const list = document.querySelector<HTMLElement>('.companies-panel')
    const detail = document.getElementById('company-detail')
    expect(list).not.toBeNull()
    expect(detail).not.toBeNull()
    if (list) list.scrollTop = 240
    if (detail) detail.scrollTop = 180

    await user.click(await screen.findByRole('link', { name: `Ouvrir l’attribution ${SAME_COMPANY_SUMMARY}` }))
    await waitFor(() => expect(screen.getByRole('heading', { name: SAME_COMPANY_SUMMARY })).toHaveFocus())
    expect(document.getElementById('company-detail')).toBe(detail)
    expect(detail?.scrollTop).toBe(0)
    expect(list?.scrollTop).toBe(240)
  })

  it('refuse un signal qui n’appartient pas à l’entreprise avant tout GET entreprise', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}?signal=sig_inaccessible`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: 'Attribution inaccessible' })).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
  })

  it('pagine tout le feed, déduplique et conserve l’ordre de découverte serveur', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? {
            body: feedPage([FIRST_ITEM, SECOND_ITEM], {
              page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
              freshness: 'all',
            }),
          }
        : {
            body: feedPage([FIRST_ITEM, LOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              freshness: 'all',
            }),
          },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    const list = document.querySelector('.companies-list')
    expect(list).not.toBeNull()
    const rows = within(list as HTMLElement).getAllByRole('link')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent(COMPANY_PROFILE.official_identity.name)
    expect(rows[1]).toHaveTextContent(SECOND_PROFILE.official_identity.name)
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('autorise une route profonde seulement après avoir découvert sa clé en page suivante', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? {
            body: feedPage([SECOND_ITEM], {
              page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
              freshness: 'all',
            }),
          }
        : {
            body: feedPage([LOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              freshness: 'all',
            }),
          },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: SECOND_PATH,
      session: AUTHENTICATED,
    })

    await screen.findByText(SECOND_PROFILE.official_identity.address!)
    expect(screen.getByRole('heading', { name: SECOND_SUMMARY })).toBeVisible()
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
    const feedCall = callsTo('/signals', 'GET')[0]
    const companyCall = callsTo(`/companies/${SECOND_PROFILE.company_key}`, 'GET')[0]
    expect(recordedCalls.indexOf(feedCall)).toBeLessThan(recordedCalls.indexOf(companyCall))
    expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('présente chaque attribution comme une carte distincte, même pour la même entreprise', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM, SAME_COMPANY_ITEM], { freshness: 'all' }) },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findAllByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    expect(document.querySelectorAll('.company-list-item')).toHaveLength(2)
    expect(screen.getAllByRole('link', { name: /Constructions Bertrand SA/ })[0]).toHaveTextContent('2 attributions')
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
  })

  it('refuse une route entreprise inconnue avant tout GET entreprise', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      'GET /companies/cmp_unknown_private': { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: '/app/companies/cmp_unknown_private',
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: 'Fiche entreprise inaccessible' })).toBeVisible()
    expect(callsTo('/companies/cmp_unknown_private', 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('ne demande une route profonde autorisée qu’après le feed qui fournit sa clé', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM]) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: FIRST_PATH,
      session: AUTHENTICATED,
    })

    await screen.findByText(COMPANY_PROFILE.official_identity.address!)
    expect(screen.getByRole('heading', { level: 2, name: FIRST_SUMMARY })).toBeVisible()
    const feedCall = callsTo('/signals', 'GET')[0]
    const companyCall = callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')[0]
    expect(feedCall).toBeDefined()
    expect(companyCall).toBeDefined()
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(feedCall && companyCall && recordedCalls.indexOf(feedCall)).toBeLessThan(
      companyCall ? recordedCalls.indexOf(companyCall) : -1,
    )
  })

  it('reste fail-closed si le feed ne fournit pas la clé entreprise annoncée par la route', async () => {
    const itemWithoutCompanyKey = { ...FIRST_ITEM, company_key: null }
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([itemWithoutCompanyKey, LOCKED_ITEM]) },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: FIRST_PATH,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: 'Les entreprises n’ont pas pu être vérifiées' })).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('ne demande aucun détail même si une page API contient beaucoup de signaux', async () => {
    const items = Array.from({ length: 12 }, (_, index): UnlockedFeedItem => ({
      ...FIRST_ITEM,
      signal_id: `sig_company_pool_${index}`,
      company_key: `cmp_pool_${index}`,
      company: { ...FIRST_ITEM.company, name: `Entreprise ${index}` },
    }))
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage(items, { freshness: 'all' }) },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await waitFor(() => expect(document.querySelectorAll('.company-list-item')).toHaveLength(12))
    for (const item of items) expect(callsTo(`/signals/${item.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('annonce une résolution tronquée sans présenter la liste comme exhaustive', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': {
        body: feedPage([FIRST_ITEM], {
          page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
          freshness: 'all',
        }),
      },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    expect(screen.getByRole('alert')).toHaveTextContent(/partielle|plafonnée/i)
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument()
  })

  it('rend la résolution incomplète, jamais un faux vide, si aucune entreprise n’est résolue', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': {
        body: feedPage([], {
          page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
          freshness: 'all',
        }),
      },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Résolution incomplète' })).toBeVisible()
    expect(document.body).not.toHaveTextContent('Aucune entreprise accessible')
    expect(callsTo('/companies', 'GET')).toHaveLength(0)
  })

  it('ignore le profil obsolète après une nouvelle sélection et conserve la navigation réelle', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: { body: CompanyProfile }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM, SECOND_ITEM]) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => new Promise((resolve) => {
        resolveFirst = resolve
      }),
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(<><AppRoutes /><LocationProbe /></>, { route: '/app/companies', session: AUTHENTICATED })

    const first = await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    const second = screen.getByRole('link', { name: new RegExp(SECOND_PROFILE.official_identity.name) })
    await user.click(first)
    await waitFor(() => expect(resolveFirst).toBeTypeOf('function'))
    await user.click(second)
    expect(
      await screen.findByRole('heading', { level: 2, name: SECOND_SUMMARY }),
    ).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent(SECOND_PATH)

    await act(async () => {
      resolveFirst({ body: COMPANY_PROFILE })
      await Promise.resolve()
    })
    expect(screen.getByRole('heading', { level: 2, name: SECOND_SUMMARY })).toBeVisible()
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('ne peint ni erreur ni identité du profil A pendant le chargement du profil B', async () => {
    const user = userEvent.setup()
    let resolveSecond!: (value: { body: CompanyProfile }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM, SECOND_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: () => new Promise((resolve) => {
        resolveSecond = resolve
      }),
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    await user.click(await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) }))
    expect(await screen.findByRole('alert')).toHaveTextContent('La fiche entreprise n’a pas pu être chargée')

    await user.click(screen.getByRole('link', { name: new RegExp(SECOND_PROFILE.official_identity.name) }))
    expect(await screen.findByRole('status')).toHaveTextContent('Chargement')
    expect(screen.queryByText('La fiche entreprise n’a pas pu être chargée')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)

    await act(async () => {
      resolveSecond({ body: SECOND_PROFILE })
      await Promise.resolve()
    })
    expect(await screen.findByRole('heading', { name: SECOND_SUMMARY })).toBeVisible()
  })

  it('conserve le focus mobile sur le détail terminal, y compris en retapant la sélection active', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === '(max-width: 1179px)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    })))
    let resolveSecond!: (value: { body: CompanyProfile }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM, SECOND_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: () => new Promise((resolve) => {
        resolveSecond = resolve
      }),
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const first = await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })

    await user.click(first)
    await waitFor(() => expect(screen.getByRole('heading', { name: FIRST_SUMMARY })).toHaveFocus())

    await user.click(screen.getByRole('link', { name: new RegExp(SECOND_PROFILE.official_identity.name) }))
    await waitFor(() => expect(resolveSecond).toBeTypeOf('function'))
    expect(screen.getByRole('status')).toHaveTextContent('Chargement')
    await waitFor(() => expect(screen.getByRole('heading', { name: SECOND_SUMMARY })).toHaveFocus())
    await act(async () => {
      resolveSecond({ body: SECOND_PROFILE })
      await Promise.resolve()
    })
    await waitFor(() => expect(screen.getByRole('heading', { name: SECOND_SUMMARY })).toHaveFocus())
  })

  it('rend une révocation 404 de la fiche comme inaccessible sans faux retry', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: {
        status: 404,
        body: { detail: { code: 'company_not_found' } },
      },
    })

    renderApp(<AppRoutes />, {
      route: FIRST_PATH,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Fiche entreprise inaccessible')
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('annule les données privées tardives lorsque le compte connecté change', async () => {
    let feedCalls = 0
    let resolveAccountA!: (value: { body: ReturnType<typeof feedPage> }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': () => {
        feedCalls += 1
        if (feedCalls === 1) return new Promise((resolve) => { resolveAccountA = resolve })
        return { body: feedPage([SECOND_ITEM], { freshness: 'all' }) }
      },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(
      <><AppRoutes /><AdoptSecondAccount /></>,
      { route: '/app/companies', session: AUTHENTICATED },
    )
    fireEvent.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    expect(
      await screen.findByRole('link', { name: new RegExp(SECOND_PROFILE.official_identity.name) }),
    ).toBeVisible()

    await act(async () => {
      resolveAccountA({ body: feedPage([FIRST_ITEM], { freshness: 'all' }) })
      await Promise.resolve()
    })
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('ne lance aucun détail lorsqu’un changement de compte remplace un grand feed', async () => {
    const accountAItems = Array.from({ length: 5 }, (_, index): UnlockedFeedItem => ({
      ...FIRST_ITEM,
      signal_id: `sig_account_a_${index}`,
      company_key: `cmp_private_a_${index}`,
      company: { ...FIRST_ITEM.company, name: `Privée A ${index}` },
    }))
    let feedCalls = 0
    mockApi({
      ...shellRoutes,
      'GET /signals': () => {
        feedCalls += 1
        return feedCalls === 1
          ? { body: feedPage(accountAItems, { freshness: 'all' }) }
          : { body: feedPage([SECOND_ITEM], { freshness: 'all' }) }
      },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(<><AppRoutes /><AdoptSecondAccount /></>, { route: '/app/companies', session: AUTHENTICATED })
    await waitFor(() => expect(document.querySelectorAll('.company-list-item')).toHaveLength(5))
    fireEvent.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    expect(await screen.findByRole('link', { name: new RegExp(SECOND_PROFILE.official_identity.name) })).toBeVisible()

    for (const item of accountAItems) expect(callsTo(`/signals/${item.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('conserve les entreprises déjà autorisées quand une page suivante échoue et annonce le résultat partiel', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        : {
            body: feedPage([FIRST_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              freshness: 'all',
            }),
          },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(
      await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) }),
    ).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Liste partielle')
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
  })

  it('garde les clés autorisées si le feed en omet une et permet une reprise honnête', async () => {
    const user = userEvent.setup()
    let feedAttempts = 0
    const secondWithoutCompanyKey = { ...SECOND_ITEM, company_key: null }
    mockApi({
      ...shellRoutes,
      'GET /signals': () => {
        feedAttempts += 1
        return {
          body: feedPage(
            feedAttempts === 1 ? [FIRST_ITEM, secondWithoutCompanyKey] : [FIRST_ITEM, SECOND_ITEM],
            { freshness: 'all' },
          ),
        }
      },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(
      await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) }),
    ).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Liste partielle')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(2))
    expect(await screen.findByRole('link', { name: new RegExp(SECOND_PROFILE.official_identity.name) })).toBeVisible()
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('n’annonce qu’une seule fois la panne quand toutes les clés entreprise manquent', async () => {
    const itemWithoutCompanyKey = { ...FIRST_ITEM, company_key: null }
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([itemWithoutCompanyKey], { freshness: 'all' }) },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(1))
    expect(screen.getByRole('alert')).toHaveTextContent('Les attributions n’ont pas pu être chargées')
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Les entreprises n’ont pas pu être vérifiées' })).toBeVisible()
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('réessaie uniquement le profil après une panne du GET entreprise autorisé', async () => {
    const user = userEvent.setup()
    let profileAttempts = 0
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => {
        profileAttempts += 1
        return profileAttempts === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: COMPANY_PROFILE }
      },
    })

    renderApp(<AppRoutes />, {
      route: FIRST_PATH,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('La fiche entreprise n’a pas pu être chargée')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: FIRST_SUMMARY }),
    ).toBeVisible()
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${FIRST_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(2)
  })

  it('redirige un 401 du feed vers la connexion sans aucune requête entreprise', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { status: 401, body: { detail: { code: 'not_authenticated' } } },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Retrouver vos signaux' })).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
  })

  it('conserve la composition, les libellés anglais et un seul main/h1', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([FIRST_ITEM], { freshness: 'all' }) },
      [`GET /signals/${FIRST_ITEM.signal_id}`]: { body: FIRST_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: '/app/companies',
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      locale: 'en',
    })

    expect(await screen.findByRole('link', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Detected awards' })).toBeVisible()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelectorAll('main')).toHaveLength(1)
    expect(document.querySelector('.companies-workspace .companies-panel + .company-detail')).not.toBeNull()
  })
})

function AdoptSecondAccount() {
  const { adopt } = useSession()
  return (
    <button
      type="button"
      onClick={() => adopt({ ...ME, account_id: 'acc_2', account_display_name: 'Compte B' })}
    >
      Basculer sur le compte B
    </button>
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>Historique précédent</button>
      <button type="button" onClick={() => navigate(1)}>Historique suivant</button>
    </>
  )
}

function mobileMatchMedia() {
  return vi.fn((query: string): MediaQueryList => ({
    matches: query === '(max-width: 1179px)',
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }))
}
