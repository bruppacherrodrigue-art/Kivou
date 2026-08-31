import { render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { I18nProvider } from '../i18n'
import type { Locale } from '../i18n'
import { SessionProvider } from '../auth/SessionProvider'
import type { SessionState } from '../auth/SessionProvider'
import type {
  BillingStatus,
  CardPresentation,
  CompanyProfile,
  LockedDetail,
  LockedFeedItem,
  Me,
  PlanCatalogue,
  TargetIcp,
  UnlockedDetail,
  UnlockedFeedItem,
} from '../api/types'

/* Le banc d'essai : une frontière HTTP déterministe, jamais un vrai réseau.
 *
 * `fetch` est remplacé par un routeur de test qui rend des charges utiles
 * calquées sur les réponses réelles du backend. Aucun appel ne part vers
 * Stripe, aucun SMTP n'est sollicité : ces intégrations sont des frontières,
 * et les tests s'arrêtent à la frontière.
 */

export interface RouteHandler {
  status?: number
  body?: unknown
  /** Compte les appels reçus, pour vérifier ce que le frontend a ENVOYÉ. */
  calls?: { method: string; body: unknown; url: string }[]
}

export type Routes = Record<
  string,
  RouteHandler | ((request: MockRequest) => RouteHandler | Promise<RouteHandler>)
>

export interface MockRequest {
  method: string
  url: string
  body: unknown
  search: URLSearchParams
}

export const recordedCalls: MockRequest[] = []

/** Installe le routeur de test. Une route absente échoue explicitement plutôt
 *  que de rendre un 200 vide : un appel oublié doit se voir. */
export function mockApi(routes: Routes) {
  recordedCalls.length = 0

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input.toString()
    const url = new URL(raw, 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? JSON.parse(init.body as string) : undefined

    const request: MockRequest = { method, url: url.pathname, body, search: url.searchParams }
    recordedCalls.push(request)

    const key = `${method} ${url.pathname}`
    const match = routes[key] ?? routes[url.pathname]

    if (!match) {
      return new Response(JSON.stringify({ detail: { code: 'signal_not_found' } }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      })
    }

    const resolved = typeof match === 'function' ? await match(request) : match
    const status = resolved.status ?? 200

    if (status === 204) return new Response(null, { status })

    return new Response(JSON.stringify(resolved.body ?? {}), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })

  vi.stubGlobal('fetch', handler)
  return handler
}

export function callsTo(path: string, method = 'POST'): MockRequest[] {
  return recordedCalls.filter((call) => call.url === path && call.method === method)
}

/** Une entrée d'historique de test : un chemin, ou un chemin ET son état de
 *  navigation — celui que `navigate(path, { state })` transporte. */
export type TestRoute = string | { pathname: string; search?: string; state?: unknown }

export function renderApp(
  ui: ReactElement,
  {
    session,
    route = '/',
    locale = 'fr',
  }: { session?: SessionState; route?: TestRoute; locale?: Locale } = {},
): RenderResult {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <I18nProvider initialLocale={locale}>
        <SessionProvider initialState={session}>{ui}</SessionProvider>
      </I18nProvider>
    </MemoryRouter>,
  )
}

// ─── Fixtures, calquées sur les réponses réelles ────────────────────────────

export const ME: Me = {
  user_id: 'usr_1',
  email: 'claire@acme.test',
  account_id: 'acc_1',
  account_display_name: 'Acme Solutions',
  locale: 'fr',
  onboarding_status: 'ready_for_signals',
  capabilities: { commercial_cockpit: false },
}

export const AUTHENTICATED: SessionState = { status: 'authenticated', me: ME }
export const UNAUTHENTICATED: SessionState = {
  status: 'unauthenticated',
  me: null,
  expired: false,
}
export const EXPIRED: SessionState = { status: 'unauthenticated', me: null, expired: true }

