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
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  feedPage,
} from '../../test/harness'
import {
  toBillingAccessView,
  toCompanySummary,
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
