import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FounderApp } from './FounderApp'

const SESSION = {
  version: 'founder-session-v1',
  service: 'kivou-founder-control',
  environment: 'PRODUCTION',
  operator_email: 'rodrigue.bruppacher@gmail.com',
  read_only: true,
  generated_at: '2026-08-29T18:30:00Z',
} as const

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FounderApp', () => {
  it('renders only confirmed session facts and no demonstration metrics', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => SESSION,
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<FounderApp />)

    expect(screen.getByText('Vérification de l’accès sécurisé…')).toBeInTheDocument()
    expect(await screen.findByText('Session Founder validée')).toBeInTheDocument()
    expect(screen.getByText('rodrigue.bruppacher@gmail.com')).toBeInTheDocument()
    expect(screen.getAllByText('Lecture seule').length).toBeGreaterThan(0)
    expect(screen.getByText(/Aucun chiffre de démonstration/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/founder/session',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('fails visibly when the founder boundary refuses the request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
      }),
    )

    render(<FounderApp />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Accès refusé')
  })
})
