import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  ME,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'

const shell = {
  'GET /target-icps': { body: [ICP] },
  'GET /billing/status': { body: DISCOVERY_STATUS },
}

describe('compte exact connecté', () => {
  it('modifie la langue connectée depuis le formulaire exact du compte', async () => {
    const user = userEvent.setup()
    mockApi({
      ...shell,
      'PATCH /me': (request) => ({
        body: { ...ME, locale: (request.body as { locale: 'fr' | 'en' }).locale },
      }),
    })
    const { container } = renderApp(<AppRoutes />, {
      route: '/app/settings/profile',
      session: AUTHENTICATED,
    })

    await user.selectOptions(await screen.findByLabelText('Langue'), 'en')
    await user.click(screen.getByRole('button', { name: 'Enregistrer les préférences' }))

    expect(callsTo('/me', 'PATCH').map((call) => call.body)).toEqual([{ locale: 'en' }])
    expect(await screen.findByText('Saved')).toBeVisible()
    expect(document.documentElement.lang).toBe('en')

    const navigation = container.querySelector('.settings-nav')
    expect(navigation).not.toBeNull()
    expect(within(navigation as HTMLElement).getAllByRole('link').map((link) => ({
      href: link.getAttribute('href'),
      label: link.textContent,
    }))).toEqual([
      { href: '/app/settings', label: 'Overview' },
      { href: '/app/settings/profile', label: 'Account' },
      { href: '/app/settings/security', label: 'Security' },
      { href: '/app/notifications', label: 'Notifications' },
      { href: '/app/billing', label: 'Subscription' },
    ])

    await user.click(within(navigation as HTMLElement).getByRole('link', { name: 'Overview' }))
    const overviewNavigation = await waitFor(() => {
      const next = container.querySelector('.settings-nav')
      expect(next).not.toBeNull()
      return next as HTMLElement
    })
    await user.click(within(overviewNavigation).getByRole('link', { name: 'Account' }))
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('conserve le brouillon de langue après une panne et ne soumet jamais deux fois', async () => {
    const user = userEvent.setup()
    let releaseFailure!: () => void
    let attempts = 0
    mockApi({
      ...shell,
      'PATCH /me': (request) => {
        attempts += 1
        if (attempts === 1) {
          return new Promise((resolve) => {
            releaseFailure = () => resolve({
              status: 503,
              body: { detail: { code: 'service_unavailable' } },
            })
          })
        }
        return { body: { ...ME, locale: (request.body as { locale: 'fr' | 'en' }).locale } }
      },
    })
    renderApp(<AppRoutes />, {
      route: '/app/settings/profile',
      session: AUTHENTICATED,
    })

    const language = await screen.findByLabelText('Langue')
    await user.selectOptions(language, 'en')
    const save = screen.getByRole('button', { name: 'Enregistrer les préférences' })
    await user.click(save)
    await user.click(save)
    expect(callsTo('/me', 'PATCH')).toHaveLength(1)
    expect(language).toBeDisabled()

    releaseFailure()
    expect(await screen.findByRole('alert')).toBeVisible()
    expect(language).toHaveValue('en')
    expect(language).toBeEnabled()

    await user.click(save)
    expect(callsTo('/me', 'PATCH').map((call) => call.body)).toEqual([
      { locale: 'en' },
      { locale: 'en' },
    ])
    expect(await screen.findByText('Saved')).toBeVisible()
  })

  it('rend entreprise, e-mail et fuseau réels sans promettre leur mutation', async () => {
    const storageGet = vi.spyOn(Storage.prototype, 'getItem')
    const storageSet = vi.spyOn(Storage.prototype, 'setItem')
    mockApi(shell)
    const { container } = renderApp(<AppRoutes />, {
      route: '/app/settings/profile',
      session: AUTHENTICATED,
    })

    const form = await screen.findByRole('form', { name: 'Informations principales' })
    expect(within(form).getByLabelText('Entreprise')).toHaveValue(ME.account_display_name)
    expect(within(form).getByLabelText('Entreprise')).toHaveAttribute('readonly')
    expect(within(form).getByLabelText('Adresse professionnelle')).toHaveValue(ME.email)
    expect(within(form).getByLabelText('Adresse professionnelle')).toHaveAttribute('readonly')
    expect(within(form).getByLabelText('Fuseau horaire')).toHaveValue('Europe/Zurich')
    expect(within(form).getByLabelText('Fuseau horaire')).toBeDisabled()
    expect(container.querySelectorAll('main')).toHaveLength(1)
    expect(container.querySelectorAll('h1')).toHaveLength(1)
    expect(container.querySelector('.settings-form-card')).toBe(form)
    expect(storageGet).not.toHaveBeenCalled()
    expect(storageSet).not.toHaveBeenCalled()
  })

  it('branche la sécurité sur le reset existant et une seule déconnexion réelle', async () => {
    const user = userEvent.setup()
    let releaseLogout!: () => void
    mockApi({
      ...shell,
      'POST /auth/logout': () => new Promise((resolve) => {
        releaseLogout = () => resolve({ status: 204 })
      }),
    })
    renderApp(<AppRoutes />, {
      route: '/app/settings/security',
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Sécurité' })).toBeVisible()
    expect(await screen.findByRole('link', { name: 'Réinitialiser le mot de passe' })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
    expect(screen.queryByLabelText(/mot de passe actuel/i)).not.toBeInTheDocument()
    const css = readFileSync(
      join(process.cwd(), 'src/reference/dashboard/dashboard-reference.css'),
      'utf8',
    )
    expect(css).toMatch(
      /\.security-action-row > a,\s*\.security-action-row > button\s*\{[^}]*grid-column:\s*1 \/ -1;[^}]*width:\s*100%;/s,
    )
    const logout = screen.getByRole('button', { name: 'Se déconnecter' })
    await user.click(logout)
    await user.click(logout)
    expect(callsTo('/auth/logout')).toHaveLength(1)

    releaseLogout()
    await waitFor(() => expect(logout).not.toBeInTheDocument())
  })
})
