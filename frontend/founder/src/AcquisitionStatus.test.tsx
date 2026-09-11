import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest'
import { AcquisitionStatus } from './AcquisitionStatus'
import { loadFounderOverview } from './api'
import type {
  FounderAcquisitionStatus,
  FounderCommercialTunnel,
  FounderCountFacet,
  FounderDirectoryRow,
  FounderOverview,
  FounderProspection,
  FounderTunnelCounts,
  FounderTunnelCurrent,
  FounderTunnelPeriod,
  FounderTunnelSlice,
} from './types'

const STOPPED_STATUS: FounderAcquisitionStatus = {
  mode: 'SHADOW',
  activity: 'STOPPED',
  activity_since: '2026-09-11T07:00:00Z',
  last_cycle_ref: 'cycle-2026-09-11',
  last_cycle_at: '2026-09-11T06:30:00Z',
  last_cycle_status: 'SUPPRESSED',
  last_cycle_reason_code: 'NO_ELIGIBLE_OPPORTUNITY',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AcquisitionStatus', () => {
  it('rend le mode, la date d’arrêt et le dernier résultat en français', () => {
    render(<AcquisitionStatus status={STOPPED_STATUS} />)

    const status = screen.getByRole('region', { name: 'État de l’acquisition' })
    expect(within(status).getByText('Mode observation')).toBeInTheDocument()
    expect(within(status).getByText(/Arrêté depuis le 11 sept\. 2026/)).toBeInTheDocument()
    expect(within(status).getByText(/cycle-2026-09-11.*11 sept\. 2026/)).toBeInTheDocument()
    expect(
      within(status).getByText('Supprimé · Aucune opportunité éligible'),
    ).toBeInTheDocument()
  })

  it('rend une activité active avec sa date de début', () => {
    render(
      <AcquisitionStatus
        status={{ ...STOPPED_STATUS, activity: 'RUNNING', activity_since: '2026-09-11T07:00:00Z' }}
      />,
    )

    expect(screen.getByText(/Actif depuis le 11 sept\. 2026/)).toBeInTheDocument()
  })

  it('ne confond pas un état inconnu avec un arrêt', () => {
    render(
      <AcquisitionStatus
        status={{ ...STOPPED_STATUS, activity: 'UNKNOWN', activity_since: null }}
      />,
    )

    expect(screen.getByText('État indisponible')).toBeInTheDocument()
    expect(screen.queryByText(/Arrêté depuis/)).not.toBeInTheDocument()
  })

  it.each([
    ['SUCCEEDED', 'Réussi'],
    ['FAILED', 'Échoué'],
  ])('traduit le résultat %s', (lastCycleStatus, expected) => {
    render(
      <AcquisitionStatus
        status={{ ...STOPPED_STATUS, last_cycle_status: lastCycleStatus, last_cycle_reason_code: null }}
      />,
    )

    expect(screen.getByText(`${expected} · Aucun motif signalé`)).toBeInTheDocument()
  })

  it('garde un motif inconnu lisible sans exposer son code brut', () => {
    render(
      <AcquisitionStatus
        status={{ ...STOPPED_STATUS, last_cycle_reason_code: 'NEW_RUNTIME_REASON' }}
      />,
    )

    expect(screen.getByText('Supprimé · Motif non répertorié')).toBeInTheDocument()
    expect(screen.queryByText(/NEW_RUNTIME_REASON/)).not.toBeInTheDocument()
  })

  it('explicite chaque donnée de cycle absente', () => {
    render(
      <AcquisitionStatus
        compact
        status={{
          mode: null,
          activity: 'STOPPED',
          activity_since: null,
          last_cycle_ref: null,
          last_cycle_at: null,
          last_cycle_status: null,
          last_cycle_reason_code: null,
        }}
      />,
    )

    const status = screen.getByRole('region', { name: 'État de l’acquisition' })
    expect(status).toHaveClass('control-runtime--compact')
    expect(within(status).getByText('Mode inconnu')).toBeInTheDocument()
    expect(within(status).getByText('Arrêté · date de début indisponible')).toBeInTheDocument()
    expect(within(status).getByText('Aucun cycle observé')).toBeInTheDocument()
    expect(within(status).getByText('Aucun résultat observé')).toBeInTheDocument()
  })

  it('ramène les quatre faits sur une colonne étroite', () => {
    const styles = readFileSync(resolve(process.cwd(), 'founder/src/styles.css'), 'utf8')

    expect(styles).toMatch(
      /@media \(max-width: 520px\) \{[\s\S]*?\.control-runtime(?:,| \{)[\s\S]*?grid-template-columns: 1fr;/,
    )
  })
})

describe('contrats Founder du tunnel commercial', () => {
  it('conserve les formes exactes de la période, de la cohorte et de la situation courante', () => {
    expectTypeOf<FounderTunnelPeriod>().toEqualTypeOf<'today' | 'last_7_days'>()
    expectTypeOf<FounderCommercialTunnel['period']>().toEqualTypeOf<FounderTunnelSlice>()
    expectTypeOf<FounderCommercialTunnel['cohort']>().toEqualTypeOf<FounderTunnelSlice>()
    expectTypeOf<FounderTunnelSlice>().toMatchTypeOf<FounderTunnelCounts>()
    expectTypeOf<FounderCommercialTunnel['current']>().toEqualTypeOf<FounderTunnelCurrent>()
    expectTypeOf<FounderOverview['acquisition_status']>().toEqualTypeOf<FounderAcquisitionStatus>()
    expectTypeOf<FounderOverview['commercial_tunnel']>().toEqualTypeOf<FounderCommercialTunnel>()
    expectTypeOf<FounderProspection['acquisition_status']>().toEqualTypeOf<FounderAcquisitionStatus>()
    expectTypeOf<FounderCountFacet['label']>().toEqualTypeOf<string>()
    expectTypeOf<FounderDirectoryRow['department_name']>().toEqualTypeOf<string | null>()
  })
})

describe('loadFounderOverview', () => {
  it('encode la semaine et la période avec la future signature', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await loadFounderOverview(3, 'today', controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/founder/overview?week_offset=3&period=today',
      expect.objectContaining({ signal: controller.signal }),
    )
  })

  it('garde l’appel courant compatible en choisissant les sept derniers jours', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await loadFounderOverview(0, controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/founder/overview?week_offset=0&period=last_7_days',
      expect.objectContaining({ signal: controller.signal }),
    )
  })
})
