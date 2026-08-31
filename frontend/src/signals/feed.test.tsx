import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import type { CardPresentation } from '../api/types'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  STALE_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const FACTUAL_FALLBACK: CardPresentation = {
  artifact_id: 'b'.repeat(64),
  version: 1,
  status: 'FALLBACK',
  schema_version: 'card-presentation-v1',
  published_at: '2026-08-30T12:00:00Z',
  content: {
    schema_version: 'card-presentation-v1',
    variant: 'FACTUAL_FALLBACK',
    headline: 'Attribution publique documentée',
    award_summary: 'Une entreprise identifiée est attributaire du marché.',
    commercial_importance: null,
    fit_reason: null,
    timing: null,
    recommended_action: null,
    target_roles: [],
    fit_need_categories: [],
    unknowns: [],
    claims: [
      {
        claim_id: 'HEADLINE',
        kind: 'FACT',
        text: 'Attribution publique documentée',
        evidence_refs: ['source:award'],
        confidence: null,
      },
      {
        claim_id: 'AWARD_SUMMARY',
        kind: 'FACT',
        text: 'Une entreprise identifiée est attributaire du marché.',
        evidence_refs: ['source:award_summary'],
        confidence: null,
      },
    ],
  },
}

const MALFORMED_PRESENTATIONS = [
  [
    'une claim sans evidence_refs',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        headline: 'HEADLINE SANS PREUVE INTERDIT',
        award_summary: 'RÉSUMÉ SANS PREUVE INTERDIT',
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 'HEADLINE SANS PREUVE INTERDIT',
          confidence: null,
        }, FACTUAL_FALLBACK.content.claims[1]],
      },
    },
  ],
  [
    'une claim avec evidence_refs vide',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        headline: 'HEADLINE PREUVE VIDE INTERDIT',
        award_summary: 'RÉSUMÉ PREUVE VIDE INTERDIT',
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 'HEADLINE PREUVE VIDE INTERDIT',
          evidence_refs: [],
          confidence: null,
        }, FACTUAL_FALLBACK.content.claims[1]],
      },
    },
  ],
  [
    'un couple statut variante invalide',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        variant: 'FULL',
        headline: 'HEADLINE COUPLE INVALIDE INTERDIT',
        award_summary: 'RÉSUMÉ COUPLE INVALIDE INTERDIT',
      },
    },
  ],
  [
    'une claim mal formée',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        headline: 'HEADLINE CLAIM MAL FORMÉE INTERDIT',
        award_summary: 'RÉSUMÉ CLAIM MAL FORMÉE INTERDIT',
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 42,
          evidence_refs: ['source:award'],
          confidence: null,
        }, FACTUAL_FALLBACK.content.claims[1]],
      },
    },
  ],
] as const

