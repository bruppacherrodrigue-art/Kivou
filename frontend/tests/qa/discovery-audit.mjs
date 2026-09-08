// Read-only QA assertions, not product eligibility or allocation rules.
const nonempty = (value) => typeof value === 'string' && value.trim().length > 0
const requireFact = (condition, code) => { if (!condition) throw new Error(code) }

export function persistedAudit(receipt, accountId, expectedCount) {
  requireFact(receipt?.dry_run === false, 'apply_receipt_required')
  const allocation = receipt.after
  requireFact(allocation?.account_id === accountId, 'audit_account')
  requireFact(allocation.quota === 3 && allocation.used === expectedCount
    && allocation.remaining === 3 - expectedCount, 'audit_counter')
  requireFact(receipt.bait_preserved === true && allocation.legacy_bait_conflict === false, 'audit_bait')
  requireFact(Array.isArray(allocation.grants) && allocation.grants.length === expectedCount, 'audit_grants')
  const grants = allocation.grants.map((grant) => {
    requireFact(nonempty(grant.signal_key) && Array.isArray(grant.procedure_references)
      && grant.procedure_references.length > 0 && grant.procedure_references.every(nonempty), 'audit_references')
    return { signal_id: grant.signal_key, procedure_references: [...grant.procedure_references] }
  })
  requireFact(new Set(grants.map((grant) => grant.signal_id)).size === expectedCount, 'audit_duplicate_keys')
  requireFact(nonempty(allocation.bait_signal_key)
    && grants.some((grant) => grant.signal_id === allocation.bait_signal_key), 'audit_bait_membership')
  return {
    account_id: allocation.account_id,
    used: allocation.used,
    remaining: allocation.remaining,
    bait_signal_id: allocation.bait_signal_key,
    as_of: receipt.as_of ?? null,
    grants,
  }
}

export function procedureProof(items, audit) {
  const seen = new Set()
  if (audit) {
    requireFact(items.length === audit.grants.length
      && new Set(items.map((item) => item.signal_id)).size === items.length, 'audit_membership')
  }
  return items.map((item) => {
    const published = nonempty(item.source?.procedure_id) ? item.source.procedure_id : null
    const grant = audit?.grants.find((candidate) => candidate.signal_id === item.signal_id)
    requireFact(!audit || grant, 'audit_membership')
    // Canonical aliases are supplied by the backend. Do not recreate their
    // namespace, UUID normalization or procedure selection rules in JS.
    const references = grant?.procedure_references ?? (published ? [published] : [])
    requireFact(references.length > 0, 'procedure_audit_required')
    const unique = new Set(references)
    requireFact([...unique].every((reference) => !seen.has(reference)), 'distinct_procedures')
    for (const reference of unique) seen.add(reference)
    return { procedure_id: published, procedure_references: [...unique] }
  })
}
