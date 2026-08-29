import { describe, expect, it, afterEach, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  PRO_CANCELLING_STATUS,
  PRO_STATUS,
  RECOVER_STATUS,
  SUPPORT_STATUS,
  TERMINAL_STATUS,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'
import type { BillingStatus } from '../api/types'

/* P0-03 §3, §17 — `billing_action` est la SEULE autorité sur ce que l'écran
 * de facturation propose.
 *
 * Deux questions, deux champs :
 *
 *     plan_code       →  quels droits le compte a-t-il maintenant ?
 *     billing_action  →  quelle action de facturation est sûre maintenant ?
 *
 * Les confondre coûte de l'argent réel. Un compte `past_due` vaut `discovery`
 * comme un compte qui n'a jamais payé — mais il porte un abonnement facturé,
 * et lui proposer « Choisir Pro » le mènerait à un 409, ou pire, à une seconde
 * facture. Ces tests interdisent ce raccourci état par état.
 */

afterEach(() => vi.unstubAllGlobals())

function billingRoutes(status: BillingStatus) {
  return {
    'GET /billing/plans': { body: CATALOGUE },
    'GET /billing/status': { body: status },
    'POST /billing/portal': { body: { portal_url: 'https://billing.stripe.test/cus_1' } },
    'POST /billing/checkout': {
      body: { checkout_url: 'https://checkout.stripe.test/cs_1', plan: 'pro', currency: 'chf' },
    },
  }
}

function render(status: BillingStatus, locale: 'fr' | 'en' = 'fr') {
  mockApi(billingRoutes(status))
  renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing', locale })
}

const choosePro = { name: /Choisir Pro/ }

describe('billing_action — choose_plan', () => {
  it('propose la grille et le paiement', async () => {
    render(DISCOVERY_STATUS)
    expect(await screen.findByRole('button', choosePro)).toBeInTheDocument()
    expect(screen.getByText('Devise')).toBeInTheDocument()
  })

  it('ne propose aucun portail', async () => {
    render(DISCOVERY_STATUS)
    await screen.findByRole('button', choosePro)
    expect(screen.queryByRole('button', { name: /Gérer ma facturation/ })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Ouvrir le portail de facturation/ }),
    ).not.toBeInTheDocument()
  })

  it('est la seule valeur qui autorise un POST /billing/checkout', async () => {
    const user = userEvent.setup()
    render(DISCOVERY_STATUS)
    await user.click(await screen.findByRole('button', choosePro))
    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(1))
  })
})

