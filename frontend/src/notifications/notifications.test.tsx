import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  PRO_STATUS,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'

/* SPEC-015 §54 — les cinq vérifications des notifications. */

afterEach(() => vi.unstubAllGlobals())

const PREFERENCE = {
  email_enabled: true,
  notification_email: 'alertes@acme.test',
  updated_at: '2026-08-10T09:00:00+00:00',
}

function routes(status = PRO_STATUS, preference = PREFERENCE, overrides = {}) {
  return {
    'GET /notification-preferences': { body: preference },
    'GET /billing/status': { body: status },
    'PATCH /notification-preferences': { body: preference },
    ...overrides,
  }
}

describe('préférences de notification', () => {
  it('compose les préférences avec les surfaces connectées et un repli à 900 px', () => {
    const css = readFileSync(
      join(process.cwd(), 'src/presentation/dashboard/app-shell.css'),
      'utf8',
    )

    expect(css).toMatch(/\.notification-toggle-row[\s\S]*grid-template-columns/)
    expect(css).toMatch(/@media \(max-width: 620px\)[\s\S]*\.notification-toggle-row/)
  })

  it('affiche l’adresse de réception enregistrée', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    const field = await screen.findByLabelText(/Adresse de réception/)
    expect(field).toHaveValue('alertes@acme.test')
  })

  it('persiste l’activation ou la coupure des alertes', async () => {
    const user = userEvent.setup()
    mockApi(
      routes(PRO_STATUS, PREFERENCE, {
        'PATCH /notification-preferences': {
          body: { ...PREFERENCE, email_enabled: false },
        },
      }),
    )
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    const toggle = await screen.findByRole('switch', { name: /Activer les alertes e-mail/ })
    expect(toggle).toBeChecked()

    await user.click(toggle)
    await user.click(screen.getByRole('button', { name: 'Enregistrer les notifications' }))

    await waitFor(() =>
      expect(callsTo('/notification-preferences', 'PATCH')).toHaveLength(1),
    )
    const sent = callsTo('/notification-preferences', 'PATCH')[0].body as Record<string, unknown>
    expect(sent.email_enabled).toBe(false)
    expect(sent).not.toHaveProperty('account_id')

    expect(await screen.findByText('Enregistré')).toBeInTheDocument()
    expect(screen.getByRole('switch')).not.toBeChecked()
  })

  it('rend la cadence depuis le droit du plan, en analyse seule', async () => {
    mockApi(routes(PRO_STATUS))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    expect(await screen.findByText('Quotidienne')).toBeInTheDocument()
    expect(screen.getByText(/La fréquence dépend de votre offre/)).toBeInTheDocument()

    // La cadence conserve le contrôle de la maquette, mais reste strictement
    // en analyse seule sous l'autorité du droit serveur.
    expect(screen.getByRole('combobox', { name: /fréquence/i })).toBeDisabled()
    expect(screen.queryByRole('radio', { name: 'Hebdomadaire' })).not.toBeInTheDocument()
  })

  it('dit « prioritaire » pour Scale, jamais « temps réel » ni « instantané »', async () => {
    const scaleStatus = {
      ...PRO_STATUS,
      plan_code: 'scale' as const,
      entitlements: { ...PRO_STATUS.entitlements, alert_cadence: 'priority' as const },
    }
    mockApi(routes(scaleStatus))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    expect(await screen.findByText('Prioritaire')).toBeInTheDocument()

    const page = (document.body.textContent ?? '').toLowerCase()
    expect(page).not.toContain('temps réel')
    expect(page).not.toContain('real-time')
    expect(page).not.toContain('realtime')
    expect(page).not.toContain('instantané')
    expect(page).not.toContain('immédiat')
  })

  it('explique l’absence d’alertes en Découverte plutôt que de la masquer', async () => {
    mockApi(routes(DISCOVERY_STATUS))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    expect(await screen.findByText('Aucune alerte')).toBeInTheDocument()
    expect(screen.getByText(/n’inclut pas d’alertes e-mail/)).toBeInTheDocument()
  })

  it('rejette une adresse invalide en le disant sur le champ', async () => {
    const user = userEvent.setup()
    mockApi(
      routes(PRO_STATUS, PREFERENCE, {
        'PATCH /notification-preferences': {
          status: 422,
          body: {
            detail: {
              code: 'invalid_notification_email',
              message: 'adresse de notification invalide',
            },
          },
        },
      }),
    )
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    const field = await screen.findByLabelText(/Adresse de réception/)
    await user.clear(field)
    await user.type(field, 'pas-une-adresse')
    await user.click(screen.getByRole('button', { name: 'Enregistrer les notifications' }))

    expect(await screen.findByText('Cette adresse n’est pas valide.')).toBeInTheDocument()
    expect(field).toHaveAttribute('aria-invalid', 'true')
  })

  it('n’invente aucun historique de livraison', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/notifications' })

    await screen.findByLabelText(/Adresse de réception/)
    const page = (document.body.textContent ?? '').toLowerCase()
    for (const invented of ['dernier envoi', 'envoyé le', 'historique des alertes', 'délivré']) {
      expect(page).not.toContain(invented)
    }
  })
})
