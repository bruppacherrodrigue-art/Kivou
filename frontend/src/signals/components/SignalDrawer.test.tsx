import { describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { PlausibleNeed, UnlockedFeedItem } from '../../api/types'
import { AUTHENTICATED, UNLOCKED_ITEM, renderApp } from '../../test/harness'
import { SignalDrawer } from './SignalDrawer'

const noop = () => undefined

/* Le copy interdit sur cet écran. Aucun de ces mots ne doit atteindre le DOM. */
const FORBIDDEN = [
  'étayé',
  'absent',
  'résolution incomplète',
  'faits publiés',
  'contact non confirmé',
]

/* Le vocabulaire proscrit sur toute la surface client. « Attribué le » reste :
 * c'est la forme verbale, pas le substantif. */
const FORBIDDEN_VOCABULARY = ['signal', 'profil cible', 'attribution', 'signal ouvert', 'analyse']

function item(overrides: Partial<UnlockedFeedItem> = {}): UnlockedFeedItem {
  return { ...UNLOCKED_ITEM, ...overrides }
}

function need(overrides: Partial<PlausibleNeed> = {}): PlausibleNeed {
  return { ...UNLOCKED_ITEM.analysis.plausible_needs.items[0], ...overrides }
}

function withNeeds(needs: PlausibleNeed[]): UnlockedFeedItem {
  return item({
    analysis: {
      ...UNLOCKED_ITEM.analysis,
      plausible_needs: { ...UNLOCKED_ITEM.analysis.plausible_needs, items: needs },
    },
  })
}

function flat(text: string | null): string {
  return (text ?? '').replace(/\s+/g, ' ').trim()
}

function renderDrawer({
  signal = UNLOCKED_ITEM as UnlockedFeedItem | null,
  loading = false,
  error = null as unknown,
  busy = false,
  compact = false,
  onClose = noop,
  onRetry = noop,
  onContacted = noop,
  onSave = noop,
  onIgnore = noop,
}: {
  signal?: UnlockedFeedItem | null
  loading?: boolean
  error?: unknown
  busy?: boolean
  compact?: boolean
  onClose?: () => void
  onRetry?: () => void
  onContacted?: () => void
  onSave?: () => void
  onIgnore?: () => void
} = {}) {
  return renderApp(
    <SignalDrawer
      item={signal}
      loading={loading}
      error={error}
      busy={busy}
      compact={compact}
      onClose={onClose}
      onRetry={onRetry}
      onContacted={onContacted}
      onSave={onSave}
      onIgnore={onIgnore}
    />,
    { session: AUTHENTICATED },
  )
}

/** La valeur associée à un intitulé de la grille de faits. */
function fact(label: string): string {
  const term = screen.getByText(label)
  const value = term.nextElementSibling
  if (!value) throw new Error(`Aucune valeur pour « ${label} »`)
  return flat(value.textContent)
}

function listOf(heading: string): string[] {
  const block = screen.getByText(heading).closest('section')
  if (!block) throw new Error(`Aucun bloc « ${heading} »`)
  return within(block).getAllByRole('listitem').map((entry) => flat(entry.textContent))
}

describe('SignalDrawer', () => {
  it('rend le statut, la correspondance, le titre et l’objet', () => {
    renderDrawer()

    expect(screen.getByText('Nouveau')).toBeInTheDocument()
    expect(screen.getByLabelText(/Correspondance/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Voirie')
    expect(screen.getByText('Réfection de la voirie communale — lot 2')).toBeInTheDocument()
  })

  it('rend la grille des faits', () => {
    renderDrawer()

    expect(fact('Titulaire')).toBe('Constructions Bertrand SA')
    expect(fact('Acheteur')).toBe('Commune de Villeneuve')
    expect(fact('Montant')).toBe('1 240 000 €')
    expect(fact('Lieu')).toBe('Villeneuve')
    expect(fact('Attribué le')).toContain('4 août 2026')
    expect(fact('CPV')).toBe('45233120')
  })

  it('rend le tiret pour un acheteur absent', () => {
    renderDrawer({ signal: item({ contract: { ...UNLOCKED_ITEM.contract, buyer: null } }) })

    expect(fact('Acheteur')).toBe('—')
  })

  it('lie le titulaire à sa fiche quand la clé entreprise est publiée', () => {
    renderDrawer()

    expect(screen.getByRole('link', { name: /Constructions Bertrand SA/ })).toHaveAttribute(
      'href',
      '/app/companies/cmp_0123456789abcdefghijklmnop',
    )
  })

  it('rend le titulaire en texte quand la clé entreprise manque', () => {
    renderDrawer({ signal: item({ company_key: null }) })

    expect(screen.queryByRole('link', { name: /Constructions Bertrand SA/ })).not.toBeInTheDocument()
    expect(fact('Titulaire')).toBe('Constructions Bertrand SA')
  })

  it('bascule sur la notification puis sur la publication selon la date disponible', () => {
    renderDrawer({
      signal: item({
        contract: {
          ...UNLOCKED_ITEM.contract,
          dates: { ...UNLOCKED_ITEM.contract.dates, award: null },
        },
      }),
    })
    expect(screen.queryByText('Attribué le')).not.toBeInTheDocument()
    expect(fact('Notifié le')).toContain('6 août 2026')

    renderDrawer({
      signal: item({
        contract: {
          ...UNLOCKED_ITEM.contract,
          dates: { award: null, contract_notification: null, publication: '2026-08-10' },
        },
      }),
    })
    expect(fact('Publié le')).toContain('10 août 2026')
  })

  it('rend le tiret quand aucune date n’est disponible', () => {
    renderDrawer({
      signal: item({
        contract: {
          ...UNLOCKED_ITEM.contract,
          dates: { award: null, contract_notification: null, publication: null },
        },
      }),
    })

    expect(fact('Attribué le')).toBe('—')
  })

  it('rend au plus trois raisons sous « Pourquoi ça vous concerne »', () => {
    renderDrawer({
      signal: item({
        analysis: {
          ...UNLOCKED_ITEM.analysis,
          fit: {
            ...UNLOCKED_ITEM.analysis.fit,
            reasons: ['Raison 1', 'Raison 2', 'Raison 3', 'Raison 4', 'Raison 5'],
          },
        },
      }),
    })

    const block = screen.getByText('Pourquoi ça vous concerne').closest('section')
    expect(block).not.toBeNull()
    expect(within(block as HTMLElement).getAllByRole('listitem')).toHaveLength(3)
    expect(screen.queryByText('Raison 4')).not.toBeInTheDocument()
  })

  it('rend la même phrase Pour vous à la place du premier libellé de règle', () => {
    renderDrawer()

    const block = screen.getByText('Pourquoi ça vous concerne').closest('section')
    expect(block).not.toBeNull()
    expect(within(block as HTMLElement).getAllByRole('listitem')[0]).toHaveTextContent(
      'Votre offre répond aux besoins de matériaux de ce titulaire.',
    )
    expect(screen.queryByText('Besoin visé : Matériaux ou composants')).not.toBeInTheDocument()
  })

  it('retire le bloc « Pourquoi ça vous concerne » quand aucune raison n’est publiée', () => {
    renderDrawer({
      signal: item({
        analysis: {
          ...UNLOCKED_ITEM.analysis,
          fit: { ...UNLOCKED_ITEM.analysis.fit, reasons: [], for_you_sentence: null },
        },
      }),
    })

    expect(screen.queryByText('Pourquoi ça vous concerne')).not.toBeInTheDocument()
  })

  it('appelle les trois actions', async () => {
    const onContacted = vi.fn()
    const onSave = vi.fn()
    const onIgnore = vi.fn()
    renderDrawer({ onContacted, onSave, onIgnore })

    await userEvent.click(screen.getByRole('button', { name: 'Marquer contacté' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sauver' }))
    await userEvent.click(screen.getByRole('button', { name: 'Ignorer' }))

    expect(onContacted).toHaveBeenCalledTimes(1)
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onIgnore).toHaveBeenCalledTimes(1)
  })

  it('désactive toutes les actions pendant une écriture', () => {
    renderDrawer({ busy: true })

    expect(screen.getByRole('button', { name: 'Marquer contacté' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Sauver' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Ignorer' })).toBeDisabled()
  })

  it('rend le statut courant comme un état, pas comme une action', () => {
    renderDrawer({ signal: item({ status: 'contacted' }) })
    expect(screen.queryByRole('button', { name: 'Marquer contacté' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Contacté ✓' })).toBeDisabled()

    renderDrawer({ signal: item({ status: 'saved' }) })
    expect(screen.getByRole('button', { name: 'Sauvé ✓' })).toBeDisabled()

    renderDrawer({ signal: item({ status: 'ignored' }) })
    expect(screen.getByRole('button', { name: 'Ignoré ✓' })).toBeDisabled()
  })

  it('rend la source en lien quand une URL est publiée', () => {
    renderDrawer()

    const link = screen.getByRole('link', { name: /Source : BOAMP 26-104412/ })
    expect(link).toHaveAttribute('href', 'https://www.boamp.fr/avis/26-104412')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('rend la source en texte quand aucune URL n’est publiée', () => {
    renderDrawer({ signal: item({ source: { ...UNLOCKED_ITEM.source, url: null } }) })

    expect(screen.queryByRole('link', { name: /Source :/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Source : BOAMP 26-104412/)).toBeInTheDocument()
  })

  it('ferme le tiroir', async () => {
    const onClose = vi.fn()
    renderDrawer({ onClose })

    await userEvent.click(screen.getByRole('button', { name: 'Fermer' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('masque son propre bouton « Fermer » en mode compact : la feuille porte déjà le sien', () => {
    renderDrawer({ compact: true })

    expect(screen.queryByRole('button', { name: 'Fermer' })).not.toBeInTheDocument()
  })

  it('rend un squelette pendant le chargement', () => {
    renderDrawer({ signal: null, loading: true })

    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument()
  })

  it('rend une alerte et une invitation à réessayer en cas d’erreur', () => {
    renderDrawer({ signal: null, error: new Error('boom') })

    const alert = screen.getByRole('alert')
    expect(alert).toBeInTheDocument()
    expect(alert).toHaveTextContent(/Réessayer/)
  })

  it('« Réessayer » appelle onRetry', async () => {
    const onRetry = vi.fn()
    renderDrawer({ signal: null, error: new Error('boom'), onRetry })

    await userEvent.click(screen.getByRole('button', { name: 'Réessayer' }))

    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('invite à sélectionner un signal quand rien n’est ouvert', () => {
    renderDrawer({ signal: null })

    expect(screen.getByText('Sélectionnez un signal')).toBeInTheDocument()
  })

  it('n’écrit aucun mot du copy interdit', () => {
    const { container } = renderDrawer()

    for (const word of FORBIDDEN) {
      expect(container.textContent?.toLowerCase()).not.toContain(word.toLowerCase())
    }
  })
  it('associe le tiroir chargé à son titre', () => {
    const { container } = renderDrawer()

    const labelledBy = container.querySelector('aside')?.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2 })).toHaveAttribute('id', labelledBy)
  })

  it.each([
    [{ signal: null, loading: true }, 'Chargement du signal'],
    [{ signal: null, error: new Error('boom') }, 'Le signal n’a pas pu être chargé.'],
    [{ signal: null }, 'Sélectionnez un signal'],
  ])('nomme le tiroir quand aucun titre ne peut le faire (%#)', (props, label) => {
    const { container } = renderDrawer(props)

    expect(container.querySelector('aside')).toHaveAttribute('aria-label', label)
  })

  it('rend les besoins impliqués, ceux que le profil vise en premier', () => {
    renderDrawer({
      signal: withNeeds([
        need({ label: 'Transport', targeted_by_your_profile: false, timing_label: 'Moyen terme' }),
        need({ label: 'Matériaux', targeted_by_your_profile: true, timing_label: 'Court terme' }),
        need({ label: 'Protections', targeted_by_your_profile: false, timing_label: null }),
        need({ label: 'Déchets', targeted_by_your_profile: false, timing_label: 'Long terme' }),
      ]),
    })

    expect(listOf('Ce que le titulaire va devoir faire')).toEqual([
      'Matériaux · Court terme',
      'Transport · Moyen terme',
      'Protections',
    ])
  })

  it('écarte un besoin sans libellé', () => {
    renderDrawer({
      signal: withNeeds([
        need({ label: null, targeted_by_your_profile: true }),
        need({ label: 'Matériaux', targeted_by_your_profile: false, timing_label: null }),
      ]),
    })

    expect(listOf('Ce que le titulaire va devoir faire')).toEqual(['Matériaux'])
  })

  it('retire le bloc des besoins quand aucun n’est publié', () => {
    renderDrawer({ signal: withNeeds([]) })

    expect(screen.queryByText('Ce que le titulaire va devoir faire')).not.toBeInTheDocument()
  })

  it('n’emploie aucun mot du vocabulaire proscrit', () => {
    const { container } = renderDrawer()

    for (const word of FORBIDDEN_VOCABULARY) {
      expect(container.textContent ?? '').not.toMatch(new RegExp(`\\b${word}\\b`, 'i'))
    }
  })
})