describe('billing_action — manage_subscription', () => {
  it('propose le portail et jamais un second paiement', async () => {
    render(PRO_STATUS)
    expect(
      await screen.findByRole('button', { name: /Gérer ma facturation/ }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', choosePro)).not.toBeInTheDocument()
  })

  it('dit où vivent moyen de paiement, factures et résiliation', async () => {
    render(PRO_STATUS)
    await screen.findByRole('button', { name: /Gérer ma facturation/ })
    expect(screen.getByText(/portail de facturation/)).toBeInTheDocument()
  })

  it('garde le portail sur une résiliation programmée', async () => {
    render(PRO_CANCELLING_STATUS)
    expect(
      await screen.findByRole('button', { name: /Gérer ma facturation/ }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Résiliation programmée/)).toBeInTheDocument()
    expect(screen.queryByRole('button', choosePro)).not.toBeInTheDocument()
  })
})

describe('billing_action — recover_payment', () => {
  it('explique la suspension et ouvre le portail, sans grille', async () => {
    render(RECOVER_STATUS)
    expect(await screen.findByText('Accès suspendu — incident de paiement')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Ouvrir le portail de facturation/ }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', choosePro)).not.toBeInTheDocument()
    expect(screen.queryByText('Devise')).not.toBeInTheDocument()
  })

  it('ne promet ni réparation automatique ni paiement immédiat', async () => {
    render(RECOVER_STATUS)
    await screen.findByText('Accès suspendu — incident de paiement')
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/sera réparé|payez maintenant|réglez maintenant/i)
  })

  /* Le cas nommé par la supervision : les droits disent Découverte, le statut
   * dit `past_due`, et l'action dit récupération. Aucun bouton d'achat. */
  it('un compte past_due n’a AUCUN bouton d’achat', async () => {
    render(RECOVER_STATUS)
    await screen.findByText('Accès suspendu — incident de paiement')
    const currentPlan = screen.getByText('Votre offre').closest('section')!
    expect(within(currentPlan).getByText('Découverte')).toBeInTheDocument()
    expect(screen.getByText('Paiement en retard')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('ne retombe jamais sur la grille quand le portail échoue', async () => {
    const user = userEvent.setup()
    mockApi({
      ...billingRoutes(RECOVER_STATUS),
      'POST /billing/portal': {
        status: 409,
        body: { detail: { code: 'no_billing_customer' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(
      await screen.findByRole('button', { name: /Ouvrir le portail de facturation/ }),
    )
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    // L'échec du portail ne rouvre pas un chemin d'achat interdit.
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
  })
})

describe('billing_action — contact_support', () => {
  it('explique calmement et n’ouvre ni achat ni portail', async () => {
    render(SUPPORT_STATUS)
    expect(await screen.findByText('Vérification de facturation nécessaire')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Gérer ma facturation/ })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Ouvrir le portail de facturation/ }),
    ).not.toBeInTheDocument()
  })

  it('offre un contact humain', async () => {
    render(SUPPORT_STATUS)
    await screen.findByText('Vérification de facturation nécessaire')
    expect(screen.getByRole('link', { name: /contact@kivou\.eu/ })).toHaveAttribute(
      'href',
      'mailto:contact@kivou.eu',
    )
  })

  it('un compte trialing n’a AUCUN bouton d’achat', async () => {
    render(SUPPORT_STATUS)
    await screen.findByText('Vérification de facturation nécessaire')
    const currentPlan = screen.getByText('Votre offre').closest('section')!
    expect(within(currentPlan).getByText('Découverte')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
  })

  it('un statut que Stripe inventerait n’ouvre aucun achat', async () => {
    render({
      ...SUPPORT_STATUS,
      subscription_status: 'something_stripe_invented_later',
      billing_action: 'contact_support',
    })
    await screen.findByText('Vérification de facturation nécessaire')
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
  })

  it('n’expose aucun détail technique de facturation', async () => {
    render(SUPPORT_STATUS)
    await screen.findByText('Vérification de facturation nécessaire')
    const page = document.body.textContent ?? ''
    for (const forbidden of [
      'cus_',
      'sub_',
      'price_',
      'lookup',
      'billing_customer',
      'conflict',
      'contact_support',
    ]) {
      expect(page).not.toContain(forbidden)
    }
  })
})

describe('copy terminale', () => {
  /* `incomplete_expired` porte encore `payment_issue`, mais l'incident n'est
   * plus « en cours » : la tentative est morte et la place est libre. Dire
   * l'inverse retiendrait un client qui peut simplement recommencer. */
  it('ne parle pas d’incident en cours sur une tentative expirée', async () => {
    render(TERMINAL_STATUS)
    expect(await screen.findByRole('button', choosePro)).toBeInTheDocument()
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('Un incident de paiement est en cours sur cet abonnement.')
    expect(page).toContain('La tentative précédente n’est plus active.')
  })

  it('garde l’incident en cours sur un abonnement réellement suspendu', async () => {
    render(RECOVER_STATUS)
    await screen.findByText('Accès suspendu — incident de paiement')
    expect(document.body.textContent).not.toContain('La tentative précédente n’est plus active.')
  })
})

describe('anti double-paiement', () => {
  it('deux clics rapprochés ne produisent qu’un seul POST /billing/checkout', async () => {
    let release = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const seen: string[] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        const method = (init?.method ?? 'GET').toUpperCase()
        seen.push(`${method} ${url.pathname}`)
        const json = (body: unknown, status = 200) =>
          new Response(JSON.stringify(body), {
            status,
            headers: { 'Content-Type': 'application/json' },
          })

        if (method === 'POST' && url.pathname === '/billing/checkout') {
          // La requête reste EN VOL : c'est la fenêtre du double-clic, celle
          // qu'un simple `setState` ne referme pas dans le même tour de boucle.
          await gate
          return json({ checkout_url: 'https://checkout.stripe.test/cs_1' })
        }
        if (url.pathname === '/billing/plans') return json(CATALOGUE)
        if (url.pathname === '/billing/status') return json(DISCOVERY_STATUS)
        return json({ detail: { code: 'signal_not_found' } }, 404)
      }),
    )

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })
    const button = await screen.findByRole('button', choosePro)

    act(() => {
      fireEvent.click(button)
      fireEvent.click(button)
    })
    await act(async () => {
      release()
      await gate
    })

    expect(seen.filter((call) => call === 'POST /billing/checkout')).toHaveLength(1)
  })
})
