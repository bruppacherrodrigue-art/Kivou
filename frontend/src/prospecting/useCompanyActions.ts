import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { companies } from '../api/endpoints'
import type { CompanyCapabilities, CompanyContactStatus, ManualContactInput, ManualContactView } from '../api/types'
import { useProspecting } from './ProspectingProvider'

export interface ActionableCompany {
  /** The requested alias, not the canonical public identity. */
  company_key: string
  private_subject_key: string | null
  capabilities: CompanyCapabilities
}
type CompanyAction = 'follow' | 'status' | 'contact' | 'delete'
interface CompanyActionState { key: string; pending: CompanyAction | null; error: unknown | null; contactConflict: ManualContactView | null }

export function useCompanyActions(company: ActionableCompany | null) {
  const { accountId, accessEpoch, run, invalidate } = useProspecting()
  const key = JSON.stringify([accountId, company?.private_subject_key, company?.company_key, accessEpoch])
  const currentKey = useRef(key)
  currentKey.current = key
  const controller = useRef<AbortController | null>(null)
  const [state, setState] = useState<CompanyActionState>({ key, pending: null, error: null, contactConflict: null })
  useEffect(() => () => { controller.current?.abort(); controller.current = null }, [key])
  const execute = useCallback(async <T,>(action: CompanyAction, capability: keyof CompanyCapabilities, load: (companyKey: string, signal: AbortSignal) => Promise<T>) => {
    if (!company?.private_subject_key || !company.capabilities[capability]) throw new Error('Company action not permitted by the dossier')
    if (controller.current) throw new Error('A company action is already pending')
    const requestController = new AbortController()
    controller.current = requestController
    setState({ key, pending: action, error: null, contactConflict: null })
    try {
      const result = await run((signal) => load(company.company_key, signal), requestController.signal)
      if (!requestController.signal.aborted && currentKey.current === key) {
        setState({ key, pending: null, error: null, contactConflict: null })
        invalidate()
      }
      return result
    } catch (error) {
      if (!requestController.signal.aborted && currentKey.current === key) {
        const extra = error instanceof ApiError && error.status === 409 && error.code === 'manual_contact_conflict' ? error.extra : null
        const contactConflict = extra && Number.isSafeInteger(extra.revision) && (extra.contact === null || typeof extra.contact === 'object')
          ? extra as unknown as ManualContactView : null
        setState({ key, pending: null, error, contactConflict })
      }
      throw error
    } finally { if (controller.current === requestController) controller.current = null }
  }, [company, key, run, invalidate])
  return {
    pending: state.key === key ? state.pending : null,
    error: state.key === key ? state.error : null,
    contactConflict: state.key === key ? state.contactConflict : null,
    follow: () => execute('follow', 'can_follow_company', (key, signal) => companies.follow(key, { signal })),
    setContactStatus: (status: CompanyContactStatus) => execute('status', 'can_follow_company', (key, signal) => companies.contact(key, status, { signal })),
    saveContact: (input: ManualContactInput) => execute('contact', 'can_manage_personal_contact', (key, signal) => companies.saveManualContact(key, input, { signal })),
    deleteContact: (revision: number) => execute('delete', 'can_manage_personal_contact', (key, signal) => companies.deleteManualContact(key, revision, { signal })),
    reload: invalidate,
  }
}
