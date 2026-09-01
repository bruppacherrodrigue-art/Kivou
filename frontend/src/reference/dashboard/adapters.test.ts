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
  publishedFactualDisplay,
  publishedPresentation,
  publishedWinnerEnrichment,
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
    const item = { ...UNLOCKED_ITEM, factual_display: display } as unknown as UnlockedFeedItem
    expect(toSignalCard(item).eventTitle).toBeNull()
    expect(toSignalCard(item).factualCompleteness).toBeNull()
  })

  it('rejette un état d’enrichissement incohérent', () => {
    const enrichment = {
      ...UNLOCKED_ITEM.winner_enrichment,
      status: 'completed',
      error_code: 'unexpected_failure',
    }

    expect(publishedWinnerEnrichment(enrichment)).toBeNull()
    const item = { ...UNLOCKED_ITEM, winner_enrichment: enrichment } as unknown as UnlockedFeedItem
    expect(toSignalCard(item).winnerEnrichment).toBeNull()
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

  it('ignore les besoins plausibles même lorsqu’ils possèdent des preuves', () => {
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

    expect(toSignalDetailView(detail).primaryNeed).toBeNull()
  })

  it('produit une seule référence canonique pour une URL et son chemin', () => {
    const detail = detailWithEvidenceItems([{
      ...UNLOCKED_DETAIL.evidence.analysis_inputs.groups[0].items[0],
      url: 'https://source.test/notice/42',
      path: '/awards/0',
      notice_id: 'notice-ignored-because-url-resolves',
      procedure_id: 'procedure-ignored-because-url-resolves',
    }])

    expect(toSignalDetailView(detail).primaryNeed).toBeNull()
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

    expect(toSignalDetailView(detail).primaryNeed).toBeNull()
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

    expect(toSignalDetailView(detail).primaryNeed).toBeNull()
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

  it('ignore les raisons de fit existantes pendant la phase factuelle', () => {
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

    expect(toSignalCard(item).fitReason).toBeNull()
  })

  it('ne promeut jamais le titre administratif du contrat dans la copie de carte', () => {
    const administrativeTitle = 'ACCORD-CADRE LOT 7 PERSONNEL ET MATÉRIAUX'
    const item = {
      ...UNLOCKED_ITEM,
      contract: { ...UNLOCKED_ITEM.contract, title: administrativeTitle },
      presentation: null,
    } as UnlockedFeedItem

    const view = toSignalCard(item)
    expect(view.eventTitle).toBe(UNLOCKED_ITEM.factual_display.headline)
    expect(JSON.stringify(view)).not.toContain(administrativeTitle)
    expect(view.presentation).toBeNull()
  })

  it('ignore aussi un ancien fallback de présentation sur la page Signaux', () => {
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
        }, {
          claim_id: 'AWARD_SUMMARY',
          kind: 'FACT',
          text: 'Le marché public a été attribué à une entreprise identifiée.',
          evidence_refs: ['source:award_summary'],
          confidence: null,
        }],
      },
    }
    const item: UnlockedFeedItem = { ...UNLOCKED_ITEM, presentation }

    const view = toSignalCard(item)
    expect(view.presentation).toBeNull()
    expect(view.eventTitle).toBe(UNLOCKED_ITEM.factual_display.headline)
  })

  it('préfère le contrat factuel serveur et ignore tout contenu commercial sur Signaux', () => {
    const item = {
      ...UNLOCKED_ITEM,
      factual_display: {
        headline: 'Constructions Bertrand remporte un marché de 1 240 000 € à Villeneuve',
        market_summary: 'Réfection factuelle de la voirie',
        object_short: 'Réfection factuelle de la voirie',
        date: { value: '2026-08-04', kind: 'award' },
        completeness: 'verified',
        missing_fields: [],
      },
      winner_enrichment: {
        status: 'partial',
        missing_fields: ['website'],
        last_verified_at: '2026-08-18T09:00:00Z',
        error_code: null,
        source: {
          kind: 'public_notice',
          connector: 'boamp',
          notice_id: '26-12345',
          url: 'https://www.boamp.fr/avis/26-12345',
          retrieved_at: '2026-08-18T09:00:00Z',
        },
      },
      presentation: VALID_FULL,
    } as unknown as UnlockedFeedItem

    const view = toSignalCard(item)

    expect(view.eventTitle).toBe(item.factual_display.headline)
    expect(view.presentation).toBeNull()
    expect(view.fitReason).toBeNull()
    expect(view.matchLabel).toBeNull()
  })

  it('le détail Signaux ne lit ni besoin plausible, ni fit, ni présentation', () => {
    const detail = {
      ...UNLOCKED_DETAIL,
      factual_display: {
        headline: 'Titre factuel publié par le serveur',
        market_summary: 'Résumé factuel publié par le serveur',
        object_short: 'Résumé factuel publié par le serveur',
        date: { value: '2026-08-04', kind: 'award' },
        completeness: 'partial',
        missing_fields: ['location'],
      },
      winner_enrichment: {
        status: 'in_progress',
        missing_fields: ['address'],
        last_verified_at: null,
        error_code: null,
        source: {
          kind: 'public_notice',
          connector: 'boamp',
          notice_id: '26-12345',
          url: null,
          retrieved_at: '2026-08-18T09:00:00Z',
        },
      },
      presentation: VALID_FULL,
    } as unknown as UnlockedDetail

    const view = toSignalDetailView(detail)

    expect(view.title).toBe(detail.factual_display.headline)
    expect(view.summary).toBe(detail.factual_display.market_summary)
    expect(view.presentation).toBeNull()
    expect(view.primaryNeed).toBeNull()
    expect(view.fitReason).toBeNull()
    expect(view.brief.offerCoverage).toBeNull()
  })

  it('mappe une carte déverrouillée uniquement depuis le contrat de feed', () => {
    expect(toSignalCard(UNLOCKED_ITEM)).toEqual({
      signalId: UNLOCKED_ITEM.signal_id,
      id: UNLOCKED_ITEM.signal_id,
      locked: false,
      companyName: UNLOCKED_ITEM.company.name,
      awardedCompanyName: UNLOCKED_ITEM.company.name,
      buyerName: UNLOCKED_ITEM.contract.buyer?.name,
      eventTitle: UNLOCKED_ITEM.factual_display.headline,
      amount: UNLOCKED_ITEM.contract.amount,
      location: UNLOCKED_ITEM.contract.location,
      eventDate: UNLOCKED_ITEM.event.date,
      eventDateKind: 'award',
      awardDate: UNLOCKED_ITEM.contract.dates.award,
      matchLabel: null,
      matchReasons: [],
      primaryNeed: null,
      fitReason: null,
      presentation: null,
      factualCompleteness: UNLOCKED_ITEM.factual_display.completeness,
      missingFacts: UNLOCKED_ITEM.factual_display.missing_fields,
      winnerEnrichment: UNLOCKED_ITEM.winner_enrichment,
      sourceSystem: UNLOCKED_ITEM.source.system,
      whyNow: UNLOCKED_ITEM.event.why_now,
      objectShort: UNLOCKED_ITEM.factual_display.object_short,
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
      factualCompleteness: null,
      missingFacts: [],
      winnerEnrichment: null,
      sourceSystem: null,
      whyNow: locked.event.why_now,
      objectShort: null,
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
      primaryNeed: null,
      fitReason: null,
      presentation: null,
      factualCompleteness: detail.factual_display.completeness,
      missingFacts: detail.factual_display.missing_fields,
      winnerEnrichment: detail.winner_enrichment,
      title: detail.factual_display.headline,
      companyName: detail.company.name,
      companyKey: detail.company_key ?? null,
      companyCountry: detail.company.country,
      companyIdentifier: detail.company.identifier,
      targetProfileLabel: null,
      sourceSystem: detail.source.system,
      summary: detail.factual_display.market_summary,
      brief: {
        whyNow: detail.event.why_now,
        offerCoverage: null,
        functionToFind: null,
        unknown: null,
      },
      facts: {
        amount: detail.contract.amount,
        location: detail.contract.location,
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
