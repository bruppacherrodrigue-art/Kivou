import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { callsTo, feedPage, mockApi } from '../../test/harness'
import { BASE, SIGNAL, renderFeed } from './signal-regression-harness'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

test('closing an email artifact then opening another signal never reuses the first artifact', async () => {
  const oldArtifact = 'a'.repeat(64)
  const newArtifact = 'b'.repeat(64)
  const other = { ...SIGNAL, signal_id: 'signal-other', presentation: { ...SIGNAL.presentation!, artifact_id: newArtifact }, contract: { ...SIGNAL.contract, lot_title: null, title: 'Autre marché' }, factual_display: { ...SIGNAL.factual_display, object_short: 'Autre marché' } }
  mockApi({ ...BASE, 'GET /signals': { body: feedPage([other]) }, 'GET /signals/signal-other': { body: { ...other, company_key: null } }, 'GET /signals/signal-other/note': { body: { note: null, revision: 0, updated_at: null } } })
  renderFeed(`/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1&presentation_artifact_id=${oldArtifact}&status=saved`)
  const drawer = await screen.findByRole('dialog', { name: 'Détail du signal' })
  await within(drawer).findByRole('heading', { name: 'Voirie' })
  await userEvent.click(within(drawer).getByRole('button', { name: 'Fermer' }))
  expect(screen.getByTestId('signal-location')).not.toHaveTextContent(oldArtifact)
  await userEvent.click(await screen.findByRole('button', { name: 'Ouvrir : Autre marché' }))
  await waitFor(() => expect(callsTo('/signals/signal-other', 'GET')).toHaveLength(1))
  expect(callsTo('/signals/signal-other', 'GET')[0].search.get('presentation_artifact_id')).toBe(newArtifact)
  expect(screen.getByTestId('signal-location')).toHaveTextContent('status=saved')
})
