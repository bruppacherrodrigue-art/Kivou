import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { SignalListRow } from '../prospecting/components/SignalListRow'
import { BASE, renderSignal } from '../prospecting/__tests__/signal-regression-harness'
import { sharedZoneLabels } from '../presentation/dashboard/zoneLabels'
import { AUTHENTICATED, UNLOCKED_ITEM, DISCOVERY_STATUS, mockApi, renderApp } from '../test/harness'

describe('recette finition: corrections de revue', () => {
  it('separe titulaire, objet et metadonnees dans la ligne V11', async () => {
    mockApi(BASE)
    renderSignal(<SignalListRow item={UNLOCKED_ITEM} onOpen={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('scope-ready')).toHaveTextContent('ready'))
    const card = screen.getByRole('article')
    expect(within(card).getByText(UNLOCKED_ITEM.company.name!)).toBeInTheDocument()
    const title = within(card).getByRole('button', { name: 'Ouvrir : Voirie' })
    expect(title).toHaveTextContent('Voirie')
    expect(title).not.toHaveTextContent('EUR')
    expect(title).not.toHaveTextContent(UNLOCKED_ITEM.company.name!)
    expect(card).toHaveTextContent('4 août')
  })
  it('normalise les zones historiques sans perdre France ni dupliquer les libelles', () => {
    expect(sharedZoneLabels({ zone_labels: ['FR', 'France', ' Occitanie ', 'Occitanie'] }))
      .toEqual(['France', 'Occitanie'])
  })
  it('omet le fuseau horaire inconnu dans le formulaire du compte', async () => {
    mockApi({ 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<AppRoutes />, { route: '/app/settings/profile', session: AUTHENTICATED })
    const form = await screen.findByRole('form', { name: 'Informations principales' })
    expect(within(form).queryByLabelText('Fuseau horaire')).not.toBeInTheDocument()
    expect(form).not.toHaveTextContent('—')
  })
})
