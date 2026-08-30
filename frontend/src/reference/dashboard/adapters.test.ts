import { describe, expect, it } from 'vitest'
import type {
  BillingStatus,
  CompanyProfile,
  FeedPage,
  LockedFeedItem,
  TargetIcp,
  UnlockedDetail,
} from '../../api/types'
import {
  CARD_PRESENTATION,
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  FACTUAL_FALLBACK_PRESENTATION,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  feedPage,
} from '../../test/harness'
import {
  toBillingAccessView,
  toCompanySummary,
  toOverviewAwardCard,
  toOverviewAwardCards,
  toSignalCard,
  toSignalCards,
  toSignalDetailView,
  toSignalPresentationView,
  toTargetProfileView,
} from './adapters'

const REFERENCE_ONLY_COPY = [
  'H. Hüther GmbH',
  'Karl Schmitt GmbH',
  'TM Ausbau GmbH',
  'GSH GmbH',
  'Sedlmeyr Spezialtüren GmbH',
  'Garzon Butor zrt.',
  'Compte démo',
  'Mode démonstration',
]

const FULL_PRESENTATION_VIEW = {
  artifactId: CARD_PRESENTATION.artifact_id,
  version: CARD_PRESENTATION.version,
  publishedAt: CARD_PRESENTATION.published_at,
  mode: 'full',
  headline: CARD_PRESENTATION.content.headline,
  awardSummary: CARD_PRESENTATION.content.award_summary,
  commercialImportance: CARD_PRESENTATION.content.commercial_importance,
  fitReason: CARD_PRESENTATION.content.fit_reason,
  timing: CARD_PRESENTATION.content.timing,
  recommendedAction: CARD_PRESENTATION.content.recommended_action,
  targetRoles: CARD_PRESENTATION.content.target_roles,
  fitNeedCategories: CARD_PRESENTATION.content.fit_need_categories,
  unknowns: CARD_PRESENTATION.content.unknowns,
  claims: CARD_PRESENTATION.content.claims.map((claim) => ({
    id: claim.claim_id,
    kind: claim.kind,
    text: claim.text,
    evidenceRefs: claim.evidence_refs,
    confidence: claim.confidence,
  })),
}

const FALLBACK_PRESENTATION_VIEW = {
  artifactId: FACTUAL_FALLBACK_PRESENTATION.artifact_id,
  version: FACTUAL_FALLBACK_PRESENTATION.version,
  publishedAt: FACTUAL_FALLBACK_PRESENTATION.published_at,
  mode: 'factualFallback',
  headline: FACTUAL_FALLBACK_PRESENTATION.content.headline,
  awardSummary: FACTUAL_FALLBACK_PRESENTATION.content.award_summary,
  commercialImportance: null,
  fitReason: null,
  timing: null,
  recommendedAction: null,
  targetRoles: [],
  fitNeedCategories: [],
  unknowns: FACTUAL_FALLBACK_PRESENTATION.content.unknowns,
  claims: FACTUAL_FALLBACK_PRESENTATION.content.claims.map((claim) => ({
    id: claim.claim_id,
    kind: claim.kind,
    text: claim.text,
    evidenceRefs: claim.evidence_refs,
    confidence: claim.confidence,
  })),
}

