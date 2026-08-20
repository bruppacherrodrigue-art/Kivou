import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AppRoutes } from '../App'
import { publicDemoSignal } from '../content/publicDemoSignal'
import { en } from '../i18n/en'
import { fr } from '../i18n/fr'
import { mockApi, recordedCalls, renderApp } from '../test/harness'

/* P0-01 — la démonstration produit publique.
 *
 * Ce que ces tests protègent, au-delà du rendu
 * ────────────────────────────────────────────
 * Une page publique qui montre un vrai signal peut se dégrader de deux façons
 * silencieuses : en appelant un point d'entrée client, et en laissant croire
 * qu'une preuve documentaire existe alors qu'il n'y en a aucune. Les deux se
 * voient à la relecture d'un diff, jamais à l'œil sur la page.
 */

afterEach(() => vi.unstubAllGlobals())

describe('démonstration publique de signal', () => {
  it('se rend entièrement sans session, et n’appelle aucun point d’entrée client', async () => {
    // Le fournisseur de session sonde `/me` au montage de l'application. Ce
    // que la page doit garantir n'est pas l'absence de cet appel, mais son
    // caractère NON BLOQUANT : ici la sonde échoue, et la page se rend quand
    // même, entièrement.
    mockApi({ 'GET /me': { status: 401, body: { code: 'not_authenticated' } } })
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })

    expect(
      await screen.findByRole('heading', { level: 1, name: fr.publicDemo.pageTitle }),
    ).toBeInTheDocument()
    expect(screen.getByText(publicDemoSignal.winner.legalName)).toBeInTheDocument()
    expect(screen.getByText(fr.publicDemo.documentaryNone)).toBeInTheDocument()

    // Aucune donnée de compte n'est demandée pour une surface publique.
    const clientRoutes = recordedCalls.filter((call) =>
      ['/signals', '/target-icps', '/billing/plans', '/notification-preferences'].some((path) =>
        call.url.startsWith(path),
      ),
    )
    expect(clientRoutes).toHaveLength(0)
  })

  it('n’a qu’un seul h1', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('affiche les faits publiés et leur source officielle, sûrement ouverte', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })

    expect(await screen.findByText(publicDemoSignal.winner.legalName)).toBeInTheDocument()
    expect(screen.getByText(publicDemoSignal.buyer.legalName)).toBeInTheDocument()

    const source = screen.getByRole('link', { name: new RegExp(fr.publicDemo.openSource) })
    expect(source).toHaveAttribute('href', publicDemoSignal.sourceUrl)
    expect(source).toHaveAttribute('target', '_blank')
    // Sans `noopener`, la page ouverte peut réécrire notre onglet.
    expect(source.getAttribute('rel')).toContain('noopener')
    expect(source.getAttribute('rel')).toContain('noreferrer')
  })

  it('conserve la section « exigence documentaire » et y dit l’absence', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })

    expect(await screen.findByText(fr.publicDemo.documentaryNone)).toBeInTheDocument()
    expect(screen.getByText(fr.publicDemo.documentaryMode)).toBeInTheDocument()
    expect(screen.getByText(fr.publicDemo.documentaryConfidence)).toBeInTheDocument()
    expect(screen.getByText(fr.publicDemo.documentaryConfidenceReason)).toBeInTheDocument()
  })

  it('ne présente jamais une exigence documentaire comme disponible', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    // Le descriptif de l'avis ne doit jamais être requalifié en passage de
    // cahier des charges : c'est la confusion que P0-01 doit rendre impossible.
    for (const forbidden of [
      'passage du cahier des charges',
      'extrait du cahier des charges',
      'exigence extraite',
      'exigence validée disponible',
    ]) {
      expect(text.toLowerCase()).not.toContain(forbidden.toLowerCase())
    }
  })

  it('affiche des dates absolues et la date de vérification', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    // Année visible = date absolue. Aucun « il y a … jours », qui deviendrait
    // faux dès que la page est mise en cache.
    expect(text).toContain('2026')
    expect(text).toMatch(/vérifiés contre la source officielle/i)
    expect(text).not.toMatch(/il y a \d+ jour/i)
    expect(text).not.toMatch(/dans \d+ jours/i)
  })

  it('n’expose ni score, ni verdict de benchmark, ni identifiant de ciblage', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = (container.textContent ?? '').toLowerCase()

    for (const leak of ['icp-materials-eu', 'normalized_score', 'final_verdict', 'tercile']) {
      expect(text).not.toContain(leak)
    }
  })
})

