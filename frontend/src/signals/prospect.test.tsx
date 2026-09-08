import { describe, expect, it } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { AppRoutes } from '../App'
import { AUTHENTICATED, DASHBOARD, ME, UNLOCKED_ITEM, callsTo, feedPage, mockApi, renderApp } from '../test/harness'
import { SignalDrawer } from './components/SignalDrawer'

const noop = () => undefined
const draw = (dates: typeof UNLOCKED_ITEM.contract.dates) => renderApp(
  <SignalDrawer item={{ ...UNLOCKED_ITEM,
    factual_display: { ...UNLOCKED_ITEM.factual_display, object_short: 'Pose de bardage' },
    contract: { ...UNLOCKED_ITEM.contract, title: 'Pose de bardage métallique sur le bâtiment communal', lot_title: null, dates },
  }} loading={false} error={null} busy={false} onClose={noop} onRetry={noop}
    onContacted={noop} onSave={noop} onIgnore={noop} />,
  { session: AUTHENTICATED },
)

describe('prospect de production', () => {
  it('ouvre le drawer avant le feed sans rappeler le détail à sa résolution', async () => {
    let releaseFeed = () => {}
    const pendingFeed = new Promise<void>((resolve) => { releaseFeed = resolve })
    const detailPath = `/signals/${UNLOCKED_ITEM.signal_id}`
    mockApi({
      '/dashboard': { body: DASHBOARD },
      '/signals': async () => {
        await pendingFeed
        return { body: feedPage([], { provisional_profile: true }) }
      },
      [detailPath]: { body: UNLOCKED_ITEM },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: {
        status: 'authenticated',
        me: { ...ME, onboarding_status: 'icp_incomplete', provisional_profile: true },
      },
    })
    expect(await screen.findByRole('heading', {
      level: 2, name: 'Réfection de la voirie communale — lot 2',
    })).toBeInTheDocument()
    expect(callsTo(detailPath, 'GET')).toHaveLength(1)
    await act(async () => { releaseFeed(); await pendingFeed })
    expect(callsTo(detailPath, 'GET')).toHaveLength(1)
    expect(screen.queryByText('0 signaux')).not.toBeInTheDocument()
  })

  it('conserve le shell et le compte pour un profil provisoire', async () => {
    mockApi({ '/dashboard': { body: DASHBOARD }, '/signals': { body: {
      items: [UNLOCKED_ITEM], plan_code: 'discovery', provisional_profile: true,
      page: { has_more: false }, filter_access: { sector: true },
      counts: { new: 1, saved: 0, contacted: 0, ignored: 0 },
    } } })
    renderApp(<AppRoutes />, { route: '/app/signals', session: {
      status: 'authenticated', me: { ...ME, onboarding_status: 'icp_incomplete', provisional_profile: true },
    } })
    expect(await screen.findByText('Découverte · profil provisoire')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Se déconnecter' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /Confirmer mon profil/ })).toBeInTheDocument()
  })

  it('affiche un titre court et l’objet complet séparément', () => {
    draw(UNLOCKED_ITEM.contract.dates)
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(/^Pose de bardage$/)
    expect(screen.getByText('Pose de bardage métallique sur le bâtiment communal')).toBeInTheDocument()
    const facts = screen.getByText('Titulaire').closest('dl')!
    expect(within(facts).getByText('Acheteur')).toBeInTheDocument()
  })

  it('qualifie une notification comme attribution', () => {
    draw({ award: null, contract_notification: '2026-08-20', publication: '2026-08-25' })
    expect(screen.getByText('Attribué le')).toBeInTheDocument()
    expect(screen.queryByText('Notifié le')).not.toBeInTheDocument()
    expect(screen.queryByText('Publié le')).not.toBeInTheDocument()
  })

  it('ne rebaptise pas une publication en attribution', () => {
    draw({ award: null, contract_notification: null, publication: '2026-08-25' })
    expect(screen.getByText('Publié le')).toBeInTheDocument()
    expect(screen.queryByText('Attribué le')).not.toBeInTheDocument()
  })
})
