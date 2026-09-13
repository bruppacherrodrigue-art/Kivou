import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { RouteHandler } from '../../test/harness'
import { COMPANY_PROFILE, callsTo, feedPage, mockApi } from '../../test/harness'
import { SignalContent } from '../components/SignalContent'
import { BASE, DETAIL, SIGNAL, item, renderFeed, renderSignal, workflow } from './signal-regression-harness'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
const detailPath = `/signals/${SIGNAL.signal_id}`

test('a suppressed Apollo result cannot reappear from the original holder snapshot', async () => {
  const companyKey = COMPANY_PROFILE.company_key
  mockApi({ ...BASE,
    [`GET ${detailPath}`]: { body: { ...DETAIL, company_key: companyKey } },
    [`GET /companies/${companyKey}`]: { body: { ...COMPANY_PROFILE, private_subject_key: 'private-holder',
      capabilities: { can_view_company_data: true, can_lookup_contact: true },
      contact_lookup: { state: 'ready', source: 'apollo', remaining: 3, monthly_quota: 5, removal_path: '/contact', can_refresh: true,
        contacts: [{ name: 'Alice Confidentiel', title: 'Achats', email: 'alice@example.test', email_status: 'verified' }] },
    } },
    [`POST /companies/${companyKey}/contact-lookup`]: { status: 409, body: { detail: { code: 'contact_lookup_suppressed' } } },
  })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  await screen.findByText('alice@example.test')
  fireEvent.click(screen.getByRole('button', { name: 'Trouver le décideur' }))
  await screen.findByRole('button', { name: 'Vérifier le résultat' })
  await waitFor(() => expect(screen.queryByText('alice@example.test')).not.toBeInTheDocument())
  expect(screen.queryByText('Alice Confidentiel')).not.toBeInTheDocument()
  expect(callsTo(`/companies/${companyKey}/contact-lookup`)).toHaveLength(1)
})
async function opened() {
  const dialog = await screen.findByRole('dialog', { name: 'Détail du signal' })
  await within(dialog).findByRole('heading', { name: 'Voirie' })
  return dialog
}

test('a deep link loads an independently requested detail even when the list is empty', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([]) } })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  const dialog = await opened()
  expect(callsTo(detailPath, 'GET')).toHaveLength(1)
  expect(within(dialog).getAllByText('Commune de Villeneuve')).toHaveLength(1)
  expect(within(dialog).getAllByRole('button', { name: 'Fermer' })).toHaveLength(1)
  expect(within(dialog).getByRole('textbox', { name: 'Vos notes sur ce signal' })).toBeInTheDocument()
})

test.each(['button', 'cancel'])('closing via %s preserves filters, replaces history and returns focus to the opener', async (method) => {
  mockApi(BASE)
  renderFeed('/app/signals?target_icp_id=icp_1&min_amount=50000&amount_currency=EUR&status=saved&q=voirie&sort=amount')
  const opener = await screen.findByRole('button', { name: 'Ouvrir : Voirie' })
  await userEvent.click(opener)
  const dialog = await opened()
  expect(screen.getByTestId('signal-navigation')).toHaveTextContent('PUSH')
  expect(screen.getByTestId('signal-location')).toHaveTextContent(`/app/signals/${SIGNAL.signal_id}?`)
  if (method === 'button') await userEvent.click(within(dialog).getByRole('button', { name: 'Fermer' }))
  else fireEvent(dialog, new Event('cancel', { cancelable: true, bubbles: true }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByTestId('signal-navigation')).toHaveTextContent('REPLACE')
  expect(screen.getByTestId('signal-location')).toHaveTextContent('target_icp_id=icp_1')
  expect(screen.getByTestId('signal-location')).toHaveTextContent('status=saved')
  expect(screen.getByTestId('signal-location')).toHaveTextContent('q=voirie')
  expect(screen.getByTestId('signal-location')).toHaveTextContent('sort=amount')
  expect(opener).toHaveFocus()
})

test('loading is named and a failed detail can be retried without exposing stale facts', async () => {
  let resolve!: (response: RouteHandler) => void
  let failed = false
  mockApi({ ...BASE, [`GET ${detailPath}`]: () => failed ? { body: DETAIL } : new Promise<RouteHandler>((done) => { resolve = done }) })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  const dialog = await screen.findByRole('dialog', { name: 'Détail du signal' })
  expect(await within(dialog).findByRole('status')).toHaveTextContent('Chargement du signal')
  expect(within(dialog).queryByRole('heading', { name: 'Voirie' })).not.toBeInTheDocument()
  await waitFor(() => expect(resolve).toBeDefined())
  await act(async () => { failed = true; resolve({ status: 500, body: { detail: 'unavailable' } }) })
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Ce signal ne peut pas être ouvert')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Réessayer' }))
  await within(dialog).findByRole('heading', { name: 'Voirie' })
  expect(callsTo(detailPath, 'GET')).toHaveLength(2)
})

