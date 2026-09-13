import type { CompanyDossierResponse, Money, UnlockedFeedItem } from '../api/types'

export interface NoticeDuration {
  value: string
  unit: 'DAY' | 'WEEK' | 'MONTH' | 'YEAR'
  scope: 'contract' | 'works' | 'purchase_order'
  period_kind: 'initial' | 'maximum' | 'unspecified'
  source_path: string
  source_notice_id?: string
  source_url?: string
  notice_kind?: 'contract_notice' | 'contract_award_notice'
}

export interface NoticeContact {
  organization_name: string
  organization_ref: string
  source: 'boamp'
  observed_at: string
  phone?: string
  email?: string
  website?: string
  contact_name?: string
}

export interface NoticeFacts {
  source_system: string
  source_notice_id: string
  source_url: string | null
  collected_at: string
  publication_date: string | null
  lot_identifier: string
  title: string | null
  description: string | null
  awarded_amount: Money | null
  minimum_amount: Money | null
  maximum_amount: Money | null
  calendar: {
    duration: NoticeDuration | null
    initial_duration: NoticeDuration | null
    maximum_duration: NoticeDuration | null
    renewals: number | null
  } | null
  buyers: { name: string }[]
  contacts: NoticeContact[]
  available_contact_fields: string[]
  contacts_locked: boolean
  notice_status: 'published' | 'notice_cancelled' | 'corrected'
}

export type ProspectingSignal = UnlockedFeedItem & {
  notice_facts?: NoticeFacts | null
  commercial_context?: { reason: string; offer_category: string | null; zone_label?: string | null }
}

export type Dossier = CompanyDossierResponse
