import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppRoutes } from '../App'
import type { CompanyProfile, UnlockedDetail } from '../api/types'
import { SignalDetail } from '../pages/SignalDetail'
import { ReferenceSignalDetail } from '../reference/dashboard/ReferenceSignalDetail'
import { toSignalDetailView } from '../reference/dashboard/adapters'
import {
  AUTHENTICATED,
  CATALOGUE,
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  fullPresentation,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const noop = () => undefined

function detailFixture(overrides: Partial<UnlockedDetail> = {}): UnlockedDetail {
  return { ...UNLOCKED_DETAIL, ...overrides }
}

function renderDetail({
  detail = UNLOCKED_DETAIL,
  profile = COMPANY_PROFILE,
  loading = false,
  error = null,
  companyLoading = false,
  companyError = null,
  onRetry = noop,
  onRetryCompany = noop,
}: {
  detail?: UnlockedDetail
  profile?: CompanyProfile | null
  loading?: boolean
  error?: unknown | null
  companyLoading?: boolean
  companyError?: unknown | null
  onRetry?: () => void
  onRetryCompany?: () => void
} = {}) {
  return renderApp(
    <ReferenceSignalDetail
      detail={loading || error ? null : toSignalDetailView(detail)}
      loading={loading}
      error={error}
      onRetry={onRetry}
      note=""
      noteState="idle"
      noteError={null}
      onNoteChange={noop}
      onNoteBlur={noop}
      onRetryNote={noop}
      companyProfile={profile}
      companyLoading={companyLoading}
      companyError={companyError}
      onRetryCompany={onRetryCompany}
    />,
    { session: AUTHENTICATED },
  )
}

function appRoutes(detail: unknown = UNLOCKED_DETAIL, profile: unknown = COMPANY_PROFILE) {
  return {
    'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: detail },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    [`GET /companies/${UNLOCKED_ITEM.company_key}`]: { body: profile },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /target-icps': { body: [ICP] },
  }
}

describe('détail factuel d’un signal', () => {
  it('met l’entreprise et le marché au premier plan sans identifiant administratif', () => {
    renderDetail()

    expect(screen.getByRole('heading', { level: 2, name: /Constructions Bertrand SA remporte un marché/ })).toBeVisible()
    expect(screen.getAllByText('Réfection de la voirie communale — lot 2').length).toBeGreaterThan(0)
    expect(screen.queryByRole('heading', { name: /12345678900011/ })).toBeNull()
    expect(screen.getByText(/Analyse commerciale non disponible/)).toBeVisible()
  })

  it('respecte la hiérarchie entreprise, résumé, faits, fiche, historique, preuves et manques', () => {
    renderDetail()

    const title = screen.getByRole('heading', { level: 2 })
    const facts = screen.getByRole('heading', { name: 'Détails du marché' })
    const company = screen.getByRole('heading', { name: COMPANY_PROFILE.official_identity.name })
    const history = screen.getByRole('heading', { name: 'Historique des attributions dans Kivou' })
    const evidence = screen.getByRole('heading', { name: 'Source officielle et preuves' })
    const missing = screen.getByRole('heading', { name: 'Données manquantes ou à confirmer' })
    const follows = (left: Element, right: Element) => Boolean(
      left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING,
    )
    expect(follows(title, facts)).toBe(true)
    expect(follows(facts, company)).toBe(true)
    expect(follows(company, history)).toBe(true)
    expect(follows(history, evidence)).toBe(true)
    expect(follows(evidence, missing)).toBe(true)
  })

  it('n’affiche aucune analyse, personne, urgence, cible ou recommandation héritée', () => {
    const presentation = fullPresentation()
    renderDetail({
      detail: detailFixture({
        presentation,
        event: {
          ...UNLOCKED_DETAIL.event,
          headline: 'URGENT — appeler Jean Dupont',
          why_now: 'Contacter le directeur des achats immédiatement',
        },
        analysis: {
          ...UNLOCKED_DETAIL.analysis,
          plausible_needs: {
            ...UNLOCKED_DETAIL.analysis.plausible_needs,
            items: [{
              ...UNLOCKED_DETAIL.analysis.plausible_needs.items[0],
              statement: 'BESOIN COMMERCIAL INVENTÉ',
            }],
          },
        },
      }),
    })

    const text = document.body.textContent ?? ''
    for (const forbidden of [
      presentation.content.headline,
      'Jean Dupont',
      'directeur des achats',
      'BESOIN COMMERCIAL INVENTÉ',
      presentation.content.recommended_action,
    ]) expect(text).not.toContain(forbidden)
  })

  it.each([
    ['award', "Date d’attribution"],
    ['notification', 'Date de notification'],
    ['publication', 'Date de publication'],
  ] as const)('conserve la sémantique de date %s publiée par le serveur', (kind, label) => {
    renderDetail({
      detail: detailFixture({
        factual_display: {
          ...UNLOCKED_DETAIL.factual_display,
          date: { value: '2026-08-15', kind },
        },
      }),
    })

    const facts = screen.getByRole('heading', { name: 'Détails du marché' }).closest('section')!
    expect(within(facts).getByText(label)).toBeVisible()
    expect(facts).toHaveTextContent('15 août 2026')
    if (kind === 'publication') expect(within(facts).queryByText("Date d’attribution")).toBeNull()
  })

  it('distingue sans ambiguïté entreprise gagnante et acheteur', () => {
    renderDetail()

    expect(screen.getAllByText('Constructions Bertrand SA').length).toBeGreaterThan(0)
    const facts = screen.getByRole('heading', { name: 'Détails du marché' }).closest('section')!
    expect(within(facts).getByText('Acheteur')).toBeVisible()
    expect(within(facts).getByText('Commune de Villeneuve')).toBeVisible()
  })

  it('relègue les identifiants et le titre administratif dans la section repliée', () => {
    renderDetail()

    const disclosure = screen.getByText('Sources et vérification').closest('details')!
    expect(disclosure).not.toHaveAttribute('open')
    expect(within(disclosure).getByText(/SIRET 12345678900011/)).toBeInTheDocument()
    expect(within(disclosure).getByText('Réfection de la voirie communale — lot 2')).toBeInTheDocument()
  })

  it('affiche les preuves publiques et uniquement les liens HTTPS sûrs', () => {
    renderDetail()

    const evidence = screen.getByRole('heading', { name: 'Source officielle et preuves' }).closest('section')!
    expect(within(evidence).getByText('Le marché est attribué à Constructions Bertrand SA.')).toBeVisible()
    expect(within(evidence).getAllByRole('link', { name: /Ouvrir l’avis/ })[0]).toHaveAttribute(
      'href',
      'https://www.boamp.fr/avis/26-104412',
    )
  })

  it('refuse les URL source et site non HTTPS', () => {
    const detail = detailFixture({
      source: { ...UNLOCKED_DETAIL.source, url: 'http://unsafe.example/notice' },
      evidence: {
        ...UNLOCKED_DETAIL.evidence,
        public_facts: UNLOCKED_DETAIL.evidence.public_facts.map((group) => ({
          ...group,
          items: group.items.map((item) => ({ ...item, url: 'javascript:alert(1)' })),
        })),
      },
    })
    const profile: CompanyProfile = {
      ...COMPANY_PROFILE,
      official_identity: { ...COMPANY_PROFILE.official_identity, website_url: 'http://unsafe.example' },
    }
    renderDetail({ detail, profile })

    expect(screen.queryByRole('link', { name: /unsafe\.example/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /Ouvrir l’avis/ })).toBeNull()
  })

  it('rend la fiche entreprise enrichie et sa provenance factuelle', () => {
    renderDetail()

    const company = screen.getByRole('heading', { name: COMPANY_PROFILE.official_identity.name }).closest('section')!
    expect(company).toHaveTextContent(COMPANY_PROFILE.official_identity.address!)
    expect(within(company).getByRole('link', { name: /constructions-bertrand/ })).toHaveAttribute(
      'href',
      COMPANY_PROFILE.official_identity.website_url,
    )
    expect(company).toHaveTextContent('23 août 2026')
    expect(screen.getByText('Faits vérifiés')).toBeVisible()
  })

  it('affiche l’historique Kivou de la gagnante sans besoin commercial', () => {
    const previous: CompanyProfile['related_signals'][number] = {
      ...COMPANY_PROFILE.related_signals[0],
      signal_id: 'sig_previous_award',
      contract_title: 'Ancienne attribution documentée',
      event: { ...COMPANY_PROFILE.related_signals[0].event, date: '2024-02-03' },
    }
    renderDetail({ profile: { ...COMPANY_PROFILE, related_signals: [COMPANY_PROFILE.related_signals[0], previous] } })

    const link = screen.getByRole('link', { name: 'Ancienne attribution documentée' })
    expect(link).toHaveAttribute('href', '/app/signals/sig_previous_award')
    expect(link.closest('li')).toHaveTextContent('3 février 2024')
    expect(document.body).not.toHaveTextContent(previous.plausible_needs[0].statement!)
  })

  it.each([
    ['pending', 'Enrichissement en attente', 'La fiche entreprise attend son enrichissement factuel.'],
    ['in_progress', 'Enrichissement en cours', 'L’enrichissement factuel de l’entreprise est en cours.'],
    ['failed', 'À vérifier', 'L’enrichissement factuel n’a pas abouti.'],
  ] as const)('rend honnêtement l’état d’enrichissement %s', (status, badge, message) => {
    renderDetail({
      detail: detailFixture({
        winner_enrichment: {
          ...UNLOCKED_DETAIL.winner_enrichment,
          status,
          error_code: status === 'failed' ? 'winner_identity_unresolved' : null,
          last_verified_at: null,
        },
      }),
      profile: null,
    })

    expect(screen.getByText(badge)).toBeVisible()
    expect(screen.getByText(new RegExp(message))).toBeVisible()
  })

  it('rend un enrichissement partiel avec les champs manquants explicites', () => {
    renderDetail({
      detail: detailFixture({
        winner_enrichment: {
          ...UNLOCKED_DETAIL.winner_enrichment,
          status: 'partial',
          missing_fields: ['address', 'website'],
          last_verified_at: '2026-08-18T09:00:00Z',
        },
      }),
      profile: {
        ...COMPANY_PROFILE,
        official_identity: {
          ...COMPANY_PROFILE.official_identity,
          address: null,
          website_url: null,
        },
      },
    })

    expect(screen.getByText('Données partielles')).toBeVisible()
    const missing = screen.getByRole('heading', { name: 'Données manquantes ou à confirmer' }).closest('section')!
    expect(missing).toHaveTextContent('Adresse')
    expect(missing).toHaveTextContent('Site officiel')
  })

  it('distingue une fiche entreprise en chargement du détail déjà disponible', () => {
    renderDetail({ profile: null, companyLoading: true })

    expect(screen.getByRole('heading', { level: 2, name: /Constructions Bertrand/ })).toBeVisible()
    expect(screen.getByText('Chargement de la fiche factuelle de l’entreprise…')).toHaveAttribute('role', 'status')
  })

  it('rend l’échec entreprise récupérable sans masquer les faits du marché', async () => {
    const user = userEvent.setup()
    const retry = vi.fn()
    renderDetail({ profile: null, companyError: new Error('unavailable'), onRetryCompany: retry })

    expect(screen.getByText('Commune de Villeneuve')).toBeVisible()
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('La fiche factuelle complète')
    await user.click(within(alert).getByRole('button', { name: 'Réessayer' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('affiche les absences de montant et de lieu sans les inventer', () => {
    renderDetail({
      detail: detailFixture({
        contract: { ...UNLOCKED_DETAIL.contract, amount: null, location: null },
        factual_display: {
          ...UNLOCKED_DETAIL.factual_display,
          headline: 'Constructions Bertrand SA remporte « Réfection de la voirie »',
          missing_fields: ['amount', 'location'],
          completeness: 'partial',
        },
      }),
    })

    const facts = screen.getByRole('heading', { name: 'Détails du marché' }).closest('section')!
    expect(within(facts).getAllByText('Non publié')).toHaveLength(2)
    expect(screen.getByText('Données partielles')).toBeVisible()
  })

  it('n’invente rien quand le contrat factuel est invalide', () => {
    const malformed = detailFixture({
      factual_display: {
        ...UNLOCKED_DETAIL.factual_display,
        headline: 'CONTENU INVALIDE À NE PAS AFFICHER',
        completeness: 'invented' as never,
      },
    })
    renderDetail({ detail: malformed, profile: null })

    expect(document.body).not.toHaveTextContent('CONTENU INVALIDE À NE PAS AFFICHER')
    expect(screen.getByRole('heading', { level: 2, name: 'Constructions Bertrand SA' })).toBeVisible()
  })

  it('navigue vers l’entreprise avec la seule company_key autorisée', () => {
    renderDetail()

    expect(screen.getByRole('link', { name: /Voir l’entreprise/ })).toHaveAttribute(
      'href',
      `/app/companies/${UNLOCKED_DETAIL.company_key}?signal=${UNLOCKED_DETAIL.signal_id}`,
    )
  })

  it('charge un deep-link directement, sans scanner les pages ni transmettre d’artefact IA', async () => {
    mockApi(appRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}?view=history`,
    })

    expect(await screen.findByRole('heading', { level: 2, name: /Constructions Bertrand SA remporte/ })).toBeVisible()
    const detailCalls = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')
    expect(detailCalls).toHaveLength(1)
    expect(detailCalls[0].search.get('presentation_artifact_id')).toBeNull()
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
  })

  it('ne demande ni détail, ni note, ni entreprise pour un teaser verrouillé', async () => {
    mockApi({
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /billing/plans': { body: CATALOGUE },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${LOCKED_ITEM.signal_id}`,
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
    expect(callsTo(`/companies/${UNLOCKED_ITEM.company_key}`, 'GET')).toHaveLength(0)
  })

  it('garde le feed visible et permet de réessayer un détail en panne', async () => {
    const user = userEvent.setup()
    let attempts = 0
    mockApi({
      ...appRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => {
        attempts += 1
        return attempts === 1
          ? { status: 503, body: { detail: { code: 'unavailable' } } }
          : { body: UNLOCKED_DETAIL }
      },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = document.querySelector('.detail-panel') as HTMLElement
    const alert = await within(panel).findByRole('alert')
    expect(screen.getByRole('button', { name: /Constructions Bertrand SA/ })).toBeVisible()
    await user.click(within(alert).getByRole('button', { name: 'Réessayer' }))
    expect(await within(panel).findByRole('heading', { name: /Constructions Bertrand SA remporte/ })).toBeVisible()
    expect(attempts).toBe(2)
  })

  it('conserve SignalDetail comme alias du workspace partagé', async () => {
    mockApi(appRoutes())
    renderApp(
      <Routes><Route path="/legacy/:signalKey" element={<SignalDetail />} /></Routes>,
      { session: AUTHENTICATED, route: `/legacy/${UNLOCKED_ITEM.signal_id}` },
    )

    expect(await screen.findByRole('heading', { level: 2, name: /Constructions Bertrand SA remporte/ })).toBeVisible()
  })

  it('maintient la sélection pendant un chargement lent', async () => {
    let resolveDetail!: (value: { body: unknown }) => void
    mockApi({
      ...appRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => new Promise((resolve) => { resolveDetail = resolve }),
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const selected = await screen.findByRole('button', { name: /Constructions Bertrand SA/ })
    expect(selected).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByRole('heading', { name: 'Chargement…' })).toBeVisible()
    await act(async () => resolveDetail({ body: UNLOCKED_DETAIL }))
    await waitFor(() => expect(selected).toHaveAttribute('aria-pressed', 'true'))
  })
})
