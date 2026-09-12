import { afterEach, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { AppRoutes } from '../App'
import type { TargetIcp } from '../api/types'
import { ICP, ME, mockApi, renderApp } from '../test/harness'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('préremplit un profil kat1 avec le département et la famille du signal', async () => {
  const profile: TargetIcp = {
    ...ICP,
    label: 'Bois et charpente',
    provisional: true,
    customer_input: {
      ...ICP.customer_input,
      offer_summary: 'Bois et charpente',
      territory_subdivisions: ['FR-38'],
      sector_cpv_prefixes: ['452611'],
    },
  }
  mockApi({
    'GET /target-icps': { body: [profile] },
    'GET /target-icps/options': {
      body: {
        zones: [{ code: 'FR-38', label: 'Isère', country: 'FR' }],
        sectors: [{ prefix: '45', label: 'Travaux de construction' }],
      },
    },
  })

  renderApp(<AppRoutes />, {
    route: '/app/confirm-profile',
    session: {
      status: 'authenticated',
      me: {
        ...ME,
        onboarding_status: 'icp_incomplete',
        provisional_profile: true,
      },
    },
  })

  await waitFor(() => expect(screen.getByLabelText('Zone')).toHaveValue(['FR-38']))
  await waitFor(() => expect(screen.getByLabelText('Secteur')).toHaveValue('452611'))
  expect(
    (screen.getByRole('option', { name: 'Bois et charpente' }) as HTMLOptionElement).selected,
  ).toBe(true)
  expect(screen.getByLabelText('Ce que vous vendez')).toHaveValue('Bois et charpente')
})
