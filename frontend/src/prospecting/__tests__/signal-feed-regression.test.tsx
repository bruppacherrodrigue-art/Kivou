import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { callsTo, feedPage, mockApi } from '../../test/harness'
import { BASE, DETAIL, SIGNAL, item, renderFeed, workflow } from './signal-regression-harness'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
const lastFeed = () => callsTo('/signals', 'GET').at(-1)!
const row = () => screen.findByRole('button', { name: 'Ouvrir : Voirie' })

// Ports feed.test.tsx's business invariants. V11 deliberately uses server-only
// filtering, page replacement and CAS workflow rather than local filtering,
// flag-specific tables, concatenation or feedback-as-status mutations.
test('server counts label each segment and all repeats each authorized status in the request', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([SIGNAL], { counts: { new: 12, saved: 5, contacted: 3, ignored: 7 } }) } })
  renderFeed()
  await row()
  expect(lastFeed().search.getAll('status')).toEqual(['new'])
  for (const label of [/^Nouveaux\s+12$/, /^Sauvegardés\s+5$/, /^Contactés\s+3$/, /^Ignorés$/, /^Tous$/]) expect(screen.getByRole('tab', { name: label })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('tab', { name: /^Sauvegardés/ }))
  await waitFor(() => expect(lastFeed().search.getAll('status')).toEqual(['saved']))
  await userEvent.click(screen.getByRole('tab', { name: 'Tous' }))
  await waitFor(() => expect(lastFeed().search.getAll('status')).toEqual(['new', 'saved', 'contacted', 'ignored']))
})

test('query text is sent to the server and does not secretly filter the returned page', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([SIGNAL, item({ signal_id: 'second', company: { ...SIGNAL.company, name: 'Éolienne Sud SARL' } })]) } })
  renderFeed()
  await screen.findByText('Éolienne Sud SARL')
  await userEvent.type(screen.getByRole('searchbox', { name: 'Rechercher un signal' }), 'eolienne')
  await waitFor(() => expect(lastFeed().search.get('q')).toBe('eolienne'))
  expect(await screen.findByText('Éolienne Sud SARL')).toBeInTheDocument()
  expect(screen.getByText(SIGNAL.company.name!)).toBeInTheDocument()
  expect(lastFeed().search.get('view')).toBe('history')
})

test('pagination carries the cursor, replaces the current page, and can return to the first page', async () => {
  mockApi({ ...BASE, 'GET /signals': ({ search }) => ({ body: search.has('cursor')
    ? feedPage([item({ signal_id: 'second', company: { ...SIGNAL.company, name: 'Amiaud SARL' } })], { counts_available: false, page: { limit: 20, offset: 0, has_more: false, next_cursor: null, scan_truncated: false } })
    : feedPage([SIGNAL], { page: { limit: 20, offset: 0, has_more: true, next_cursor: 'cur1', scan_truncated: false } }) }) })
  renderFeed()
  await row()
  await userEvent.click(screen.getByRole('button', { name: 'Page suivante' }))
  expect(await screen.findByText('Amiaud SARL')).toBeInTheDocument()
  expect(screen.queryByText(SIGNAL.company.name!)).not.toBeInTheDocument()
  expect(lastFeed().search.get('cursor')).toBe('cur1')
  expect(screen.getAllByRole('article')).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Page suivante' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Première page' }))
  expect(await screen.findByText(SIGNAL.company.name!)).toBeInTheDocument()
  expect(lastFeed().search.has('cursor')).toBe(false)
})

test('count truncation is visibly qualified independently of next-page availability', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([SIGNAL], { counts_truncated: true, counts: { new: 12, saved: 5, contacted: 3, ignored: 0 }, page: { limit: 20, offset: 0, has_more: false, next_cursor: null, scan_truncated: false } }) } })
  renderFeed()
  await row()
  expect(screen.getByRole('tab', { name: /^Nouveaux\s+12\+$/ })).toBeInTheDocument()
  expect(screen.getByText('1 signal sur cette page')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Page suivante' })).not.toBeInTheDocument()
})

test('an incomplete provisional landing keeps real signals and adds one waiting row', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([SIGNAL], { provisional_profile: true, landing_cohort: { signal_id: SIGNAL.signal_id, expected: 3, materialized: 1 } }) } })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)

  expect(await screen.findByText('Vos prochains signaux arriveront ici')).toBeInTheDocument()
  expect(screen.getAllByText('Vos prochains signaux arriveront ici')).toHaveLength(1)
  expect(screen.getAllByRole('article')).toHaveLength(1)
})

test('a complete provisional landing has no waiting row', async () => {
  const items = [SIGNAL, item({ signal_id: 'second' }), item({ signal_id: 'third' })]
  mockApi({ ...BASE, 'GET /signals': { body: feedPage(items, { provisional_profile: true, landing_cohort: { signal_id: SIGNAL.signal_id, expected: 3, materialized: 3 } }) } })
  renderFeed()

  expect(await screen.findAllByRole('article')).toHaveLength(3)
  expect(screen.queryByText('Vos prochains signaux arriveront ici')).not.toBeInTheDocument()
})

test('a list failure is announced and retried explicitly', async () => {
  let failed = true
  mockApi({ ...BASE, 'GET /signals': () => failed ? { status: 500, body: { detail: 'unavailable' } } : { body: feedPage([SIGNAL]) } })
  renderFeed()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Vos signaux ne sont pas chargés')
  failed = false
  await userEvent.click(within(alert).getByRole('button', { name: 'Réessayer' }))
  await row()
  expect(callsTo('/signals', 'GET')).toHaveLength(2)
})

test('an empty new segment guides the user to saved signals', async () => {
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([]) } })
  renderFeed()
  expect(await screen.findByRole('heading', { name: 'Vous êtes à jour' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Voir les sauvegardés' }))
  await waitFor(() => expect(lastFeed().search.getAll('status')).toEqual(['saved']))
  expect(await screen.findByRole('heading', { name: 'Aucun signal dans cette sélection' })).toBeInTheDocument()
})

test('a successful detail workflow refreshes the list and server global counts', async () => {
  let saved = false
  mockApi({ ...BASE,
    'GET /signals': () => ({ body: feedPage(saved ? [] : [SIGNAL], { counts: { new: saved ? 3 : 4, saved: saved ? 2 : 1, contacted: 0, ignored: 0 } }) }),
    [`GET /signals/${SIGNAL.signal_id}`]: () => ({ body: { ...DETAIL, status: saved ? 'saved' : 'new', status_revision: saved ? 5 : 4 } }),
    [`PUT /signals/${SIGNAL.signal_id}/status`]: () => { saved = true; return { body: workflow('saved') } },
  })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1`)
  const dialog = await screen.findByRole('dialog', { name: 'Détail du signal' })
  await within(dialog).findByRole('heading', { name: 'Voirie' })
  await userEvent.click(within(dialog).getByRole('button', { name: 'Sauvegarder' }))
  expect(await screen.findByRole('tab', { name: /^Nouveaux\s+3$/ })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: /^Sauvegardés\s+2$/ })).toBeInTheDocument()
  expect(screen.queryByRole('article')).not.toBeInTheDocument()
  expect(within(dialog).getByRole('button', { name: 'Retirer des sauvegardés' })).toBeInTheDocument()
})
