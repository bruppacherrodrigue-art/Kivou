import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppRoutes } from '../App'
import { SignalDetail } from '../pages/SignalDetail'
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

afterEach(() => vi.unstubAllGlobals())

function detailRoutes(detail: unknown = UNLOCKED_DETAIL) {
  return {
    'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: detail },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /target-icps': { body: [ICP] },
  }
}

async function detailPanel(): Promise<HTMLElement> {
  await screen.findByRole('heading', { level: 2, name: UNLOCKED_ITEM.contract.title! })
  const panel = document.querySelector('.detail-panel')
  if (!(panel instanceof HTMLElement)) throw new Error('detail-panel absent')
  return panel
}

describe('détail exact d’un signal réel', () => {
  it('compose les cartes exactes depuis le détail API sans réintroduire l’ancien DOM', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    for (const heading of [
      'Le signal en quatre points',
      'Détails du marché',
      'Questions avant de contacter l’entreprise',
      'Constructions Bertrand SA',
      'Note sur ce signal',
    ]) {
      expect(within(panel).getByRole('heading', { name: heading })).toBeVisible()
    }
    expect(within(panel).getByText('Commune de Villeneuve')).toBeVisible()
    expect(panel.querySelector('.commercial-brief-card')).not.toBeNull()
    expect(panel.querySelector('.facts-card')).not.toBeNull()
    expect(panel.querySelector('.verification-card')).not.toBeNull()
    expect(panel.querySelector('.signal-note-card')).not.toBeNull()
    expect(panel.querySelector('[class*="evidence"]')).toBeNull()
    const notice = panel.querySelector('.prototype-notice')
    expect(notice).toHaveTextContent(/données réelles|informations publiées/i)
    expect(notice).not.toHaveTextContent(/démonstration|jeu d’exemples|maquette/i)
    expect(within(panel).getByText('Profil : Matériaux — Occitanie')).toBeVisible()
    expect(within(panel).getAllByText('France').length).toBeGreaterThan(0)
    expect(within(panel).getByText('SIRET 12345678900011')).toBeVisible()
    expect(within(panel).getAllByText(/BOAMP.*26-104412/).length).toBeGreaterThan(1)
    expect(within(panel).getByText('Date d’attribution')).toBeVisible()
    expect(within(panel).queryByText('Contrat conclu')).not.toBeInTheDocument()
    const scope = panel.querySelector('.volume-grid')
    expect(scope).toHaveTextContent('Non publié')
    expect(scope).not.toHaveTextContent('Le marché est attribué')
    expect(scope?.querySelectorAll('.volume-item')).toHaveLength(5)
    expect(panel.querySelectorAll('.questions-list > li')).toHaveLength(3)
    for (const item of panel.querySelectorAll('.volume-item, .questions-list > li')) {
      expect(item).toHaveTextContent('Non publié')
    }
  })

  it('conserve le statut d’hypothèse et n’invente aucune certitude d’achat', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(panel).toHaveTextContent(UNLOCKED_DETAIL.analysis.plausible_needs.note)
    expect(panel).toHaveTextContent(
      UNLOCKED_DETAIL.analysis.plausible_needs.items[0].statement!,
    )
    expect(panel.textContent?.toLowerCase()).not.toMatch(
      /va acheter|achètera|achat prévu|achat certain|client garanti/,
    )
  })

  it('rend la source officielle uniquement quand l’API fournit une URL sûre', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const link = await screen.findByRole('link', { name: 'Ouvrir l’avis' })
    expect(link).toHaveAttribute('href', 'https://www.boamp.fr/avis/26-104412')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    for (const leak of ['/home/', '/tmp/', 'tests/', 'fixtures/', 'src/signals', '.jsonl']) {
      expect(document.body.textContent).not.toContain(leak)
    }
  })

  it('masque les actions source et entreprise quand leurs autorités sont absentes', async () => {
    const withoutActions = {
      ...UNLOCKED_DETAIL,
      company_key: null,
      source: { ...UNLOCKED_DETAIL.source, url: null },
    }
    mockApi(detailRoutes(withoutActions))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await detailPanel()
    expect(screen.queryByRole('link', { name: 'Ouvrir l’avis' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Voir l’entreprise' })).not.toBeInTheDocument()
  })

  it('navigue vers l’entreprise avec la seule company_key autorisée', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const link = await screen.findByRole('link', { name: 'Voir l’entreprise' })
    expect(link).toHaveAttribute(
      'href',
      `/app/companies/${UNLOCKED_DETAIL.company_key}`,
    )
    expect(link).not.toHaveAttribute('state')
  })

  it('ne demande ni détail, ni note, ni feedback pour une route verrouillée', async () => {
    mockApi({
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${LOCKED_ITEM.signal_id}`,
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/feedback`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain('Constructions Bertrand')
  })

  it('garde le feed disponible et réessaie localement un détail en panne', async () => {
    const user = userEvent.setup()
    let detailCalls = 0
    mockApi({
      ...detailRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => {
        detailCalls += 1
        return detailCalls === 1
          ? { status: 503, body: { detail: { code: 'signal_unavailable' } } }
          : { body: UNLOCKED_DETAIL }
      },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    expect(await screen.findByText('Signal non disponible dans cette lecture')).toBeVisible()
    expect(document.querySelector('.signal-list .signal-item')).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByText('Commune de Villeneuve')).toBeVisible()
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(2)
  })

  it('rend les champs nullable comme non publiés sans fabriquer de valeur', async () => {
    const nullable = {
      ...UNLOCKED_DETAIL,
      company: { name: null, country: null, identifier: null },
      company_key: null,
      contract: {
        ...UNLOCKED_DETAIL.contract,
        title: null,
        buyer: null,
        amount: null,
        cpv: null,
        location: null,
        dates: { award: null, contract_notification: null, publication: null },
      },
      source: {
        system: null,
        country: null,
        notice_id: null,
        procedure_id: null,
        url: null,
      },
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        plausible_needs: { note: '', items: [] },
        contract_reading: {
          note: '',
          summary: null,
          contract_type: null,
          sector: null,
        },
      },
      evidence: { ...UNLOCKED_DETAIL.evidence, public_facts: [] },
    }
    mockApi(detailRoutes(nullable))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const heading = await screen.findByRole('heading', { level: 2, name: 'Non publié' })
    const panel = heading.closest('.detail-panel') as HTMLElement
    expect(within(panel).getAllByText('Non publié').length).toBeGreaterThan(3)
    expect(within(panel).queryByRole('link', { name: /avis|entreprise/i })).not.toBeInTheDocument()
  })

  it('conserve le wrapper SignalDetail comme alias du workspace exact', async () => {
    mockApi(detailRoutes())
    renderApp(
      <Routes>
        <Route path="app/signals/:signalKey" element={<SignalDetail />} />
      </Routes>,
      {
        session: AUTHENTICATED,
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      },
    )

    expect(await screen.findByRole('heading', { level: 2, name: UNLOCKED_ITEM.contract.title! })).toBeVisible()
    expect(document.querySelector('.workspace-grid .feed-panel + .detail-panel')).not.toBeNull()
  })
})
