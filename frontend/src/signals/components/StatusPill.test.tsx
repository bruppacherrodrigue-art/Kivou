import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import type { UnifiedStatus } from '../../api/types'
import { AUTHENTICATED, renderApp } from '../../test/harness'
import { StatusPill } from './StatusPill'

const FRENCH_LABELS: Record<UnifiedStatus, string> = {
  new: 'Nouveau',
  saved: 'Sauvé',
  contacted: 'Contacté',
  ignored: 'Ignoré',
}

describe('StatusPill', () => {
  it.each(Object.entries(FRENCH_LABELS))('rend le libellé français de %s', (status, label) => {
    renderApp(<StatusPill status={status as UnifiedStatus} />, { session: AUTHENTICATED })

    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('porte le statut machine en attribut de données', () => {
    const { container } = renderApp(<StatusPill status="contacted" />, { session: AUTHENTICATED })

    const pill = container.querySelector('[data-status]')
    expect(pill).not.toBeNull()
    expect(pill).toHaveAttribute('data-status', 'contacted')
  })

  it('rend le libellé anglais dans la locale anglaise', () => {
    renderApp(<StatusPill status="saved" />, { session: AUTHENTICATED, locale: 'en' })

    expect(screen.getByText('Saved')).toBeInTheDocument()
  })
})
