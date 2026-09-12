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

function item(overrides: Partial<UnlockedFeedItem> = {}): UnlockedFeedItem {
  return { ...UNLOCKED_ITEM, ...overrides }
}

function need(overrides: Partial<PlausibleNeed> = {}): PlausibleNeed {
  return { ...UNLOCKED_ITEM.analysis.plausible_needs.items[0], timing_status: 'determined', quantity_status: null, ...overrides }
}

function withNeeds(needs: PlausibleNeed[]): UnlockedFeedItem {
  return item({
    analysis: {
      ...UNLOCKED_ITEM.analysis,
      plausible_needs: { ...UNLOCKED_ITEM.analysis.plausible_needs, items: needs },
    },
  })
}

function renderDrawer({
  signal = UNLOCKED_ITEM as UnlockedFeedItem | null,
  loading = false,
  error = null as unknown,
  busy = false,
  compact = false,
  redesigned = false,
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
  redesigned?: boolean
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
      redesigned={redesigned}
      onClose={onClose}
      onRetry={onRetry}
      onContacted={onContacted}
      onSave={onSave}
      onIgnore={onIgnore}
    />,
    { session: AUTHENTICATED },
  )
}

describe('SignalDrawer', () => {
  it('rend la fiche de décision dans l’ordre validé et sans grille répétée', () => {
    renderDrawer({
      redesigned: true,
      signal: item({
        commercial_calendar: {
          start_month: '2026-10',
          duration_months: 6,
          source: 'public_notice',
        },
        local_circuit: [{
          siren: '331364729',
          name: 'Bétons du Midi',
          trade: 'Béton prêt à l’emploi',
          city: 'GRENOBLE',
          employees: 24,
          href: '/app/companies/directory/331364729',
          source: 'registre',
        }],
      }),
    })

    const panel = screen.getByRole('complementary')
    const headings = within(panel).getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    expect(headings).toEqual([
      'Titulaire',
      'Pourquoi ça vous concerne',
      'Calendrier',
      'Le circuit local',
    ])
    expect(panel).toHaveTextContent('Grenoble')
    expect(panel).not.toHaveTextContent('GRENOBLE')
  })

  it('remplace un titre répété par le repli client et corrige « à Isère »', () => {
    const repeated = item({
      analysis: {
        ...UNLOCKED_ITEM.analysis,
        fit: {
          ...UNLOCKED_ITEM.analysis.fit,
          for_you_sentence: 'Voirie : un marché pertinent pour votre activité.',
        },
      },
    })
    const { unmount } = renderDrawer({ redesigned: true, signal: repeated })
    expect(screen.getByText('Ce marché correspond à votre profil cible dans cette zone et ce secteur.')).toBeVisible()
    unmount()

    renderDrawer({
      redesigned: true,
      signal: item({
        analysis: {
          ...UNLOCKED_ITEM.analysis,
          fit: {
            ...UNLOCKED_ITEM.analysis.fit,
            for_you_sentence: 'Votre savoir-faire est recherché à Isère pour ce chantier.',
          },
        },
        contract: {
          ...UNLOCKED_ITEM.contract,
          location: {
            country: 'FR',
            subdivision_code: 'FR-38',
            subdivision_label: 'ISÈRE',
            locality: null,
            postal_code: null,
          },
        },
      }),
    })
    expect(screen.getByText('Votre savoir-faire est recherché en Isère pour ce chantier.')).toBeVisible()
  })

  it('omet calendrier et circuit local quand leurs données manquent', () => {
    renderDrawer({ redesigned: true })

    expect(screen.queryByRole('heading', { name: 'Calendrier' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Le circuit local' })).not.toBeInTheDocument()
  })

  it('masque le bloc des besoins quand timing et quantité sont indéterminés', () => {
    renderDrawer({ signal: withNeeds([need({ timing: null, timing_label: null, timing_status: null, quantity_status: null })]) })
    expect(screen.queryByText('Ce que le titulaire va devoir faire')).not.toBeInTheDocument()
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

  it('ne présente pas les inférences métier comme des exigences du dossier', () => {
    renderDrawer({
      signal: withNeeds([
        need({ label: 'Transport', targeted_by_your_profile: false, timing_label: 'Moyen terme' }),
        need({ label: 'Matériaux', targeted_by_your_profile: true, timing_label: 'Court terme' }),
        need({ label: 'Protections', targeted_by_your_profile: false, timing_label: null }),
        need({ label: 'Déchets', targeted_by_your_profile: false, timing_label: 'Long terme' }),
      ]),
    })

    expect(screen.queryByText('Ce que le titulaire va devoir faire')).not.toBeInTheDocument()
  })

  it('retire le bloc des besoins quand aucun n’est publié', () => {
    renderDrawer({ signal: withNeeds([]) })

    expect(screen.queryByText('Ce que le titulaire va devoir faire')).not.toBeInTheDocument()
  })

})
