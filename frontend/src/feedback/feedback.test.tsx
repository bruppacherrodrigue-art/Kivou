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

describe('retour client V1', () => {
  it('enregistre un signal pertinent avec une note facultative', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    await user.click(screen.getByLabelText('Pertinent'))
    await user.type(screen.getByLabelText(/Note sur ce signal/), 'Vérifier le calendrier de livraison.')
    await user.click(screen.getByRole('button', { name: 'Enregistrer mon avis' }))

    await waitFor(() => expect(callsTo(PATH, 'PUT')).toHaveLength(1))
    expect(callsTo(PATH, 'PUT')[0].body).toEqual({
      relevance: 'relevant',
      reason: null,
      note: 'Vérifier le calendrier de livraison.',
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
    for (const label of expected) expect(screen.getByLabelText(label)).toBeInTheDocument()

    const group = screen.getByRole('group', { name: /Pourquoi ce signal n’est-il pas pertinent/ })
    expect(group.querySelectorAll('input[type="radio"]')).toHaveLength(expected.length)
  })

  it('rend la note disponible quel que soit le jugement et la borne à 500 caractères', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    const note = screen.getByLabelText(/Note sur ce signal/)
    expect(note).toHaveAttribute('maxlength', String(MAXIMUM_NOTE_LENGTH))

    await user.click(screen.getByLabelText('Pas pertinent'))
    expect(screen.getByLabelText(/Note sur ce signal/)).toBeInTheDocument()
  })

  it('enregistre ensemble la raison et la note d’un signal non pertinent', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    await openDetail()

    await user.click(screen.getByLabelText('Pas pertinent'))
    await user.click(screen.getByLabelText('Trop tard'))
    await user.type(screen.getByLabelText(/Note sur ce signal/), 'Le fournisseur est déjà choisi.')
    await user.click(screen.getByRole('button', { name: 'Enregistrer mon avis' }))

    await waitFor(() => expect(callsTo(PATH, 'PUT')).toHaveLength(1))
    expect(callsTo(PATH, 'PUT')[0].body).toEqual({
      relevance: 'not_relevant',
      reason: 'too_late',
      note: 'Le fournisseur est déjà choisi.',
    })
  })

  it('n’expose aucun suivi commercial dans la V1', async () => {
    mockApi(routes())
    await openDetail()

    expect(
      screen.queryByRole('button', { name: 'J’ai contacté cette entreprise' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/Avez-vous contacté cette entreprise/)).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_unlocked_1/contacted')).toHaveLength(0)
  })
})
