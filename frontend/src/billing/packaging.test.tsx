import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, ME, mockApi, renderApp } from '../test/harness'

/* P0-03 §14, §15 — ne pas vendre ce qui n'existe pas.
 *
 * L'audit préalable a trouvé deux capacités annoncées par la grille et
 * introuvables dans le produit :
 *
 *   — l'export : `export_level` n'est qu'un champ de catalogue. Aucune route
 *     backend, aucune UI. « Export limité » décrit le néant ;
 *   — les filtres de base et avancés : l'API gère bien `country` et `winner`,
 *     mais le feed n'expose que fraîcheur et sélecteur de profil, tous deux au
 *     niveau minimum. Un client qui paie pour « Filtres avancés » ne trouvera
 *     aucun filtre avancé.
 *
 * Ces deux-là quittent la COPY VISIBLE. Les champs du contrat backend, eux,
 * ne bougent pas : ils décrivent des décisions serveur réelles, et les
 * supprimer casserait l'autorisation des filtres côté API.
 *
 * Les limites territoriales sont désormais exercées côté serveur. La variante
 * publique de la grille les rend depuis le catalogue ; la variante connectée
 * conserve ici son contenu historique et ses actions de facturation.
 */

afterEach(() => vi.unstubAllGlobals())

function renderPlans() {
  mockApi({
    'GET /billing/plans': { body: CATALOGUE },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  })
  renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })
}

async function selectPro() {
  const user = userEvent.setup()
  const selector = await screen.findByLabelText(/Offre|Plan/)
  await user.selectOptions(selector, 'pro')
  return selector
}

const FORBIDDEN_FR = [
  'Export limité',
  'Export étendu',
  'Pas d’export',
  'Filtres essentiels',
  'Filtres de base',
  'Filtres avancés',
]

const FORBIDDEN_EN = [
  'Limited export',
  'Extended export',
  'No export',
  'Essential filters',
  'Basic filters',
  'Advanced filters',
  'Scheduled export',
  'Manual export',
]

describe('vérité du packaging', () => {
  it('ne vend aucune capacité inexistante — FR', async () => {
    renderPlans()
    await selectPro()
    const page = document.body.textContent ?? ''
    for (const forbidden of FORBIDDEN_FR) {
      expect(page).not.toContain(forbidden)
    }
  })

  it('ne vend aucune capacité inexistante — EN', async () => {
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    // `account.locale` fait autorité une fois connecté : passer `locale: 'en'`
    // au rendu ne suffit pas, `LocaleFollowsAccount` le ramènerait au français.
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/billing',
      locale: 'en',
    })
    const user = userEvent.setup()
    await user.selectOptions(await screen.findByLabelText(/Plan/), 'pro')
    const page = document.body.textContent ?? ''
    for (const forbidden of FORBIDDEN_EN) {
      expect(page).not.toContain(forbidden)
    }
  })

  it('conserve les capacités réellement utilisables', async () => {
    renderPlans()
    const user = userEvent.setup()
    const selector = await screen.findByLabelText('Offre')

    await user.selectOptions(selector, 'discovery')
    expect(document.body.textContent).toContain('3 signaux réels débloqués définitivement')
    expect(document.body.textContent).toContain('Jusqu’à 1 territoire par profil')

    await user.selectOptions(selector, 'pro')
    const page = document.body.textContent ?? ''
    // Profils : appliqué par `feedable_target_icps` et `over_limit_icps`.
    expect(page).toMatch(/profils? de ciblage/)
    expect(page).toContain('Plusieurs territoires par profil')
    // L'accès payant au flux et aux détails vient du contrat serveur ; le
    // compteur Discovery ne doit pas être transposé à Pro.
    expect(page).toContain('Accès au flux et aux détails')
    // Historique : appliqué par `within_history_window`.
    expect(page).toMatch(/Historique 365 jours/)
    // Preuve : servie par le détail.
    expect(page).toContain('Preuve documentaire complète')
    // Alertes : UI Notifications, préférence, job et cadence appliquée.
    expect(page).toContain('Alertes e-mail quotidiennes')

    await user.selectOptions(selector, 'scale')
    expect(document.body.textContent).toContain('Couverture territoriale étendue')
  })

  it('ne change pas les prix, qui viennent toujours du serveur', async () => {
    renderPlans()
    await selectPro()
    const page = document.body.textContent ?? ''
    expect(page).toContain('49')
    expect(page).toContain('99')
    expect(page).toContain('199')
    expect(page).toContain('Gratuit')
  })

  it('n’expose jamais l’offre Founding', async () => {
    renderPlans()
    await selectPro()
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/founding|fondateur/i)
    expect(page).not.toContain('29')
  })

  it('garde Pro recommandé', async () => {
    renderPlans()
    const selector = await selectPro()
    expect(within(selector).getByRole('option', { name: /Pro.*Recommandé/ })).toBeInTheDocument()
  })
})