describe('adaptateurs de la vue d’ensemble', () => {
  it('alimente la carte uniquement depuis la présentation validée partagée', () => {
    expect(toOverviewAwardCard(UNLOCKED_ITEM)).toEqual({
      id: UNLOCKED_ITEM.signal_id,
      locked: false,
      companyName: UNLOCKED_ITEM.company.name,
      teaserHeadline: null,
      headline: CARD_PRESENTATION.content.headline,
      awardSummary: CARD_PRESENTATION.content.award_summary,
      commercialImportance: CARD_PRESENTATION.content.commercial_importance,
      fitReason: CARD_PRESENTATION.content.fit_reason,
      timing: CARD_PRESENTATION.content.timing,
      recommendedAction: CARD_PRESENTATION.content.recommended_action,
      presentationVariant: 'FULL',
      amount: UNLOCKED_ITEM.contract.amount,
      location: UNLOCKED_ITEM.contract.location,
      awardDate: UNLOCKED_ITEM.contract.dates.award,
      sourceSystem: UNLOCKED_ITEM.source.system,
    })
  })

  it('reste factuel sans artefact et pour un FALLBACK validé', () => {
    const absent = toOverviewAwardCard({ ...UNLOCKED_ITEM, presentation: null })
    const fallback = toOverviewAwardCard({
      ...UNLOCKED_ITEM,
      presentation: FACTUAL_FALLBACK_PRESENTATION,
    })

    expect(absent).toMatchObject({
      headline: null,
      awardSummary: null,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: null,
    })
    expect(fallback).toMatchObject({
      headline: FACTUAL_FALLBACK_PRESENTATION.content.headline,
      awardSummary: FACTUAL_FALLBACK_PRESENTATION.content.award_summary,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: 'FACTUAL_FALLBACK',
    })
    expect(JSON.stringify(absent)).not.toContain(UNLOCKED_ITEM.contract.title)
  })

  it('partage le rejet strict des recommandations sans preuve', () => {
    const invalid = {
      ...CARD_PRESENTATION,
      content: {
        ...CARD_PRESENTATION.content,
        claims: [{ ...CARD_PRESENTATION.content.claims[2], evidence_refs: [] }],
      },
    }

    expect(toOverviewAwardCard({
      ...UNLOCKED_ITEM,
      presentation: invalid as unknown as typeof CARD_PRESENTATION,
    })).toMatchObject({
      headline: null,
      awardSummary: null,
      presentationVariant: null,
    })
  })

  it('ignore une présentation injectée dans un teaser et préserve l’ordre serveur', () => {
    const leakingLocked = {
      ...LOCKED_ITEM,
      presentation: CARD_PRESENTATION,
    } as FeedPage['items'][number]

    expect(toOverviewAwardCard(leakingLocked)).toMatchObject({
      locked: true,
      teaserHeadline: LOCKED_ITEM.headline,
      headline: null,
      awardSummary: null,
      presentationVariant: null,
    })
    expect(JSON.stringify(toOverviewAwardCard(leakingLocked))).not.toContain(
      CARD_PRESENTATION.content.award_summary,
    )
    expect(toOverviewAwardCards(feedPage([LOCKED_ITEM, UNLOCKED_ITEM]) as FeedPage)
      .map((card) => card.id)).toEqual([LOCKED_ITEM.signal_id, UNLOCKED_ITEM.signal_id])
  })
})

