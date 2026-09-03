import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Place, UnlockedFeedItem } from '../../api/types'
import { AUTHENTICATED, UNLOCKED_ITEM, renderApp } from '../../test/harness'
import { SignalRow, placeLabel, signalObject, truncate } from './SignalRow'

const noop = () => undefined

function item(overrides: Partial<UnlockedFeedItem> = {}): UnlockedFeedItem {
  return { ...UNLOCKED_ITEM, ...overrides }
}

function place(overrides: Partial<Place> = {}): Place {
  return {
    country: null,
    locality: null,
    postal_code: null,
    subdivision_code: null,
    subdivision_label: null,
    ...overrides,
  }
}

function renderRow({
  signal = UNLOCKED_ITEM,
  selected = false,
  compact = false,
  onOpen = noop,
}: {
  signal?: UnlockedFeedItem
  selected?: boolean
  compact?: boolean
  onOpen?: (signalKey: string) => void
} = {}) {
  return renderApp(
    <table>
      <tbody>
        <SignalRow item={signal} selected={selected} compact={compact} onOpen={onOpen} />
      </tbody>
    </table>,
    { session: AUTHENTICATED },
  )
}

/** Les espaces insécables d'`Intl` ne doivent pas décider du test. */
function flat(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

describe('signalObject', () => {
  it('préfère le titre de lot', () => {
    expect(signalObject(UNLOCKED_ITEM)).toBe('Voirie')
  })

  it('retombe sur le titre du marché puis sur l’objet court', () => {
    const withoutLot = item({
      contract: { ...UNLOCKED_ITEM.contract, lot_title: null },
    })
    expect(signalObject(withoutLot)).toBe('Réfection de la voirie communale — lot 2')

    const withoutTitle = item({
      contract: { ...UNLOCKED_ITEM.contract, lot_title: null, title: null },
    })
    expect(signalObject(withoutTitle)).toBe('Réfection de la voirie communale — lot 2')
  })

  it('rend null quand aucun libellé n’est publié', () => {
    const bare = item({
      contract: { ...UNLOCKED_ITEM.contract, lot_title: null, title: null },
      factual_display: { ...UNLOCKED_ITEM.factual_display, object_short: null },
    })
    expect(signalObject(bare)).toBeNull()
  })
})

describe('truncate', () => {
  it('laisse un texte court intact', () => {
    expect(truncate('Voirie')).toBe('Voirie')
  })

  it('coupe à soixante caractères et pose une ellipse', () => {
    const long = 'a'.repeat(120)
    expect(truncate(long)).toBe(`${'a'.repeat(60)}…`)
  })
})

describe('placeLabel', () => {
  it('préfère la localité', () => {
    expect(placeLabel(place({ locality: 'Nice', subdivision_label: 'Alpes-Maritimes' }), 'fr')).toBe(
      'Nice',
    )
  })

  it('rend le libellé de subdivision, jamais son code', () => {
    const label = placeLabel(
      place({ subdivision_code: 'FR-31', subdivision_label: 'Haute-Garonne' }),
      'fr',
    )
    expect(label).toBe('Haute-Garonne')
  })

  it('rend le nom du pays quand seul le pays est publié', () => {
    expect(placeLabel(place({ country: 'FR' }), 'fr')).toBe('France')
    expect(placeLabel(place({ country: 'FR' }), 'en')).toBe('France')
    expect(placeLabel(place({ country: 'CH' }), 'en')).toBe('Switzerland')
  })

  it('ne rend jamais un code de subdivision seul', () => {
    expect(placeLabel(place({ subdivision_code: 'FR-31' }), 'fr')).toBe('—')
  })

  it('rend le tiret quand rien n’est publié', () => {
    expect(placeLabel(null, 'fr')).toBe('—')
    expect(placeLabel(place(), 'fr')).toBe('—')
  })
})

describe('SignalRow', () => {
  it('rend les six colonnes du tableau', () => {
    renderRow()

    const row = screen.getByRole('row')
    const cells = within(row).getAllByRole('cell')
    expect(cells).toHaveLength(6)
    expect(flat(cells[0].textContent ?? '')).toBe('4 août')
    expect(flat(cells[1].textContent ?? '')).toContain('Constructions Bertrand SA')
    expect(flat(cells[2].textContent ?? '')).toBe('Voirie')
    expect(flat(cells[3].textContent ?? '')).toBe('1 240 000 €')
    expect(flat(cells[4].textContent ?? '')).toBe('Villeneuve')
    expect(within(cells[5]).getByLabelText(/Correspondance/)).toBeInTheDocument()
  })

  it('rend le tiret pour un titulaire ou un montant absent', () => {
    renderRow({
      signal: item({
        company: { ...UNLOCKED_ITEM.company, name: null },
        contract: { ...UNLOCKED_ITEM.contract, amount: null },
      }),
    })

    const cells = within(screen.getByRole('row')).getAllByRole('cell')
    expect(flat(cells[1].textContent ?? '')).toBe('—')
    expect(flat(cells[3].textContent ?? '')).toBe('—')
  })

  it('tronque l’objet à soixante caractères et garde le texte complet en infobulle', () => {
    const long = 'Collège de Levens, lot 2 : gros œuvre, charpente bois, façades et génie civil'
    renderRow({
      signal: item({ contract: { ...UNLOCKED_ITEM.contract, lot_title: long } }),
    })

    const cell = within(screen.getByRole('row')).getAllByRole('cell')[2]
    expect(flat(cell.textContent ?? '')).toBe(flat(`${long.slice(0, 60)}…`))
    expect(cell.querySelector('[title]')).toHaveAttribute('title', long)
  })

  it('rend le lieu en clair, jamais un code', () => {
    const { container } = renderRow({
      signal: item({
        contract: {
          ...UNLOCKED_ITEM.contract,
          location: place({ subdivision_code: 'FR-31', subdivision_label: 'Haute-Garonne' }),
        },
      }),
    })

    const cells = within(screen.getByRole('row')).getAllByRole('cell')
    expect(flat(cells[4].textContent ?? '')).toBe('Haute-Garonne')
    expect(container.textContent).not.toContain('FR-31')
  })

  it('affiche la pastille groupement seulement quand l’API la publie', () => {
    renderRow()
    expect(screen.queryByText('groupement')).not.toBeInTheDocument()

    renderRow({ signal: item({ company: { ...UNLOCKED_ITEM.company, consortium: true } }) })
    expect(screen.getAllByText('groupement').length).toBeGreaterThan(0)
  })

  it('marque la ligne sélectionnée', () => {
    renderRow({ selected: true })
    expect(screen.getByRole('row')).toHaveAttribute('aria-current', 'true')

    renderRow()
    expect(screen.getAllByRole('row')[1]).not.toHaveAttribute('aria-current')
  })

  it('ouvre le signal une seule fois au clic sur le titulaire', async () => {
    const onOpen = vi.fn()
    renderRow({ onOpen })

    await userEvent.click(screen.getByRole('button', { name: /Constructions Bertrand SA/ }))

    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(onOpen).toHaveBeenCalledWith('sig_unlocked_1')
  })

  it('ouvre le signal au clic sur la ligne', async () => {
    const onOpen = vi.fn()
    renderRow({ onOpen })

    await userEvent.click(within(screen.getByRole('row')).getAllByRole('cell')[2])

    expect(onOpen).toHaveBeenCalledWith('sig_unlocked_1')
  })

  it('retire la colonne Lieu en mode compact', () => {
    renderRow({ compact: true })

    const cells = within(screen.getByRole('row')).getAllByRole('cell')
    expect(cells).toHaveLength(5)
    expect(flat(screen.getByRole('row').textContent ?? '')).not.toContain('Villeneuve')
  })
})
