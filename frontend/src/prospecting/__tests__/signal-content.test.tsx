import { fireEvent, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { AUTHENTICATED, renderApp, UNLOCKED_ITEM } from '../../test/harness'
import { HolderSummary } from '../components/HolderSummary'
import { SignalContent } from '../components/SignalContent'
import { DetailFrame } from '../components/DetailFrame'
import type { NoticeFacts } from '../models'

const facts: NoticeFacts = {
  source_system: 'BOAMP', source_notice_id: '26-123', source_url: 'https://www.boamp.fr/avis/26-123',
  collected_at: '2026-09-13T10:00:00Z', publication_date: '2026-09-12', lot_identifier: 'LOT-0001',
  title: 'Ouvrages de génie civil', description: null, awarded_amount: { value: '1492999', currency: 'EUR' },
  minimum_amount: null, maximum_amount: null,
  calendar: { duration: { value: '18', unit: 'MONTH', scope: 'works', period_kind: 'unspecified', source_path: 'lot.duration' }, initial_duration: null, maximum_duration: null, renewals: null },
  buyers: [{ name: 'Métropole Nice Côte d’Azur' }], contacts: [], available_contact_fields: [], contacts_locked: false, notice_status: 'published',
}

test('signal gives buyer once, factual calendar, selected-offer reason and notes without an approach panel', () => {
  renderApp(<SignalContent item={{ ...UNLOCKED_ITEM, notice_facts: facts, commercial_context: { reason: 'Votre offre de matériaux correspond aux ouvrages béton de ce marché.', offer_category: 'materials_and_components' } }} holder={<div>Titulaire</div>} notes={<textarea aria-label="Vos notes" />} />, { session: AUTHENTICATED })
  expect(screen.getAllByText('Métropole Nice Côte d’Azur')).toHaveLength(1)
  expect(screen.getByText('18 mois')).toBeInTheDocument()
  expect(screen.getByText(/Attribué le/)).toHaveTextContent('4 août 2026')
  expect(screen.queryByText(/BOAMP publié le/)).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Pourquoi ça vous concerne' })).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Vos notes' })).toBeInTheDocument()
  expect(screen.queryByText(/idée d’approche|Hypothèse|probable en/i)).not.toBeInTheDocument()
})

test('known holder contacts replace the missing-contact guide and company name is a company route link', () => {
  const contact = { organization_name: 'Constructions Bertrand SA', organization_ref: 'ORG-1', source: 'boamp' as const, observed_at: '2026-09-12', phone: '0492000000', email: 'agence@example.com', website: 'https://example.com' }
  renderApp(<HolderSummary name="Constructions Bertrand SA" href="/app/companies/cmp_1" contacts={[contact]} />, { session: AUTHENTICATED })
  expect(screen.getByRole('link', { name: 'Constructions Bertrand SA' })).toHaveAttribute('href', '/app/companies/cmp_1')
  expect(screen.getByRole('link', { name: '0492000000' })).toHaveAttribute('href', 'tel:0492000000')
  expect(screen.queryByRole('heading', { name: 'Trouver le bon interlocuteur' })).not.toBeInTheDocument()
  expect(screen.queryByText(/indisponible/i)).not.toBeInTheDocument()
})

test('duplicate source contacts share one action while distinct agencies retain their attribution', () => {
  const contact = { organization_name: 'Agence Nice', organization_ref: 'ORG-1', identifiers: [{ scheme: 'SIRET', value: '56213603600885' }], source: 'boamp' as const, source_notice_id: '26-123', observed_at: '2026-09-13', email: 'agence@artisan.fr' }
  renderApp(<HolderSummary name="Entreprise" contacts={[contact, { ...contact, source_notice_id: '26-124' }, { ...contact, organization_name: 'Agence Lyon', identifiers: [{ scheme: 'SIRET', value: '56213603600018' }] }]} />, { session: AUTHENTICATED })
  expect(screen.getAllByRole('link', { name: 'agence@artisan.fr' })).toHaveLength(2)
  expect(screen.getByText('Agence Nice')).toBeInTheDocument()
  expect(screen.getByText('Agence Lyon')).toBeInTheDocument()
})

