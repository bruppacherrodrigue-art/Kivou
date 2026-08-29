import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { AppRoutes } from '../App'
import { AUTHENTICATED, ME, callsTo, mockApi, renderApp } from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const OPERATOR = {
  status: 'authenticated' as const,
  me: { ...ME, capabilities: { commercial_cockpit: true } },
}

describe('séparation du Founder Console', () => {
  it('ne sert plus le cockpit à un client du SaaS', () => {
    assertCockpitAbsent(AUTHENTICATED)
  })

  it('ne sert plus le cockpit à un ancien opérateur interne', () => {
    assertCockpitAbsent(OPERATOR)
  })
})

function assertCockpitAbsent(session: typeof AUTHENTICATED): void {
  mockApi({})
  renderApp(<AppRoutes />, { session, route: '/app/internal/cockpit' })

  expect(screen.queryByRole('link', { name: 'Cockpit commercial' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Cockpit commercial' })).not.toBeInTheDocument()
  expect(callsTo('/internal/commercial-cockpit', 'GET')).toHaveLength(0)
}
