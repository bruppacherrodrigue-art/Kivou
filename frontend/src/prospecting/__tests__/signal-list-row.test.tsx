import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { UnifiedStatus } from '../../api/types'
import { LOCKED_ITEM, mockApi } from '../../test/harness'
import { SignalListRow } from '../components/SignalListRow'
import { BASE, SIGNAL, item, renderSignal } from './signal-regression-harness'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
async function ready() { await waitFor(() => expect(screen.getByTestId('scope-ready')).toHaveTextContent('ready')) }

// V11 replaces table/compact/flag layouts, but keeps the underlying facts,
// server status, accessible opening and no-invented-data guarantees.
test('separates title, holder, place, exact amount and dated status without truncating the title', async () => {
  mockApi(BASE)
  const title = 'Collège de Levens, lot 2 : gros œuvre, charpente bois, façades et génie civil'
  renderSignal(<SignalListRow item={item({ factual_display: { ...SIGNAL.factual_display, object_short: title } })} onOpen={vi.fn()} />)
  await ready()
  const row = screen.getByRole('article')
  expect(within(row).getByRole('button', { name: `Ouvrir : ${title}` })).toHaveTextContent(title)
  expect(within(row).getByText(SIGNAL.company.name!)).toBeInTheDocument()
  expect(row).toHaveTextContent('Villeneuve')
  expect(row).toHaveTextContent('1 240 000 €')
  expect(row).toHaveTextContent('4 août')
  expect(within(row).queryByLabelText(/Correspondance \d/)).not.toBeInTheDocument()
})

test.each([['new', 'Nouveau'], ['saved', 'Sauvegardé'], ['contacted', 'Contacté'], ['ignored', 'Ignoré']] as const)('preserves the server %s status label and machine attribute', async (status, label) => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={item({ status })} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByText(label)).toHaveAttribute('data-status', status)
})

test('translates status into English without deriving it from the fit label', async () => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={item({ status: 'saved', analysis: { ...SIGNAL.analysis, fit: { ...SIGNAL.analysis.fit, label: 'Custom API fit label' } } })} onOpen={vi.fn()} />, 'en')
  await ready()
  expect(screen.getByText('Saved')).toHaveAttribute('data-status', 'saved')
  expect(screen.getByText('Custom API fit label')).toBeInTheDocument()
})

test.each(['click', 'keyboard'])('opens exactly once with %s on the accessible title', async (method) => {
  mockApi(BASE)
  const open = vi.fn()
  renderSignal(<SignalListRow item={SIGNAL} onOpen={open} />)
  await ready()
  const title = screen.getByRole('button', { name: 'Ouvrir : Voirie' })
  if (method === 'click') await userEvent.click(title)
  else { title.focus(); await userEvent.keyboard('{Enter}') }
  expect(open).toHaveBeenCalledOnce()
})

test('omits unpublished holder, money and location rather than filling them with dashes or codes', async () => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={item({ company: { ...SIGNAL.company, name: null }, contract: { ...SIGNAL.contract, amount: null, location: { country: null, locality: null, subdivision_code: 'FR-31', subdivision_label: null, postal_code: null } } })} onOpen={vi.fn()} />)
  await ready()
  const row = screen.getByRole('article')
  expect(row).not.toHaveTextContent('FR-31')
  expect(row).not.toHaveTextContent('—')
  expect(row).not.toHaveTextContent('€')
  expect(row).not.toHaveTextContent(SIGNAL.company.name!)
})

test.each([false, true])('shows a consortium marker only when the API declares it (%s)', async (consortium) => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={item({ company: { ...SIGNAL.company, consortium } })} onOpen={vi.fn()} />)
  await ready()
  expect(screen.queryByText('Groupement') !== null).toBe(consortium)
})

test('locked teasers contain no missing-currency amount, national aggregate or workflow actions', async () => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={{ ...LOCKED_ITEM, teaser: { ...LOCKED_ITEM.teaser, amount: { value: '950000', currency: null }, department: 'TERRITOIRE MÉTROPOLITAIN' } }} onOpen={vi.fn()} />)
  await ready()
  const row = screen.getByRole('article')
  expect(row).not.toHaveTextContent('950')
  expect(row).not.toHaveTextContent(/Territoire métropolitain/i)
  expect(within(row).queryByRole('button', { name: 'Sauvegarder le signal' })).not.toBeInTheDocument()
  expect(within(row).getByRole('button', { name: 'Découvrir' })).toBeInTheDocument()
})

test('locked rows offer access options without assuming a subscription is the solution', async () => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={LOCKED_ITEM} onOpen={vi.fn()} />)
  await ready()
  const row = screen.getByRole('article')
  expect(row).toHaveTextContent('Découvrez les possibilités d’accès à ce signal.')
  expect(row).not.toHaveTextContent(/abonnement/i)
})

test.each(['saved', 'contacted', 'ignored'] as UnifiedStatus[])('offers an explicit reversible action for the %s status', async (status) => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={item({ status })} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByRole('button', { name: status === 'saved' ? 'Rétablir comme nouveau' : 'Rétablir le signal' })).toBeEnabled()
})
