import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
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
    expect(rows[0]).toHaveTextContent('Réfection de la voirie communale — lot 2')
    expect(rows[0].textContent?.replace(/\u202f|\u00a0/g, ' ')).toContain('1 240 000 €')
    expect(rows[0]).toHaveTextContent('4 août 2026')
    expect(rows[0]).toHaveTextContent('Date d’attribution')
    expect(rows[0]).toHaveTextContent('Besoin visé : Matériaux ou composants')
    expect(rows[0]).not.toHaveTextContent('Très bon pour votre profil')
    expect(rows[1]).toHaveTextContent('Deuxième selon le serveur SA')
    expect(document.body).not.toHaveTextContent('À examiner d’abord')
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
    expect(row).toHaveTextContent('CALENDRIER SERVEUR — décision commerciale à examiner.')
    expect(row).not.toHaveTextContent('999 jours')
    expect(row).not.toHaveTextContent(UNLOCKED_ITEM.analysis.plausible_needs.items[0].statement!)
  })

  it('nomme la nature exacte de la date publiée par le serveur', async () => {
    const notified = {
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        status: 'recently_notified_contract' as const,
        type: 'recently_notified_contract' as const,
        clock: 'notification',
        date: '2026-02-03',
      },
    }
    mockApi(feedWith([notified]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent('Date de notification : 3 février 2026')
    expect(row).not.toHaveTextContent('Date de l’événement')
  })

  it('masque la correspondance quand l’API ne fournit aucune raison concrète', async () => {
    const unsupported = {
      ...UNLOCKED_ITEM,
      analysis: {
        ...UNLOCKED_ITEM.analysis,
        fit: { ...UNLOCKED_ITEM.analysis.fit, reasons: [] },
      },
    }
    mockApi(feedWith([unsupported]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row.querySelector('.signal-match')).toBeNull()
    expect(row).not.toHaveTextContent(UNLOCKED_ITEM.analysis.fit.label)
  })

  it('ne reformule jamais un signal ancien comme une attribution récente', async () => {
    mockApi(feedWith([STALE_ITEM]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent(STALE_ITEM.event.why_now)
    expect(row).not.toHaveTextContent(/vient de remporter|nouveau contrat/i)
  })

  it('choisit le premier élément réellement déverrouillé sans promouvoir le teaser précédent', async () => {
    mockApi({
      ...feedWith([LOCKED_ITEM, UNLOCKED_ITEM]),
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', { level: 2, name: UNLOCKED_ITEM.contract.title! }),
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
    expect(row).toHaveTextContent('Award date: 4 August 2026')
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
