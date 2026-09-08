import assert from 'node:assert/strict'
import test from 'node:test'
import { persistedAudit, procedureProof } from './discovery-audit.mjs'

const grant = (key, refs = [`procedure:FR:decp:${key}`]) => ({
  signal_key: key, opportunity_key: `opportunity-${key}`,
  procedure_references: refs, granted_at: '2026-09-08T09:00:00Z',
})
const receipt = (grants = [grant('bait')]) => ({
  dry_run: false, bait_preserved: true, audit_token: 'private-apply-audit', as_of: '2026-09-08',
  before: { used: 3 },
  // Proposals are intentionally inconsistent: only AFTER is persisted truth.
  proposed_grants: [grant('bait'), grant('proposal-two'), grant('proposal-three')],
  after: {
    account_id: 'qa-account', quota: 3, used: grants.length, remaining: 3 - grants.length,
    bait_signal_key: 'bait', legacy_bait_conflict: false, grants,
  },
})

test('apply receipt reports actual 1/3, never the proposed three; token is omitted', () => {
  const audit = persistedAudit(receipt(), 'qa-account', 1)
  assert.equal(audit.used, 1)
  assert.equal(audit.remaining, 2)
  assert.equal(audit.bait_signal_id, 'bait')
  assert.deepEqual(audit.grants.map((entry) => entry.signal_id), ['bait'])
  assert.equal(JSON.stringify(audit).includes('private-apply-audit'), false)
})

test('dry-run, account mismatch, wrong count and missing bait are rejected', () => {
  assert.throws(() => persistedAudit({ ...receipt(), dry_run: true }, 'qa-account', 1), /apply_receipt_required/)
  assert.throws(() => persistedAudit(receipt(), 'other-account', 1), /audit_account/)
  assert.throws(() => persistedAudit(receipt(), 'qa-account', 3), /audit_counter/)
  assert.throws(() => persistedAudit(receipt([grant('not-the-bait')]), 'qa-account', 1), /audit_bait_membership/)
})

test('maps API signal_id to audit signal_key with distinct backend procedure references', () => {
  const audit = persistedAudit(receipt([grant('bait'), grant('two'), grant('three')]), 'qa-account', 3)
  const proof = procedureProof(['three', 'bait', 'two'].map((signal_id) => ({ signal_id, source: { procedure_id: null } })), audit)
  assert.deepEqual(proof.map((entry) => entry.procedure_id), [null, null, null])
  assert.deepEqual(proof.map((entry) => entry.procedure_references[0]), [
    'procedure:FR:decp:three', 'procedure:FR:decp:bait', 'procedure:FR:decp:two',
  ])
})

test('overlapping aliases, duplicate grants and unaccounted API rows fail closed', () => {
  const audit = persistedAudit(receipt([grant('bait', ['procedure:uuid:shared']), grant('two', ['procedure:uuid:shared'])]), 'qa-account', 2)
  assert.throws(() => procedureProof([{ signal_id: 'bait' }, { signal_id: 'two' }], audit), /distinct_procedures/)
  assert.throws(() => procedureProof([{ signal_id: 'bait' }, { signal_id: 'unknown' }], audit), /audit_membership/)
  assert.throws(() => persistedAudit(receipt([grant('bait'), grant('bait')]), 'qa-account', 2), /audit_duplicate_keys/)
})

test('without an audit, existing API procedure IDs must be present and distinct', () => {
  const items = ['bait', 'two', 'three'].map((signal_id) => ({ signal_id, source: { procedure_id: `procedure-${signal_id}` } }))
  assert.equal(procedureProof(items, null).length, 3)
  assert.throws(() => procedureProof([{ signal_id: 'bait' }], null), /procedure_audit_required/)
  assert.throws(() => procedureProof([items[0], items[0]], null), /distinct_procedures/)
})
