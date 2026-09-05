import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { AUTHENTICATED, DISCOVERY_STATUS, callsTo, mockApi, renderApp } from '../test/harness'

describe('Settings account data', () => {
  it('requires explicit confirmation and schedules account deletion', async () => {
    mockApi({
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'POST /account/deletion': { body: { scheduled_for: '2026-09-06T12:00:00+00:00' } },
    })
    renderApp(<AppRoutes />, { route: '/app/settings', session: AUTHENTICATED })
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Supprimer mon compte' })
    expect(button).toBeDisabled()

    await user.type(screen.getByLabelText('Saisissez SUPPRIMER pour confirmer'), 'SUPPRIMER')
    await user.click(button)

    await waitFor(() => expect(callsTo('/account/deletion')).toHaveLength(1))
    expect(await screen.findByText(/Suppression programmée/)).toBeInTheDocument()
  })
})