test('unknown holder guides the next action, and locked values are placeholders only', () => {
  const open = vi.fn()
  const { rerender } = renderApp(<HolderSummary name="GJG FONCIERE" href="/app/companies/cmp_2" onOpenCompany={open} />, { session: AUTHENTICATED })
  expect(screen.getByRole('heading', { name: 'Trouver le bon interlocuteur' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Compléter la fiche entreprise' }))
  expect(open).toHaveBeenCalledOnce()
  // Separate mounted view keeps the normal providers provided by renderApp.
  rerender(<div />)
  renderApp(<HolderSummary name="GJG FONCIERE" href="/app/companies/cmp_2" lockedFields={['phone', 'workforce']} lockedMessage="Comme pour Démo Bâtiment : dirigeant, téléphone, e-mail, historique des marchés." onUpgrade={open} />, { session: AUTHENTICATED })
  expect(screen.getByText('Comme pour Démo Bâtiment : dirigeant, téléphone, e-mail, historique des marchés.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Voir ce contact — 49 €/mois' })).toBeInTheDocument()
  expect(screen.queryByText('0492000000')).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Trouver le bon interlocuteur' })).not.toBeInTheDocument()
})

test('complete landing demo displays the public director and contact data', () => {
  renderApp(<HolderSummary name="Titulaire Démonstration" directory={{ siren: '562136036', name: 'Titulaire Démonstration', source: 'registre', removal_path: '/contact', fields_locked: false, available_fields: ['directors', 'phone', 'email', 'website'], director_display_name: 'Anna Egli', director_display_title: 'Présidente', phone: '04 76 00 00 00', published_email: 'contact@egli.example', website_url: 'https://egli.example/' }} />, { session: AUTHENTICATED })
  expect(screen.getByText(/Anna Egli/)).toHaveTextContent('Dirigeant : Anna Egli · Présidente')
  expect(screen.getByRole('link', { name: '04 76 00 00 00' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'contact@egli.example' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /offres/i })).not.toBeInTheDocument()
})

test('temporary landing access shows the bait contact without actionable or selectable values', () => {
  const claim = vi.fn()
  renderApp(<HolderSummary name="Titulaire Démonstration" claimRequired onClaimAccess={claim} directory={{ siren: '562136036', name: 'Titulaire Démonstration', source: 'registre', removal_path: '/contact', fields_locked: false, available_fields: ['directors', 'phone', 'email', 'website'], director_display_name: 'Anna Egli', director_display_title: 'Présidente', phone: '04 76 00 00 00', published_email: 'contact@egli.example', website_url: 'https://egli.example/' }} />, { session: AUTHENTICATED })

  expect(screen.getByText('04 76 00 00 00')).toBeInTheDocument()
  expect(screen.getByText('contact@egli.example')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '04 76 00 00 00' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'contact@egli.example' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /egli\.example/ })).not.toBeInTheDocument()
  expect(screen.getByText('contact@egli.example').closest('[data-contact-claim-required="true"]')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Créer mon accès pour appeler' }))
  expect(claim).toHaveBeenCalledOnce()
})

test('complete landing demo shows its public history and a qualified fallback calendar', () => {
  renderApp(<SignalContent item={{
    ...UNLOCKED_ITEM,
    landing_demo: true,
    notice_facts: null,
    contract: { ...UNLOCKED_ITEM.contract, dates: { award: null, contract_notification: null, publication: '2026-09-03' } },
    holder_history: {
      resolution: 'company_key', source: 'public_awards',
      last_12_months: { awards_count: 3, total_amounts: [{ value: '1490000', currency: 'EUR' }], recurring_buyers: ['Commune de Blois'] },
      summary: { consortium_share: '0.0' },
    },
  }} holder={null} notes={null} />, { session: AUTHENTICATED })
  expect(screen.getByRole('heading', { name: 'Calendrier' })).toBeInTheDocument()
  expect(screen.getByText(/Publié le/)).toHaveTextContent('3 septembre 2026')
  expect(screen.getByRole('heading', { name: 'Historique des marchés' })).toBeInTheDocument()
  expect(screen.getByText(/3 marchés attribués/)).toBeInTheDocument()
  expect(screen.getByText(/1,5 M€/)).toBeInTheDocument()
  expect(screen.getByText(/Commune de Blois/)).toBeInTheDocument()
})

test('detail frame labels its modal and closes using its single close control', () => {
  const close = vi.fn()
  renderApp(<DetailFrame title="Détail du signal" onClose={close}><p>Détail</p></DetailFrame>, { session: AUTHENTICATED })
  expect(screen.getByRole('dialog', { name: 'Détail du signal' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Fermer' }))
  expect(close).toHaveBeenCalledOnce()
})

test.each([undefined, 'javascript:alert(1)'])('qualifies a consultation duration even when its source URL is unavailable or unsafe (%s)', (sourceUrl) => {
  const duration = { ...facts.calendar!.duration!, notice_kind: 'contract_notice' as const, source_notice_id: '25-prior', source_url: sourceUrl }
  renderApp(<SignalContent item={{ ...UNLOCKED_ITEM, notice_facts: { ...facts, calendar: { ...facts.calendar!, duration } } }} holder={null} notes={null} />, { session: AUTHENTICATED })
  expect(screen.getByText(/selon l’avis de consultation/i)).toBeInTheDocument()
  expect(screen.getByText(/25-prior/)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /25-prior/ })).not.toBeInTheDocument()
})

test('links the qualified duration to its own consultation source when a safe URL is present', () => {
  const duration = { ...facts.calendar!.duration!, notice_kind: 'contract_notice' as const, source_notice_id: '25-prior', source_url: 'https://www.boamp.fr/avis/25-prior' }
  renderApp(<SignalContent item={{ ...UNLOCKED_ITEM, notice_facts: { ...facts, calendar: { ...facts.calendar!, duration } } }} holder={null} notes={null} />, { session: AUTHENTICATED })
  expect(screen.getByText(/selon l’avis de consultation/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /25-prior/ })).toHaveAttribute('href', duration.source_url)
})
