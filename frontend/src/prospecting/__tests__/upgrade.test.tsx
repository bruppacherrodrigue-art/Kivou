import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlanCatalogue } from '../../api/types'
import { readCheckoutReturn } from '../../billing/checkoutIntent'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, PRO_STATUS, callsTo, mockApi, renderApp } from '../../test/harness'
import { UpgradeDialog } from '../components/UpgradeDialog'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

const checkout = {
  body: { checkout_url: 'https://checkout.stripe.test/cs_paywall', plan: 'pro', currency: 'eur' },
}

function setup(catalogue: PlanCatalogue = CATALOGUE, status = DISCOVERY_STATUS) {
  mockApi({
    'GET /billing/plans': { body: catalogue },
    'GET /billing/status': { body: status },
    'POST /billing/checkout': checkout,
  })
}

describe('paywall commercial du signal verrouillé', () => {
  it('présente Essential et Pro depuis le catalogue, avec le recommandé fourni par le serveur', async () => {
    setup()
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42' }} upgradeTo={['essential', 'pro']} />, { session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Continuez votre prospection' })).toBeVisible()
    expect(screen.getAllByText('SIGNAL VERROUILLÉ').length).toBeGreaterThan(0)
    expect(screen.getByText('Vous avez utilisé vos 3 signaux Découverte. Passez à un abonnement pour accéder aux prochaines opportunités et à leurs preuves.')).toBeVisible()
    const essential = screen.getByRole('heading', { name: 'Essential' }).closest('section')!
    const pro = screen.getByRole('heading', { name: 'Pro' }).closest('section')!
    expect(within(essential).getByText(/^49.*€$/)).toBeVisible()
    expect(within(essential).getByText('/ mois')).toBeVisible()
    expect(within(pro).getByText(/^99.*€$/)).toBeVisible()
    expect(within(pro).getByText('Recommandé')).toBeVisible()
    expect(within(essential).getByText('1 profil cible')).toBeVisible()
    expect(within(pro).getByText('3 profils cibles')).toBeVisible()
    expect(document.body).not.toHaveTextContent('(s)')
  })

  it('adapte la présentation à l’unique plan réellement disponible', async () => {
    setup()
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42' }} upgradeTo={['essential']} />, { session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Essential' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Pro' })).not.toBeInTheDocument()
    expect(screen.queryByText('Choisir une offre')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveAttribute('data-plan-count', '1')
  })

  it('reste piloté par le catalogue lorsqu’un troisième plan achetable y apparaît', async () => {
    const scale = {
      ...CATALOGUE.plans[2],
      plan_code: 'scale',
      recommended: false,
      monthly_price: { eur: { currency: 'eur', amount_minor_units: 19900 } },
      entitlements: { ...CATALOGUE.plans[2].entitlements, max_active_icps: 8 },
    }
    const catalogue = { ...CATALOGUE, plans: [...CATALOGUE.plans, scale] } as unknown as PlanCatalogue
    setup(catalogue)
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42' }} />, { session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Essential' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Pro' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Scale' })).toBeVisible()
    const scaleCard = screen.getByRole('heading', { name: 'Scale' }).closest('section')!
    expect(within(scaleCard).getByText(/^199.*€$/)).toBeVisible()
    expect(screen.getByRole('dialog')).toHaveAttribute('data-plan-count', '3')
  })

  it('n’annonce pas trois signaux utilisés lorsque le compteur serveur dit le contraire', async () => {
    setup(CATALOGUE, { ...DISCOVERY_STATUS, discovery: { ...DISCOVERY_STATUS.discovery, granted_signal_count: 1, remaining_slots: 2 } })
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42' }} />, { session: AUTHENTICATED })

    await screen.findByRole('heading', { name: 'Continuez votre prospection' })
    expect(document.body).not.toHaveTextContent('utilisé vos 3 signaux')
    expect(document.body).toHaveTextContent('Votre accès Découverte ne couvre pas ce signal')
  })

  it('ferme avec la croix, Échap ou Continuer avec Découverte et place le focus dans la fenêtre', async () => {
    const onClose = vi.fn()
    setup()
    renderApp(<UpgradeDialog onClose={onClose} intent={{ kind: 'signal', signalKey: 'sig-42' }} />, { session: AUTHENTICATED })
    const close = await screen.findByRole('button', { name: 'Fermer' })
    expect(close).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Continuer avec Découverte' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(onClose).toHaveBeenCalledTimes(2)
    await userEvent.click(close)
    expect(onClose).toHaveBeenCalledTimes(3)
  })

  it('ouvre Stripe directement, conserve le signal et bloque les doubles clics', async () => {
    let release!: (value: typeof checkout) => void
    const pending = new Promise<typeof checkout>((resolve) => { release = resolve })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'POST /billing/checkout': () => pending,
    })
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42', artifactId: 'artifact-7' }} />, { session: AUTHENTICATED })

    const button = await screen.findByRole('button', { name: /Choisir Pro — 99.*€\/mois/ })
    act(() => { fireEvent.click(button); fireEvent.click(button) })
    expect(callsTo('/billing/checkout')).toHaveLength(1)
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent('Ouverture du paiement…')

    await act(async () => { release(checkout); await pending })
    expect(callsTo('/billing/checkout')[0].body).toEqual({ plan: 'pro', currency: 'eur' })
    expect(readCheckoutReturn('acc_1')).toEqual({ kind: 'signal', signalKey: 'sig-42', artifactId: 'artifact-7' })
    expect(assign).toHaveBeenCalledWith('https://checkout.stripe.test/cs_paywall')
  })

  it('affiche une erreur exploitable et permet de réessayer', async () => {
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'POST /billing/checkout': { status: 503, body: { detail: { code: 'billing_unavailable' } } },
    })
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42' }} />, { session: AUTHENTICATED })

    await userEvent.click(await screen.findByRole('button', { name: /Choisir Essential — 49.*€\/mois/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Facturation indisponible')
    expect(screen.getByRole('button', { name: /Choisir Essential — 49.*€\/mois/ })).toBeEnabled()
  })

  it('renvoie vers la gestion de facturation quand le serveur interdit une nouvelle souscription', async () => {
    setup(CATALOGUE, PRO_STATUS)
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'sig-42' }} />, { session: AUTHENTICATED })
    expect(await screen.findByRole('link', { name: 'Gérer ma facturation' })).toBeVisible()
    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(0))
  })
})
