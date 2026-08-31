import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { AppRoutes } from '../App'
import { SignalDetail } from '../pages/SignalDetail'
import type { CardPresentation } from '../api/types'
import {
  AUTHENTICATED,
  CATALOGUE,
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

function detailRoutes(detail: unknown = UNLOCKED_DETAIL) {
  const presentation = (detail as { presentation?: CardPresentation | null }).presentation ?? null
  return {
    'GET /signals': { body: feedPage([{ ...UNLOCKED_ITEM, presentation }]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: detail },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /target-icps': { body: [ICP] },
  }
}

type FactualFallbackPresentation = Extract<CardPresentation, { status: 'FALLBACK' }>

const FACTUAL_FALLBACK: FactualFallbackPresentation = {
  artifact_id: 'b'.repeat(64),
  version: 1,
  status: 'FALLBACK',
  schema_version: 'card-presentation-v1',
  published_at: '2026-08-30T12:00:00Z',
  content: {
    schema_version: 'card-presentation-v1',
    variant: 'FACTUAL_FALLBACK',
    headline: 'Attribution publique documentée',
    award_summary: 'Une entreprise identifiée est attributaire du marché.',
    commercial_importance: null,
    fit_reason: null,
    timing: null,
    recommended_action: null,
    target_roles: [],
    fit_need_categories: [],
    unknowns: [],
    claims: [
      {
        claim_id: 'HEADLINE',
        kind: 'FACT',
        text: 'Attribution publique documentée',
        evidence_refs: ['source:award'],
        confidence: null,
      },
      {
        claim_id: 'AWARD_SUMMARY',
        kind: 'FACT',
        text: 'Une entreprise identifiée est attributaire du marché.',
        evidence_refs: ['source:award_summary'],
        confidence: null,
      },
    ],
  },
}

function presentationFixture(artifactId: string, headline: string): CardPresentation {
  const awardSummary = `${headline} — synthèse publiée`
  return {
    ...FACTUAL_FALLBACK,
    artifact_id: artifactId,
    content: {
      ...FACTUAL_FALLBACK.content,
      headline,
      award_summary: awardSummary,
      claims: [
        { ...FACTUAL_FALLBACK.content.claims[0], text: headline },
        { ...FACTUAL_FALLBACK.content.claims[1], text: awardSummary },
      ],
    },
  }
}

const MALFORMED_PRESENTATIONS = [
  [
    'une claim sans evidence_refs',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        headline: 'HEADLINE SANS PREUVE INTERDIT',
        award_summary: 'RÉSUMÉ SANS PREUVE INTERDIT',
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 'HEADLINE SANS PREUVE INTERDIT',
          confidence: null,
        }, FACTUAL_FALLBACK.content.claims[1]],
      },
    },
  ],
  [
    'une claim avec evidence_refs vide',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        headline: 'HEADLINE PREUVE VIDE INTERDIT',
        award_summary: 'RÉSUMÉ PREUVE VIDE INTERDIT',
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 'HEADLINE PREUVE VIDE INTERDIT',
          evidence_refs: [],
          confidence: null,
        }, FACTUAL_FALLBACK.content.claims[1]],
      },
    },
  ],
  [
    'un couple statut variante invalide',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        variant: 'FULL',
        headline: 'HEADLINE COUPLE INVALIDE INTERDIT',
        award_summary: 'RÉSUMÉ COUPLE INVALIDE INTERDIT',
      },
    },
  ],
  [
    'une claim mal formée',
    {
      ...FACTUAL_FALLBACK,
      content: {
        ...FACTUAL_FALLBACK.content,
        headline: 'HEADLINE CLAIM MAL FORMÉE INTERDIT',
        award_summary: 'RÉSUMÉ CLAIM MAL FORMÉE INTERDIT',
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 42,
          evidence_refs: ['source:award'],
          confidence: null,
        }, FACTUAL_FALLBACK.content.claims[1]],
      },
    },
  ],
] as const

async function detailPanel(
  heading = 'Présentation non publiée',
): Promise<HTMLElement> {
  await screen.findByRole('heading', { level: 2, name: heading })
  const panel = document.querySelector('.detail-panel')
  if (!(panel instanceof HTMLElement)) throw new Error('detail-panel absent')
  return panel
}

