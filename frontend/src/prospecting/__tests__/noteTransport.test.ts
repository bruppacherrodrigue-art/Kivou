import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { companies } from '../../api/endpoints'
import type { CompanyDossierResponse } from '../../api/types'
import { apiNoteTransport } from '../ProspectingProvider'

afterEach(() => vi.restoreAllMocks())
const identity = { accountId: 'a', kind: 'company' as const, entityId: 'isolated-private-key', addressKey: 'requested-alias' }
const options = { signal: new AbortController().signal }
describe('company note API identity binding', () => {
  it('reads and writes the requested alias while checking its server private subject', async () => {
    const read = vi.spyOn(companies, 'dossier').mockResolvedValue({ private_subject_key: identity.entityId, canonical_company_key: 'public-canonical-key', note: 'Own note', note_revision: 3, note_updated_at: null } as CompanyDossierResponse)
    const write = vi.spyOn(companies, 'note').mockResolvedValue({ company_key: identity.addressKey, note: 'Next', revision: 4, updated_at: 'now' })
    expect(await apiNoteTransport.read(identity, options)).toEqual({ note: 'Own note', revision: 3, updated_at: null })
    await apiNoteTransport.save(identity, { note: 'Next', expected_revision: 3 }, options)
    expect(read).toHaveBeenCalledWith('requested-alias', options)
    expect(write).toHaveBeenCalledWith('requested-alias', 'Next', 3, options)
  })

  it('refuses to bind a note editor to a different server private subject', async () => {
    vi.spyOn(companies, 'dossier').mockResolvedValue({ private_subject_key: 'another-private-key', note_revision: 0, note_updated_at: null } as CompanyDossierResponse)
    await expect(apiNoteTransport.read(identity, options)).rejects.toThrow('Private company identity changed')
    await expect(apiNoteTransport.save({ ...identity, addressKey: undefined }, { note: 'x', expected_revision: 0 }, options)).rejects.toThrow('addressed company key')
  })

  it('adapts the exact conflict extra envelope without an unnecessary GET', () => {
    expect(apiNoteTransport.conflict?.(new ApiError(409, 'note_conflict', '', { note: 'Server draft', revision: 7, updated_at: null })))
      .toEqual({ note: 'Server draft', revision: 7, updated_at: null })
  })
})