describe('hero de la page d’accueil', () => {
  it('montre le signal, ses deux CTA et la mention du mode d’analyse', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })

    expect(await screen.findByText(publicDemoSignal.winner.legalName)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: fr.landing.heroPrimary })[0]).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(
      screen.getByRole('link', { name: new RegExp(fr.publicDemo.previewCta) }),
    ).toHaveAttribute('href', '/exemple-de-signal')

    // Sans cette mention, le besoin affiché passerait pour une exigence lue
    // dans un document.
    expect(screen.getByText(fr.publicDemo.previewMode)).toBeInTheDocument()
  })

  it('annonce un exemple, pas une fraîcheur figée dans le code', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/' })
    await screen.findByText(publicDemoSignal.winner.legalName)
    const text = container.textContent ?? ''

    expect(text).toContain(fr.publicDemo.previewEyebrow)
    // « Signal récent » vieillirait sans que personne ne le voie.
    expect(text).not.toContain('Signal récent')
  })

  it('sépare le fait publié de l’inférence Kivou', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    await screen.findByText(publicDemoSignal.winner.legalName)

    // La requête est portée SUR la carte : « Besoin plausible » apparaît aussi
    // dans la chaîne de valeur plus bas, et une recherche globale confondrait
    // les deux.
    const card = screen.getByText(publicDemoSignal.winner.legalName).closest('article')!
    expect(within(card).getByText(fr.publicDemo.previewNeedLabel)).toBeInTheDocument()
    expect(within(card).getByText(publicDemoSignal.need.statement)).toBeInTheDocument()
    // La formulation reste au conditionnel du corpus — jamais « va acheter ».
    expect(publicDemoSignal.need.statement).toMatch(/pourrait/)
  })
})

describe('navigation publique', () => {
  it('ouvre et referme un menu accessible au clavier', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    const toggle = await screen.findByRole('button', { name: fr.nav.openMenu })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('link', { name: fr.publicDemo.navLabel })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('données de démonstration', () => {
  it('n’expose aucun champ lié à un compte client', () => {
    const keys = JSON.stringify(publicDemoSignal).toLowerCase()

    for (const forbidden of [
      'icp',
      'score',
      'band',
      'feedback',
      'grant',
      'billing',
      'account_id',
      'target_icp',
    ]) {
      expect(keys).not.toContain(`"${forbidden}"`)
    }
  })

  it('porte une source et une date de vérification exploitables', () => {
    expect(publicDemoSignal.sourceUrl).toMatch(/^https:\/\/ted\.europa\.eu\//)
    expect(publicDemoSignal.lastVerifiedAt).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(publicDemoSignal.documentary.mode).toBe('metadata_fallback')
    expect(publicDemoSignal.documentary.validatedRequirement).toBe(false)
  })

  it('a une date d’attribution réelle, antérieure au début d’exécution', () => {
    const award = new Date(publicDemoSignal.timing.awardDate)
    const start = new Date(publicDemoSignal.timing.startDate)

    expect(Number.isNaN(award.getTime())).toBe(false)
    // Sans vraie date d'attribution, le hero n'aurait pas le droit de parler
    // de « nouvelle attribution ».
    expect(award.getTime()).toBeLessThan(start.getTime())
  })
})

describe('dictionnaires', () => {
  it('couvre les mêmes clés publicDemo en français et en anglais', () => {
    expect(Object.keys(en.publicDemo).sort()).toEqual(Object.keys(fr.publicDemo).sort())
  })

  it('ne laisse aucune chaîne publicDemo vide', () => {
    for (const dictionary of [fr.publicDemo, en.publicDemo]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(typeof value === 'string' && value.trim().length > 0, key).toBe(true)
      }
    }
  })
})
