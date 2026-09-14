import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, PRO_STATUS, callsTo, mockApi, renderApp } from '../../test/harness'
import { UpgradeDialog } from '../components/UpgradeDialog'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
function Probe() { const location = useLocation(); return <output data-testid="route">{JSON.stringify({ path: location.pathname, search: location.search, state: location.state })}</output> }
describe('server catalogue upgrade invitation', () => {
  it.each([
    { locale: 'fr' as const, currency: 'chf' as const, essential: 4900, pro: 9900, labels: ['49 CHF', '99 CHF'] },
    { locale: 'fr' as const, currency: 'eur' as const, essential: 4900, pro: 9900, labels: ['49 €', '99 €'] },
    { locale: 'en' as const, currency: 'chf' as const, essential: 4950, pro: 9975, labels: ['CHF 49.50', 'CHF 99.75'] },
    { locale: 'en' as const, currency: 'eur' as const, essential: 4950, pro: 9975, labels: ['€49.50', '€99.75'] },
  ])('renders catalogue minor units exactly once in $locale/$currency', async ({ locale, currency, essential, pro, labels }) => {
    const catalogue = { ...CATALOGUE, currencies: [currency], plans: CATALOGUE.plans.map(plan => ({
      ...plan,
      monthly_price: plan.plan_code === 'discovery' ? {} : {
        [currency]: { currency, amount_minor_units: plan.plan_code === 'essential' ? essential : pro },
      },
    })) }
    mockApi({ 'GET /billing/plans': { body: catalogue }, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'company', companyKey: 'requested-alias' }} />, { session: AUTHENTICATED, locale })
    const essentialHeading = await screen.findByRole('heading', { name: locale === 'fr' ? 'Essentiel' : 'Essential' })
    const proHeading = screen.getByRole('heading', { name: 'Pro' })
    for (const [index, heading] of [essentialHeading, proHeading].entries()) {
      const section = heading.closest('section')!
      expect(within(section).getByText(text => text.replace(/[\u00a0\u202f]/g, ' ') === `${labels[index]} / ${locale === 'fr' ? 'mois' : 'month'}`)).toBeVisible()
    }
    expect(callsTo('/billing/checkout')).toHaveLength(0)
    expect(callsTo('/billing/portal')).toHaveLength(0)
  })
  it('requires an explicit plan choice and carries the company intent without starting payment', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<><UpgradeDialog onClose={vi.fn()} intent={{ kind: 'company', companyKey: 'requested-alias' }} /><Probe /></>, { session: AUTHENTICATED, route: '/app/companies/requested-alias' })
    fireEvent.click(await screen.findByRole('button', { name: 'Choisir Essentiel' }))
    expect(screen.getByTestId('route')).toHaveTextContent('"path":"/app/billing"')
    expect(screen.getByTestId('route')).toHaveTextContent('"checkoutIntent":{"kind":"company","companyKey":"requested-alias"}')
    expect(screen.getByTestId('route')).toHaveTextContent('"checkoutAccountId":"acc_1"')
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
  it('does not offer a second subscription when the server requires management', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: { ...PRO_STATUS, billing_action: 'manage_subscription' } } })
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'signal' }} />, { session: AUTHENTICATED })
    await screen.findByRole('link', { name: 'Gérer ma facturation' })
    expect(screen.getByRole('heading', { name: 'Votre prospection, avec les bons accès.' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Choisir Essentiel' })).not.toBeInTheDocument())
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
})
