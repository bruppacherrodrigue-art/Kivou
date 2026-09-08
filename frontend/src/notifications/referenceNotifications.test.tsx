import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import {
  AUTHENTICATED,
  DASHBOARD,
  ICP,
  ME,
  PRO_STATUS,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'

const preference = {
  email_enabled: false,
  notification_email: null,
  updated_at: '2026-08-29T09:00:00+00:00',
}

const shell = {
  'GET /dashboard': { body: DASHBOARD },
  'GET /target-icps': { body: [ICP] },
  'GET /billing/status': { body: PRO_STATUS },
}

describe('notifications exactes connectées', () => {
  it('charge et met à jour uniquement le contrat réel de notification', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      'GET /notification-preferences': { body: preference },
      'PATCH /notification-preferences': (request) => ({
        body: { ...preference, ...(request.body as object) },
      }),
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    await user.click(await screen.findByRole('switch', { name: /activer les alertes e-mail/i }))
    expect(screen.getByLabelText('Adresse de réception')).toHaveAttribute('readonly')
    await user.click(screen.getByRole('button', { name: /enregistrer les notifications/i }))

    expect(callsTo('/notification-preferences', 'PATCH')[0].body).toEqual({
      email_enabled: true,
    })
    expect(screen.getByText(/Une adresse en attente de vérification ne reçoit aucune alerte/)).toBeVisible()
    expect(callsTo('/auth/email/request')).toHaveLength(0)
    expect(callsTo('/auth/email/verify')).toHaveLength(0)
    expect(document.querySelector('.settings-form-card')).not.toBeNull()
    expect(callsTo('/signals', 'GET')).toHaveLength(0)
  })

  it('conserve le choix de coupure après une panne de sauvegarde', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      'GET /notification-preferences': {
        body: { ...preference, email_enabled: true, notification_email: 'old@example.test' },
      },
      'PATCH /notification-preferences': {
        status: 503,
        body: { detail: { code: 'notification_unavailable' } },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    const input = await screen.findByLabelText('Adresse de réception')
    await user.click(screen.getByRole('switch', { name: /activer les alertes/i }))
    await user.click(screen.getByRole('button', { name: /enregistrer les notifications/i }))

    expect(await screen.findByRole('alert')).toBeVisible()
    expect(input).toHaveValue('old@example.test')
    expect(input).toHaveAttribute('readonly')
    expect(screen.getByRole('switch')).not.toBeChecked()
    expect(screen.getByRole('button', { name: /enregistrer les notifications/i })).toBeEnabled()
    expect(screen.queryByText('Enregistré')).not.toBeInTheDocument()
    expect(callsTo('/notification-preferences', 'PATCH')[0].body).toEqual({ email_enabled: false })
  })

  it('affiche la cadence serveur dans le contrôle source mais en analyse seule', async () => {
    mockApi({
      ...shell,
      'GET /notification-preferences': { body: preference },
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    const form = await screen.findByRole('form', { name: 'Réception des nouveaux signaux' })
    const cadence = within(form).getByLabelText('Fréquence')
    expect(cadence).toHaveValue('daily')
    expect(cadence).toBeDisabled()
    expect(callsTo('/notification-preferences', 'PATCH')).toHaveLength(0)
  })

  it('relance les préférences localement sans relire la cadence', async () => {
    const user = userEvent.setup()
    let preferenceAttempts = 0
    mockApi({
      ...shell,
      'GET /notification-preferences': () => {
        preferenceAttempts += 1
        return preferenceAttempts === 1
          ? { status: 503, body: { detail: { code: 'notification_unavailable' } } }
          : { body: preference }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Les préférences n’ont pas pu être chargées')
    const billingCallsBeforeRetry = callsTo('/billing/status', 'GET').length
    await user.click(within(alert).getByRole('button', { name: /réessayer les préférences/i }))

    expect(await screen.findByRole('form', { name: 'Réception des nouveaux signaux' })).toBeVisible()
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(2)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(billingCallsBeforeRetry)
  })

  it('garde le formulaire éditable quand la cadence échoue et relance seulement la facturation', async () => {
    const user = userEvent.setup()
    let billingAttempts = 0
    mockApi({
      ...shell,
      'GET /notification-preferences': { body: preference },
      'GET /billing/status': () => {
        billingAttempts += 1
        return billingAttempts <= 1
          ? { status: 503, body: { detail: { code: 'billing_unavailable' } } }
          : { body: PRO_STATUS }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    const form = await screen.findByRole('form', { name: 'Réception des nouveaux signaux' })
    expect(within(form).getByRole('switch', { name: /activer les alertes/i })).toBeEnabled()
    const cadenceAlert = within(form).getByRole('alert')
    expect(cadenceAlert).toHaveTextContent('La fréquence n’a pas pu être chargée')
    await user.click(within(cadenceAlert).getByRole('button', { name: /réessayer la fréquence/i }))

    await waitFor(() => expect(within(form).getByLabelText('Fréquence')).toHaveValue('daily'))
    expect(callsTo('/notification-preferences', 'GET')).toHaveLength(1)
    expect(callsTo('/billing/status', 'GET')).toHaveLength(2)
  })

  it('fige le brouillon pendant la sauvegarde et verrouille les doubles soumissions', async () => {
    const user = userEvent.setup()
    let release!: () => void
    mockApi({
      ...shell,
      'GET /notification-preferences': { body: preference },
      'PATCH /notification-preferences': (request) => new Promise((resolve) => {
        release = () => resolve({ body: { ...preference, ...(request.body as object) } })
      }),
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    const toggle = await screen.findByRole('switch', { name: /activer les alertes/i })
    await user.click(toggle)
    const input = screen.getByLabelText('Adresse de réception')
    expect(input).toHaveAttribute('readonly')
    const save = screen.getByRole('button', { name: /enregistrer les notifications/i })
    await user.click(save)

    expect(toggle).toBeDisabled()
    expect(input).toBeDisabled()
    expect(save).toBeDisabled()
    await user.click(save)
    expect(callsTo('/notification-preferences', 'PATCH')).toHaveLength(1)

    await act(async () => release())
    expect(await screen.findByText('Enregistré')).toBeVisible()
  })

  it('permet de couper les alertes sans adresse et affiche le lien de vérification', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      'GET /notification-preferences': { body: { ...preference, email_enabled: true } },
      'PATCH /notification-preferences': { body: preference },
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    await user.click(await screen.findByRole('switch', { name: /activer les alertes/i }))
    await user.click(screen.getByRole('button', { name: /enregistrer les notifications/i }))

    const input = screen.getByLabelText('Adresse de réception')
    expect(input).toHaveValue('')
    expect(input).toHaveAttribute('readonly')
    expect(screen.getByRole('link', { name: 'Modifier et vérifier mon adresse email' })).toHaveAttribute('href', '/app/settings/profile')
    expect(callsTo('/notification-preferences', 'PATCH')[0].body).toEqual({ email_enabled: false })
    expect(await screen.findByText('Enregistré')).toBeVisible()
  })

  it('ignore la réponse de sauvegarde privée du compte précédent', async () => {
    const user = userEvent.setup()
    let releaseAccountA!: () => void
    let preferenceReads = 0
    mockApi({
      ...shell,
      'GET /notification-preferences': () => {
        preferenceReads += 1
        return {
          body: preferenceReads === 1
            ? { ...preference, email_enabled: true, notification_email: 'a@example.test' }
            : { ...preference, email_enabled: true, notification_email: 'b@example.test' },
        }
      },
      'PATCH /notification-preferences': () => new Promise((resolve) => {
        releaseAccountA = () => resolve({
          body: { ...preference, email_enabled: true, notification_email: 'a-secret@example.test' },
        })
      }),
    })
    renderApp(
      <>
        <AppRoutes />
        <AdoptAccountB />
      </>,
      { route: '/app/notifications', session: AUTHENTICATED },
    )

    await screen.findByLabelText('Adresse de réception')
    await user.click(screen.getByRole('switch', { name: /activer les alertes/i }))
    await user.click(screen.getByRole('button', { name: /enregistrer les notifications/i }))
    await user.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))

    expect(await screen.findByLabelText('Adresse de réception')).toHaveValue('b@example.test')
    await act(async () => releaseAccountA())
    expect(screen.getByLabelText('Adresse de réception')).toHaveValue('b@example.test')
    expect(screen.queryByText(/a-secret@example\.test/)).not.toBeInTheDocument()
  })

  it('invalide la session sur un 401 des préférences', async () => {
    mockApi({
      ...shell,
      'GET /notification-preferences': {
        status: 401,
        body: { detail: { code: 'not_authenticated' } },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { level: 1, name: 'Retrouver vos signaux' })).toBeVisible()
  })
})

function AdoptAccountB() {
  const { adopt } = useSession()
  return (
    <button
      type="button"
      onClick={() => adopt({
        ...ME,
        account_id: 'acc_notifications_b',
        account_display_name: 'Compte B',
      })}
    >
      Basculer sur le compte B
    </button>
  )
}
