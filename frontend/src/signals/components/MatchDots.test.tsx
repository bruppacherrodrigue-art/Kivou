import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import type { Fit } from '../../api/types'
import { AUTHENTICATED, renderApp } from '../../test/harness'
import { MatchDots, matchLevel } from './MatchDots'

function fit(overrides: Partial<Fit> = {}): Fit {
  return {
    label: 'matched_needs',
    target_icp_id: 'icp_1',
    target_icp_label: 'Matériaux — Occitanie',
    reasons: [],
    ...overrides,
  }
}

describe('matchLevel', () => {
  it.each([
    ['strong', 4],
    ['promising', 3],
    ['weak', 2],
    ['unknown', 1],
  ] as const)('lit la bande %s comme %i points', (band, filled) => {
    expect(matchLevel(fit({ band }))).toEqual({ filled, derived: false })
  })

  it.each([
    ['matched_needs', 3],
    ['territory_only', 2],
    ['targeted_profile', 1],
  ] as const)('dérive %s en %i points quand la bande manque', (label, filled) => {
    expect(matchLevel(fit({ label }))).toEqual({ filled, derived: true })
  })

  it('dérive un point pour un libellé inconnu', () => {
    expect(matchLevel(fit({ label: 'Très bon pour votre profil' }))).toEqual({
      filled: 1,
      derived: true,
    })
  })
})

describe('MatchDots', () => {
  it('rend quatre points, pleins selon la bande', () => {
    const { container } = renderApp(<MatchDots fit={fit({ band: 'promising' })} />, {
      session: AUTHENTICATED,
    })

    expect(container.querySelectorAll('[data-dot]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-dot="filled"]')).toHaveLength(3)
  })

  it('rend le nombre de points dérivé du libellé quand la bande manque', () => {
    const { container } = renderApp(<MatchDots fit={fit({ label: 'territory_only' })} />, {
      session: AUTHENTICATED,
    })

    expect(container.querySelectorAll('[data-dot="filled"]')).toHaveLength(2)
    expect(container.querySelector('[data-derived]')).toHaveAttribute('data-derived', 'true')
  })

  it('ne marque pas comme dérivée une correspondance venue de la bande', () => {
    const { container } = renderApp(<MatchDots fit={fit({ band: 'strong' })} />, {
      session: AUTHENTICATED,
    })

    expect(container.querySelector('[data-derived]')).toHaveAttribute('data-derived', 'false')
  })

  it('annonce la correspondance aux technologies d’assistance', () => {
    renderApp(<MatchDots fit={fit({ band: 'strong' })} />, { session: AUTHENTICATED })

    expect(screen.getByLabelText('Correspondance 4/4')).toBeInTheDocument()
  })
})