export function factualFallbackPresentation({
  artifactId,
  headline,
  awardSummary,
  headlineEvidenceRefs,
  awardSummaryEvidenceRefs,
}: {
  artifactId: string
  headline: string
  awardSummary: string
  headlineEvidenceRefs: [string, ...string[]]
  awardSummaryEvidenceRefs: [string, ...string[]]
}): CardPresentation {
  return {
    artifact_id: artifactId,
    version: 1,
    status: 'FALLBACK',
    schema_version: 'card-presentation-v1',
    published_at: '2026-08-30T12:00:00Z',
    content: {
      schema_version: 'card-presentation-v1',
      variant: 'FACTUAL_FALLBACK',
      headline,
      award_summary: awardSummary,
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
          text: headline,
          evidence_refs: headlineEvidenceRefs,
          confidence: null,
        },
        {
          claim_id: 'AWARD_SUMMARY',
          kind: 'FACT',
          text: awardSummary,
          evidence_refs: awardSummaryEvidenceRefs,
          confidence: null,
        },
      ],
    },
  }
}

export const UNLOCKED_ITEM: UnlockedFeedItem = {
  locked: false,
  signal_id: 'sig_unlocked_1',
  target_icp_id: 'icp_1',
  presentation: null,
  company: {
    name: 'Constructions Bertrand SA',
    country: 'FR',
    identifier: { scheme: 'SIRET', value: '12345678900011' },
  },
  event: {
    status: 'recent_award',
    type: 'recent_award',
    clock: 'award',
    date: '2026-08-04',
    age_days: 14,
    headline: 'Constructions Bertrand SA vient de remporter un marché public.',
    why_now: 'La décision est récente : les besoins d’exécution se décident maintenant.',
    award_date_note: 'La date d’attribution est publiée.',
    award_clock_status: 'recent',
    is_new_opportunity: true,
  },
  contract: {
    title: 'Réfection de la voirie communale — lot 2',
    lot: '2',
    lot_title: 'Voirie',
    reference: 'MP-2026-0412',
    buyer: { name: 'Commune de Villeneuve', country: 'FR', identifier: null },
    amount: { value: '1240000', currency: 'EUR' },
    cpv: '45233120',
    location: {
      country: 'FR',
      locality: 'Villeneuve',
      postal_code: '31270',
      subdivision_code: 'FR-31',
    },
    dates: {
      award: '2026-08-04',
      contract_notification: '2026-08-06',
      publication: '2026-08-10',
    },
  },
  analysis: {
    plausible_needs: {
      note: 'Ces besoins sont plausibles : ils découlent des exigences du marché, pas d’un achat annoncé.',
      items: [
        {
          category: 'materials_or_components',
          label: 'Matériaux ou composants',
          statement: 'Le chantier peut nécessiter un approvisionnement en enrobés.',
          confidence: 'medium',
          timing: 'near_term',
          timing_label: 'Court terme',
          targeted_by_your_profile: true,
          reasoning: 'Le cahier des charges impose 4 200 m² de reprise de chaussée.',
        },
      ],
    },
    fit: {
      label: 'Très bon pour votre profil',
      target_icp_id: 'icp_1',
      target_icp_label: 'Matériaux — Occitanie',
      reasons: ['Besoin visé : Matériaux ou composants', 'Territoire couvert : FR'],
    },
  },
  source: {
    system: 'BOAMP',
    country: 'FR',
    notice_id: '26-104412',
    procedure_id: 'proc-9981',
    url: 'https://www.boamp.fr/avis/26-104412',
  },
}

export const LOCKED_ITEM: LockedFeedItem = {
  locked: true,
  signal_id: 'sig_locked_1',
  target_icp_id: 'icp_1',
  unlock_required: 'paid_plan',
  event: {
    status: 'recent_award',
    type: 'recent_award',
    date: '2026-08-02',
    why_now: 'La décision est récente : les besoins d’exécution se décident maintenant.',
    is_new_opportunity: true,
  },
  context: {
    country: 'FR',
    place_country: 'FR',
    sector: 'Travaux publics',
    contract_magnitude: '250k_1m',
    currency: 'EUR',
    plausible_need_count: 2,
  },
  headline: 'Un marché public vient d’être attribué.',
}

