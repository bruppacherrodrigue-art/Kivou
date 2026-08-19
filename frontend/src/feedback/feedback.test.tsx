import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  UNLOCKED_DETAIL,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'
import { MAXIMUM_NOTE_LENGTH } from '../api/types'

/* SPEC-015 §52 — les six vérifications du retour client. */

afterEach(() => vi.unstubAllGlobals())

const PATH = '/signals/sig_unlocked_1/feedback'

function routes(overrides: Record<string, unknown> = {}) {
  return {
    'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    [`PUT ${PATH}`]: {
      body: {
        signal_id: 'sig_unlocked_1',
        interaction: {
          relevance: 'relevant',
          reason: null,
          note: null,
          contacted: false,
          contacted_at: null,
          updated_at: '2026-08-18T10:00:00+00:00',
        },
      },
    },
    ...overrides,
  }
}

async function openDetail() {
  renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_unlocked_1' })
  await screen.findByRole('heading', { name: 'Votre avis sur ce signal' })
}

describe('retour client', () => {
  it('enregistre « pertinent » sans exiger de raison', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    await user.click(screen.getByLabelText('Pertinent'))
    await user.click(screen.getByRole('button', { name: 'Enregistrer mon avis' }))

    await waitFor(() => expect(callsTo(PATH, 'PUT')).toHaveLength(1))
    expect(callsTo(PATH, 'PUT')[0].body).toEqual({
      relevance: 'relevant',
      reason: null,
      note: null,
    })
  })

  it('exige une raison pour « pas pertinent », sans appeler le serveur', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    await user.click(screen.getByLabelText('Pas pertinent'))
    await user.click(screen.getByRole('button', { name: 'Enregistrer mon avis' }))

    expect(
      await screen.findByText(/Indiquez une raison pour enregistrer un avis/),
    ).toBeInTheDocument()
    expect(callsTo(PATH, 'PUT')).toHaveLength(0)
  })

  it('propose exactement les six raisons approuvées', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    await user.click(screen.getByLabelText('Pas pertinent'))

    const expected = [
      'Déjà couvert',
      'Réalisé en interne',
      'Mauvais type de client',
      'Trop tard',
      'Besoin erroné',
      'Autre',
    ]
    for (const label of expected) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }

    const group = screen.getByRole('group', { name: /Pourquoi ce signal n’est-il pas pertinent/ })
    expect(group.querySelectorAll('input[type="radio"]')).toHaveLength(expected.length)
  })

  it('borne la précision libre à la longueur acceptée par le backend', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    await user.click(screen.getByLabelText('Pas pertinent'))
    await user.click(screen.getByLabelText('Autre'))

    const note = screen.getByLabelText(/Précision/)
    expect(note).toHaveAttribute('maxlength', String(MAXIMUM_NOTE_LENGTH))
  })

  it('garde « contacté » séparé du jugement de pertinence', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'POST /signals/sig_unlocked_1/contacted': {
          body: {
            signal_id: 'sig_unlocked_1',
            recorded: true,
            interaction: {
              relevance: null,
              reason: null,
              note: null,
              contacted: true,
              contacted_at: '2026-08-18T11:00:00+00:00',
              updated_at: '2026-08-18T11:00:00+00:00',
            },
          },
        },
      }),
    )
    await openDetail()

    // Deux commandes distinctes, deux points d'entrée distincts.
    await user.click(screen.getByRole('button', { name: 'J’ai contacté cette entreprise' }))

    await waitFor(() =>
      expect(callsTo('/signals/sig_unlocked_1/contacted')).toHaveLength(1),
    )
    // Marquer « contacté » n'a écrit AUCUN avis de pertinence.
    expect(callsTo(PATH, 'PUT')).toHaveLength(0)
    expect(screen.getByLabelText('Pertinent')).not.toBeChecked()
    expect(screen.getByLabelText('Pas pertinent')).not.toBeChecked()
  })

  it('dit ce que « contacté » signifie, et rien de plus', async () => {
    mockApi(routes())
    await openDetail()

    // La copie DÉMENT explicitement les trois interprétations abusives : c'est
    // cette phrase qui doit être là, et les mots qu'elle contient ne peuvent
    // donc pas servir d'interdits littéraux.
    const disclaimer = screen.getByText(/vous avez pris contact/)
    expect(disclaimer).toHaveTextContent('ne dit rien d’une réponse')
    expect(disclaimer).toHaveTextContent('rendez-vous')
    expect(disclaimer).toHaveTextContent('affaire gagnée')

    // Aucune ÉTAPE en aval n'est pour autant fabriquée : ni pipeline, ni
    // relance, ni statut CRM inventé.
    const page = (document.body.textContent ?? '').toLowerCase()
    for (const invented of ['pipeline', 'relance', 'opportunité', 'devis envoyé', 'négociation']) {
      expect(page).not.toContain(invented)
    }
  })

  it('ne rejoue pas une transition trompeuse quand le contact était déjà enregistré', async () => {
    const already = {
      ...UNLOCKED_DETAIL,
      interaction: {
        relevance: null,
        reason: null,
        note: null,
        contacted: true,
        contacted_at: '2026-08-15T09:00:00+00:00',
        updated_at: '2026-08-15T09:00:00+00:00',
      },
    }
    mockApi({ ...routes(), 'GET /signals/sig_unlocked_1': { body: already } })
    await openDetail()

    // L'état confirmé est rendu d'emblée ; l'action n'est plus proposée, donc
    // aucun clic ne peut simuler une nouvelle démarche commerciale.
    expect(screen.getByText(/Contact enregistré le/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'J’ai contacté cette entreprise' }),
    ).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_1/contacted')).toHaveLength(0)
  })
})
