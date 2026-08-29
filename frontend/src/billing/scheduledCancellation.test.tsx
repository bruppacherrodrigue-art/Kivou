import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  ME,
  PRO_CANCELLING_OTHER_DATE_STATUS,
  PRO_CANCELLING_STATUS,
  PRO_STATUS,
  RECOVER_STATUS,
  SUPPORT_STATUS,
  mockApi,
  renderApp,
} from '../test/harness'
import type { BillingStatus } from '../api/types'

/* P0-03G — dire au client QUAND son abonnement s'arrête, et ne jamais l'inventer.
 *
 * Le défaut fermé côté serveur : une résiliation demandée au portail restait
 * invisible, parce que Stripe l'exprimait par une date (`cancel_at`) et que
 * Kivou ne lisait qu'un booléen. Le serveur rend désormais
 * `scheduled_cancellation_at`.
 *
 * Ce que ce fichier verrouille côté écran :
 *
 *   1. la date affichée vient EXCLUSIVEMENT de `scheduled_cancellation_at` ;
 *      `current_period_end` ne la remplace jamais, même quand elle existe ;
 *   2. « fin de période » ne se dit QUE si l'échéance tombe vraiment dessus —
 *      Stripe permet de planifier une autre date, et l'annoncer comme une fin
 *      de période donnerait au client une échéance fausse ;
 *   3. une échéance annoncée ne coupe RIEN. L'accès reste celui du plan payé
 *      jusqu'à ce que Stripe change le statut. Le navigateur ne décide d'aucun
 *      droit, et surtout pas en comparant une date à l'horloge locale ;
 *   4. l'écran d'un compte SUSPENDU ne porte pas cette notice : dire « votre
 *      abonnement prendra fin le … » à quelqu'un dont l'accès est déjà coupé
 *      met deux affirmations contradictoires sur le même écran.
 */

afterEach(() => vi.unstubAllGlobals())

function render(status: BillingStatus, locale: 'fr' | 'en' = 'fr') {
  mockApi({
    'GET /billing/plans': { body: CATALOGUE },
    'GET /billing/status': { body: status },
    'POST /billing/portal': { body: { portal_url: 'https://billing.stripe.test/cus_1' } },
  })
  const session =
    locale === 'fr'
      ? AUTHENTICATED
      : { status: 'authenticated' as const, me: { ...ME, locale: 'en' } }
  renderApp(<AppRoutes />, { session, route: '/app/billing', locale })
}

// ─── A. aucune échéance ──────────────────────────────────────────────────────