/** Un signal ANCIEN : la formulation ne doit jamais dire « vient de remporter ». */
export const STALE_ITEM: UnlockedFeedItem = {
  ...UNLOCKED_ITEM,
  signal_id: 'sig_stale_1',
  company: { ...UNLOCKED_ITEM.company, name: 'Travaux Delmas SARL' },
  event: {
    status: 'stale_award',
    type: null,
    clock: 'award',
    date: '2025-11-12',
    age_days: 280,
    headline: 'Travaux Delmas SARL a remporté un marché public en novembre 2025.',
    why_now: 'Ce signal est sorti de la fenêtre commerciale utile.',
    award_date_note: 'La date d’attribution est publiée.',
    award_clock_status: 'stale',
    is_new_opportunity: false,
  },
}

export const UNLOCKED_DETAIL: UnlockedDetail = {
  ...UNLOCKED_ITEM,
  company_key: 'cmp_0123456789abcdefghijklmnop',
  analysis: {
    ...UNLOCKED_ITEM.analysis,
    contract_reading: {
      note: 'Lecture produite par Kivou à partir des pièces publiées.',
      summary: 'Marché de travaux de voirie sur trois tronçons communaux.',
      contract_type: 'Travaux',
      sector: 'Travaux publics',
    },
  },
  evidence: {
    public_facts: [
      {
        fact: 'award_winner',
        label: 'Attributaire',
        items: [
          {
            source_system: 'BOAMP',
            source_kind: 'notice',
            notice_id: '26-104412',
            procedure_id: 'proc-9981',
            url: 'https://www.boamp.fr/avis/26-104412',
            path: null,
            excerpt: 'Le marché est attribué à Constructions Bertrand SA.',
            retrieved_at: '2026-08-11T09:00:00+00:00',
          },
        ],
      },
    ],
    analysis_inputs: {
      note: 'Ces pièces documentent l’exigence dont le besoin est déduit. Elles ne prouvent pas un achat.',
      groups: [
        {
          plausible_need: 'materials_or_components',
          label: 'Matériaux ou composants',
          items: [
            {
              source_system: 'BOAMP',
              source_kind: 'document',
              notice_id: '26-104412',
              procedure_id: 'proc-9981',
              url: 'https://www.boamp.fr/avis/26-104412',
              path: null,
              excerpt: 'Reprise de chaussée sur 4 200 m², enrobés à chaud.',
              retrieved_at: '2026-08-11T09:00:00+00:00',
            },
          ],
        },
      ],
    },
  },
  opportunity_id: 'opp_1',
  customer_ready: true,
  read_at: '2026-08-18',
  language: 'fr',
  interaction: null,
}

export const LOCKED_DETAIL: LockedDetail = {
  ...LOCKED_ITEM,
  access: { granted: false, reason: 'plan_entitlement_required', upgrade_to: ['essential', 'pro', 'scale'] },
  read_at: '2026-08-18',
  language: 'fr',
}

export const COMPANY_PROFILE: CompanyProfile = {
  company_key: 'cmp_0123456789abcdefghijklmnop',
  official_identity: {
    name: 'Constructions Bertrand SA',
    country: 'FR',
    address: '12 rue des Ateliers, 31270 Villeneuve',
    identifiers: [
      { scheme: 'SIRET', value: '12345678900011' },
      { scheme: 'TVA', value: 'FR12123456789' },
    ],
    website_url: 'https://constructions-bertrand.example/entreprise',
    observed_at: '2026-08-23T12:00:00Z',
    source: 'public_notice',
  },
  related_signals: [
    {
      signal_id: 'sig_unlocked_1',
      contract_title: 'Réfection de la voirie communale — lot 2',
      amount: { value: '1240000', currency: 'EUR' },
      event: {
        status: 'recent_award',
        date: '2026-08-04',
        headline: 'Constructions Bertrand SA vient de remporter un marché public.',
        why_now: 'La décision est récente : les besoins d’exécution se décident maintenant.',
        award_date_note: 'La date d’attribution est publiée.',
      },
      plausible_needs: [
        {
          label: 'Matériaux ou composants',
          statement: 'Le chantier peut nécessiter un approvisionnement en enrobés.',
          timing_label: 'Court terme',
          reasoning: 'Le cahier des charges impose 4 200 m² de reprise de chaussée.',
        },
      ],
      fit: {
        label: 'Très bon pour votre profil',
        reasons: ['Besoin visé : Matériaux ou composants', 'Territoire couvert : FR'],
      },
    },
  ],
  coverage: {
    related_signals_complete: true,
    unavailable_fields: [],
  },
}

