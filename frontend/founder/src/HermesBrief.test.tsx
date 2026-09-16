import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HermesBrief } from './HermesBrief'
import type {
  ChiefOfStaffStatus,
  FounderChiefOfStaffLatest,
  FounderChiefOfStaffView,
} from './types'

function available(status: ChiefOfStaffStatus = 'WATCH'): FounderChiefOfStaffView {
  const payload: FounderChiefOfStaffLatest = {
    version: 'founder-chief-of-staff-latest-v1',
    state: 'AVAILABLE',
    stale: false,
    captured_at: '2026-09-15T05:30:00Z',
    model_route: 'anthropic/claude-sonnet-4.6',
    usage_metadata: { input_tokens: 800, output_tokens: 120 },
    estimated_cost: '0.02',
    actual_cost: '0.008',
    facts: [
      {
        fact_ref: 'fact:business:mrr:chf', domain: 'BUSINESS', metric_key: 'weekly_mrr_minor_units',
        value: 12345, unit: 'MINOR_UNITS', currency: 'CHF', period_start: '2026-09-07T22:00:00Z',
        period_end: '2026-09-14T22:00:00Z', captured_at: '2026-09-15T05:30:00Z',
        source_contract: 'WeeklyCommercialCockpit', source_version: 'v1', data_status: 'KNOWN',
      },
      {
        fact_ref: 'fact:business:mrr:eur', domain: 'BUSINESS', metric_key: 'weekly_mrr_minor_units',
        value: 6700, unit: 'MINOR_UNITS', currency: 'EUR', period_start: '2026-09-07T22:00:00Z',
        period_end: '2026-09-14T22:00:00Z', captured_at: '2026-09-15T05:30:00Z',
        source_contract: 'WeeklyCommercialCockpit', source_version: 'v1', data_status: 'KNOWN',
      },
      {
        fact_ref: 'fact:data:m2:unknown', domain: 'DATA', metric_key: 'retained_m2_mrr_minor_units',
        value: null, unit: 'MINOR_UNITS', currency: null, period_start: '2026-09-07T22:00:00Z',
        period_end: '2026-09-14T22:00:00Z', captured_at: '2026-09-15T05:30:00Z',
        source_contract: 'WedgeM2Efficiency', source_version: 'v1', data_status: 'INSUFFICIENT_EVIDENCE',
      },
    ],
    report: {
      report_version: 'chief-of-staff-report-v1', report_ref: 'report:daily:fixture',
      context_fingerprint: 'a'.repeat(64), cadence: 'DAILY', period_start: '2026-09-14T00:00:00+02:00',
      period_end: '2026-09-15T00:00:00+02:00', created_at: '2026-09-15T05:30:00Z',
      executive_status: status, executive_summary: 'La situation demande une surveillance humaine.',
      reason_codes: ['BUSINESS_WATCH'], confidence: '0.8', supervisor_version: 'hermes-agent-0.20.4',
      profile_version: '1.1.0', source_refs: ['fact:business:mrr:chf', 'fact:business:mrr:eur', 'fact:data:m2:unknown'],
      observations: [{
        observation_id: 'observation:currency', domain: 'BUSINESS', kind: 'STATUS',
        summary: 'Les revenus sont établis dans deux devises distinctes.',
        impact: 'Aucune consolidation entre devises ne doit être faite.',
        reason_codes: ['CURRENCIES_SEPARATE'], fact_refs: ['fact:business:mrr:chf', 'fact:business:mrr:eur'], confidence: '0.9',
      }],
      priorities: [1, 2, 3, 4].map((priority) => ({
        priority, owner: 'FOUNDER' as const, recommended_action: `Examiner la priorité ${['une', 'deux', 'trois', 'quatre'][priority - 1]}.`,
        reason_codes: ['HUMAN_REVIEW_REQUIRED'], fact_refs: ['fact:business:mrr:chf'], approval_required: true,
      })),
      decision_requests: [{
        decision_id: 'decision:focus', owner: 'FOUNDER', question: 'Faut-il conserver le focus actuel ?',
        reason_codes: ['FOUNDER_DECISION_REQUIRED'], fact_refs: ['fact:business:mrr:chf'], human_decision_required: true,
      }],
      unknowns: [{
        unknown_id: 'unknown:m2', domain: 'DATA', summary: 'Les preuves de rétention sont insuffisantes.',
        reason_codes: ['INSUFFICIENT_M2_EVIDENCE'], fact_refs: ['fact:data:m2:unknown'],
      }],
    },
  }
  return { kind: 'available', data: payload as Extract<FounderChiefOfStaffView, { kind: 'available' }>['data'] }
}

describe('HermesBrief', () => {
  it.each([
    ['HEALTHY', 'Sain'],
    ['WATCH', 'À surveiller'],
    ['CRITICAL', 'Critique'],
    ['UNKNOWN', 'Inconnu'],
  ] as const)('affiche le statut %s en français', (status, label) => {
    render(<HermesBrief view={available(status)} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('affiche le rapport sourcé, borne les priorités et sépare CHF et EUR', () => {
    render(<HermesBrief view={available()} />)
    expect(screen.getByRole('heading', { name: 'Brief d’Hermes' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Points clés' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Décisions demandées' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Inconnues et preuves insuffisantes' })).toBeInTheDocument()
    const priorities = screen.getByRole('heading', { name: 'Priorités recommandées' }).closest('section')
    expect(within(priorities!).getAllByRole('listitem')).toHaveLength(6)
    expect(priorities).toHaveTextContent('priorité trois')
    expect(priorities).not.toHaveTextContent('priorité quatre')
    const evidence = screen.getByText(/Preuves citées/).closest('details')
    expect(evidence).toHaveTextContent(/123[.,]45.*CHF/)
    expect(evidence).toHaveTextContent(/67[.,]00.*EUR/)
    expect(evidence).toHaveTextContent('Valeur inconnue')
    expect(screen.queryByRole('button', { name: /exécuter|approuver|envoyer/i })).not.toBeInTheDocument()
    expect(screen.getAllByText(/recommandation non exécutée/)).toHaveLength(3)
  })

  it('affiche les états vide, indisponible, périmé et actualisation', () => {
    const { rerender } = render(<HermesBrief view={{ kind: 'empty' }} />)
    expect(screen.getByText('Aucun brief disponible')).toBeInTheDocument()
    rerender(<HermesBrief view={{ kind: 'unavailable' }} />)
    expect(screen.getByText('Brief momentanément indisponible')).toBeInTheDocument()
    const stale = available()
    if (stale.kind === 'available') stale.data.stale = true
    rerender(<HermesBrief view={stale} refreshing />)
    expect(screen.getByText('Rapport périmé')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Brief d’Hermes' })).toHaveAttribute('aria-busy', 'true')
  })
})