describe('détail exact d’un signal réel', () => {
  it('épingle le détail sur l’artefact publié du feed et refuse une autre publication', async () => {
    const feedPresentation = presentationFixture('a'.repeat(64), 'Publication A vue dans le feed')
    const detailPresentation = presentationFixture('c'.repeat(64), 'Publication B interdite')
    mockApi({
      ...detailRoutes({ ...UNLOCKED_DETAIL, presentation: detailPresentation }),
      'GET /signals': {
        body: feedPage([{ ...UNLOCKED_ITEM, presentation: feedPresentation }]),
      },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByText('Commune de Villeneuve')
    const detailCalls = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')
    expect(detailCalls).toHaveLength(1)
    expect(detailCalls[0].search.get('presentation_artifact_id')).toBe(
      feedPresentation.artifact_id,
    )
    const panel = await detailPanel()
    expect(panel).not.toHaveTextContent(detailPresentation.content.headline)
  })

  it('honore le deep-link seulement si son artefact est encore celui du feed', async () => {
    const publicationA = presentationFixture('a'.repeat(64), 'Publication A épinglée')
    mockApi({
      ...detailRoutes({ ...UNLOCKED_DETAIL, presentation: publicationA }),
      'GET /signals': { body: feedPage([{ ...UNLOCKED_ITEM, presentation: publicationA }]) },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}?presentation_artifact_id=${publicationA.artifact_id}`,
    })

    expect(await screen.findByRole('heading', { name: publicationA.content.headline })).toBeVisible()
    const detailCall = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')[0]
    expect(detailCall.search.get('presentation_artifact_id')).toBe(publicationA.artifact_id)
  })

  it('échoue fermé si le deep-link vise une publication remplacée dans le feed', async () => {
    const publicationA = presentationFixture('a'.repeat(64), 'Publication A devenue obsolète')
    const publicationB = presentationFixture('c'.repeat(64), 'Publication B interdite pour ce lien')
    mockApi({
      ...detailRoutes({ ...UNLOCKED_DETAIL, presentation: publicationB }),
      'GET /signals': { body: feedPage([{ ...UNLOCKED_ITEM, presentation: publicationB }]) },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}?presentation_artifact_id=${publicationA.artifact_id}`,
    })

    const panel = await detailPanel()
    const detailCall = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')[0]
    expect(detailCall.search.get('presentation_artifact_id')).toBeNull()
    expect(panel).not.toHaveTextContent(publicationA.content.headline)
    expect(panel).not.toHaveTextContent(publicationB.content.headline)
    expect(document.body).not.toHaveTextContent(publicationB.content.headline)
  })

  it('n’adopte aucune publication du détail quand le feed n’en publie pas', async () => {
    const detailPresentation = presentationFixture('c'.repeat(64), 'Publication B interdite')
    mockApi({
      ...detailRoutes({ ...UNLOCKED_DETAIL, presentation: detailPresentation }),
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await screen.findByText('Commune de Villeneuve')
    const detailCalls = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')
    expect(detailCalls).toHaveLength(1)
    expect(detailCalls[0].search.get('presentation_artifact_id')).toBeNull()
    const panel = await detailPanel()
    expect(panel).not.toHaveTextContent(detailPresentation.content.headline)
  })

  it('compose les cartes exactes depuis le détail API sans réintroduire l’ancien DOM', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    for (const heading of [
      'Détails du marché',
      'Constructions Bertrand SA',
      'Note sur ce signal',
    ]) {
      expect(within(panel).getByRole('heading', { name: heading })).toBeVisible()
    }
    expect(within(panel).getByText('Signal d’attribution')).toBeVisible()
    expect(within(panel).getByText('Commune de Villeneuve')).toBeVisible()
    expect(panel.querySelector('.commercial-brief-card')).toBeNull()
    expect(panel.querySelector('.facts-card')).not.toBeNull()
    expect(panel.querySelector('.verification-card')).toBeNull()
    expect(panel.querySelector('.signal-note-card')).not.toBeNull()
    expect(panel.querySelector('[class*="evidence"]')).toBeNull()
    const notice = panel.querySelector('.prototype-notice')
    expect(notice).toHaveTextContent(/données réelles|informations publiées/i)
    expect(notice).not.toHaveTextContent(/démonstration|jeu d’exemples|maquette/i)
    expect(within(panel).queryByText('Profil : Matériaux — Occitanie')).not.toBeInTheDocument()
    expect(within(panel).getAllByText('France').length).toBeGreaterThan(0)
    expect(within(panel).getByText('SIRET 12345678900011')).toBeVisible()
    expect(within(panel).getAllByText(/BOAMP.*26-104412/).length).toBeGreaterThan(1)
    expect(within(panel).getAllByText('Date d’attribution').length).toBeGreaterThan(0)
    expect(within(panel).queryByText('Contrat conclu')).not.toBeInTheDocument()
    expect(panel.querySelector('.volume-grid')).toBeNull()
    expect(panel.querySelector('.questions-list')).toBeNull()
  })

  it('sépare conclusion, faits, inférences, recommandation et inconnues d’un FULL publié', async () => {
    const presentation = fullPresentation()
    const detail = {
      ...UNLOCKED_DETAIL,
      presentation,
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        fit: {
          ...UNLOCKED_DETAIL.analysis.fit,
          reasons: ['RAISON ANALYSIS INTERDITE'],
        },
      },
      event: { ...UNLOCKED_DETAIL.event, why_now: 'URGENCE EVENT INTERDITE' },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel(presentation.content.headline)
    expect(within(panel).getByText('Analyse publiée')).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Conclusion commerciale' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Fait publié' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Interprétation Kivou' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Recommandation' })).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'À vérifier' })).toBeVisible()
    expect(within(panel).getByText('Responsable achats')).toBeVisible()
    expect(within(panel).getByText('Fonction pertinente pour vérifier le besoin documenté.')).toBeVisible()
    expect(panel).toHaveTextContent('Confiance moyenne · Fondé sur les preuves publiées')
    for (const claim of presentation.content.claims) {
      expect(panel).toHaveTextContent(claim.text)
    }
    expect(panel).not.toHaveTextContent('RAISON ANALYSIS INTERDITE')
    expect(panel).not.toHaveTextContent('URGENCE EVENT INTERDITE')
  })

  it('limite un FALLBACK aux faits publiés sans conclusion ni conseil commercial', async () => {
    const detail = { ...UNLOCKED_DETAIL, presentation: FACTUAL_FALLBACK }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel(FACTUAL_FALLBACK.content.headline)
    expect(within(panel).getByText('Faits publiés uniquement')).toBeVisible()
    expect(within(panel).getByRole('heading', { name: 'Fait publié' })).toBeVisible()
    expect(within(panel).queryByRole('heading', { name: 'Interprétation Kivou' })).toBeNull()
    expect(within(panel).queryByRole('heading', { name: 'Recommandation' })).toBeNull()
    expect(panel.querySelector('.commercial-brief-card')).toBeNull()
  })

  it.each([
    ['award', 'recent_award', "Date d’attribution"],
    ['notification', 'recently_notified_contract', 'Date de notification'],
    ['publication', 'recently_published_award', 'Date de publication'],
  ] as const)('libelle la date de détail %s sans en changer le sens', async (clock, status, label) => {
    const detail = {
      ...UNLOCKED_DETAIL,
      event: {
        ...UNLOCKED_DETAIL.event,
        clock,
        status,
        date: '2026-08-15',
      },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(within(panel).getAllByText(label).length).toBeGreaterThan(0)
    expect(panel).toHaveTextContent('15 août 2026')
  })

  it('ne présente jamais une publication comme une attribution dans le détail', async () => {
    const detail = {
      ...UNLOCKED_DETAIL,
      event: {
        ...UNLOCKED_DETAIL.event,
        clock: 'publication' as const,
        status: 'recently_published_award' as const,
        date: '2026-08-15',
      },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(within(panel).getAllByText('Date de publication').length).toBeGreaterThan(0)
    expect(within(panel).queryByText("Date d’attribution")).not.toBeInTheDocument()
  })

  it('maintient acheteur et attributaire sous des libellés distincts et non inversables', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    const factGrid = panel.querySelector('.signal-fact-grid') as HTMLElement
    const buyerLabel = within(factGrid).getByText('Acheteur', { selector: 'dt' })
    const awardeeLabel = within(factGrid).getByText('Entreprise attributaire', { selector: 'dt' })
    expect(buyerLabel.parentElement).toHaveTextContent('Commune de Villeneuve')
    expect(buyerLabel.parentElement).not.toHaveTextContent('Constructions Bertrand SA')
    expect(awardeeLabel.parentElement).toHaveTextContent('Constructions Bertrand SA')
    expect(awardeeLabel.parentElement).not.toHaveTextContent('Commune de Villeneuve')
  })

  it('affiche un rôle indisponible sans inventer personne, fonction ou urgence', async () => {
    const detail = {
      ...UNLOCKED_DETAIL,
      presentation: null,
      event: {
        ...UNLOCKED_DETAIL.event,
        headline: 'URGENT : Jean Dupont doit être appelé',
        why_now: 'Contacter immédiatement le directeur des achats.',
      },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(within(panel).getByText('Rôle cible non disponible')).toBeVisible()
    expect(within(panel).queryByText('Pourquoi maintenant')).not.toBeInTheDocument()
    expect(panel).not.toHaveTextContent(/urgent|jean dupont|directeur|responsable|chef de projet/i)
  })

  it.each([
    ['absente', null, 'Présentation non publiée'],
    ['fallback factuel', FACTUAL_FALLBACK, FACTUAL_FALLBACK.content.headline],
  ] as const)(
    'ne reconstruit aucune copie commerciale depuis analysis quand la présentation est %s',
    async (_case, presentation, heading) => {
      const poisonedAnalysis = {
        ...UNLOCKED_DETAIL.analysis,
        fit: {
          ...UNLOCKED_DETAIL.analysis.fit,
          target_icp_label: 'PROFIL ANALYSIS INTERDIT',
          reasons: [],
        },
        plausible_needs: {
          note: 'BESOIN ANALYSIS INTERDIT',
          items: [{
            ...UNLOCKED_DETAIL.analysis.plausible_needs.items[0],
            label: 'OFFRE ANALYSIS INTERDITE',
            statement: 'COPIE ANALYSIS INTERDITE',
          }],
        },
      }
      const detail = {
        ...UNLOCKED_DETAIL,
        presentation,
        analysis: poisonedAnalysis,
        event: {
          ...UNLOCKED_DETAIL.event,
          headline: 'HEADLINE EVENT INTERDIT',
          why_now: 'URGENCE EVENT INTERDITE',
        },
        contract: {
          ...UNLOCKED_DETAIL.contract,
          title: 'TITRE ADMINISTRATIF SOURCE',
        },
      }
      mockApi(detailRoutes(detail))
      renderApp(<AppRoutes />, {
        session: AUTHENTICATED,
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      })

      const panel = await detailPanel(heading)
      expect(panel.querySelector('.commercial-brief-card')).toBeNull()
      expect(within(panel).getByText('Rôle cible non disponible')).toBeVisible()
      for (const forbidden of [
        'PROFIL ANALYSIS INTERDIT',
        'BESOIN ANALYSIS INTERDIT',
        'OFFRE ANALYSIS INTERDITE',
        'COPIE ANALYSIS INTERDITE',
        'HEADLINE EVENT INTERDIT',
        'URGENCE EVENT INTERDITE',
      ]) {
        expect(panel).not.toHaveTextContent(forbidden)
      }
      expect(panel).toHaveTextContent('TITRE ADMINISTRATIF SOURCE')
      if (presentation) {
        expect(presentation.content.claims.map((claim) => claim.text)).toEqual([
          presentation.content.headline,
          presentation.content.award_summary,
        ])
        for (const claim of presentation.content.claims) {
          expect(panel).toHaveTextContent(claim.text)
        }
      }
    },
  )

  it.each(MALFORMED_PRESENTATIONS)(
    'traite %s reçue du détail API comme une présentation absente',
    async (_case, presentation) => {
      const detail = { ...UNLOCKED_DETAIL, presentation }
      mockApi(detailRoutes(detail))
      renderApp(<AppRoutes />, {
        session: AUTHENTICATED,
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      })

      const panel = await detailPanel()
      expect(within(panel).getByRole('heading', { level: 2 })).toHaveTextContent(
        'Présentation non publiée',
      )
      expect(panel.querySelector('.published-status')).toHaveTextContent('Analyse indisponible')
      expect(panel).toHaveTextContent('Constructions Bertrand SA')
      expect(panel).toHaveTextContent('Commune de Villeneuve')
      expect(panel).not.toHaveTextContent(presentation.content.headline)
      expect(panel).not.toHaveTextContent(presentation.content.award_summary)
    },
  )

  it.each([
    ['absence', null, 'BOAMP', 'Analyse indisponible'],
    ['publication sans source', FACTUAL_FALLBACK, null, 'Faits publiés uniquement'],
    [
      'publication avec source',
      FACTUAL_FALLBACK,
      'BOAMP',
      'Faits publiés uniquement',
    ],
  ] as const)(
    'distingue le statut artefact de la source optionnelle : %s',
    async (_case, presentation, sourceSystem, expected) => {
      const detail = {
        ...UNLOCKED_DETAIL,
        presentation,
        source: { ...UNLOCKED_DETAIL.source, system: sourceSystem },
      }
      mockApi(detailRoutes(detail))
      renderApp(<AppRoutes />, {
        session: AUTHENTICATED,
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      })

      const panel = await detailPanel(
        presentation?.content.headline ?? 'Présentation non publiée',
      )
      expect(panel.querySelector('.published-status')).toHaveTextContent(expected)
    },
  )

  it.each([
    ['absente', null, 'Analyse indisponible', 'unpublished'],
    [
      'publiée',
      FACTUAL_FALLBACK,
      'Faits publiés uniquement',
      'published',
    ],
  ] as const)(
    'expose un marqueur d’icône stable quand la présentation est %s',
    async (_case, presentation, expectedText, expectedIcon) => {
      const detail = {
        ...UNLOCKED_DETAIL,
        presentation,
      }
      mockApi(detailRoutes(detail))
      renderApp(<AppRoutes />, {
        session: AUTHENTICATED,
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      })

      const panel = await detailPanel(
        presentation?.content.headline ?? 'Présentation non publiée',
      )
      const status = panel.querySelector('.published-status') as HTMLElement
      expect(status).toHaveTextContent(expectedText)
      expect(status.querySelectorAll('[data-presentation-icon]')).toHaveLength(1)
      expect(status.querySelector('[data-presentation-icon]')).toHaveAttribute(
        'data-presentation-icon',
        expectedIcon,
      )
      expect(status.querySelector('[data-presentation-icon]')).toHaveAttribute(
        'aria-hidden',
        'true',
      )
    },
  )

  it('garde le titre administratif uniquement dans les faits clairement libellés', async () => {
    const administrativeTitle = 'ACCORD-CADRE LOT 7 PERSONNEL ET MATÉRIAUX'
    const detail = {
      ...UNLOCKED_DETAIL,
      presentation: null,
      contract: { ...UNLOCKED_DETAIL.contract, title: administrativeTitle },
    }
    mockApi(detailRoutes(detail))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(within(panel).getByRole('heading', { level: 2 })).toHaveTextContent(
      'Présentation non publiée',
    )
    const officialTitleLabel = within(panel).getByText('Titre officiel de la source', {
      selector: 'dt',
    })
    expect(officialTitleLabel.parentElement).toHaveTextContent(administrativeTitle)
    expect(panel.querySelector('.commercial-brief-card')).toBeNull()
  })

  it('ne reprend aucun besoin plausible hors d’un artefact publié', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const panel = await detailPanel()
    expect(panel).not.toHaveTextContent(UNLOCKED_DETAIL.analysis.plausible_needs.note)
    expect(panel).not.toHaveTextContent(UNLOCKED_DETAIL.analysis.plausible_needs.items[0].label!)
    expect(panel.textContent?.toLowerCase()).not.toMatch(
      /va acheter|achètera|achat prévu|achat certain|client garanti/,
    )
  })

  it('rend la source officielle uniquement quand l’API fournit une URL sûre', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const link = await screen.findByRole('link', { name: 'Ouvrir l’avis' })
    expect(link).toHaveAttribute('href', 'https://www.boamp.fr/avis/26-104412')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    for (const leak of ['/home/', '/tmp/', 'tests/', 'fixtures/', 'src/signals', '.jsonl']) {
      expect(document.body.textContent).not.toContain(leak)
    }
  })

  it('masque les actions source et entreprise quand leurs autorités sont absentes', async () => {
    const withoutActions = {
      ...UNLOCKED_DETAIL,
      company_key: null,
      source: { ...UNLOCKED_DETAIL.source, url: null },
    }
    mockApi(detailRoutes(withoutActions))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    await detailPanel()
    expect(screen.queryByRole('link', { name: 'Ouvrir l’avis' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Voir l’entreprise' })).not.toBeInTheDocument()
  })

  it('navigue vers l’entreprise avec la seule company_key autorisée', async () => {
    mockApi(detailRoutes())
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const link = await screen.findByRole('link', { name: 'Voir l’entreprise' })
    expect(link).toHaveAttribute(
      'href',
      `/app/companies/${UNLOCKED_DETAIL.company_key}?signal=${UNLOCKED_ITEM.signal_id}`,
    )
    expect(link).not.toHaveAttribute('state')
  })

  it('ne demande ni détail, ni note, ni feedback pour une route verrouillée', async () => {
    mockApi({
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${LOCKED_ITEM.signal_id}`,
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/feedback`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain('Constructions Bertrand')
  })

  it('garde le feed disponible et réessaie localement un détail en panne', async () => {
    const user = userEvent.setup()
    let detailCalls = 0
    mockApi({
      ...detailRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => {
        detailCalls += 1
        return detailCalls === 1
          ? { status: 503, body: { detail: { code: 'signal_unavailable' } } }
          : { body: UNLOCKED_DETAIL }
      },
    })
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    expect(await screen.findByText('Signal non disponible dans cette lecture')).toBeVisible()
    expect(document.querySelector('.signal-list .signal-item')).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByText('Commune de Villeneuve')).toBeVisible()
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(2)
  })

  it('rend les champs nullable comme non publiés sans fabriquer de valeur', async () => {
    const nullable = {
      ...UNLOCKED_DETAIL,
      company: { name: null, country: null, identifier: null },
      company_key: null,
      contract: {
        ...UNLOCKED_DETAIL.contract,
        title: null,
        buyer: null,
        amount: null,
        cpv: null,
        location: null,
        dates: { award: null, contract_notification: null, publication: null },
      },
      source: {
        system: null,
        country: null,
        notice_id: null,
        procedure_id: null,
        url: null,
      },
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        plausible_needs: { note: '', items: [] },
        contract_reading: {
          note: '',
          summary: null,
          contract_type: null,
          sector: null,
        },
      },
      evidence: { ...UNLOCKED_DETAIL.evidence, public_facts: [] },
    }
    mockApi(detailRoutes(nullable))
    renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
    })

    const heading = await screen.findByRole('heading', { level: 2, name: 'Présentation non publiée' })
    const panel = heading.closest('.detail-panel') as HTMLElement
    expect(within(panel).getAllByText('Non publié').length).toBeGreaterThan(3)
    expect(within(panel).queryByRole('link', { name: /avis|entreprise/i })).not.toBeInTheDocument()
  })

  it('conserve le wrapper SignalDetail comme alias du workspace exact', async () => {
    mockApi(detailRoutes())
    renderApp(
      <Routes>
        <Route path="app/signals/:signalKey" element={<SignalDetail />} />
      </Routes>,
      {
        session: AUTHENTICATED,
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      },
    )

    expect(await screen.findByRole('heading', { level: 2, name: 'Présentation non publiée' })).toBeVisible()
    expect(document.querySelector('.workspace-grid .feed-panel + .detail-panel')).not.toBeNull()
  })
})
