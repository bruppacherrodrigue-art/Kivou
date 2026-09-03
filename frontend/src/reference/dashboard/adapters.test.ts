import { describe, expect, it } from 'vitest'
import type {
  BillingStatus,
  CardPresentation,
  CompanyProfile,
  Evidence,
  FeedPage,
  LockedFeedItem,
  TargetIcp,
  UnlockedFeedItem,
} from '../../api/types'
import {
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_ITEM,
  feedPage,
} from '../../test/harness'
import {
  eventDateKind,
  publishedFactualDisplay,
  publishedPresentation,
  publishedWinnerEnrichment,
  toBillingAccessView,
  toCompanySummary,
  toOverviewAwardCard,
  toOverviewAwardCards,
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

const VALID_FALLBACK: CardPresentation = {
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
    unknowns: [{
      text: 'Date de début non publiée',
      evidence_refs: ['source:unknown'],
    }],
    claims: [{
      claim_id: 'HEADLINE',
      kind: 'FACT',
      text: 'Attribution publique documentée',
      evidence_refs: ['source:award'],
      confidence: null,
    }, {
      claim_id: 'AWARD_SUMMARY',
      kind: 'FACT',
      text: 'Une entreprise identifiée est attributaire du marché.',
      evidence_refs: ['source:award_summary'],
      confidence: null,
    }],
  },
}

const VALID_FULL: CardPresentation = {
  artifact_id: 'c'.repeat(64),
  version: 2,
  status: 'PASS',
  schema_version: 'card-presentation-v1',
  published_at: '2026-08-30T14:00:00+02:00',
  content: {
    schema_version: 'card-presentation-v1',
    variant: 'FULL',
    headline: 'Attribution publique documentée',
    award_summary: 'Une entreprise identifiée est attributaire du marché.',
    commercial_importance: 'Le montant publié rend le marché commercialement significatif.',
    fit_reason: 'Le besoin documenté correspond au ciblage déclaré.',
    timing: 'Le calendrier opérationnel reste à confirmer.',
    recommended_action: 'Vérifier le besoin auprès du responsable achats.',
    target_roles: [{
      role: 'PROCUREMENT_MANAGER',
      rationale: 'Fonction pertinente pour vérifier le besoin documenté.',
      evidence_refs: ['source:role'],
    }],
    fit_need_categories: ['materials_or_components'],
    unknowns: [{
      text: 'Date de début non publiée',
      evidence_refs: ['source:unknown'],
    }],
    claims: [{
      claim_id: 'HEADLINE',
      kind: 'FACT',
      text: 'Attribution publique documentée',
      evidence_refs: ['source:award'],
      confidence: null,
    }, {
      claim_id: 'AWARD_SUMMARY',
      kind: 'FACT',
      text: 'Une entreprise identifiée est attributaire du marché.',
      evidence_refs: ['source:award_summary'],
      confidence: null,
    }, {
      claim_id: 'COMMERCIAL_IMPORTANCE',
      kind: 'INFERENCE',
      text: 'Le montant publié rend le marché commercialement significatif.',
      evidence_refs: ['source:amount'],
      confidence: 'high',
    }, {
      claim_id: 'FIT_REASON',
      kind: 'INFERENCE',
      text: 'Le besoin documenté correspond au ciblage déclaré.',
      evidence_refs: ['source:fit'],
      confidence: 'medium',
    }, {
      claim_id: 'TIMING',
      kind: 'INFERENCE',
      text: 'Le calendrier opérationnel reste à confirmer.',
      evidence_refs: ['source:date'],
      confidence: 'low',
    }, {
      claim_id: 'RECOMMENDED_ACTION',
      kind: 'RECOMMENDATION',
      text: 'Vérifier le besoin auprès du responsable achats.',
      evidence_refs: ['source:action'],
      confidence: null,
    }],
  },
}

type MutableObject = Record<string, unknown>
type MutablePresentation = MutableObject & {
  content: MutableObject & {
    claims: MutableObject[]
    target_roles: MutableObject[]
    fit_need_categories: unknown[]
    unknowns: MutableObject[]
  }
}
type PresentationMutant = readonly [
  string,
  CardPresentation,
  (presentation: MutablePresentation) => void,
]

