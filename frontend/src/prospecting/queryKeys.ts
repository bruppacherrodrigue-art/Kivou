export interface ProspectingScope {
  accountId: string
  targetIcpId: string
  targetRevision: number
  offerCategory: string | null
  subdivisionCode: string | null
  minAmount: string | null
  amountCurrency: string | null
  accessEpoch: number
}

export interface NoteIdentity {
  accountId: string
  kind: 'signal' | 'company'
  /** Signal key, or the private_subject_key returned by the company API. */
  entityId: string
  /** Requested API alias. Never substitutes for private subject identity. */
  addressKey?: string
}

export function noteKey(identity: NoteIdentity): string {
  return JSON.stringify([identity.accountId, identity.kind, identity.entityId])
}

type QueryValue = string | number | boolean | null | readonly (string | number)[]
export interface ResourceScopeOptions {
  /** Directory/company resources have no targeting dependency at all. */
  scopeIndependent?: boolean
  /** Known signal details can show facts without a current target, but still re-key with it. */
  allowWithoutScope?: boolean
}

/** The stable signature includes the full projection scope and page/filter inputs. */
export function prospectingKey(
  resource: string,
  scope: ProspectingScope,
  parameters: Record<string, QueryValue> = {},
  options: ResourceScopeOptions = {},
): string {
  return JSON.stringify([
    resource, scope.accountId, options.scopeIndependent ? null : [
      scope.targetIcpId, scope.targetRevision, scope.offerCategory, scope.subdivisionCode,
      scope.minAmount, scope.amountCurrency,
    ], scope.accessEpoch,
    Object.keys(parameters).sort().map((key) => [key, parameters[key]]),
  ])
}
