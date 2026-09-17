import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { useLocation } from 'react-router-dom'
import { AppRoutes } from '../App'
import { ME, callsTo, mockApi, renderApp, UNAUTHENTICATED } from '../test/harness'

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

test('free signup collects a trade and zone then opens the materialized bait', async () => {
  mockApi({
    'GET /auth/discovery-preview/options': { body: {
      zones: [{ code: 'FR-41', label: 'Loir-et-Cher' }],
      sectors: [{ key: 'facade_cladding', label: 'Bardage métallique' }],
    } },
    'POST /auth/discovery-preview': { body: {
      signal_id: 'signal-bait',
      landing_cohort: { expected: 3, materialized: 3 },
      me: { ...ME, temporary_access: true, provisional_profile: true },
    } },
  })
  renderApp(<><AppRoutes /><Location /></>, {
    route: '/signup?plan=discovery',
    session: UNAUTHENTICATED,
  })

  expect(await screen.findByRole('heading', { name: 'Quels marchés vous intéressent ?' })).toBeInTheDocument()
  expect(screen.queryByLabelText(/e-mail/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/mot de passe/i)).not.toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Zone'), 'FR-41')
  await userEvent.selectOptions(screen.getByLabelText('Secteur'), 'facade_cladding')
  await userEvent.click(screen.getByRole('button', { name: 'Recevoir mes signaux' }))

  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/app/signals/signal-bait'))
  expect(callsTo('/auth/discovery-preview', 'POST')[0].body).toEqual({
    zone: 'FR-41', sector: 'facade_cladding',
  })
})
