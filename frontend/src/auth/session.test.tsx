import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useSession } from './SessionProvider'
import { AUTHENTICATED, ME, mockApi, renderApp } from '../test/harness'

/* P0-02 §5.A — ce qu'une relecture de session ratée a le droit de conclure.
 *
 * Le cas qui a motivé ces vérifications n'est pas théorique : un
 * `POST /target-icps` réussit, la relecture de `/me` échoue sur une coupure
 * réseau, et le client se retrouvait déconnecté avec un ciblage qu'il ne
 * savait pas enregistré. Un 401 et une panne réseau ne disent PAS la même
 * chose ; les confondre coûte une session valable.
 */

afterEach(() => vi.unstubAllGlobals())

/** Un témoin minimal : il affiche l'état de session et rejoue `refresh()` à la
 *  demande, en rapportant si la promesse a tenu ou non. */
function SessionProbe() {
  const { state, refresh } = useSession()
  return (
    <div>
      <p data-testid="status">{state.status}</p>
      <p data-testid="outcome" />
      <button
        onClick={() => {
          const outcome = document.querySelector('[data-testid="outcome"]')!
          refresh().then(
            () => {
              outcome.textContent = 'resolved'
            },
            () => {
              outcome.textContent = 'rejected'
            },
          )
        }}
      >
        relire
      </button>
    </div>
  )
}

/** Une panne réseau : `fetch` rejette, ce qu'aucun code de statut ne décrit. */
function stubNetworkFailure() {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
  )
}

describe('relecture de session', () => {
  it('invalide la session sur un vrai 401', async () => {
    const user = userEvent.setup()
    mockApi({ 'GET /me': { status: 401, body: { detail: { code: 'not_authenticated' } } } })
    renderApp(<SessionProbe />, { session: AUTHENTICATED })

    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
    await user.click(screen.getByRole('button', { name: 'relire' }))

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))
    // Un refus explicite du serveur n'est pas une erreur à relancer : il a été
    // traité, la session est tombée.
    await waitFor(() => expect(screen.getByTestId('outcome')).toHaveTextContent('resolved'))
  })

  it('conserve une session authentifiée quand le serveur répond 500', async () => {
    const user = userEvent.setup()
    mockApi({ 'GET /me': { status: 500, body: { detail: { code: 'billing_error' } } } })
    renderApp(<SessionProbe />, { session: AUTHENTICATED })

    await user.click(screen.getByRole('button', { name: 'relire' }))

    await waitFor(() => expect(screen.getByTestId('outcome')).toHaveTextContent('rejected'))
    // Une panne du serveur ne dit rien de la validité du cookie de session.
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
  })

  it('conserve une session authentifiée quand le réseau tombe', async () => {
    const user = userEvent.setup()
    stubNetworkFailure()
    renderApp(<SessionProbe />, { session: AUTHENTICATED })

    await user.click(screen.getByRole('button', { name: 'relire' }))

    await waitFor(() => expect(screen.getByTestId('outcome')).toHaveTextContent('rejected'))
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
  })

  it('rend une session valable après une relecture réussie', async () => {
    const user = userEvent.setup()
    mockApi({ 'GET /me': { body: ME } })
    renderApp(<SessionProbe />, { session: AUTHENTICATED })

    await user.click(screen.getByRole('button', { name: 'relire' }))

    await waitFor(() => expect(screen.getByTestId('outcome')).toHaveTextContent('resolved'))
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
  })

  it('résout le démarrage plutôt que de rester bloqué, même si le réseau tombe', async () => {
    stubNetworkFailure()
    // Aucun état injecté : c'est la vérification initiale de `SessionProvider`.
    renderApp(<SessionProbe />)

    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    // Sans résolution, l'application resterait sur un écran de chargement
    // qu'aucun événement ne viendrait terminer.
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))
  })

  it('résout le démarrage sur un 401, sans propager d’erreur', async () => {
    mockApi({ 'GET /me': { status: 401, body: { detail: { code: 'not_authenticated' } } } })
    renderApp(<SessionProbe />)

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))
  })
})
