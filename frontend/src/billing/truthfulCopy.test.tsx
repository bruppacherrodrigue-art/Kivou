import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_DETAIL,
  LOCKED_ITEM,
  ME,
  PRO_STATUS,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

/* Deux écrans qui affirmaient ce qu'ils ne peuvent pas savoir.
 *
 * `/checkout/cancel` est une URL de retour : n'importe qui peut l'ouvrir, à
 * n'importe quel moment. Elle ne reçoit rien de Stripe, n'interroge rien, et
 * ne sait donc ni qu'un paiement a été interrompu, ni qu'aucun débit n'a eu
 * lieu, ni que l'offre n'a pas changé. Elle affirmait pourtant les trois.
 *
 * Le teaser verrouillé, lui, disait « réservés aux offres payantes ». C'est
 * faux dès qu'un compte PAYANT rencontre un signal verrouillé — ce qui arrive
 * normalement, par la fenêtre d'historique de son plan. Le client lit alors
 * qu'il lui faut payer ce qu'il paie déjà.
 */

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

const BILLING = {
  'GET /billing/plans': { body: CATALOGUE },
  'GET /target-icps': { body: [ICP] },
}

/* Le statut vient du `mockApi` de chaque test : le passer ici en plus ferait
 * croire que ce rendu le décide, alors qu'il est lu par le composant. */
function render(route: string, locale: 'fr' | 'en' = 'fr') {
  const session =
    locale === 'fr'
      ? AUTHENTICATED
      : { status: 'authenticated' as const, me: { ...ME, locale: 'en' } }
  renderApp(<AppRoutes />, { session, route, locale })
}

async function selectLockedPreview() {
  const user = userEvent.setup()
  const workspace = await screen.findByTestId('signal-workspace')
  await user.click(await within(workspace).findByRole('button', { name: /signal verrouillé/i }))
  return within(workspace).findByRole('region', { name: 'Détail du signal sélectionné' })
}

// ─── 1. le retour depuis le paiement ─────────────────────────────────────────

describe('retour depuis le parcours de paiement', () => {
  const FORBIDDEN_FR = [
    'Rien n’a été débité',
    'Rien n\'a été débité',
    'votre offre n’a pas changé',
    'n’a pas changé',
  ]
  const FORBIDDEN_EN = [
    'Nothing was charged',
    'your plan has not changed',
    'has not changed',
  ]

  it('n’affirme aucun débit ni aucune offre inchangée — FR', async () => {
    mockApi({ ...BILLING, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    render('/checkout/cancel')

    await screen.findByRole('heading', { level: 1 })
    const page = document.body.textContent ?? ''
    for (const claim of FORBIDDEN_FR) {
      expect(page).not.toContain(claim)
    }
  })

  it('n’affirme aucun débit ni aucune offre inchangée — EN', async () => {
    mockApi({ ...BILLING, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    render('/checkout/cancel', 'en')

    await screen.findByRole('heading', { level: 1 })
    const page = document.body.textContent ?? ''
    for (const claim of FORBIDDEN_EN) {
      expect(page).not.toContain(claim)
    }
  })

  /* Le cas qui rend l'ancienne copy indéfendable : un client déjà Pro ouvre
   * l'adresse à la main. Rien n'a été « interrompu », et l'écran n'a aucun
   * moyen de le savoir. */
  it('un compte déjà payant n’y lit rien sur un débit récent', async () => {
    mockApi({ ...BILLING, 'GET /billing/status': { body: PRO_STATUS } })
    render('/checkout/cancel')

    await screen.findByRole('heading', { level: 1 })
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/débit|débité|prélèv/i)
    expect(page).not.toMatch(/offre n’a pas changé|plan n’a pas changé/i)
  })

  it('renvoie vers la facturation pour vérifier l’état réel', async () => {
    mockApi({ ...BILLING, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    render('/checkout/cancel')

    const cta = await screen.findByRole('link', { name: 'Voir ma facturation' })
    expect(cta).toHaveAttribute('href', '/app/billing')
  })

  it('ne dit que ce que la page sait', async () => {
    mockApi({ ...BILLING, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    render('/checkout/cancel')

    await screen.findByRole('heading', { level: 1 })
    const page = document.body.textContent ?? ''
    expect(page).toMatch(/Cette page ne modifie pas votre accès/)
  })
})

// ─── 2. le teaser verrouillé, vrai pour tous les plans ───────────────────────

describe('signal verrouillé sur un compte payant', () => {
  /* §19 — un compte Pro rencontre un signal hors de sa fenêtre d'historique.
   * Le signal est verrouillé légitimement, mais lui dire que l'information est
   * « réservée aux offres payantes » lui demande d'acheter ce qu'il a déjà. */
  it('le teaser ne parle plus d’offres payantes', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
    })
    render('/app/signals')

    const panel = await selectLockedPreview()
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('réservés aux offres payantes')
    expect(page).not.toContain('réservées aux offres payantes')
    expect(panel).toHaveTextContent('Ces informations ne sont pas incluses dans votre accès actuel.')
  })

  it('le teaser propose une action universelle, jamais « Voir les offres »', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
    })
    render('/app/signals')

    const panel = await selectLockedPreview()
    expect(screen.queryByRole('link', { name: 'Voir les offres' })).not.toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it('le détail n’invite pas à comparer une grille qu’un payant ne verra pas', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
    })
    render('/app/signals/sig_locked_1')

    await screen.findByText('Ce signal est verrouillé')
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Comparez les offres')
    expect(page).not.toContain('offres payantes')
  })

  it('le détail conserve la vérité sur droits et fenêtre d’historique', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
    })
    render('/app/signals/sig_locked_1')

    await screen.findByText('Ce signal est verrouillé')
    const page = document.body.textContent ?? ''
    expect(page).toMatch(/droits/)
    expect(page).toMatch(/fenêtre d’historique/)
  })

  it('le détail garde une action universelle vers la facturation', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
    })
    render('/app/signals/sig_locked_1')

    await screen.findByText('Ce signal est verrouillé')
    expect(screen.queryByRole('link', { name: 'Voir les offres' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it('reste vrai pour un compte Découverte', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
    })
    render('/app/signals')

    const panel = await selectLockedPreview()
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('réservés aux offres payantes')
    expect(within(panel).getByRole('link', { name: 'Gérer mon accès' })).toBeInTheDocument()
  })

  it('reste vrai en anglais', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
    })
    render('/app/signals/sig_locked_1', 'en')

    await screen.findByText('This signal is locked')
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('reserved for paid plans')
    expect(page).not.toContain('Compare the plans')
    expect(page).toMatch(/history window/)
    expect(screen.getByRole('link', { name: 'Manage my access' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
  })

  it('ne laisse fuir aucune donnée protégée, quel que soit le plan', async () => {
    mockApi({
      ...BILLING,
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
    })
    render('/app/signals')

    await screen.findByText('Verrouillé')
    const page = document.body.textContent ?? ''
    for (const secret of ['Constructions Bertrand', '12345678900011', 'boamp.fr']) {
      expect(page).not.toContain(secret)
    }
  })
})