describe('adaptateurs de présentation du dashboard de référence', () => {
  it('mappe une carte déverrouillée avec la seule présentation commerciale publiée', () => {
    expect(toSignalCard(UNLOCKED_ITEM)).toEqual({
      id: UNLOCKED_ITEM.signal_id,
      locked: false,
      companyName: UNLOCKED_ITEM.company.name,
      eventTitle: null,
      amount: UNLOCKED_ITEM.contract.amount,
      location: UNLOCKED_ITEM.contract.location,
      eventDate: UNLOCKED_ITEM.event.date,
      eventDateKind: 'award',
      eventStatus: UNLOCKED_ITEM.event.status,
      awardDate: UNLOCKED_ITEM.contract.dates.award,
      presentation: FULL_PRESENTATION_VIEW,
      matchLabel: null,
      matchReasons: [],
      sourceSystem: UNLOCKED_ITEM.source.system,
      whyNow: '',
    })
  })

  it('ignore même une présentation injectée dans une carte verrouillée', () => {
    const locked = {
      ...LOCKED_ITEM,
      presentation: CARD_PRESENTATION,
      company: UNLOCKED_ITEM.company,
      contract: UNLOCKED_ITEM.contract,
      analysis: UNLOCKED_ITEM.analysis,
      source: UNLOCKED_ITEM.source,
    } as unknown as LockedFeedItem

    const card = toSignalCard(locked)

    expect(card).toEqual({
      id: locked.signal_id,
      locked: true,
      companyName: null,
      eventTitle: locked.headline,
      amount: null,
      location: null,
      eventDate: locked.event.date,
      eventDateKind: 'award',
      eventStatus: locked.event.status,
      awardDate: null,
      presentation: null,
      matchLabel: null,
      matchReasons: [],
      sourceSystem: null,
      whyNow: locked.event.why_now,
    })
    expect(JSON.stringify(card)).not.toContain(CARD_PRESENTATION.artifact_id)
    expect(JSON.stringify(card)).not.toContain(CARD_PRESENTATION.content.headline)
  })

  it('conserve l’ordre et les valeurs du FeedPage sans données de repli', () => {
    const feed = feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) as FeedPage

    expect(toSignalCards(feed).map((card) => card.id)).toEqual([
      UNLOCKED_ITEM.signal_id,
      LOCKED_ITEM.signal_id,
    ])
    expectNoReferenceOnlyCopy(toSignalCards(feed))
  })

  it('mappe le détail depuis la présentation et conserve les seuls faits publiés', () => {
    const detail: UnlockedDetail = UNLOCKED_DETAIL
    const view = toSignalDetailView(detail)

    expect(view).toEqual({
      id: detail.signal_id,
      companyName: detail.company.name,
      companyKey: detail.company_key ?? null,
      companyCountry: detail.company.country,
      companyIdentifier: detail.company.identifier,
      sourceSystem: detail.source.system,
      presentation: FULL_PRESENTATION_VIEW,
      facts: {
        amount: detail.contract.amount,
        location: detail.contract.location,
        eventDate: detail.event.date,
        eventDateKind: 'award',
        awardDate: detail.contract.dates.award,
        execution: null,
        buyer: detail.contract.buyer?.name ?? null,
        officialTitle: detail.contract.title,
        notice: detail.source.notice_id,
        cpv: detail.contract.cpv,
        sourceUrl: detail.source.url,
      },
    })
    expect(view.facts.sourceUrl).toBe(UNLOCKED_DETAIL.source.url)
    expect(view).not.toHaveProperty('brief')
    expect(view).not.toHaveProperty('summary')
    expect(view).not.toHaveProperty('scope')
    expect(view).not.toHaveProperty('questions')
    expectNoReferenceOnlyCopy(view)
  })

  it.each([
    'http://source.example/notice',
    'javascript:alert(1)',
    'data:text/html,notice',
    '/notice/relative',
  ])('masque une URL source non HTTPS : %s', (url) => {
    const view = toSignalDetailView({
      ...UNLOCKED_DETAIL,
      source: { ...UNLOCKED_DETAIL.source, url },
    })

    expect(view.facts.sourceUrl).toBeNull()
  })

  it('ne reconstruit aucun récit commercial depuis les champs bruts empoisonnés', () => {
    const poison = {
      whyNow: 'RAW WHY NOW À NE PAS PUBLIER',
      fit: 'RAW FIT À NE PAS PUBLIER',
      need: 'RAW NEED À NE PAS PUBLIER',
      summary: 'RAW SUMMARY À NE PAS PUBLIER',
    }
    const detail: UnlockedDetail = {
      ...UNLOCKED_DETAIL,
      event: { ...UNLOCKED_DETAIL.event, why_now: poison.whyNow },
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        fit: {
          ...UNLOCKED_DETAIL.analysis.fit,
          label: poison.fit,
          reasons: [poison.fit],
        },
        plausible_needs: {
          note: poison.need,
          items: UNLOCKED_DETAIL.analysis.plausible_needs.items.map((need) => ({
            ...need,
            statement: poison.need,
            reasoning: poison.need,
          })),
        },
        contract_reading: {
          note: poison.summary,
          summary: poison.summary,
          contract_type: poison.summary,
          sector: poison.summary,
        },
      },
    }

    const detailView = toSignalDetailView(detail)
    const cardView = toSignalCard(detail)
    const serialized = JSON.stringify([detailView, cardView])

    expect(detailView.presentation).toEqual(FULL_PRESENTATION_VIEW)
    expect(cardView.presentation).toEqual(FULL_PRESENTATION_VIEW)
    expect(cardView).toMatchObject({
      eventTitle: null,
      matchLabel: null,
      matchReasons: [],
      whyNow: '',
    })
    for (const value of Object.values(poison)) expect(serialized).not.toContain(value)
  })

  it('laisse la présentation absente sans repli sur l’analyse brute', () => {
    const detail: UnlockedDetail = {
      ...UNLOCKED_DETAIL,
      presentation: null,
      event: { ...UNLOCKED_DETAIL.event, why_now: 'RAW WHY NOW' },
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        fit: { ...UNLOCKED_DETAIL.analysis.fit, label: 'RAW FIT', reasons: ['RAW FIT'] },
        plausible_needs: { note: 'RAW NEED', items: [] },
        contract_reading: {
          note: 'RAW SUMMARY',
          summary: 'RAW SUMMARY',
          contract_type: null,
          sector: null,
        },
      },
    }

    const detailView = toSignalDetailView(detail)
    const cardView = toSignalCard(detail)

    expect(detailView.presentation).toBeNull()
    expect(cardView.presentation).toBeNull()
    expect(JSON.stringify([detailView, cardView])).not.toMatch(/RAW (WHY NOW|FIT|NEED|SUMMARY)/)
  })

  it('normalise une présentation FULL validée sans perdre la qualification des claims', () => {
    expect(toSignalPresentationView(CARD_PRESENTATION)).toEqual(FULL_PRESENTATION_VIEW)
  })

  it('normalise un FALLBACK en faits seuls et sans contenu commercial', () => {
    const view = toSignalPresentationView(FACTUAL_FALLBACK_PRESENTATION)

    expect(view).toEqual(FALLBACK_PRESENTATION_VIEW)
    expect(view?.claims.every((claim) => claim.kind === 'FACT')).toBe(true)
    expect(view).toMatchObject({
      mode: 'factualFallback',
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      targetRoles: [],
      fitNeedCategories: [],
    })
  })

  it('expose le même artefact publié dans le feed et le détail', () => {
    const cardPresentation = toSignalCard(UNLOCKED_ITEM).presentation
    const detailPresentation = toSignalDetailView(UNLOCKED_DETAIL).presentation

    expect(cardPresentation).toEqual(detailPresentation)
    expect(cardPresentation).toMatchObject({
      artifactId: CARD_PRESENTATION.artifact_id,
      version: CARD_PRESENTATION.version,
      publishedAt: CARD_PRESENTATION.published_at,
    })
  })

  it.each([
    ['valeur null', null],
    ['objet vide', {}],
    ['contenu absent', { ...CARD_PRESENTATION, content: undefined }],
    ['schéma enveloppe inconnu', { ...CARD_PRESENTATION, schema_version: 'card-presentation-v2' }],
    ['date de publication invalide', { ...CARD_PRESENTATION, published_at: 'date-invalide' }],
    [
      'statut et variante incohérents',
      {
        ...CARD_PRESENTATION,
        status: 'PASS',
        content: {
          ...FACTUAL_FALLBACK_PRESENTATION.content,
          variant: 'FACTUAL_FALLBACK',
        },
      },
    ],
    [
      'liste de claims vide',
      {
        ...CARD_PRESENTATION,
        content: { ...CARD_PRESENTATION.content, claims: [] },
      },
    ],
    [
      'fait sans preuve',
      {
        ...CARD_PRESENTATION,
        content: {
          ...CARD_PRESENTATION.content,
          claims: [{ ...CARD_PRESENTATION.content.claims[0], evidence_refs: [] }],
        },
      },
    ],
    [
      'recommandation sans preuve',
      {
        ...CARD_PRESENTATION,
        content: {
          ...CARD_PRESENTATION.content,
          claims: [{ ...CARD_PRESENTATION.content.claims[2], evidence_refs: [] }],
        },
      },
    ],
    [
      'inférence sans confiance',
      {
        ...CARD_PRESENTATION,
        content: {
          ...CARD_PRESENTATION.content,
          claims: [{ ...CARD_PRESENTATION.content.claims[1], confidence: null }],
        },
      },
    ],
    [
      'rôle inconnu',
      {
        ...CARD_PRESENTATION,
        content: { ...CARD_PRESENTATION.content, target_roles: ['CEO'] },
      },
    ],
    [
      'headline trop long',
      {
        ...CARD_PRESENTATION,
        content: { ...CARD_PRESENTATION.content, headline: 'x'.repeat(161) },
      },
    ],
    [
      'fallback enrichi d’une recommandation',
      {
        ...FACTUAL_FALLBACK_PRESENTATION,
        content: {
          ...FACTUAL_FALLBACK_PRESENTATION.content,
          recommended_action: 'Appeler immédiatement.',
        },
      },
    ],
    [
      'fallback enrichi d’une inférence',
      {
        ...FACTUAL_FALLBACK_PRESENTATION,
        content: {
          ...FACTUAL_FALLBACK_PRESENTATION.content,
          claims: [CARD_PRESENTATION.content.claims[1]],
        },
      },
    ],
  ] satisfies Array<[string, unknown]>)('rejette sans lever d’exception : %s', (_label, payload) => {
    expect(() => toSignalPresentationView(payload)).not.toThrow()
    expect(toSignalPresentationView(payload)).toBeNull()
  })

  it('qualifie la date depuis l’horloge, avec le statut comme repli', () => {
    const notified = toSignalCard({
      ...UNLOCKED_ITEM,
      event: {
        ...UNLOCKED_ITEM.event,
        status: 'recently_notified_contract',
        type: 'recently_notified_contract',
        clock: 'notification',
      },
    })
    const publishedLocked = toSignalCard({
      ...LOCKED_ITEM,
      event: {
        ...LOCKED_ITEM.event,
        status: 'recently_published_award',
        type: 'recently_published_award',
      },
    })

    expect(notified.eventDateKind).toBe('notification')
    expect(publishedLocked.eventDateKind).toBe('publication')
  })

  it.each(['award_winner', 'amount', 'award_date', 'procedure_buyers'])(
    'ne reconstruit jamais une présentation depuis le fait public %s',
    (fact) => {
      const detail: UnlockedDetail = {
        ...UNLOCKED_DETAIL,
        presentation: null,
        evidence: {
          ...UNLOCKED_DETAIL.evidence,
          public_facts: [{
            fact,
            label: `Libellé ${fact}`,
            items: UNLOCKED_DETAIL.evidence.public_facts[0].items,
          }],
        },
      }

      expect(toSignalDetailView(detail).presentation).toBeNull()
    },
  )

  it('présente le ciblage, la facturation et l’entreprise sans valeurs de maquette', () => {
    const target: TargetIcp = ICP
    const access: BillingStatus = DISCOVERY_STATUS
    const company: CompanyProfile = COMPANY_PROFILE

    expect(toTargetProfileView(target)).toEqual({
      id: target.target_icp_id,
      label: target.label,
      firstTerritory: target.customer_input.territories[0],
      active: true,
    })
    expect(toBillingAccessView(access)).toEqual({
      planCode: access.plan_code,
      billingAction: access.billing_action,
      subscriptionStatus: access.subscription_status,
    })
    expect(toCompanySummary(company)).toEqual({
      key: company.company_key,
      name: company.official_identity.name,
      country: company.official_identity.country,
      address: company.official_identity.address,
      websiteUrl: company.official_identity.website_url,
      relatedSignalCount: company.related_signals.length,
    })
    expectNoReferenceOnlyCopy([
      toTargetProfileView(target),
      toBillingAccessView(access),
      toCompanySummary(company),
    ])
  })
})

function expectNoReferenceOnlyCopy(value: unknown) {
  const serialized = JSON.stringify(value)
  for (const forbidden of REFERENCE_ONLY_COPY) {
    expect(serialized).not.toContain(forbidden)
  }
}
