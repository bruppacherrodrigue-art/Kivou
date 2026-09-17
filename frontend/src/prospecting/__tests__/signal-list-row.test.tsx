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
test('separates title, holder, place, rounded amount and dated status without truncating the title', async () => {
  mockApi(BASE)
  const title = 'Collège de Levens, lot 2 : gros œuvre, charpente bois, façades et génie civil'
  renderSignal(<SignalListRow item={item({ factual_display: { ...SIGNAL.factual_display, object_short: title } })} onOpen={vi.fn()} />)
  await ready()
  const row = screen.getByRole('article')
  expect(within(row).getByRole('button', { name: `Ouvrir : ${title}` })).toHaveTextContent(title)
  expect(within(row).getByText(SIGNAL.company.name!)).toBeInTheDocument()
  expect(row).toHaveTextContent('Villeneuve')
  expect(row).toHaveTextContent('1,2 M€')
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
  expect(screen.queryByText('Custom API fit label')).not.toBeInTheDocument()
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
  expect(within(row).getByText('Titulaire réservé')).toBeInTheDocument()
  expect(within(row).getByRole('button', { name: `Ouvrir : ${LOCKED_ITEM.headline}` })).toBeInTheDocument()
})

test.each(['click', 'keyboard'])('opens a locked landing teaser with %s', async (method) => {
  mockApi(BASE)
  const open = vi.fn()
  renderSignal(<SignalListRow item={{ ...LOCKED_ITEM, landing_example_holder: 'Boussiquet' }} onOpen={open} />)
  await ready()
  const title = screen.getByRole('button', { name: `Ouvrir : ${LOCKED_ITEM.headline}` })
  if (method === 'click') await userEvent.click(title)
  else { title.focus(); await userEvent.keyboard('{Enter}') }
  expect(open).toHaveBeenCalledOnce()
})

test('locked rows offer access options without assuming a subscription is the solution', async () => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={{ ...LOCKED_ITEM, landing_example_holder: 'Boussiquet' }} onOpen={vi.fn()} />)
  await ready()
  const row = screen.getByRole('article')
  expect(row).toHaveTextContent('dans la Haute-Garonne')
  expect(row).toHaveTextContent('Comme pour Boussiquet : dirigeant, téléphone, e-mail, historique des marchés.')
  expect(row).not.toHaveTextContent(/abonnement/i)
})

test('locked rows distinguish an award date from a publication fallback', async () => {
  mockApi(BASE)
  const { unmount } = renderSignal(<SignalListRow item={{ ...LOCKED_ITEM, teaser: { ...LOCKED_ITEM.teaser, date_kind: 'award' } }} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByText(/Attribué le/)).toBeInTheDocument()
  unmount()
  renderSignal(<SignalListRow item={{ ...LOCKED_ITEM, teaser: { ...LOCKED_ITEM.teaser, date_kind: 'publication' } }} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByText(/Publié le/)).toBeInTheDocument()
})

test('landing rows use the relevant lot instead of the raw INX notice wording', async () => {
  mockApi(BASE)
  const raw = 'INX La présente consultation concerne la construction d’une patinoire communautaire\n - Bardage, Façade'
  renderSignal(<SignalListRow item={{ ...LOCKED_ITEM, headline: raw, landing_example_holder: 'Boussiquet' }} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByRole('button', { name: 'Ouvrir : Bardage, Façade — patinoire communautaire' })).toBeInTheDocument()
  expect(screen.queryByText(/INX La présente consultation/)).not.toBeInTheDocument()
})

test('opened landing rows also use the relevant INX lot wording', async () => {
  mockApi(BASE)
  const raw = 'INX La présente consultation concerne la construction d’une patinoire communautaire.\\n - Bardage, Façade'
  renderSignal(<SignalListRow item={item({ landing_example_holder: 'Boussiquet', factual_display: { ...SIGNAL.factual_display, object_short: raw } })} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByRole('button', { name: 'Ouvrir : Bardage, Façade — patinoire communautaire' })).toBeInTheDocument()
  expect(screen.queryByText(/INX La présente consultation/)).not.toBeInTheDocument()
})

test.each(['saved', 'contacted', 'ignored'] as UnifiedStatus[])('offers an explicit reversible action for the %s status', async (status) => {
  mockApi(BASE)
  renderSignal(<SignalListRow item={item({ status })} onOpen={vi.fn()} />)
  await ready()
  expect(screen.getByRole('button', { name: status === 'saved' ? 'Rétablir comme nouveau' : 'Rétablir le signal' })).toBeEnabled()
})