export const CATALOGUE: PlanCatalogue = {
  catalogue_version: 'kivou-plans-v0.1',
  billing_interval: 'month',
  currencies: ['chf', 'eur'],
  plans: [
    {
      plan_code: 'discovery',
      purchasable: false,
      recommended: false,
      monthly_price: {},
      entitlements: entitlements({ icps: 1, cadence: 'none', granted: 3, history: 0 }),
    },
    {
      plan_code: 'essential',
      purchasable: true,
      recommended: false,
      monthly_price: { chf: { amount_minor_units: 4900, currency: 'chf' }, eur: { amount_minor_units: 4900, currency: 'eur' } },
      entitlements: entitlements({ icps: 1, cadence: 'weekly', history: 30 }),
    },
    {
      plan_code: 'pro',
      purchasable: true,
      recommended: true,
      monthly_price: { chf: { amount_minor_units: 9900, currency: 'chf' }, eur: { amount_minor_units: 9900, currency: 'eur' } },
      entitlements: entitlements({ icps: 3, cadence: 'daily', history: 365, territory: 'multiple' }),
    },
    {
      plan_code: 'scale',
      purchasable: true,
      recommended: false,
      monthly_price: { chf: { amount_minor_units: 19900, currency: 'chf' }, eur: { amount_minor_units: 19900, currency: 'eur' } },
      entitlements: entitlements({
        icps: 10,
        cadence: 'priority',
        history: null,
        territory: 'expanded',
      }),
    },
  ],
}

function entitlements({
  icps,
  cadence,
  history,
  granted = 0,
  territory = 'single',
}: {
  icps: number
  cadence: 'none' | 'weekly' | 'daily' | 'priority'
  history: number | null
  granted?: number
  territory?: 'single' | 'multiple' | 'expanded'
}) {
  return {
    max_active_icps: icps,
    history_days: history,
    history_scope: (history === null ? 'all_available' : 'window') as 'all_available' | 'window',
    territory_mode: territory,
    max_territories_per_icp: territory === 'single' ? 1 : null,
    feed_access: true,
    detail_access: true,
    evidence_access: true,
    filter_level: 'basic' as const,
    export_level: 'none' as const,
    alert_cadence: cadence,
    granted_signals: granted,
  }
}

export const DISCOVERY_STATUS: BillingStatus = {
  plan_code: 'discovery',
  offer_code: null,
  currency: null,
  subscription_status: null,
  cancel_at_period_end: false,
  current_period_end: null,
  scheduled_cancellation_at: null,
  payment_issue: null,
  billing_action: 'choose_plan',
  entitlements: entitlements({ icps: 1, cadence: 'none', history: 0, granted: 3 }),
  discovery: { granted_signal_count: 3, remaining_slots: 0, limit: 3 },
  target_icps_over_limit: [],
  policy: { billing: 'kivou-billing-v0.1' },
}

export const PRO_STATUS: BillingStatus = {
  plan_code: 'pro',
  offer_code: null,
  currency: 'chf',
  subscription_status: 'active',
  cancel_at_period_end: false,
  current_period_end: '2026-09-18T00:00:00+00:00',
  scheduled_cancellation_at: null,
  payment_issue: null,
  billing_action: 'manage_subscription',
  entitlements: entitlements({ icps: 3, cadence: 'daily', history: 365, territory: 'multiple' }),
  discovery: { granted_signal_count: 3, remaining_slots: 0, limit: 3 },
  target_icps_over_limit: [],
  policy: { billing: 'kivou-billing-v0.1' },
}