const BASE = {
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
  [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
  [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
    body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
  },
}

function feedWith(items: unknown[], overrides = {}) {
  return {
    ...BASE,
    'GET /signals': { body: feedPage(items as never[], overrides) },
  }
}

async function signalList(): Promise<HTMLElement> {
  await screen.findByRole('heading', { level: 2, name: /attributions documentées/i })
  const list = document.querySelector('.signal-list')
  if (!(list instanceof HTMLElement)) throw new Error('signal-list absente')
  return list
}

describe('feed de signaux dans le workspace de référence', () => {
  it('hiérarchise les valeurs réelles et conserve strictement l’ordre serveur', async () => {
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_server_second',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième selon le serveur SA' },
      contract: { ...UNLOCKED_ITEM.contract, title: 'Deuxième marché réel' },
    }
    mockApi(feedWith([UNLOCKED_ITEM, second]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const rows = (await signalList()).querySelectorAll('button.signal-item')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Constructions Bertrand SA')
    expect(rows[0]).toHaveTextContent('Présentation non publiée')
    expect(rows[0]).not.toHaveTextContent('Réfection de la voirie communale — lot 2')
    expect(rows[0].textContent?.replace(/\u202f|\u00a0/g, ' ')).toContain('1 240 000 €')
    expect(rows[0]).toHaveTextContent('4 août 2026')
    expect(rows[1]).toHaveTextContent('Deuxième selon le serveur SA')
  })

  it('rend le calendrier et la justification du serveur sans recalcul navigateur', async () => {
    const item = {
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        date: '2026-02-03',
        age_days: 999,
        why_now: 'CALENDRIER SERVEUR — décision commerciale à examiner.',
      },
    }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent('3 février 2026')
    expect(row).not.toHaveTextContent('CALENDRIER SERVEUR — décision commerciale à examiner.')
    expect(row).not.toHaveTextContent('999 jours')
    expect(row).not.toHaveTextContent(UNLOCKED_ITEM.analysis.plausible_needs.items[0].statement!)
  })

  it('ne reformule jamais un signal ancien comme une attribution récente', async () => {
    mockApi(feedWith([STALE_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).not.toHaveTextContent(STALE_ITEM.event.why_now)
    expect(row).not.toHaveTextContent(/vient de remporter|nouveau contrat/i)
  })

  it.each([
    ['award', 'recent_award', "Date d’attribution"],
    ['notification', 'recently_notified_contract', 'Date de notification'],
    ['publication', 'recently_published_award', 'Date de publication'],
  ] as const)('libelle une date %s sans en changer le sens', async (clock, status, label) => {
    const item = {
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        clock,
        status,
        date: '2026-08-15',
      },
    }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item') as HTMLElement
    expect(within(row).getByText(label)).toBeVisible()
    expect(row).toHaveTextContent('15 août 2026')
  })

  it('ne présente jamais une date de publication comme une date d’attribution', async () => {
    const item = {
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        clock: 'publication' as const,
        status: 'recently_published_award' as const,
        date: '2026-08-15',
      },
    }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item') as HTMLElement
    expect(within(row).getByText('Date de publication')).toBeVisible()
    expect(within(row).queryByText("Date d’attribution")).not.toBeInTheDocument()
  })

  it('omet toute adéquation quand l’API ne fournit aucune raison concrète', async () => {
    const item = {
      ...UNLOCKED_ITEM,
      analysis: {
        ...UNLOCKED_ITEM.analysis,
        fit: { ...UNLOCKED_ITEM.analysis.fit, reasons: [] },
      },
    }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item') as HTMLElement
    expect(row.querySelector('.signal-match')).not.toBeInTheDocument()
    expect(row).not.toHaveTextContent(/correspond à votre ciblage/i)
  })

  it('reste neutre sans présentation et n’invente ni urgence ni priorité', async () => {
    const item = {
      ...UNLOCKED_ITEM,
      presentation: null,
      event: {
        ...UNLOCKED_ITEM.event,
        headline: 'URGENT : appeler Jean Dupont immédiatement',
        why_now: 'URGENT : contacter le directeur des achats aujourd’hui.',
      },
    }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item') as HTMLElement
    expect(row).toHaveTextContent('Présentation non publiée')
    expect(row).toHaveTextContent('Constructions Bertrand SA')
    expect(row).toHaveTextContent('Commune de Villeneuve')
    expect(row).not.toHaveTextContent(/urgent|jean dupont|directeur des achats|examiner d’abord/i)
  })

  it.each(MALFORMED_PRESENTATIONS)(
    'traite %s reçue du feed API comme une présentation absente',
    async (_case, presentation) => {
      const item = { ...UNLOCKED_ITEM, presentation }
      mockApi(feedWith([item]))
      renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

      const row = (await signalList()).querySelector('.signal-item') as HTMLElement
      expect(row).toHaveTextContent('Présentation non publiée')
      expect(row).toHaveTextContent('Constructions Bertrand SA')
      expect(row).toHaveTextContent('Commune de Villeneuve')
      expect(row).not.toHaveTextContent(presentation.content.headline)
      expect(row).not.toHaveTextContent(presentation.content.award_summary)
    },
  )

  it('continue de rendre un FALLBACK factuel valide sans le réécrire', async () => {
    const item = { ...UNLOCKED_ITEM, presentation: FACTUAL_FALLBACK }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item') as HTMLElement
    expect(row).toHaveTextContent(FACTUAL_FALLBACK.content.headline)
    expect(row).not.toHaveTextContent('Présentation non publiée')
  })

  it('choisit le premier élément réellement déverrouillé sans promouvoir le teaser précédent', async () => {
    mockApi({
      ...feedWith([LOCKED_ITEM, UNLOCKED_ITEM]),
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', { level: 2, name: 'Présentation non publiée' }),
    ).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('protège entièrement un teaser verrouillé puis transmet seulement sa clé à Billing', async () => {
    const user = userEvent.setup()
    mockApi({
      ...feedWith([LOCKED_ITEM]),
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const locked = await screen.findByRole('button', { name: new RegExp(LOCKED_ITEM.headline) })
    const preview = locked.textContent ?? ''
    for (const protectedValue of [
      'Constructions Bertrand',
      '12345678900011',
      'Réfection de la voirie',
      'boamp.fr',
      '26-104412',
      '1240000',
    ]) {
      expect(preview).not.toContain(protectedValue)
    }
    await user.click(locked)

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
  })

  it('ne prétend jamais qu’un plan précis ouvre un teaser paid_plan', async () => {
    mockApi({
      ...feedWith([LOCKED_ITEM]),
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect((await screen.findAllByText('Accès payant requis')).length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toMatch(/Accessible avec (Essentiel|Pro|Scale)/)
    expect(callsTo('/billing/plans', 'GET')).toHaveLength(0)
  })

  it('signale honnêtement un scan backend borné même sans page suivante', async () => {
    mockApi(feedWith([UNLOCKED_ITEM], {
      page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
    }))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await signalList()
    expect(
      screen.getByText(
        'La lecture a été bornée : des signaux plus anciens existent au-delà de cette page.',
      ),
    ).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Charger plus de signaux' })).toBeNull()
  })

  it('rend un état vide honnête dans la géométrie du feed', async () => {
    mockApi(feedWith([]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const list = await signalList()
    expect(within(list).getByText('Aucune attribution ne correspond à cette lecture.')).toBeVisible()
    expect(list.querySelectorAll('.signal-item')).toHaveLength(1)
  })

  it('met à jour le badge du signal sélectionné depuis sa note API réelle', async () => {
    mockApi({
      ...feedWith([UNLOCKED_ITEM]),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: {
          signal_id: UNLOCKED_ITEM.signal_id,
          note: 'Relancer le responsable achats',
          updated_at: '2026-08-29T18:00:00+00:00',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item') as HTMLElement
    expect(await within(row).findByText('Note ajoutée')).toBeVisible()
    expect(within(row).queryByText('À examiner d’abord')).toBeNull()
  })

  it('déduplique une page suivante qui recouvre la page précédente', async () => {
    const user = userEvent.setup()
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_unlocked_2',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième SA' },
    }
    const third = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_unlocked_3',
      company: { ...UNLOCKED_ITEM.company, name: 'Troisième SA' },
    }
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
              body: feedPage([second, third], {
                page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
              }),
            }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await user.click(await screen.findByRole('button', { name: 'Charger plus de signaux' }))
    await waitFor(() =>
      expect(document.querySelectorAll('.signal-list .signal-item')).toHaveLength(3),
    )
    expect(screen.getByText('Troisième SA')).toBeVisible()
  })

  it('garde les cartes et réessaie localement une page suivante en échec', async () => {
    const user = userEvent.setup()
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_page_retry',
      company: { ...UNLOCKED_ITEM.company, name: 'Page réessayée SA' },
    }
    let call = 0
    mockApi({
      ...BASE,
      'GET /signals': () => {
        call += 1
        if (call === 1) {
          return {
            body: feedPage([UNLOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            }),
          }
        }
        if (call === 2) return { status: 503, body: { detail: { code: 'feed_unavailable' } } }
        return {
          body: feedPage([second], {
            page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
          }),
        }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await user.click(await screen.findByRole('button', { name: 'Charger plus de signaux' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Les informations n’ont pas pu être chargées.',
    )
    expect(within(await signalList()).getByText('Constructions Bertrand SA')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Réessayer le chargement de la suite' }))
    expect(await screen.findByText('Page réessayée SA')).toBeVisible()
  })

  it('rend une panne initiale comme un état produit réessayable', async () => {
    const user = userEvent.setup()
    let call = 0
    mockApi({
      ...BASE,
      'GET /signals': () => {
        call += 1
        return call === 1
          ? { status: 500, body: { detail: 'Traceback: sqlalchemy.exc.OperationalError' } }
          : { body: feedPage([UNLOCKED_ITEM]) }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Les informations n’ont pas pu être chargées.')
    expect(document.body.textContent).not.toMatch(/Traceback|sqlalchemy/)
    await user.click(within(alert).getByRole('button', { name: 'Réessayer' }))
    expect(within(await signalList()).getByText('Constructions Bertrand SA')).toBeVisible()
  })

  it('formate et traduit selon la locale du compte', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/signals',
      locale: 'en',
    })

    await screen.findByRole('heading', { level: 2, name: 'Documented awards' })
    const row = document.querySelector('.signal-list .signal-item')!
    expect(row).toHaveTextContent('Constructions Bertrand SA')
    expect(row).toHaveTextContent('Award date')
    expect(row.textContent?.replace(/\u202f|\u00a0/g, ' ')).toContain('1,240,000')
    expect(screen.getByRole('heading', { level: 1, name: 'Signals' })).toBeVisible()
  })

  it('n’expose ni preuve longue ni vocabulaire interne dans le feed', async () => {
    mockApi({
      ...feedWith([UNLOCKED_ITEM, LOCKED_ITEM]),
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await signalList()
    const page = (document.body.textContent ?? '').toLowerCase()
    for (const forbidden of [
      'preuve documentaire',
      'acquisition engine',
      'apollo',
      'instantly',
      'opportunity_key',
      'signal_key',
      'scan_truncated',
    ]) {
      expect(page).not.toContain(forbidden)
    }
  })
})