function mutatePresentation(
  source: CardPresentation,
  mutate: (presentation: MutablePresentation) => void,
): MutablePresentation {
  const candidate = structuredClone(source) as unknown as MutablePresentation
  mutate(candidate)
  return candidate
}

function setClaimedText(
  presentation: MutablePresentation,
  field: string,
  claimIndex: number,
  text: string,
) {
  presentation.content[field] = text
  presentation.content.claims[claimIndex].text = text
}

function appendFactClaim(
  presentation: MutablePresentation,
  claimId: string,
  text: string,
) {
  presentation.content.claims.push({
    claim_id: claimId,
    kind: 'FACT',
    text,
    evidence_refs: ['source:extra'],
    confidence: null,
  })
}

const STRICT_PRESENTATION_MUTANTS = [
  ['extra envelope key', VALID_FALLBACK, (value) => { value.qa_status = 'PASS' }],
  ['missing envelope key', VALID_FALLBACK, (value) => { delete value.published_at }],
  ['short artifact id', VALID_FALLBACK, (value) => { value.artifact_id = 'a'.repeat(63) }],
  ['uppercase artifact id', VALID_FALLBACK, (value) => { value.artifact_id = 'A'.repeat(64) }],
  ['non hexadecimal artifact id', VALID_FALLBACK, (value) => { value.artifact_id = 'g'.repeat(64) }],
  ['zero version', VALID_FALLBACK, (value) => { value.version = 0 }],
  ['fractional version', VALID_FALLBACK, (value) => { value.version = 1.5 }],
  ['string version', VALID_FALLBACK, (value) => { value.version = '1' }],
  ['unsafe integer version', VALID_FALLBACK, (value) => {
    value.version = Number.MAX_SAFE_INTEGER + 1
  }],
  ['invalid calendar datetime', VALID_FALLBACK, (value) => {
    value.published_at = '2026-02-30T12:00:00Z'
  }],
  ['datetime without timezone', VALID_FALLBACK, (value) => {
    value.published_at = '2026-08-30T12:00:00'
  }],
  ['datetime with invalid offset', VALID_FALLBACK, (value) => {
    value.published_at = '2026-08-30T12:00:00+24:00'
  }],
  ['untrimmed datetime', VALID_FALLBACK, (value) => {
    value.published_at = ' 2026-08-30T12:00:00Z'
  }],
  ['extra content key', VALID_FALLBACK, (value) => { value.content.provider = 'private' }],
  ['missing content key', VALID_FALLBACK, (value) => {
    delete (value.content as MutableObject).unknowns
  }],
  ['mismatched status variant', VALID_FALLBACK, (value) => { value.content.variant = 'FULL' }],
  ['mismatched schema', VALID_FALLBACK, (value) => {
    value.content.schema_version = 'card-presentation-v2'
  }],
  ['untrimmed headline', VALID_FALLBACK, (value) => {
    setClaimedText(value, 'headline', 0, ' Attribution publique documentée')
  }],
  ['headline longer than 160 code points', VALID_FALLBACK, (value) => {
    setClaimedText(value, 'headline', 0, 'é'.repeat(161))
  }],
  ['summary longer than 420 code points', VALID_FALLBACK, (value) => {
    setClaimedText(value, 'award_summary', 1, 'é'.repeat(421))
  }],
  ['commercial text longer than 420 code points', VALID_FULL, (value) => {
    setClaimedText(value, 'commercial_importance', 2, 'é'.repeat(421))
  }],
  ['action text longer than 320 code points', VALID_FULL, (value) => {
    setClaimedText(value, 'recommended_action', 5, 'é'.repeat(321))
  }],
  ['claims is not an array', VALID_FALLBACK, (value) => { value.content.claims = null as never }],
  ['claims is empty', VALID_FALLBACK, (value) => { value.content.claims = [] }],
  ['more than twelve claims', VALID_FALLBACK, (value) => {
    while (value.content.claims.length < 13) {
      const index = value.content.claims.length
      appendFactClaim(value, `EXTRA_${index}`, `Fait supplémentaire ${index}`)
    }
  }],
  ['extra claim key', VALID_FALLBACK, (value) => { value.content.claims[0].provider = 'private' }],
  ['missing claim key', VALID_FALLBACK, (value) => {
    delete value.content.claims[0].evidence_refs
  }],
  ['invalid claim id grammar', VALID_FALLBACK, (value) => {
    value.content.claims[0].claim_id = 'headline-invalid'
  }],
  ['duplicate claim ids', VALID_FALLBACK, (value) => {
    value.content.claims[1].claim_id = value.content.claims[0].claim_id
  }],
  ['invalid claim kind', VALID_FALLBACK, (value) => {
    value.content.claims[0].kind = 'OPINION'
  }],
  ['inference without confidence', VALID_FULL, (value) => {
    value.content.claims[2].confidence = null
  }],
  ['fact with confidence', VALID_FALLBACK, (value) => {
    value.content.claims[0].confidence = 'high'
  }],
  ['non string claim text', VALID_FALLBACK, (value) => {
    value.content.claims[0].text = 42
  }],
  ['untrimmed claim text', VALID_FALLBACK, (value) => {
    appendFactClaim(value, 'EXTRA', ' Fait supplémentaire')
  }],
  ['claim text longer than 420 code points', VALID_FALLBACK, (value) => {
    appendFactClaim(value, 'EXTRA', 'é'.repeat(421))
  }],
  ['claim evidence is not an array', VALID_FALLBACK, (value) => {
    value.content.claims[0].evidence_refs = 'source:award'
  }],
  ['claim evidence is empty', VALID_FALLBACK, (value) => {
    value.content.claims[0].evidence_refs = []
  }],
  ['more than sixteen claim refs', VALID_FALLBACK, (value) => {
    value.content.claims[0].evidence_refs = Array.from(
      { length: 17 },
      (_, index) => `source:award:${index}`,
    )
  }],
  ['untrimmed evidence ref', VALID_FALLBACK, (value) => {
    value.content.claims[0].evidence_refs = [' source:award']
  }],
  ['evidence ref longer than 256 code points', VALID_FALLBACK, (value) => {
    value.content.claims[0].evidence_refs = ['r'.repeat(257)]
  }],
  ['headline without exact fact claim', VALID_FALLBACK, (value) => {
    value.content.headline = 'Titre sans claim exacte'
  }],
  ['summary without exact fact claim', VALID_FALLBACK, (value) => {
    value.content.award_summary = 'Résumé sans claim exacte'
  }],
  ['commercial field without exact inference', VALID_FULL, (value) => {
    value.content.fit_reason = 'Adéquation sans claim exacte'
  }],
  ['unknowns is not an array', VALID_FALLBACK, (value) => { value.content.unknowns = null as never }],
  ['more than eight unknowns', VALID_FALLBACK, (value) => {
    value.content.unknowns = Array.from({ length: 9 }, (_, index) => ({
      text: `Inconnue ${index}`,
      evidence_refs: [`source:unknown:${index}`],
    }))
  }],
  ['extra unknown key', VALID_FALLBACK, (value) => {
    value.content.unknowns[0].provider = 'private'
  }],
  ['missing unknown key', VALID_FALLBACK, (value) => {
    delete value.content.unknowns[0].evidence_refs
  }],
  ['untrimmed unknown text', VALID_FALLBACK, (value) => {
    value.content.unknowns[0].text = ' Date de début non publiée'
  }],
  ['unknown longer than 240 code points', VALID_FALLBACK, (value) => {
    value.content.unknowns[0].text = 'é'.repeat(241)
  }],
  ['unknown without proof', VALID_FALLBACK, (value) => {
    value.content.unknowns[0].evidence_refs = []
  }],
  ['more than sixteen unknown refs', VALID_FALLBACK, (value) => {
    value.content.unknowns[0].evidence_refs = Array.from(
      { length: 17 },
      (_, index) => `source:unknown:${index}`,
    )
  }],
  ['target roles is not an array', VALID_FULL, (value) => {
    value.content.target_roles = null as never
  }],
  ['more than six target roles', VALID_FULL, (value) => {
    value.content.target_roles = Array.from({ length: 7 }, () => ({
      ...value.content.target_roles[0],
    }))
  }],
  ['extra role key', VALID_FULL, (value) => {
    value.content.target_roles[0].provider = 'private'
  }],
  ['missing role key', VALID_FULL, (value) => {
    delete value.content.target_roles[0].evidence_refs
  }],
  ['invalid role kind', VALID_FULL, (value) => {
    value.content.target_roles[0].role = 'CHIEF_EXECUTIVE'
  }],
  ['duplicate roles', VALID_FULL, (value) => {
    value.content.target_roles.push({ ...value.content.target_roles[0] })
  }],
  ['untrimmed role rationale', VALID_FULL, (value) => {
    value.content.target_roles[0].rationale = ' Fonction pertinente'
  }],
  ['role rationale longer than 420 code points', VALID_FULL, (value) => {
    value.content.target_roles[0].rationale = 'é'.repeat(421)
  }],
  ['role without proof', VALID_FULL, (value) => {
    value.content.target_roles[0].evidence_refs = []
  }],
  ['more than sixteen role refs', VALID_FULL, (value) => {
    value.content.target_roles[0].evidence_refs = Array.from(
      { length: 17 },
      (_, index) => `source:role:${index}`,
    )
  }],
  ['need categories is not an array', VALID_FULL, (value) => {
    value.content.fit_need_categories = null as never
  }],
  ['more than eight need categories', VALID_FULL, (value) => {
    value.content.fit_need_categories = Array.from(
      { length: 9 },
      () => 'materials_or_components',
    )
  }],
  ['invalid need category', VALID_FULL, (value) => {
    value.content.fit_need_categories[0] = 'personnel'
  }],
  ['duplicate need categories', VALID_FULL, (value) => {
    value.content.fit_need_categories.push('materials_or_components')
  }],
  ['fallback with commercial text', VALID_FALLBACK, (value) => {
    value.content.fit_reason = 'Conclusion commerciale interdite'
  }],
  ['fallback with target role', VALID_FALLBACK, (value) => {
    value.content.target_roles = structuredClone(
      VALID_FULL.content.target_roles,
    ) as unknown as MutableObject[]
  }],
  ['fallback with need category', VALID_FALLBACK, (value) => {
    value.content.fit_need_categories = ['materials_or_components']
  }],
  ['fallback with inference claim', VALID_FALLBACK, (value) => {
    value.content.claims.push(
      structuredClone(VALID_FULL.content.claims[2]) as unknown as MutableObject,
    )
  }],
  ['full without commercial text', VALID_FULL, (value) => {
    value.content.commercial_importance = null
  }],
  ['full without target role', VALID_FULL, (value) => { value.content.target_roles = [] }],
  ['full without need category', VALID_FULL, (value) => {
    value.content.fit_need_categories = []
  }],
] satisfies readonly PresentationMutant[]