/* Les états où le compte porte ENCORE un abonnement.
 *
 * Leur `plan_code` vaut `discovery` — exactement comme un compte qui n'a jamais
 * rien payé. C'est précisément le piège : seul `billing_action` les distingue,
 * et proposer un paiement à l'un d'eux le facturerait deux fois. */

/** Incident de paiement : l'abonnement existe, l'accès est suspendu. */
export const RECOVER_STATUS: BillingStatus = {
  ...DISCOVERY_STATUS,
  currency: 'chf',
  subscription_status: 'past_due',
  payment_issue: 'payment_past_due',
  billing_action: 'recover_payment',
  discovery: { granted_signal_count: 0, remaining_slots: 3, limit: 3 },
}

/** Anomalie de facturation : ni achat, ni promesse de réparation. */
export const SUPPORT_STATUS: BillingStatus = {
  ...DISCOVERY_STATUS,
  currency: 'chf',
  subscription_status: 'trialing',
  billing_action: 'contact_support',
  discovery: { granted_signal_count: 0, remaining_slots: 3, limit: 3 },
}

/** Tentative terminale : plus rien n'est facturé, la place est libre. */
export const TERMINAL_STATUS: BillingStatus = {
  ...DISCOVERY_STATUS,
  currency: 'chf',
  subscription_status: 'incomplete_expired',
  payment_issue: 'payment_incomplete_expired',
  billing_action: 'choose_plan',
  discovery: { granted_signal_count: 0, remaining_slots: 3, limit: 3 },
}

/** Abonnement payant qui s'arrêtera en fin de période — l'accès court encore.
 *
 * P0-03G — l'échéance vient de `scheduled_cancellation_at`, jamais d'un calcul
 * local ni de `current_period_end`. Ici les deux coïncident, ce qui est le cas
 * courant ; `PRO_CANCELLING_OTHER_DATE_STATUS` décrit celui où ils diffèrent. */
export const PRO_CANCELLING_STATUS: BillingStatus = {
  ...PRO_STATUS,
  cancel_at_period_end: true,
  scheduled_cancellation_at: '2026-09-18T00:00:00+00:00',
}

/** Résiliation planifiée à une AUTRE date que la fin de période.
 *
 * Stripe le permet. Parler de « fin de période » dans ce cas donnerait au
 * client une échéance fausse. */
export const PRO_CANCELLING_OTHER_DATE_STATUS: BillingStatus = {
  ...PRO_STATUS,
  cancel_at_period_end: false,
  scheduled_cancellation_at: '2026-11-30T00:00:00+00:00',
}

export const ICP: TargetIcp = {
  target_icp_id: 'icp_1',
  label: 'Matériaux — Occitanie',
  status: 'active',
  matching_revision: 1,
  plan_limit: null,
  customer_input: {
    offer_summary: '',
    offers: ['materials_and_components'],
    secondary_offers: [],
    buyer_trades: ['roads_and_civil_works'],
    secondary_buyer_trades: [],
    territories: ['FR'],
    minimum_contract_value: { currency: 'EUR', minimum_amount: 50000, maximum_amount: null },
  },
  missing_fields: [],
  created_at: '2026-08-01T09:00:00+00:00',
  updated_at: '2026-08-01T09:00:00+00:00',
}

export function feedPage(items: (UnlockedFeedItem | LockedFeedItem)[], overrides = {}) {
  return {
    items,
    total_returned: items.length,
    page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
    excluded: { without_display_name: 0, by_freshness: 0 },
    read_at: '2026-08-18',
    freshness: 'new',
    language: 'fr',
    plan_code: 'discovery',
    policy: { feed: 'customer-feed-v0.1', recency: 'v1', paywall: 'kivou-paywall-v0.1' },
    ...overrides,
  }
}
