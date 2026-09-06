import { screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { SignalCardRow } from '../signals/components/SignalRow'
import { sharedZoneLabels } from '../presentation/dashboard/zoneLabels'
import { AUTHENTICATED, UNLOCKED_ITEM, DISCOVERY_STATUS, mockApi, renderApp } from '../test/harness'

describe('recette finition: corrections de revue', () => {
  it('separe titulaire, objet et metadonnees en trois rangees', () => {
    const { container } = renderApp(<SignalCardRow item={UNLOCKED_ITEM} selected={false} onOpen={vi.fn()} />, { session: AUTHENTICATED })
    const card = container.querySelector('article')!
    expect(card.children).toHaveLength(3)
    expect(card.children[0]).toHaveTextContent(UNLOCKED_ITEM.company.name!)
    expect(card.children[1]).toHaveTextContent('Voirie')
    expect(card.children[1]).not.toHaveTextContent('EUR')
    expect(within(card.children[2] as HTMLElement).getByRole('img')).toHaveAccessibleName()
    expect(card.children[2]).toHaveTextContent('4 août')
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
