import { describe, expect, it } from 'vitest'
import type {
  BillingStatus,
  CardPresentation,
  CompanyProfile,
  FeedPage,
  LockedFeedItem,
  TargetIcp,
  UnlockedDetail,
} from '../../api/types'
import {
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  UNLOCKED_PRESENTATION,
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

describe('adaptateurs de présentation du dashboard de référence', () => {
  it('alimente la vue d’ensemble uniquement depuis la présentation publiée', () => {
    const rawTitle = 'TITRE BRUT À NE JAMAIS AFFICHER DANS LA VUE D’ENSEMBLE'
    const item = {
      ...UNLOCKED_ITEM,
      contract: { ...UNLOCKED_ITEM.contract, title: rawTitle },
    }

    expect(toOverviewAwardCard(item)).toEqual({
      id: item.signal_id,
      locked: false,
      companyName: item.company.name,
      teaserHeadline: null,
      headline: UNLOCKED_PRESENTATION.content.headline,
      awardSummary: UNLOCKED_PRESENTATION.content.award_summary,
      commercialImportance: UNLOCKED_PRESENTATION.content.commercial_importance,
      fitReason: UNLOCKED_PRESENTATION.content.fit_reason,
      timing: UNLOCKED_PRESENTATION.content.timing,
      recommendedAction: UNLOCKED_PRESENTATION.content.recommended_action,
      presentationVariant: UNLOCKED_PRESENTATION.content.variant,
      amount: item.contract.amount,
      location: item.contract.location,
      awardDate: item.contract.dates.award,
      sourceSystem: item.source.system,
    })
    expect(JSON.stringify(toOverviewAwardCard(item))).not.toContain(rawTitle)
  })

  it('reste factuel quand aucun artefact courant n’est publié', () => {
    const view = toOverviewAwardCard({ ...UNLOCKED_ITEM, presentation: null })

    expect(view).toMatchObject({
      companyName: UNLOCKED_ITEM.company.name,
      headline: null,
      awardSummary: null,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: null,
      amount: UNLOCKED_ITEM.contract.amount,
      location: UNLOCKED_ITEM.contract.location,
      awardDate: UNLOCKED_ITEM.contract.dates.award,
    })
    expect(JSON.stringify(view)).not.toContain(UNLOCKED_ITEM.contract.title)
    expect(JSON.stringify(view)).not.toContain(UNLOCKED_ITEM.analysis.fit.label)
  })

  it('accepte uniquement la paire FALLBACK et FACTUAL_FALLBACK sans inférence', () => {
    const fallback: CardPresentation = {
      artifact_id: 'card_fallback_1',
      schema_version: 'card-presentation-v1',
      version: 1,
      status: 'FALLBACK',
      published_at: '2026-08-18T08:00:00+00:00',
      content: {
        schema_version: 'card-presentation-v1',
        variant: 'FACTUAL_FALLBACK',
        headline: 'Marché de voirie attribué à Constructions Bertrand SA',
        award_summary:
          'Constructions Bertrand SA est l’attributaire publié d’un marché de voirie de 1,24 M€.',
        commercial_importance: null,
        fit_reason: null,
        timing: null,
        recommended_action: null,
        target_roles: [],
        fit_need_categories: [],
        unknowns: [],
        claims: [{
          claim_id: 'claim_fallback_1',
          kind: 'FACT',
          text: 'Le montant public est de 1,24 M€.',
          evidence_refs: ['notice:26-104412'],
          confidence: 'high',
        }],
      },
    }

    expect(toOverviewAwardCard({ ...UNLOCKED_ITEM, presentation: fallback })).toMatchObject({
      headline: fallback.content.headline,
      awardSummary: fallback.content.award_summary,
      presentationVariant: 'FACTUAL_FALLBACK',
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
    })
  })

  it.each([
    ['schéma externe inconnu', {
      ...UNLOCKED_PRESENTATION,
      schema_version: 'card-presentation-v2',
    }],
    ['paire statut/variante incohérente', {
      ...UNLOCKED_PRESENTATION,
      status: 'FALLBACK',
    }],
    ['champ commercial FULL absent', {
      ...UNLOCKED_PRESENTATION,
      content: { ...UNLOCKED_PRESENTATION.content, fit_reason: null },
    }],
  ])('échoue fermé pour un artefact invalide : %s', (_label, presentation) => {
    const item = {
      ...UNLOCKED_ITEM,
      presentation: presentation as unknown as CardPresentation,
      contract: {
        ...UNLOCKED_ITEM.contract,
        title: 'TITRE BRUT INTERDIT EN REPLI',
      },
    }

    expect(toOverviewAwardCard(item)).toMatchObject({
      headline: null,
      awardSummary: null,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: null,
    })
    expect(JSON.stringify(toOverviewAwardCard(item))).not.toContain('TITRE BRUT INTERDIT')
  })

  it('ne lit jamais une présentation injectée dans un teaser verrouillé', () => {
    const leakingLocked = {
      ...LOCKED_ITEM,
      presentation: UNLOCKED_PRESENTATION,
    } as FeedPage['items'][number]

    expect(toOverviewAwardCard(leakingLocked)).toEqual({
      id: LOCKED_ITEM.signal_id,
      locked: true,
      companyName: null,
      teaserHeadline: LOCKED_ITEM.headline,
      headline: null,
      awardSummary: null,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: null,
      amount: null,
      location: null,
      awardDate: null,
      sourceSystem: null,
    })
    expect(JSON.stringify(toOverviewAwardCard(leakingLocked))).not.toContain(
      UNLOCKED_PRESENTATION.content.award_summary,
    )
  })

  it('préserve l’ordre serveur dans les cartes de la vue d’ensemble', () => {
    const feed = feedPage([LOCKED_ITEM, UNLOCKED_ITEM]) as FeedPage
    expect(toOverviewAwardCards(feed).map((card) => card.id)).toEqual([
      LOCKED_ITEM.signal_id,
      UNLOCKED_ITEM.signal_id,
    ])
  })

  it('mappe une carte déverrouillée uniquement depuis le contrat de feed', () => {
    expect(toSignalCard(UNLOCKED_ITEM)).toEqual({
      id: UNLOCKED_ITEM.signal_id,
      locked: false,
      companyName: UNLOCKED_ITEM.company.name,
      eventTitle: UNLOCKED_ITEM.contract.title,
      amount: UNLOCKED_ITEM.contract.amount,
      location: UNLOCKED_ITEM.contract.location,
      eventDate: UNLOCKED_ITEM.event.date,
      awardDate: UNLOCKED_ITEM.contract.dates.award,
      matchLabel: UNLOCKED_ITEM.analysis.fit.label,
      matchReasons: UNLOCKED_ITEM.analysis.fit.reasons,
      sourceSystem: UNLOCKED_ITEM.source.system,
      whyNow: UNLOCKED_ITEM.event.why_now,
    })
  })

  it('ne révèle aucun champ protégé dans une carte verrouillée', () => {
    const locked: LockedFeedItem = LOCKED_ITEM

    expect(toSignalCard(locked)).toEqual({
      id: locked.signal_id,
      locked: true,
      companyName: null,
      eventTitle: locked.headline,
      amount: null,
      location: null,
      eventDate: locked.event.date,
      awardDate: null,
      matchLabel: null,
      matchReasons: [],
      sourceSystem: null,
      whyNow: locked.event.why_now,
    })
  })

  it('conserve l’ordre et les valeurs du FeedPage sans données de repli', () => {
    const feed = feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) as FeedPage

    expect(toSignalCards(feed).map((card) => card.id)).toEqual([
      UNLOCKED_ITEM.signal_id,
      LOCKED_ITEM.signal_id,
    ])
    expectNoReferenceOnlyCopy(toSignalCards(feed))
  })

  it('mappe le détail sans requalifier les faits publiés en périmètre', () => {
    const detail: UnlockedDetail = UNLOCKED_DETAIL
    const view = toSignalDetailView(detail)

    expect(view).toEqual({
      id: detail.signal_id,
      title: detail.contract.title,
      companyName: detail.company.name,
      companyKey: detail.company_key ?? null,
      companyCountry: detail.company.country,
      companyIdentifier: detail.company.identifier,
      targetProfileLabel: detail.analysis.fit.target_icp_label,
      sourceSystem: detail.source.system,
      summary: detail.analysis.contract_reading?.summary ?? null,
      brief: {
        whyNow: detail.event.why_now,
        offerCoverage: detail.analysis.plausible_needs.items[0].statement,
        functionToFind: null,
        unknown: detail.analysis.plausible_needs.note,
      },
      facts: {
        amount: detail.contract.amount,
        awardDate: detail.contract.dates.award,
        execution: null,
        buyer: detail.contract.buyer?.name ?? null,
        notice: detail.source.notice_id,
        cpv: detail.contract.cpv,
        sourceUrl: detail.source.url,
      },
      scope: [],
      questions: [],
    })
    expect(view.facts.sourceUrl).toBe(UNLOCKED_DETAIL.source.url)
    expect(view.brief.whyNow).toBe(UNLOCKED_DETAIL.event.why_now)
    expectNoReferenceOnlyCopy(view)
  })

  it.each(['award_winner', 'amount', 'award_date', 'procedure_buyers'])(
    'ne transforme jamais le fait public %s en périmètre publié',
    (fact) => {
      const detail: UnlockedDetail = {
        ...UNLOCKED_DETAIL,
        evidence: {
          ...UNLOCKED_DETAIL.evidence,
          public_facts: [{
            fact,
            label: `Libellé ${fact}`,
            items: UNLOCKED_DETAIL.evidence.public_facts[0].items,
          }],
        },
      }

      expect(toSignalDetailView(detail).scope).toEqual([])
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