test.each([['Sauvegarder', 'saved', 'Retirer des sauvegardés'], ['Ignorer', 'ignored', 'Rétablir'], ['Marquer contacté', 'contacted', 'Rétablir comme nouveau']] as const)('the %s action writes a revisioned status and remains reversible', async (label, next, reverseLabel) => {
  let status = SIGNAL.status
  let revision = 4
  mockApi({ ...BASE,
    [`GET ${detailPath}`]: () => ({ body: { ...DETAIL, status, status_revision: revision } }),
    [`PUT ${detailPath}/status`]: ({ body }) => { const request = body as { status: typeof status }; status = request.status; return { body: workflow(status, ++revision) } },
  })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  const dialog = await opened()
  await userEvent.click(within(dialog).getByRole('button', { name: label }))
  await within(dialog).findByRole('button', { name: reverseLabel })
  expect(callsTo(`${detailPath}/status`, 'PUT')[0].body).toEqual({ status: next, expected_revision: 4 })
  await userEvent.click(within(dialog).getByRole('button', { name: reverseLabel }))
  await waitFor(() => expect(callsTo(`${detailPath}/status`, 'PUT')).toHaveLength(2))
  expect(callsTo(`${detailPath}/status`, 'PUT')[1].body).toEqual({ status: 'new', expected_revision: 5 })
  expect(callsTo(`${detailPath}/feedback`, 'PUT')).toHaveLength(0)
  expect(callsTo(`${detailPath}/contacted`, 'POST')).toHaveLength(0)
})

test('all workflow controls are disabled during a write, with no duplicate submit', async () => {
  let resolve!: (response: RouteHandler) => void
  mockApi({ ...BASE, [`PUT ${detailPath}/status`]: () => new Promise<RouteHandler>((done) => { resolve = done }) })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  const dialog = await opened()
  await userEvent.click(within(dialog).getByRole('button', { name: 'Marquer contacté' }))
  for (const name of ['Marquer contacté', 'Sauvegarder', 'Ignorer']) expect(within(dialog).getByRole('button', { name })).toBeDisabled()
  await userEvent.click(within(dialog).getByRole('button', { name: 'Marquer contacté' }))
  expect(callsTo(`${detailPath}/status`, 'PUT')).toHaveLength(1)
  await act(async () => { resolve({ body: workflow('contacted') }) })
})

test('a failed action preserves server counts including zero instead of inventing an optimistic rollback increment', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([SIGNAL], { counts: { new: 0, saved: 0, contacted: 0, ignored: 0 } }) }, [`PUT ${detailPath}/status`]: { status: 500, body: { detail: 'unavailable' } } })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  const dialog = await opened()
  await userEvent.click(within(dialog).getByRole('button', { name: 'Marquer contacté' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Le statut n’a pas pu être enregistré')
  expect(within(dialog).getByRole('button', { name: 'Marquer contacté' })).toBeEnabled()
  expect(screen.getByRole('tab', { name: /^Nouveaux\s+0$/ })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: /^Contactés\s+0$/ })).toBeInTheDocument()
})

test('does not show missing facts, inferred needs, estimated start dates or duplicated legacy fit reasons', async () => {
  mockApi(BASE)
  renderSignal(<SignalContent item={item({ contract: { ...SIGNAL.contract, buyer: null, amount: null, location: null, dates: { award: null, publication: null, contract_notification: null } }, commercial_calendar: { start_month: '2026-10', duration_months: 18, source: 'public_notice' }, analysis: { ...SIGNAL.analysis, fit: { ...SIGNAL.analysis.fit, reasons: ['Private rule reason'], for_you_sentence: 'Old static reason' } } })} holder={null} notes={null} />)
  await waitFor(() => expect(screen.getByTestId('scope-ready')).toHaveTextContent('ready'))
  expect(screen.queryByRole('heading', { name: 'Acheteur' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Calendrier' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Pourquoi ça vous concerne' })).not.toBeInTheDocument()
  for (const word of ['—', 'Private rule reason', 'Old static reason', 'Démarrage probable', 'Ce que le titulaire va devoir faire', 'contact non confirmé', 'résolution incomplète', 'Idée d’approche']) expect(document.body).not.toHaveTextContent(word)
})

test.each([null, 'javascript:alert(1)'])('keeps the source identity readable when its URL cannot be linked (%s)', async (url) => {
  mockApi(BASE)
  renderSignal(<SignalContent item={item({ source: { ...SIGNAL.source, url } })} holder={null} notes={null} />)
  await waitFor(() => expect(screen.getByTestId('scope-ready')).toHaveTextContent('ready'))
  expect(screen.queryByRole('link', { name: /Consulter l’avis/ })).not.toBeInTheDocument()
  expect(screen.getByText(/BOAMP.*26-104412/)).toBeInTheDocument()
})

test('source URL remains external and protected while the buyer is only shown once', async () => {
  mockApi(BASE)
  renderSignal(<SignalContent item={SIGNAL} holder={null} notes={null} />)
  await waitFor(() => expect(screen.getByTestId('scope-ready')).toHaveTextContent('ready'))
  expect(screen.getAllByText('Commune de Villeneuve')).toHaveLength(1)
  const link = screen.getByRole('link', { name: /Consulter l’avis.*BOAMP/ })
  expect(link).toHaveAttribute('href', SIGNAL.source.url)
  expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
})