describe('adaptateurs de présentation du dashboard de référence', () => {
  it('projette le Dashboard depuis le même artefact FALLBACK publié sans titre brut', () => {
    const item: UnlockedFeedItem = {
      ...UNLOCKED_ITEM,
      presentation: VALID_FALLBACK,
      contract: {
        ...UNLOCKED_ITEM.contract,
        title: 'TITRE ADMINISTRATIF INTERDIT',
        buyer: { name: 'Commune acheteuse', country: 'FR', identifier: null },
      },
    }

    expect(toOverviewAwardCard(item)).toEqual(expect.objectContaining({
      id: item.signal_id,
      locked: false,
      presentationArtifactId: VALID_FALLBACK.artifact_id,
      companyName: item.company.name,
      buyerName: 'Commune acheteuse',
      headline: VALID_FALLBACK.content.headline,
      awardSummary: VALID_FALLBACK.content.award_summary,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: 'FACTUAL_FALLBACK',
      eventDate: item.event.date,
      eventDateKind: 'award',
    }))
    expect(JSON.stringify(toOverviewAwardCard(item))).not.toContain(item.contract.title)
  })

  it('expose les conclusions commerciales uniquement depuis un artefact PASS/FULL valide', () => {
    const card = toOverviewAwardCard({ ...UNLOCKED_ITEM, presentation: VALID_FULL })

    expect(card).toEqual(expect.objectContaining({
      presentationArtifactId: VALID_FULL.artifact_id,
      headline: VALID_FULL.content.headline,
      awardSummary: VALID_FULL.content.award_summary,
      commercialImportance: VALID_FULL.content.commercial_importance,
      fitReason: VALID_FULL.content.fit_reason,
      timing: VALID_FULL.content.timing,
      recommendedAction: VALID_FULL.content.recommended_action,
      presentationVariant: 'FULL',
    }))
  })

  it('échoue fermé sur une présentation absente ou malformée sans perdre les faits structurés', () => {
    const malformed = mutatePresentation(VALID_FALLBACK, (value) => {
      value.content.claims[0].evidence_refs = []
    })

    for (const presentation of [null, malformed]) {
      const card = toOverviewAwardCard({
        ...UNLOCKED_ITEM,
        presentation: presentation as CardPresentation | null,
        contract: { ...UNLOCKED_ITEM.contract, title: 'TITRE BRUT À NE PAS RECONSTRUIRE' },
      })
      expect(card).toEqual(expect.objectContaining({
        presentationArtifactId: null,
        headline: null,
        awardSummary: null,
        commercialImportance: null,
        fitReason: null,
        amount: UNLOCKED_ITEM.contract.amount,
        eventDate: UNLOCKED_ITEM.event.date,
      }))
      expect(JSON.stringify(card)).not.toContain('TITRE BRUT À NE PAS RECONSTRUIRE')
    }
  })

  it('ignore toute présentation injectée dans un teaser verrouillé', () => {
    const leakingLocked = { ...LOCKED_ITEM, presentation: VALID_FULL } as unknown as FeedPage['items'][number]
    const card = toOverviewAwardCard(leakingLocked)

    expect(card.locked).toBe(true)
    expect(card.presentationArtifactId).toBeNull()
    expect(card.headline).toBeNull()
    expect(card.awardSummary).toBeNull()
    expect(JSON.stringify(card)).not.toContain(VALID_FULL.content.headline)
  })

  it('conserve strictement l’ordre du feed dans la projection Overview', () => {
    const first = { ...UNLOCKED_ITEM, presentation: VALID_FALLBACK }
    const second = { ...LOCKED_ITEM, signal_id: 'sig_locked_second' }

    expect(toOverviewAwardCards(feedPage([first, second]) as FeedPage).map((card) => card.id)).toEqual([
      first.signal_id,
      second.signal_id,
    ])
  })

  it.each([
    ['FALLBACK/FACTUAL_FALLBACK', VALID_FALLBACK],
    ['PASS/FULL', VALID_FULL],
  ] as const)('accepte sans réécrire un artefact public valide %s', (_case, presentation) => {
    expect(publishedPresentation(presentation)).toBe(presentation)
  })

  it.each(STRICT_PRESENTATION_MUTANTS)(
    'rejette le mutant de contrat public : %s',
    (_case, source, mutate) => {
      const presentation = mutatePresentation(source, mutate)
      expect(publishedPresentation(presentation)).toBeNull()
    },
  )

  it('ne normalise jamais un texte invalide avant de le refuser', () => {
    const presentation = mutatePresentation(VALID_FALLBACK, (value) => {
      setClaimedText(value, 'headline', 0, ' Attribution publique documentée ')
    })

    expect(publishedPresentation(presentation)).toBeNull()
    expect(presentation.content.headline).toBe(' Attribution publique documentée ')
  })

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

  it('ferme aussi statiquement les faits et l’enrichissement d’un teaser verrouillé', () => {
    const leaking = {
      ...LOCKED_ITEM,
      factual_display: UNLOCKED_ITEM.factual_display,
      winner_enrichment: UNLOCKED_ITEM.winner_enrichment,
    }
    // @ts-expect-error Le teaser ne porte jamais ces clés protégées.
    const invalid: LockedFeedItem = leaking

    expect(invalid.factual_display).toBe(UNLOCKED_ITEM.factual_display)
  })

  it.each([
    ['complétude inconnue', {
      ...UNLOCKED_ITEM.factual_display,
      completeness: 'smart',
    }],
    ['clé supplémentaire', {
      ...UNLOCKED_ITEM.factual_display,
      commercial_relevance: 'forte',
    }],
    ['résumé et objet divergents', {
      ...UNLOCKED_ITEM.factual_display,
      object_short: 'Objet reconstruit côté navigateur',
    }],
  ])('rejette un contrat factuel invalide : %s', (_case, display) => {
    expect(publishedFactualDisplay(display)).toBeNull()
  })

  it('rejette un état d’enrichissement incohérent', () => {
    const enrichment = {
      ...UNLOCKED_ITEM.winner_enrichment,
      status: 'completed',
      error_code: 'unexpected_failure',
    }

    expect(publishedWinnerEnrichment(enrichment)).toBeNull()
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

