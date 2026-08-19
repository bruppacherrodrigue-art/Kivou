import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  LOCKED_DETAIL,
  UNLOCKED_DETAIL,
  mockApi,
  renderApp,
} from '../test/harness'

/* SPEC-015 §51 — les six vérifications du détail. */

afterEach(() => vi.unstubAllGlobals())

function detailRoutes(payload: unknown) {
  return {
    'GET /signals/sig_unlocked_1': { body: payload },
    'GET /signals/sig_locked_1': { body: payload },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  }
}

describe('détail d’un signal', () => {
  it('sépare visiblement les faits publics de l’analyse Kivou', async () => {
    mockApi(detailRoutes(UNLOCKED_DETAIL))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_unlocked_1' })

    const facts = await screen.findByRole('region', { name: /Ce que la source officielle publie/ })
    const analysis = screen.getByRole('region', { name: /Ce que Kivou déduit de ces faits/ })

    expect(facts).not.toBe(analysis)
    // Le fait public — l'acheteur — vit dans la section des faits.
    expect(within(facts).getByText('Commune de Villeneuve')).toBeInTheDocument()
    // L'hypothèse vit dans l'autre, et pas l'inverse.
    expect(within(analysis).getByText('Matériaux ou composants')).toBeInTheDocument()
    expect(within(facts).queryByText('Matériaux ou composants')).not.toBeInTheDocument()

    // Les trois dates restent distinctes : attribution ≠ notification ≠ publication.
    expect(within(facts).getByText('Attribution')).toBeInTheDocument()
    expect(within(facts).getByText('Notification du contrat')).toBeInTheDocument()
    expect(within(facts).getByText('Publication')).toBeInTheDocument()
  })

  it('conserve au besoin son statut d’hypothèse', async () => {
    mockApi(detailRoutes(UNLOCKED_DETAIL))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_unlocked_1' })

    const analysis = await screen.findByRole('region', {
      name: /Ce que Kivou déduit de ces faits/,
    })
    expect(within(analysis).getByText('Besoins plausibles')).toBeInTheDocument()
    // La note de l'API, qui porte le mot « plausible », n'est pas masquée.
    expect(
      within(analysis).getByText(/Ces besoins sont plausibles/),
    ).toBeInTheDocument()
    expect(within(analysis).getByText(/peut nécessiter/)).toBeInTheDocument()

    // Aucune formulation d'achat certain.
    const page = (document.body.textContent ?? '').toLowerCase()
    expect(page).not.toMatch(/va acheter|achètera|achat prévu|achat certain|client garanti/)
  })

  it('affiche la preuve uniquement là où l’API en renvoie, et sépare les deux natures', async () => {
    const user = userEvent.setup()
    mockApi(detailRoutes(UNLOCKED_DETAIL))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_unlocked_1' })

    const evidence = await screen.findByRole('region', { name: /Chaque fait ci-dessous renvoie/ })
    expect(within(evidence).getByText('Preuves des faits publiés')).toBeInTheDocument()
    expect(within(evidence).getByText('Éléments ayant servi à l’analyse')).toBeInTheDocument()
    // La mise en garde de l'API : ces pièces ne prouvent pas un achat.
    expect(within(evidence).getByText(/Elles ne prouvent pas un achat/)).toBeInTheDocument()

    // Les passages sont repliés par défaut, puis lisibles en entier.
    expect(screen.queryByText(/Le marché est attribué à/)).not.toBeInTheDocument()
    await user.click(within(evidence).getByRole('button', { name: /Attributaire/ }))
    expect(
      await within(evidence).findByText('Le marché est attribué à Constructions Bertrand SA.'),
    ).toBeInTheDocument()
  })

  it('rend le lien source de façon sûre et sans chemin interne', async () => {
    mockApi(detailRoutes(UNLOCKED_DETAIL))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_unlocked_1' })

    const link = await screen.findByRole('link', { name: /Ouvrir l’avis source/ })
    expect(link).toHaveAttribute('href', 'https://www.boamp.fr/avis/26-104412')
    expect(link).toHaveAttribute('target', '_blank')
    // `noopener` évite que la page ouverte garde une référence à la nôtre.
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))

    const page = document.body.textContent ?? ''
    for (const leak of ['/home/', '/tmp/', 'tests/', 'fixtures/', 'src/signals', '.jsonl']) {
      expect(page).not.toContain(leak)
    }
  })

  it('ne laisse fuiter aucun champ protégé sur un détail verrouillé', async () => {
    mockApi(detailRoutes(LOCKED_DETAIL))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' })

    expect(await screen.findByRole('heading', { name: 'Ce signal est verrouillé' })).toBeInTheDocument()

    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Constructions Bertrand')
    expect(page).not.toContain('Commune de Villeneuve')
    expect(page).not.toContain('Réfection de la voirie')
    expect(page).not.toContain('boamp.fr')
    expect(page).not.toContain('MP-2026-0412')
    expect(page).not.toContain('1240000')
    expect(screen.queryByText('Preuve documentaire')).not.toBeInTheDocument()

    expect(screen.getByRole('link', { name: 'Voir les offres' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it('n’expose aucun contrôle de retour sur un signal verrouillé', async () => {
    mockApi(detailRoutes(LOCKED_DETAIL))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' })

    await screen.findByRole('heading', { name: 'Ce signal est verrouillé' })

    expect(screen.queryByText('Pertinent')).not.toBeInTheDocument()
    expect(screen.queryByText('Pas pertinent')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'J’ai contacté cette entreprise' }),
    ).not.toBeInTheDocument()
  })

  it('rend un signal introuvable comme un état produit', async () => {
    mockApi({
      'GET /signals/inconnu': {
        status: 404,
        body: { detail: { code: 'signal_not_found', message: 'signal introuvable' } },
      },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/inconnu' })

    expect(await screen.findByText('Signal introuvable')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Retour aux signaux' })).toBeInTheDocument()
  })
})
