import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppRoutes } from '../App'
import { SignalDetail } from '../pages/SignalDetail'
import {
  AUTHENTICATED,
  CARD_PRESENTATION,
  CATALOGUE,
  DISCOVERY_STATUS,
  FACTUAL_FALLBACK_PRESENTATION,
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

async function detailPanel(heading = CARD_PRESENTATION.content.headline): Promise<HTMLElement> {
  await screen.findByRole('heading', { level: 2, name: heading })
  const panel = document.querySelector('.detail-panel')
  if (!(panel instanceof HTMLElement)) throw new Error('detail-panel absent')
  return panel
}

describe('détail exact d’un signal réel', () => {
  it('rend la présentation FULL publiée et sépare faits, interprétations et recommandations', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(within(panel).getByText('Analyse publiée')).toBeVisible()
    expect(panel).toHaveTextContent(CARD_PRESENTATION.content.award_summary)
    for (const value of [
      CARD_PRESENTATION.content.commercial_importance,
      CARD_PRESENTATION.content.fit_reason,
      CARD_PRESENTATION.content.timing,
      CARD_PRESENTATION.content.recommended_action,
    ]) {
      expect(panel).toHaveTextContent(value!)
    }
    expect(within(panel).getByText('Responsable achats chantier')).toBeVisible()
    expect(within(panel).getByText('Responsable travaux')).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Fait publié' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Interprétation Kivou' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Recommandation' })).toBeVisible()
    expect(within(panel).getByText(/Confiance moyenne · Fondé sur les preuves publiées/)).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'À vérifier' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Détails du marché' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Constructions Bertrand SA' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Note sur ce signal' })).toBeVisible()
    expect(panel.querySelectorAll('.volume-item')).toHaveLength(0)
    expect(panel).not.toHaveTextContent('À identifier après qualification du signal.')
    expect(panel).not.toHaveTextContent('Profil : Matériaux — Occitanie')
    expect(panel).toHaveTextContent('Commune de Villeneuve')
    expect(panel).toHaveTextContent('SIRET 12345678900011')
    expect(panel).toHaveTextContent('Date d’attribution')
  })

  it('n’utilise jamais les anciens champs narratifs comme intelligence commerciale', async () => {
    const detail = {
      ...UNLOCKED_DETAIL,
      contract: { ...UNLOCKED_DETAIL.contract, title: 'TITRE BRUT SECONDAIRE' },
      event: { ...UNLOCKED_DETAIL.event, why_now: 'WHY_NOW_BRUT_INTERDIT' },
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        fit: { ...UNLOCKED_DETAIL.analysis.fit, reasons: ['MATCH_BRUT_INTERDIT'] },
        contract_reading: {
          ...UNLOCKED_DETAIL.analysis.contract_reading!,
          summary: 'RESUME_BRUT_INTERDIT',
        },
        plausible_needs: {
          ...UNLOCKED_DETAIL.analysis.plausible_needs,
          items: UNLOCKED_DETAIL.analysis.plausible_needs.items.map((need) => ({
            ...need,
            statement: 'BESOIN_BRUT_INTERDIT',
          })),
        },
      },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    const hero = panel.querySelector('.detail-hero')!
    expect(hero).not.toHaveTextContent('TITRE BRUT SECONDAIRE')
    expect(panel).not.toHaveTextContent('WHY_NOW_BRUT_INTERDIT')
    expect(panel).not.toHaveTextContent('MATCH_BRUT_INTERDIT')
    expect(panel).not.toHaveTextContent('RESUME_BRUT_INTERDIT')
    expect(panel).not.toHaveTextContent('BESOIN_BRUT_INTERDIT')
    const disclosure = within(panel).getByText('Sources et faits publiés').closest('details')!
    expect(disclosure).toHaveTextContent('TITRE BRUT SECONDAIRE')
  })

  it('reste transparent quand aucune présentation n’est publiée', async () => {
    const detail = {
      ...UNLOCKED_DETAIL,
      presentation: null,
      event: { ...UNLOCKED_DETAIL.event, why_now: 'WHY_NOW_NE_DOIT_PAS_APPARAITRE' },
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        fit: { ...UNLOCKED_DETAIL.analysis.fit, reasons: ['MATCH_NE_DOIT_PAS_APPARAITRE'] },
      },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel('Analyse commerciale indisponible')
    expect(within(panel).getByText('Analyse indisponible')).toBeVisible()
    expect(panel).toHaveTextContent('Les faits publiés restent consultables.')
    expect(panel.querySelector('.commercial-brief-card')).toBeNull()
    expect(panel.querySelector('.presentation-claims')).toBeNull()
    expect(panel).not.toHaveTextContent('WHY_NOW_NE_DOIT_PAS_APPARAITRE')
    expect(panel).not.toHaveTextContent('MATCH_NE_DOIT_PAS_APPARAITRE')
    expect(panel).not.toHaveTextContent(CARD_PRESENTATION.content.fit_reason!)
  })

  it('limite un FALLBACK aux faits publiés sans conseil commercial', async () => {
    const detail = { ...UNLOCKED_DETAIL, presentation: FACTUAL_FALLBACK_PRESENTATION }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel(FACTUAL_FALLBACK_PRESENTATION.content.headline)
    expect(within(panel).getByText('Faits publiés uniquement')).toBeVisible()
    expect(panel).toHaveTextContent(FACTUAL_FALLBACK_PRESENTATION.content.award_summary)
    expect(within(panel).getByRole('heading', { name: 'Faits publiés' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Fait publié' })).toBeVisible()
    expect(within(panel).queryByRole('heading', { name: 'Interprétation Kivou' })).toBeNull()
    expect(within(panel).queryByRole('heading', { name: 'Recommandation' })).toBeNull()
    expect(panel.querySelector('.commercial-brief-card')).toBeNull()
    expect(panel.querySelector('.presentation-targets')).toBeNull()
    expect(panel).not.toHaveTextContent(CARD_PRESENTATION.content.fit_reason!)
    expect(panel).not.toHaveTextContent(CARD_PRESENTATION.content.recommended_action!)
    expect(panel).not.toHaveTextContent(/priorité (élevée|normale)|à qualifier/i)
  })

  it('qualifie la date du détail depuis l’horloge serveur', async () => {
    const detail = {
      ...UNLOCKED_DETAIL,
      event: {
        ...UNLOCKED_DETAIL.event,
        status: 'recently_published_award' as const,
        type: 'recently_published_award' as const,
        clock: 'publication',
        date: '2026-08-10',
      },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(within(panel).getAllByText('Date de publication').length).toBeGreaterThan(0)
    expect(within(panel).getAllByText('10 août 2026').length).toBeGreaterThan(0)
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

  it('ne présente pas une URL non HTTPS comme avis officiel', async () => {
    mockApi(detailRoutes({
      ...UNLOCKED_DETAIL,
      source: { ...UNLOCKED_DETAIL.source, url: 'javascript:alert(1)' },
    }))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await detailPanel()
    expect(screen.queryByRole('link', { name: 'Ouvrir l’avis' })).not.toBeInTheDocument()
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

  it('navigue vers la fiche entreprise canonique en conservant le signal source', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const link = await screen.findByRole('link', { name: 'Voir l’entreprise' })
    expect(link).toHaveAttribute(
      'href',
      `/app/companies/${UNLOCKED_DETAIL.company_key}?signal=${UNLOCKED_ITEM.signal_id}`,
    )
    expect(link).not.toHaveTextContent(/contact/i)
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
    await waitFor(() => expect(screen.getByText('Commune de Villeneuve')).toBeVisible())
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(2)
  })

  it('rend les champs absents avec des libellés précis sans fabriquer de valeur', async () => {
    const nullable = {
      ...UNLOCKED_DETAIL,
      presentation: null,
      event: { ...UNLOCKED_DETAIL.event, date: null },
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
    }
    mockApi(detailRoutes(nullable))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel('Analyse commerciale indisponible')
    for (const value of [
      'Montant non publié',
      'Territoire non publié',
      'Acheteur non publié',
      'Date d’attribution non publiée',
    ]) {
      expect(panel).toHaveTextContent(value)
    }
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

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: CARD_PRESENTATION.content.headline,
      }),
    ).toBeVisible()
    expect(document.querySelector('.workspace-grid .feed-panel + .detail-panel')).not.toBeNull()
  })
})
