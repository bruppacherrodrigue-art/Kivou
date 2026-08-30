import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CARD_PRESENTATION,
  CATALOGUE,
  DISCOVERY_STATUS,
  FACTUAL_FALLBACK_PRESENTATION,
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

function fullPresentation(
  content: Partial<typeof CARD_PRESENTATION.content> = {},
): typeof CARD_PRESENTATION {
  return {
    ...CARD_PRESENTATION,
    content: { ...CARD_PRESENTATION.content, ...content },
  }
}

async function signalList(): Promise<HTMLElement> {
  await waitFor(() => {
    expect(document.querySelector('.signal-list')).toBeInstanceOf(HTMLElement)
  })
  const list = document.querySelector('.signal-list')
  if (!(list instanceof HTMLElement)) throw new Error('signal-list absente')
  return list
}

describe('feed de signaux dans le workspace de référence', () => {
  it('rend la présentation FULL comme synthèse commerciale et conserve l’ordre serveur', async () => {
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_server_second',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième selon le serveur SA' },
      contract: { ...UNLOCKED_ITEM.contract, title: 'TITRE BRUT DEUXIÈME À NE PAS AFFICHER' },
      presentation: fullPresentation({
        headline: 'Deuxième attribution synthétisée',
        award_summary: 'Un second marché documenté est prêt à être qualifié.',
        fit_reason: 'La prestation correspond au profil actif du compte.',
        timing: 'Le calendrier opérationnel reste à confirmer.',
      }),
    }
    mockApi(feedWith([UNLOCKED_ITEM, second]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const rows = (await signalList()).querySelectorAll('button.signal-item')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Constructions Bertrand SA')
    expect(rows[0]).toHaveTextContent(CARD_PRESENTATION.content.headline)
    expect(rows[0]).toHaveTextContent(CARD_PRESENTATION.content.award_summary)
    expect(rows[0].textContent?.replace(/\u202f|\u00a0/g, ' ')).toContain('1 240 000 €')
    expect(rows[0]).toHaveTextContent('4 août 2026')
    expect(rows[0]).toHaveTextContent('Date d’attribution')
    expect(rows[0]).toHaveTextContent(CARD_PRESENTATION.content.fit_reason!)
    expect(rows[0]).toHaveTextContent(CARD_PRESENTATION.content.timing!)
    expect(rows[0]).toHaveTextContent('Analyse publiée')
    expect(rows[0]).toHaveTextContent('Voir l’analyse')
    expect(rows[0]).toHaveAccessibleName(
      `Ouvrir le signal « ${CARD_PRESENTATION.content.headline} » pour Constructions Bertrand SA — Analyse publiée`,
    )
    expect(rows[0].getAttribute('aria-label')).not.toContain(CARD_PRESENTATION.content.award_summary)
    expect(rows[0]).not.toHaveTextContent(UNLOCKED_ITEM.analysis.fit.label)
    expect(rows[1]).toHaveTextContent('Deuxième selon le serveur SA')
    expect(rows[1]).toHaveTextContent('Deuxième attribution synthétisée')
    expect(rows[1]).not.toHaveTextContent('TITRE BRUT DEUXIÈME À NE PAS AFFICHER')
    expect(document.body).not.toHaveTextContent('À examiner d’abord')
  })

  it('rend le timing publié par la présentation sans recycler les champs bruts', async () => {
    const item = {
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        date: '2026-02-03',
        age_days: 999,
        headline: 'TITRE ÉVÉNEMENT BRUT INTERDIT',
        why_now: 'POISON WHY NOW — priorité absolue.',
      },
      contract: { ...UNLOCKED_ITEM.contract, title: 'TITRE CONTRAT BRUT INTERDIT' },
      analysis: {
        plausible_needs: {
          ...UNLOCKED_ITEM.analysis.plausible_needs,
          items: [{
            ...UNLOCKED_ITEM.analysis.plausible_needs.items[0],
            statement: 'POISON BESOIN BRUT INTERDIT',
          }],
        },
        fit: {
          ...UNLOCKED_ITEM.analysis.fit,
          label: 'POISON SCORE BRUT INTERDIT',
          reasons: ['POISON RAISON BRUTE INTERDITE'],
        },
      },
      presentation: fullPresentation({
        timing: 'TIMING VALIDÉ — contacter après qualification du calendrier.',
      }),
    }
    mockApi(feedWith([item]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent('3 février 2026')
    expect(row).toHaveTextContent('TIMING VALIDÉ — contacter après qualification du calendrier.')
    expect(row).not.toHaveTextContent('999 jours')
    for (const poison of [
      'TITRE ÉVÉNEMENT BRUT INTERDIT',
      'POISON WHY NOW — priorité absolue.',
      'TITRE CONTRAT BRUT INTERDIT',
      'POISON BESOIN BRUT INTERDIT',
      'POISON SCORE BRUT INTERDIT',
      'POISON RAISON BRUTE INTERDITE',
    ]) {
      expect(row).not.toHaveTextContent(poison)
    }
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

  it('rend un état transparent quand aucune présentation validée n’est publiée', async () => {
    const unsupported = {
      ...UNLOCKED_ITEM,
      presentation: null,
      contract: { ...UNLOCKED_ITEM.contract, title: 'POISON TITRE CONTRAT SANS PRÉSENTATION' },
      event: {
        ...UNLOCKED_ITEM.event,
        headline: 'POISON TITRE ÉVÉNEMENT SANS PRÉSENTATION',
        why_now: 'POISON URGENCE SANS PRÉSENTATION',
      },
      analysis: {
        plausible_needs: {
          ...UNLOCKED_ITEM.analysis.plausible_needs,
          items: [{
            ...UNLOCKED_ITEM.analysis.plausible_needs.items[0],
            statement: 'POISON BESOIN SANS PRÉSENTATION',
          }],
        },
        fit: {
          ...UNLOCKED_ITEM.analysis.fit,
          label: 'POISON MATCH SANS PRÉSENTATION',
          reasons: ['POISON RAISON SANS PRÉSENTATION'],
        },
      },
    }
    mockApi(feedWith([unsupported]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent('Analyse indisponible')
    expect(row).toHaveTextContent('Analyse commerciale indisponible')
    expect(row).toHaveTextContent(
      'Les faits publiés restent consultables. Aucun résumé, motif de pertinence, besoin ou conseil n’est affiché tant qu’aucune présentation validée n’est publiée.',
    )
    expect(row).toHaveTextContent('Voir les faits publiés')
    expect(row.querySelector('.signal-match')).toBeNull()
    expect(row.querySelector('.signal-reason')).toBeNull()
    for (const poison of [
      'POISON TITRE CONTRAT SANS PRÉSENTATION',
      'POISON TITRE ÉVÉNEMENT SANS PRÉSENTATION',
      'POISON URGENCE SANS PRÉSENTATION',
      'POISON BESOIN SANS PRÉSENTATION',
      'POISON MATCH SANS PRÉSENTATION',
      'POISON RAISON SANS PRÉSENTATION',
    ]) {
      expect(row).not.toHaveTextContent(poison)
    }
  })

  it('rend le FALLBACK comme factuel sans commercial, urgence ni priorité implicite', async () => {
    const fallback = {
      ...STALE_ITEM,
      presentation: {
        ...FACTUAL_FALLBACK_PRESENTATION,
        content: {
          ...FACTUAL_FALLBACK_PRESENTATION.content,
          unknowns: ['POISON INCONNU SECONDAIRE NON AFFICHÉ DANS LE FEED'],
        },
      },
      event: {
        ...STALE_ITEM.event,
        headline: 'POISON ÉVÉNEMENT FALLBACK',
        why_now: 'À examiner d’abord — priorité maximale.',
      },
      contract: { ...STALE_ITEM.contract, title: 'POISON CONTRAT FALLBACK' },
      analysis: {
        ...STALE_ITEM.analysis,
        fit: {
          ...STALE_ITEM.analysis.fit,
          label: 'Correspondance commerciale brute interdite',
          reasons: ['Raison commerciale brute interdite'],
        },
      },
    }
    mockApi(feedWith([fallback]))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent('Faits publiés uniquement')
    expect(row).toHaveTextContent(FACTUAL_FALLBACK_PRESENTATION.content.headline)
    expect(row).toHaveTextContent(FACTUAL_FALLBACK_PRESENTATION.content.award_summary)
    expect(row).toHaveTextContent('Voir les faits publiés')
    expect(row.querySelector('.signal-match')).toBeNull()
    expect(row.querySelector('.signal-reason')).toBeNull()
    expect(row).not.toHaveTextContent(CARD_PRESENTATION.content.fit_reason!)
    expect(row).not.toHaveTextContent(CARD_PRESENTATION.content.timing!)
    expect(row).not.toHaveTextContent(/à examiner d’abord|priorité maximale/i)
    expect(row).not.toHaveTextContent('Correspondance commerciale brute interdite')
    expect(row).not.toHaveTextContent('Raison commerciale brute interdite')
    expect(row).not.toHaveTextContent('POISON CONTRAT FALLBACK')
    expect(row).not.toHaveTextContent('POISON ÉVÉNEMENT FALLBACK')
  })

  it('choisit le premier élément réellement déverrouillé sans promouvoir le teaser précédent', async () => {
    mockApi({
      ...feedWith([LOCKED_ITEM, UNLOCKED_ITEM]),
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: CARD_PRESENTATION.content.headline,
      }),
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

  it('affiche la note comme état de travail séparé sans remplacer l’état de présentation', async () => {
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
    expect(within(row).getByText('Analyse publiée')).toBeVisible()
    expect(within(row).getByText('Voir l’analyse')).toBeVisible()
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

  it('formate et traduit la présentation et ses états selon la locale du compte', async () => {
    mockApi(feedWith([UNLOCKED_ITEM]))
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/signals',
      locale: 'en',
    })

    await screen.findByRole('heading', { level: 2, name: 'Detected signals' })
    const row = (await signalList()).querySelector('.signal-item')!
    expect(row).toHaveTextContent('Constructions Bertrand SA')
    expect(row).toHaveTextContent(CARD_PRESENTATION.content.headline)
    expect(row).toHaveTextContent(CARD_PRESENTATION.content.award_summary)
    expect(row).toHaveTextContent('Published analysis')
    expect(row).toHaveTextContent('View analysis')
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
