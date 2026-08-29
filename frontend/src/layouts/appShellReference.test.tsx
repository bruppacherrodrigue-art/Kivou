import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

const NOTIFICATIONS = {
  email_enabled: false,
  notification_email: null,
  updated_at: '2026-08-29T09:00:00+00:00',
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.documentElement.lang = 'fr'
})

describe('shell connecté exact de la référence', () => {
  it('rend les cinq entrées exactes, dans l’ordre, avec les valeurs réelles du compte', async () => {
    stubDesktopMedia()
    mockConnectedApi()

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' }),
    ).toBeVisible()

    const provider = document.querySelector<HTMLElement>('.dashboard-provider')
    expect(provider).not.toBeNull()
    expect(provider?.style.getPropertyValue('--sidebar-width')).toBe('240px')
    expect(provider?.querySelector('.kivou-sidebar')).not.toBeNull()
    expect(provider?.querySelector('.sidebar-brand .kivou-brand-lockup')).not.toBeNull()
    expect(provider?.querySelector('.dashboard-workspace > .topbar')).not.toBeNull()

    const navigation = provider?.querySelector('.sidebar-menu')
    expect(navigation).not.toBeNull()
    const links = within(navigation as HTMLElement).getAllByRole('link')
    expect(links.map((link) => link.textContent?.trim())).toEqual([
      'Vue d’ensemble',
      'Signaux',
      'Entreprises',
      'Profil de ciblage',
      'Compte',
    ])
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/app/dashboard',
      '/app/signals',
      '/app/companies',
      '/app/icps',
      '/app/settings',
    ])
    expect(links[0]).toHaveAttribute('aria-current', 'page')

    expect(screen.getByText(ME.account_display_name)).toBeVisible()
    expect(screen.getByText(ME.email)).toBeVisible()
    expect(document.querySelector('.demo-mode-badge')).toHaveTextContent('Découverte')
    expect(screen.getByText(`${ICP.label} · ${ICP.customer_input.territories[0]}`)).toBeVisible()
    expect(screen.queryByText(/Compte démo|Mode démonstration|Maquette de travail/)).not.toBeInTheDocument()
    expect(document.querySelector('.demo-account .account-avatar')).toHaveTextContent('AS')
  })

  it('groupe facturation, notifications et réglages sous Compte', async () => {
    stubDesktopMedia()
    mockConnectedApi()

    renderApp(<AppRoutes />, { route: '/app/billing', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { level: 1, name: 'Compte' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Compte' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Vue d’ensemble' })).not.toHaveAttribute(
      'aria-current',
    )
  })

  it('laisse les routes publiques en français et applique la locale seulement au connecté', async () => {
    stubDesktopMedia()
    const englishSession = {
      status: 'authenticated' as const,
      me: { ...ME, locale: 'en' as const },
    }

    const publicRender = renderApp(<AppRoutes />, {
      route: '/',
      session: englishSession,
      locale: 'en',
    })
    expect((await screen.findAllByRole('link', { name: 'Comment ça marche' }))[0]).toBeVisible()
    expect(document.documentElement.lang).toBe('fr')
    publicRender.unmount()

    mockConnectedApi()
    renderApp(<AppRoutes />, {
      route: '/app/dashboard',
      session: englishSession,
      locale: 'fr',
    })

    expect(await screen.findByRole('link', { name: 'Overview' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Target profile' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Account' })).toBeVisible()
    expect(document.documentElement.lang).toBe('en')
  })

  it('réinitialise les ressources avant d’afficher un autre compte', async () => {
    const user = userEvent.setup()
    const accountB = {
      ...ME,
      account_id: 'acc_b',
      user_id: 'usr_b',
      account_display_name: 'Entreprise B',
      email: 'b@example.test',
    }
    const profileB = {
      ...ICP,
      target_icp_id: 'icp_b',
      label: 'Profil B',
      customer_input: {
        ...ICP.customer_input,
        territories: ['BE'],
      },
    }
    let releaseAProfiles:
      | ((response: { body: (typeof ICP)[] }) => void)
      | undefined
    let releaseABilling:
      | ((response: { body: typeof DISCOVERY_STATUS }) => void)
      | undefined
    let profileCall = 0
    let billingCall = 0

    mockApi({
      'GET /target-icps': () => {
        profileCall += 1
        if (profileCall === 1) {
          return new Promise((resolve) => {
            releaseAProfiles = resolve
          })
        }
        return { body: [profileB] }
      },
      'GET /billing/status': () => {
        billingCall += 1
        if (billingCall === 1) {
          return new Promise((resolve) => {
            releaseABilling = resolve
          })
        }
        return { body: { ...DISCOVERY_STATUS, plan_code: 'essential' as const } }
      },
    })

    renderApp(
      <>
        <AppRoutes />
        <AccountSwitcher account={accountB} />
      </>,
      { route: '/app/settings', session: AUTHENTICATED },
    )

    await waitFor(() => {
      expect(profileCall).toBe(1)
      expect(billingCall).toBe(1)
    })
    expect(screen.getAllByText(ME.account_display_name)).not.toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Passer au compte B' }))

    expect(await screen.findAllByText(accountB.account_display_name)).not.toHaveLength(0)
    expect(await screen.findByText('Profil B · BE')).toBeVisible()
    expect(document.querySelector('.demo-mode-badge')).toHaveTextContent('Essentiel')
    expect(profileCall).toBe(2)
    expect(billingCall).toBe(2)
    expect(screen.queryByText(ME.account_display_name)).not.toBeInTheDocument()

    await act(async () => {
      releaseAProfiles?.({ body: [{ ...ICP, label: 'Profil A secret' }] })
      releaseABilling?.({ body: { ...DISCOVERY_STATUS, plan_code: 'pro' } })
    })

    expect(screen.queryByText(/Profil A secret/)).not.toBeInTheDocument()
    expect(document.querySelector('.demo-mode-badge')).toHaveTextContent('Essentiel')
  })
})

function AccountSwitcher({ account }: { account: typeof ME }) {
  const { adopt } = useSession()
  return (
    <button type="button" onClick={() => adopt(account)}>
      Passer au compte B
    </button>
  )
}

function mockConnectedApi() {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /billing/plans': {
      body: { catalogue_version: 'test', billing_interval: 'month', currencies: [], plans: [] },
    },
    'GET /notification-preferences': { body: NOTIFICATIONS },
  })
}

function stubDesktopMedia() {
  const media: MediaQueryList = {
    matches: false,
    media: '(max-width: 767px)',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
}
