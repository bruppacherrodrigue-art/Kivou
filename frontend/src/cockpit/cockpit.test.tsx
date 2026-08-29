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
  it.each([
    ['client', AUTHENTICATED],
    ['ancien opérateur interne', OPERATOR],
  ])('ne sert plus le cockpit dans le SaaS pour %s', (_label, session) => {
    mockApi({})
    renderApp(<AppRoutes />, { session, route: '/app/internal/cockpit' })

    expect(screen.queryByRole('link', { name: 'Cockpit commercial' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Cockpit commercial' })).not.toBeInTheDocument()
    expect(callsTo('/internal/commercial-cockpit', 'GET')).toHaveLength(0)
  })
})