describe('aucune résiliation programmée', () => {
  it('n’affiche aucune notice', async () => {
    render(PRO_STATUS)

    await screen.findByRole('button', { name: /Gérer ma facturation/ })
    expect(screen.queryByText(/Résiliation programmée/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/prendra fin/)
  })

  it('un compte Découverte n’en voit pas davantage', async () => {
    render({ ...PRO_STATUS, plan_code: 'discovery', billing_action: 'choose_plan' })

    await screen.findByRole('button', { name: /Choisir Pro/ })
    expect(screen.queryByText(/Résiliation programmée/)).not.toBeInTheDocument()
  })
})

// ─── B. échéance qui tombe sur la fin de période ─────────────────────────────

describe('résiliation en fin de période', () => {
  it('annonce la fin de période avec la date du serveur — FR', async () => {
    render(PRO_CANCELLING_STATUS)

    expect(await screen.findByText('Résiliation programmée')).toBeInTheDocument()
    expect(
      screen.getByText(/Votre abonnement prendra fin à la fin de la période en cours, le/),
    ).toBeInTheDocument()
    expect(document.body.textContent).toMatch(/18 septembre 2026/)
  })

  it('annonce la fin de période — EN', async () => {
    render(PRO_CANCELLING_STATUS, 'en')

    expect(await screen.findByText('Cancellation scheduled')).toBeInTheDocument()
    expect(
      screen.getByText(/Your subscription will end at the end of the current period, on/),
    ).toBeInTheDocument()
    expect(document.body.textContent).toMatch(/18 September 2026/)
  })
})

// ─── C. échéance à une AUTRE date ────────────────────────────────────────────

describe('résiliation à une date distincte', () => {
  it('dit la date, sans jamais parler de fin de période — FR', async () => {
    render(PRO_CANCELLING_OTHER_DATE_STATUS)

    expect(await screen.findByText('Résiliation programmée')).toBeInTheDocument()
    expect(screen.getByText(/Votre abonnement prendra fin le/)).toBeInTheDocument()
    const page = document.body.textContent ?? ''
    expect(page).toMatch(/30 novembre 2026/)
    expect(page).not.toMatch(/fin de la période en cours/)
  })

  it('dit la date, sans « end of the current period » — EN', async () => {
    render(PRO_CANCELLING_OTHER_DATE_STATUS, 'en')

    expect(await screen.findByText('Cancellation scheduled')).toBeInTheDocument()
    const page = document.body.textContent ?? ''
    expect(page).toMatch(/30 November 2026/)
    expect(page).not.toMatch(/end of the current period/)
  })

  /* Le cœur du défaut, transposé à l'écran : la date de fin de période EXISTE
   * et vaut autre chose. La reprendre annoncerait au client une échéance qui
   * n'est pas la sienne. */
  it('n’emprunte jamais la date à current_period_end', async () => {
    render(PRO_CANCELLING_OTHER_DATE_STATUS)

    await screen.findByText('Résiliation programmée')
    const page = document.body.textContent ?? ''
    expect(page).toMatch(/30 novembre 2026/)
    expect(page).not.toMatch(/18 septembre 2026/)
  })

  it('ne promet aucun renouvellement quand une résiliation est programmée', async () => {
    render(PRO_CANCELLING_OTHER_DATE_STATUS)

    await screen.findByText('Résiliation programmée')
    expect(document.body.textContent).not.toMatch(/Prochain renouvellement/)
  })
})

// ─── D. l'accès ne bouge pas ─────────────────────────────────────────────────

describe('une échéance annoncée ne coupe rien', () => {
  it('garde le plan payant et le portail', async () => {
    render(PRO_CANCELLING_STATUS)

    await screen.findByText('Résiliation programmée')
    const currentPlan = screen.getByText('Votre offre').closest('section')!
    expect(within(currentPlan).getByText('Pro')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Gérer ma facturation/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
  })

  it('vaut aussi pour une échéance déjà passée — le navigateur ne décide rien', async () => {
    /* Si l'écran comparait la date à l'horloge locale, il retirerait ici un
     * accès que le serveur dit encore actif. Stripe reste l'autorité. */
    render({
      ...PRO_CANCELLING_STATUS,
      scheduled_cancellation_at: '2020-01-01T00:00:00+00:00',
    })

    await screen.findByText('Résiliation programmée')
    const currentPlan = screen.getByText('Votre offre').closest('section')!
    expect(within(currentPlan).getByText('Pro')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Gérer ma facturation/ })).toBeInTheDocument()
  })
})

// ─── E. les écrans où la notice n'a rien à faire ─────────────────────────────

describe('comptes dont l’accès n’est pas actif', () => {
  it('un compte suspendu ne lit pas « prendra fin »', async () => {
    render({
      ...RECOVER_STATUS,
      scheduled_cancellation_at: '2026-09-18T00:00:00+00:00',
      cancel_at_period_end: true,
    })

    await screen.findByText('Accès suspendu — incident de paiement')
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/Résiliation programmée/)
    expect(page).not.toMatch(/prendra fin/)
  })

  it('un compte en anomalie de facturation non plus', async () => {
    render({
      ...SUPPORT_STATUS,
      scheduled_cancellation_at: '2026-09-18T00:00:00+00:00',
      cancel_at_period_end: true,
    })

    await screen.findByText('Vérification de facturation nécessaire')
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/Résiliation programmée/)
    expect(page).not.toMatch(/prendra fin/)
  })
})

// ─── F. rien de technique ne fuit ────────────────────────────────────────────

describe('la notice ne dit rien de technique', () => {
  it('n’expose ni nom de champ ni horodatage brut', async () => {
    render(PRO_CANCELLING_OTHER_DATE_STATUS)

    await screen.findByText('Résiliation programmée')
    const page = document.body.textContent ?? ''
    for (const forbidden of [
      'scheduled_cancellation_at',
      'cancel_at_period_end',
      'cancel_at',
      '2026-11-30T00:00:00',
    ]) {
      expect(page).not.toContain(forbidden)
    }
  })
})
