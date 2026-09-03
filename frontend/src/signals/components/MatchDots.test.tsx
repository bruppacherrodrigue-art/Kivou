import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import type { PlausibleNeed, UnlockedFeedItem } from '../../api/types'
import { AUTHENTICATED, UNLOCKED_ITEM, renderApp } from '../../test/harness'
import { MatchDots, matchLevel } from './MatchDots'

const TARGETED = UNLOCKED_ITEM.analysis.plausible_needs.items[0]

function need(overrides: Partial<PlausibleNeed> = {}): PlausibleNeed {
  return { ...TARGETED, ...overrides }
}

/** Un item dont on choisit la bande, les besoins visés et le lieu. */
function item({
  band,
  needs = [need({ targeted_by_your_profile: false })],
  located = true,
}: {
  band?: NonNullable<UnlockedFeedItem['analysis']['fit']['band']>
  needs?: PlausibleNeed[]
  located?: boolean
} = {}): UnlockedFeedItem {
  return {
    ...UNLOCKED_ITEM,
    contract: {
      ...UNLOCKED_ITEM.contract,
      location: located ? UNLOCKED_ITEM.contract.location : null,
    },
    analysis: {
      ...UNLOCKED_ITEM.analysis,
      plausible_needs: { ...UNLOCKED_ITEM.analysis.plausible_needs, items: needs },
      fit: { ...UNLOCKED_ITEM.analysis.fit, band },
    },
  }
}

describe('matchLevel', () => {
  it.each([
    ['strong', 4],
    ['promising', 3],
    ['weak', 2],
    ['unknown', 1],
  ] as const)('lit la bande %s comme %i points', (band, filled) => {
    expect(matchLevel(item({ band }))).toEqual({ filled, derived: false })
  })

  it('dérive trois points quand un besoin est visé par le profil', () => {
    expect(matchLevel(item({ needs: [need({ targeted_by_your_profile: true })] }))).toEqual({
      filled: 3,
      derived: true,
    })
  })

  it('dérive deux points quand seul le lieu est connu', () => {
    expect(matchLevel(item({ located: true }))).toEqual({ filled: 2, derived: true })
  })

  it('dérive un point sans besoin visé ni lieu', () => {
    expect(matchLevel(item({ located: false }))).toEqual({ filled: 1, derived: true })
  })

  it('ne dérive jamais du libellé de fit, que le backend traduit', () => {
    const translated = item({ located: false })
    translated.analysis.fit.label = 'matched_needs'
    expect(matchLevel(translated).filled).toBe(1)
  })

  it('préfère la bande aux faits dérivés', () => {
    const strongButBare = item({ band: 'strong', located: false })
    expect(matchLevel(strongButBare)).toEqual({ filled: 4, derived: false })
  })
})

describe('MatchDots', () => {
  it('rend quatre points, pleins selon la bande', () => {
    const { container } = renderApp(<MatchDots item={item({ band: 'promising' })} />, {
      session: AUTHENTICATED,
    })

    expect(container.querySelectorAll('[data-dot]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-dot="filled"]')).toHaveLength(3)
  })

  it('rend le nombre de points dérivé des faits quand la bande manque', () => {
    const { container } = renderApp(<MatchDots item={item({ located: true })} />, {
      session: AUTHENTICATED,
    })

    expect(container.querySelectorAll('[data-dot="filled"]')).toHaveLength(2)
    expect(container.querySelector('[data-derived]')).toHaveAttribute('data-derived', 'true')
  })

  it('ne marque pas comme dérivée une correspondance venue de la bande', () => {
    const { container } = renderApp(<MatchDots item={item({ band: 'strong' })} />, {
      session: AUTHENTICATED,
    })

    expect(container.querySelector('[data-derived]')).toHaveAttribute('data-derived', 'false')
  })

  it('annonce la correspondance aux technologies d’assistance', () => {
    renderApp(<MatchDots item={item({ band: 'strong' })} />, { session: AUTHENTICATED })

    expect(screen.getByLabelText('Correspondance 4/4')).toBeInTheDocument()
  })
})
