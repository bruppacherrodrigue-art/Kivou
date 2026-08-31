import { describe, expect, it } from 'vitest'
import type {
  BillingStatus,
  CardPresentation,
  CompanyProfile,
  Evidence,
  EvidenceItem,
  FeedPage,
  LockedFeedItem,
  TargetIcp,
  UnlockedFeedItem,
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
  eventDateKind,
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
  it('ferme statiquement la présence de présentation selon le verrouillage', () => {
    const unlockedWithUndefinedPresentation = { ...UNLOCKED_ITEM, presentation: undefined }
    // @ts-expect-error Un item déverrouillé porte toujours la clé nullable de l'API.
    const invalidUnlocked: UnlockedFeedItem = unlockedWithUndefinedPresentation
    const lockedWithPresentation = { ...LOCKED_ITEM, presentation: null }
    // @ts-expect-error Un teaser verrouillé interdit explicitement cette clé.
    const invalidLocked: LockedFeedItem = lockedWithPresentation

    expect(invalidUnlocked.presentation).toBeUndefined()
    expect(invalidLocked.presentation).toBeNull()
  })

  it('ferme statiquement FALLBACK aux claims factuelles uniquement', () => {
    const invalidFallback = {
      artifact_id: 'b'.repeat(64),
      version: 1,
      status: 'FALLBACK',
      schema_version: 'card-presentation-v1',
      published_at: '2026-08-30T12:00:00Z',
      content: {
        schema_version: 'card-presentation-v1',
        variant: 'FACTUAL_FALLBACK',
        headline: 'Attribution documentée',
        award_summary: 'Attribution documentée depuis la source.',
        commercial_importance: null,
        fit_reason: null,
        timing: null,
        recommended_action: null,
        target_roles: [],
        fit_need_categories: [],
        unknowns: [],
        claims: [{
          claim_id: 'INVALID_INFERENCE',
          kind: 'INFERENCE',
          text: 'Inférence interdite',
          evidence_refs: ['source:award'],
          // @ts-expect-error FALLBACK ne peut porter la confiance d'une inférence.
          confidence: 'medium',
        }],
      },
    } satisfies CardPresentation

    expect(invalidFallback.status).toBe('FALLBACK')
  })

  it('ferme statiquement les groupes de preuve à la taxonomie Need Graph', () => {
    const invalidGroup: Evidence['analysis_inputs']['groups'][number] = {
      // @ts-expect-error Une catégorie inconnue ne peut pas relier une preuve.
      plausible_need: 'unknown_need_category',
      label: 'Inconnue',
      items: [],
    }

    expect(invalidGroup.items).toEqual([])
  })

  it.each([
    [{ clock: 'award', status: 'recent_award' }, 'award'],
    [{ clock: 'notification', status: 'recently_notified_contract' }, 'notification'],
    [{ clock: 'publication', status: 'recently_published_award' }, 'publication'],
  ] as const)('mappe %j vers la nature de date qualifiée %s', (event, expected) => {
    expect(eventDateKind(event.clock, event.status)).toBe(expected)
  })

  it('échoue fermé si le statut et l’horloge qualifiée se contredisent', () => {
    expect(() => eventDateKind('publication', 'recent_award')).toThrow(/incohérent/i)
  })

  it('sélectionne le premier besoin ciblé non blanc qui possède des preuves', () => {
    const detail: UnlockedDetail = {
      ...UNLOCKED_DETAIL,
      analysis: {
        ...UNLOCKED_DETAIL.analysis,
        plausible_needs: {
          ...UNLOCKED_DETAIL.analysis.plausible_needs,
          items: [
            {
              ...UNLOCKED_DETAIL.analysis.plausible_needs.items[0],
              category: 'workforce_capacity',
              label: '  ',
              statement: 'Besoin vide à ne pas retenir',
              targeted_by_your_profile: true,
            },
            {
              ...UNLOCKED_DETAIL.analysis.plausible_needs.items[0],
              category: 'specialist_subcontracting',
              label: 'Personnel',
              statement: 'Besoin générique à ne pas retenir',
              targeted_by_your_profile: false,
            },
            {
              ...UNLOCKED_DETAIL.analysis.plausible_needs.items[0],
              category: 'equipment_or_rental',
              label: 'Équipement sans preuve',
              statement: 'Besoin ciblé mais non prouvé',
              targeted_by_your_profile: true,
            },
            {
              ...UNLOCKED_DETAIL.analysis.plausible_needs.items[0],
              category: 'materials_or_components',
              label: '  Matériaux  ',
              statement: 'Besoin ciblé et prouvé',
              targeted_by_your_profile: true,
            },
          ],
        },
      },
      evidence: {
        ...UNLOCKED_DETAIL.evidence,
        analysis_inputs: {
          ...UNLOCKED_DETAIL.evidence.analysis_inputs,
          groups: [
            {
              plausible_need: 'workforce_capacity',
              label: 'Personnel',
              items: UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items,
            },
            {
              plausible_need: 'materials_or_components',
              label: 'Matériaux',
              items: [{
                ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
                url: 'https://source.test/materials',
                path: null,
                notice_id: null,
                procedure_id: null,
              }],
            },
          ],
        },
      },
    }

    expect(toSignalDetailView(detail).primaryNeed).toEqual({
      label: 'Matériaux',
      evidenceRefs: [
        `evidence:url:${encodeURIComponent('https://source.test/materials')}`,
      ],
    })
  })

  it('produit une seule référence canonique pour une URL et son chemin', () => {
    const detail = detailWithEvidenceItems([{
      ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
      url: 'https://source.test/notice/42',
      path: '/awards/0',
      notice_id: 'notice-ignored-because-url-resolves',
      procedure_id: 'procedure-ignored-because-url-resolves',
    }])

    expect(toSignalDetailView(detail).primaryNeed?.evidenceRefs).toEqual([
      `evidence:url:${encodeURIComponent('https://source.test/notice/42')}`
        + `:path:${encodeURIComponent('/awards/0')}`,
    ])
  })

  it('évite les collisions entre deux avis qui partagent le même chemin', () => {
    const detail = detailWithEvidenceItems([
      {
        ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
        source_system: 'TED',
        url: null,
        notice_id: 'notice-1',
        procedure_id: null,
        path: '/awards/0',
      },
      {
        ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
        source_system: 'TED',
        url: null,
        notice_id: 'notice-2',
        procedure_id: null,
        path: '/awards/0',
      },
    ])

    const refs = toSignalDetailView(detail).primaryNeed?.evidenceRefs ?? []
    expect(refs).toHaveLength(2)
    expect(new Set(refs).size).toBe(2)
    expect(refs.every((reference) => reference.startsWith('evidence:source:'))).toBe(true)
    expect(refs).not.toContain('/awards/0')
    expect(refs).not.toContain('notice-1')
    expect(refs).not.toContain('notice-2')
  })

  it('évite les collisions entre deux systèmes qui réutilisent le même identifiant', () => {
    const detail = detailWithEvidenceItems([
      {
        ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
        source_system: 'TED',
        url: null,
        notice_id: 'shared-42',
        procedure_id: null,
        path: null,
      },
      {
        ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
        source_system: 'BOAMP',
        url: null,
        notice_id: 'shared-42',
        procedure_id: null,
        path: null,
      },
    ])

    const refs = toSignalDetailView(detail).primaryNeed?.evidenceRefs ?? []
    expect(refs).toHaveLength(2)
    expect(new Set(refs).size).toBe(2)
    expect(refs).not.toContain('shared-42')
  })

  it('rejette un chemin isolé sans source résoluble', () => {
    const detail = detailWithEvidenceItems([{
      ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
      source_system: null,
      url: null,
      notice_id: null,
      procedure_id: null,
      path: '/awards/0',
    }])

    expect(toSignalDetailView(detail).primaryNeed).toBeNull()
  })

  it('ne sélectionne aucun besoin ciblé sans référence de preuve exploitable', () => {
    const detail: UnlockedDetail = {
      ...UNLOCKED_DETAIL,
      evidence: {
        ...UNLOCKED_DETAIL.evidence,
        analysis_inputs: {
          ...UNLOCKED_DETAIL.evidence.analysis_inputs,
          groups: UNLOCKED_DETAIL.evidence.analysis_inputs.groups.map((group) => ({
            ...group,
            items: group.items.map((item) => ({
              ...item,
              url: '  ',
              path: null,
              notice_id: null,
              procedure_id: null,
            })),
          })),
        },
      },
    }

    expect(toSignalDetailView(detail).primaryNeed).toBeNull()
  })

  it('ne synthétise pas une raison d’adéquation depuis un score ou une catégorie', () => {
    const item = {
      ...UNLOCKED_ITEM,
      presentation: null,
      analysis: {
        ...UNLOCKED_ITEM.analysis,
        fit: {
          ...UNLOCKED_ITEM.analysis.fit,
          reasons: [],
          score: 0.91,
          category: 'materials_or_components',
        },
      },
    } as UnlockedFeedItem & {
      analysis: UnlockedFeedItem['analysis'] & {
        fit: UnlockedFeedItem['analysis']['fit'] & { score: number; category: string }
      }
    }

    expect(toSignalCard(item).fitReason).toBeNull()
    expect(toSignalCard(item).matchLabel).toBeNull()
  })

  it('retient uniquement la première raison backend non vide', () => {
    const item: UnlockedFeedItem = {
      ...UNLOCKED_ITEM,
      analysis: {
        ...UNLOCKED_ITEM.analysis,
        fit: {
          ...UNLOCKED_ITEM.analysis.fit,
          reasons: ['  ', '  Besoin visé : Matériaux  ', 'Territoire couvert : FR'],
        },
      },
    }

    expect(toSignalCard(item).fitReason).toBe('Besoin visé : Matériaux')
  })

  it('ne promeut jamais le titre administratif du contrat dans la copie de carte', () => {
    const administrativeTitle = 'ACCORD-CADRE LOT 7 PERSONNEL ET MATÉRIAUX'
    const item = {
      ...UNLOCKED_ITEM,
      contract: { ...UNLOCKED_ITEM.contract, title: administrativeTitle },
      presentation: null,
    } as UnlockedFeedItem

    const view = toSignalCard(item)
    expect(view.eventTitle).toBeNull()
    expect(JSON.stringify(view)).not.toContain(administrativeTitle)
    expect(view.presentation).toBeNull()
  })

  it('transporte sans réécriture le fallback factuel publié par le backend', () => {
    const presentation: CardPresentation = {
      artifact_id: 'a'.repeat(64),
      version: 1,
      status: 'FALLBACK',
      schema_version: 'card-presentation-v1',
      published_at: '2026-08-30T12:00:00Z',
      content: {
        schema_version: 'card-presentation-v1',
        variant: 'FACTUAL_FALLBACK',
        headline: 'Attribution publique documentée',
        award_summary: 'Le marché public a été attribué à une entreprise identifiée.',
        commercial_importance: null,
        fit_reason: null,
        timing: null,
        recommended_action: null,
        target_roles: [],
        fit_need_categories: [],
        unknowns: [],
        claims: [{
          claim_id: 'HEADLINE',
          kind: 'FACT',
          text: 'Attribution publique documentée',
          evidence_refs: ['source:award'],
          confidence: null,
        }],
      },
    }
    const item: UnlockedFeedItem = { ...UNLOCKED_ITEM, presentation }

    const view = toSignalCard(item)
    expect(view.presentation).toBe(presentation)
    expect(view.eventTitle).toBe(presentation.content.headline)
  })

  it('mappe une carte déverrouillée uniquement depuis le contrat de feed', () => {
    expect(toSignalCard(UNLOCKED_ITEM)).toEqual({
      signalId: UNLOCKED_ITEM.signal_id,
      id: UNLOCKED_ITEM.signal_id,
      locked: false,
      companyName: UNLOCKED_ITEM.company.name,
      awardedCompanyName: UNLOCKED_ITEM.company.name,
      buyerName: UNLOCKED_ITEM.contract.buyer?.name,
      eventTitle: null,
      amount: UNLOCKED_ITEM.contract.amount,
      location: UNLOCKED_ITEM.contract.location,
      eventDate: UNLOCKED_ITEM.event.date,
      eventDateKind: 'award',
      awardDate: UNLOCKED_ITEM.contract.dates.award,
      matchLabel: UNLOCKED_ITEM.analysis.fit.reasons[0],
      matchReasons: UNLOCKED_ITEM.analysis.fit.reasons,
      primaryNeed: null,
      fitReason: UNLOCKED_ITEM.analysis.fit.reasons[0],
      presentation: null,
      sourceSystem: UNLOCKED_ITEM.source.system,
      whyNow: UNLOCKED_ITEM.event.why_now,
    })
  })

  it('ne révèle aucun champ protégé dans une carte verrouillée', () => {
    const locked: LockedFeedItem = LOCKED_ITEM

    expect(toSignalCard(locked)).toEqual({
      signalId: locked.signal_id,
      id: locked.signal_id,
      locked: true,
      companyName: null,
      awardedCompanyName: null,
      buyerName: null,
      eventTitle: locked.headline,
      amount: null,
      location: null,
      eventDate: locked.event.date,
      eventDateKind: 'award',
      awardDate: null,
      matchLabel: null,
      matchReasons: [],
      primaryNeed: null,
      fitReason: null,
      presentation: null,
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
      signalId: detail.signal_id,
      id: detail.signal_id,
      locked: false,
      eventDate: detail.event.date,
      eventDateKind: 'award',
      buyerName: detail.contract.buyer?.name,
      awardedCompanyName: detail.company.name,
      primaryNeed: {
        label: detail.analysis.plausible_needs.items[0].label,
        evidenceRefs: [
          `evidence:url:${encodeURIComponent(
            detail.evidence.analysis_inputs.groups[0].items[0].url!,
          )}`,
        ],
      },
      fitReason: detail.analysis.fit.reasons[0],
      presentation: null,
      title: null,
      companyName: detail.company.name,
      companyKey: detail.company_key ?? null,
      companyCountry: detail.company.country,
      companyIdentifier: detail.company.identifier,
      targetProfileLabel: detail.analysis.fit.target_icp_label,
      sourceSystem: detail.source.system,
      summary: null,
      brief: {
        whyNow: detail.event.why_now,
        offerCoverage: detail.analysis.plausible_needs.items[0].label,
        functionToFind: null,
        unknown: detail.analysis.plausible_needs.note,
      },
      facts: {
        amount: detail.contract.amount,
        awardDate: detail.contract.dates.award,
        execution: null,
        buyer: detail.contract.buyer?.name ?? null,
        officialTitle: detail.contract.title,
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

function detailWithEvidenceItems(items: EvidenceItem[]): UnlockedDetail {
  return {
    ...UNLOCKED_DETAIL,
    evidence: {
      ...UNLOCKED_DETAIL.evidence,
      analysis_inputs: {
        ...UNLOCKED_DETAIL.evidence.analysis_inputs,
        groups: [{
          plausible_need: 'materials_or_components',
          label: 'Matériaux ou composants',
          items,
        }],
      },
    },
  }
}
