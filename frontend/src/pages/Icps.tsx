import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight,
  Building2,
  Check,
  FileCheck2,
  Pencil,
  Target,
  X,
} from 'lucide-react'
import { billing, icps as icpsApi, signals } from '../api/endpoints'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { describeError } from '../api/errorCopy'
import type { TargetIcp, UnlockedFeedItem } from '../api/types'
import { interpolate, useI18n } from '../i18n'
import type { Locale } from '../i18n'
import type { Dictionary } from '../i18n/fr'
import {
  type ReferenceTargetingDraft,
  type TargetingField,
  UnknownTargetingToken,
  toTargetIcpPayload,
} from '../reference/dashboard/targetingInput'
import { useResource } from '../reference/dashboard/resources'
import { ReferenceLink } from '../reference/router/ReferenceLink'
import { Button } from '../reference/dashboard/ui/button'
import { Input } from '../reference/dashboard/ui/input'
import { Textarea } from '../reference/dashboard/ui/textarea'
import { notifyTargetIcpChanged } from '../targeting/targetIcpEvents'

interface ProfilesState {
  data: TargetIcp[] | null
  loading: boolean
  error: unknown | null
}

interface TargetingFormError {
  message: string
  field?: TargetingField
}

const EMPTY_DRAFT: ReferenceTargetingDraft = {
  name: '',
  offer: '',
  precision: '',
  companies: '',
  territory: '',
  terms: '',
  minAmount: '',
  currency: 'EUR',
}

function profileDraft(
  profile: TargetIcp,
  dictionary: Dictionary,
  locale: Locale,
): ReferenceTargetingDraft {
  const [offer = '', ...precision] = profile.customer_input.offer_summary.split('\n\n')
  const threshold = profile.customer_input.minimum_contract_value
  return {
    name: profile.label,
    offer,
    precision: precision.join('\n\n'),
    companies: profile.customer_input.buyer_trades.map((code) => dictionary.trades[code]).join(', '),
    territory: profile.customer_input.territories.map((code) => {
      const territory = MVP_TERRITORIES.find((candidate) => candidate.code === code)
      return territory ? territoryLabel(territory, locale) : code
    }).join(', '),
    terms: profile.customer_input.offers.map((code) => dictionary.offers[code]).join(', '),
    minAmount: threshold ? String(threshold.minimum_amount) : '',
    currency: threshold?.currency ?? 'EUR',
  }
}

export function Icps() {
  const { t, locale, amount } = useI18n()
  const copy = t.reference.targetingPage
  const mounted = useRef(false)
  const listGeneration = useRef(0)
  const saveGeneration = useRef(0)
  const saveInFlight = useRef(false)
  const [profiles, setProfiles] = useState<ProfilesState>({ data: null, loading: true, error: null })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<ReferenceTargetingDraft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<TargetingFormError | null>(null)
  const [saved, setSaved] = useState(false)
  const editButton = useRef<HTMLButtonElement>(null)
  const createButton = useRef<HTMLButtonElement>(null)
  const creationStartedFromEditor = useRef(false)
  const firstField = useRef<HTMLInputElement>(null)
  const loadBilling = useCallback(() => billing.status(), [])
  const access = useResource(loadBilling)

  const loadProfiles = useCallback(async () => {
    const generation = ++listGeneration.current
    setProfiles((previous) => ({ ...previous, loading: true, error: null }))
    try {
      const data = await icpsApi.list()
      if (!mounted.current || listGeneration.current !== generation) return
      setProfiles({ data, loading: false, error: null })
      setSelectedId((current) => {
        if (current && data.some((profile) => profile.target_icp_id === current)) return current
        return data.find((profile) => profile.status === 'active')?.target_icp_id
          ?? data[0]?.target_icp_id
          ?? null
      })
    } catch (error) {
      if (!mounted.current || listGeneration.current !== generation) return
      setProfiles((previous) => ({ ...previous, loading: false, error }))
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void loadProfiles()
    return () => {
      mounted.current = false
      listGeneration.current += 1
      saveGeneration.current += 1
    }
  }, [loadProfiles])

  useEffect(() => {
    if (editing) firstField.current?.focus()
  }, [editing])

  const selected = profiles.data?.find((profile) => profile.target_icp_id === selectedId)
    ?? profiles.data?.find((profile) => profile.status === 'active')
    ?? profiles.data?.[0]
    ?? null

  const startEditing = () => {
    if (!selected) return
    creationStartedFromEditor.current = false
    setDraft(profileDraft(selected, t, locale))
    setCreating(false)
    setEditing(true)
    setFormError(null)
    setSaved(false)
  }

  const startCreating = () => {
    creationStartedFromEditor.current = editing && Boolean(selected)
    setDraft(EMPTY_DRAFT)
    setCreating(true)
    setEditing(true)
    setFormError(null)
    setSaved(false)
    window.requestAnimationFrame(() => firstField.current?.focus())
  }

  const stopEditing = () => {
    if (creating && selected && creationStartedFromEditor.current) {
      setDraft(profileDraft(selected, t, locale))
      setCreating(false)
      setFormError(null)
      setSaved(false)
      window.requestAnimationFrame(() => createButton.current?.focus())
      return
    }
    setEditing(false)
    setCreating(false)
    setFormError(null)
    setSaved(false)
    window.requestAnimationFrame(() => (selected ? editButton.current : createButton.current)?.focus())
  }

  const updateDraft = (field: keyof ReferenceTargetingDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }))
    setFormError(null)
    setSaved(false)
  }

  const save = async () => {
    if (saveInFlight.current) return
    const previous = creating ? undefined : selected?.customer_input
    let payload: ReturnType<typeof toTargetIcpPayload>
    try {
      payload = toTargetIcpPayload(draft, t, previous)
    } catch (error) {
      if (error instanceof UnknownTargetingToken) {
        setFormError({
          message: interpolate(copy.unknownToken, { token: error.token }),
          field: error.field,
        })
        const fieldId: Record<TargetingField, string> = {
          offers: 'profile-terms',
          buyer_trades: 'profile-companies',
          territories: 'profile-territory',
          threshold: 'profile-min-amount',
        }
        window.requestAnimationFrame(() => document.getElementById(fieldId[error.field])?.focus())
      } else setFormError({ message: copy.saveError })
      return
    }

    const generation = ++saveGeneration.current
    saveInFlight.current = true
    setSaving(true)
    setFormError(null)
    try {
      const result = creating
        ? await icpsApi.create(payload)
        : await icpsApi.update(selected!.target_icp_id, payload)
      if (!mounted.current || saveGeneration.current !== generation) return
      setProfiles((current) => ({
        data: creating
          ? [...(current.data ?? []), result]
          : (current.data ?? []).map((profile) => (
              profile.target_icp_id === result.target_icp_id ? result : profile
            )),
        loading: false,
        error: null,
      }))
      setSelectedId(result.target_icp_id)
      setEditing(false)
      setCreating(false)
      setSaved(true)
      notifyTargetIcpChanged()
      void access.retry()
      window.requestAnimationFrame(() => editButton.current?.focus())
    } catch (caught) {
      if (!mounted.current || saveGeneration.current !== generation) return
      const errorCopy = describeError(caught, t)
      setFormError({
        message: [copy.saveError, errorCopy.title, errorCopy.body]
          .filter((part): part is string => Boolean(part))
          .join(' '),
      })
    } finally {
      if (saveGeneration.current === generation) {
        saveInFlight.current = false
        if (mounted.current) setSaving(false)
      }
    }
  }

  const selectedInput = selected?.customer_input
  const view = useMemo(() => {
    if (!selectedInput) return null
    const threshold = selectedInput.minimum_contract_value
    const [offer = '', ...precision] = selectedInput.offer_summary.split('\n\n')
    return {
      offer: offer.trim() || t.reference.missingValue,
      precision: precision.join('\n\n').trim(),
      companies: selectedInput.buyer_trades.length > 0
        ? selectedInput.buyer_trades.map((code) => t.trades[code]).join(', ')
        : t.icp.noTrades,
      territories: selectedInput.territories.length > 0
        ? selectedInput.territories.map((code) => {
            const territory = MVP_TERRITORIES.find((candidate) => candidate.code === code)
            return territory ? territoryLabel(territory, locale) : code
          }).join(', ')
        : t.reference.missingValue,
      threshold: threshold
        ? amount(String(threshold.minimum_amount), threshold.currency) ?? t.reference.missingValue
        : t.reference.missingValue,
      terms: selectedInput.offers.map((code) => t.offers[code]),
    }
  }, [amount, locale, selectedInput, t])

  const overLimit = Boolean(
    selected &&
    !access.loading &&
    !access.error &&
    access.data?.target_icps_over_limit.includes(selected.target_icp_id),
  )
  const planLimited = Boolean(selected?.plan_limit)
  const currentDraft = selected ? profileDraft(selected, t, locale) : EMPTY_DRAFT
  const draftIsValid = Boolean(
    draft.name.trim() &&
    draft.offer.trim() &&
    draft.companies.trim() &&
    draft.territory.trim() &&
    draft.terms.trim() &&
    draft.minAmount.trim() &&
    Number.isFinite(Number(draft.minAmount)) &&
    Number(draft.minAmount) >= 0,
  )
  const hasChanges = creating || JSON.stringify(draft) !== JSON.stringify(currentDraft)
  const profileStatus = creating
    ? t.onboarding.statusIncomplete
    : planLimited
      ? t.icp.territoryLimitedBadge
      : access.loading
        ? t.reference.loading
        : access.error || access.data === null
          ? t.reference.missingValue
          : overLimit
            ? t.icp.overLimitBadge
            : selected?.status === 'active'
              ? t.reference.statuses.activeProfile
              : t.onboarding.statusIncomplete

  return (
    <div className="target-profile-main">
      <section className="target-profile-intro" aria-labelledby="target-profile-title">
        <div>
          <p className="section-label">{copy.monitoredTargeting}</p>
          <h2 id="target-profile-title">{t.reference.headings.targetProfile}</h2>
          <p>{copy.lead}</p>
        </div>

        {!editing && selected ? (
          <Button ref={editButton} type="button" className="primary-action target-edit-button" onClick={startEditing}>
            <Pencil aria-hidden="true" /> {copy.editProfile}
          </Button>
        ) : !editing && profiles.data?.length === 0 ? (
          <Button ref={createButton} type="button" className="primary-action target-edit-button" onClick={startCreating}>
            <Pencil aria-hidden="true" /> {copy.createProfile}
          </Button>
        ) : editing ? (
          <div className="target-edit-actions">
            {!creating && selected ? (
              <Button ref={createButton} type="button" variant="outline" className="secondary-action" disabled={saving} onClick={startCreating}>
                {copy.createProfile}
              </Button>
            ) : null}
            <Button type="button" variant="outline" className="secondary-action" disabled={saving} onClick={stopEditing}>
              <X aria-hidden="true" /> {copy.cancel}
            </Button>
            <Button
              type="submit"
              form="target-profile-form"
              className="primary-action"
              disabled={saving || !draftIsValid || !hasChanges}
            >
              <Check aria-hidden="true" /> {saving ? t.reference.saving : t.reference.save}
            </Button>
          </div>
        ) : null}
      </section>

      {saved ? <p className="target-demo-message" role="status"><Check aria-hidden="true" /> {t.icp.updated}</p> : null}
      {profiles.loading && profiles.data !== null ? (
        <p className="target-demo-message" role="status">{t.reference.loading}</p>
      ) : null}
      {access.loading && access.data !== null ? (
        <p className="target-demo-message" role="status">{copy.loadingAccess}</p>
      ) : null}
      {formError && !formError.field ? <p className="target-demo-message" role="alert">{formError.message}</p> : null}
      {profiles.error ? (
        <p className="target-demo-message" role="alert">
          {t.reference.messages.profileLoadError}{' '}
          <button type="button" onClick={() => void loadProfiles()}>{t.reference.retry}</button>
        </p>
      ) : null}
      {access.error ? (
        <p className="target-demo-message" role="alert">
          {t.reference.messages.billingLoadError}{' '}
          <button type="button" onClick={() => void access.retry()}>{t.reference.retry}</button>
        </p>
      ) : null}
      {!creating && selected && (overLimit || planLimited) ? (
        <p className="target-demo-message" role="alert">
          {overLimit ? t.icp.overLimitHelp : interpolate(
            selected.plan_limit?.limit === 1
              ? t.icp.territoryLimitedHelpOne
              : t.icp.territoryLimitedHelpOther,
            { limit: selected.plan_limit?.limit ?? 0 },
          )}
        </p>
      ) : null}

      {profiles.loading && profiles.data === null ? (
        <section className="target-definition-card" role="status" aria-label={t.reference.loading} aria-labelledby="target-loading-title">
          <h3 id="target-loading-title">{t.reference.loading}</h3>
        </section>
      ) : profiles.error && profiles.data === null ? null : (
        <div className="target-profile-layout">
          <div className="target-profile-primary">
            <section className="target-definition-card" aria-labelledby="target-definition-title">
              <div className="target-card-heading">
                <div>
                  <p className="card-kicker">{t.reference.headings.targetProfile}</p>
                  <h3 id="target-definition-title">
                    {editing ? draft.name || copy.newProfile : selected?.label ?? copy.newProfile}
                  </h3>
                </div>
                <span className="target-active-status"><span aria-hidden="true" /> {profileStatus}</span>
              </div>

              {profiles.data && profiles.data.length > 1 && !editing ? (
                <label className="target-field">
                  <span>{copy.profileSelector}</span>
                  <select value={selected?.target_icp_id ?? ''} onChange={(event) => setSelectedId(event.target.value)}>
                    {profiles.data.map((profile) => (
                      <option value={profile.target_icp_id} key={profile.target_icp_id}>{profile.label}</option>
                    ))}
                  </select>
                </label>
              ) : null}

              {editing ? (
                <TargetingForm
                  draft={draft}
                  update={updateDraft}
                  submit={() => void save()}
                  firstField={firstField}
                  copy={copy}
                  error={formError}
                  disabled={saving}
                />
              ) : selected && view ? (
                <>
                  <dl className="target-definition-grid">
                    <div className="target-definition-wide"><dt>{t.reference.fields.offer}</dt><dd>{view.offer}</dd></div>
                    {view.precision ? <div className="target-definition-wide"><dt>{t.reference.fields.precision}</dt><dd>{view.precision}</dd></div> : null}
                    <div className="target-definition-wide"><dt>{t.reference.fields.companiesSought}</dt><dd>{view.companies}</dd></div>
                    <div><dt>{t.reference.fields.commercialTerritory}</dt><dd>{view.territories}</dd></div>
                    <div><dt>{t.reference.fields.minimumAmount}</dt><dd>{view.threshold}</dd></div>
                    <div><dt>{t.reference.fields.observedEvent}</dt><dd>{copy.observedAward}</dd></div>
                  </dl>
                  <div className="target-terms-block">
                    <span>{t.reference.fields.keywords}</span>
                    <div>{view.terms.length > 0
                      ? view.terms.map((term) => <span key={term}>{term}</span>)
                      : <span>{t.reference.missingValue}</span>}</div>
                  </div>
                </>
              ) : <p>{t.icp.listEmptyBody}</p>}
            </section>

            <section className="target-logic-card" aria-labelledby="target-logic-title">
              <div className="target-card-heading">
                <div><p className="card-kicker">{copy.method}</p><h3 id="target-logic-title">{t.reference.headings.matchingLogic}</h3></div>
                <Target aria-hidden="true" />
              </div>
              <div className="target-flow" aria-label={copy.selectionSteps}>
                <div><span>1</span><strong>{copy.stepAward}</strong><p>{copy.stepAwardBody}</p></div>
                <ArrowRight aria-hidden="true" />
                <div><span>2</span><strong>{copy.stepCompare}</strong><p>{copy.stepCompareBody}</p></div>
                <ArrowRight aria-hidden="true" />
                <div><span>3</span><strong>{copy.stepSignal}</strong><p>{copy.stepSignalBody}</p></div>
              </div>
            </section>
          </div>

          <aside className="target-profile-side">
            <section className="target-impact-card" aria-labelledby="target-impact-title">
              <div className="target-card-heading">
                <div><p className="card-kicker">{copy.examples}</p><h3 id="target-impact-title">{t.reference.headings.matchingExamples}</h3></div>
                <Building2 aria-hidden="true" />
              </div>
              <div className="target-example-list">
                {!creating && selected ? <TargetExamples key={selected.target_icp_id} targetId={selected.target_icp_id} /> : (
                  <TargetExamplePlaceholders />
                )}
              </div>
              <Button asChild className="primary-action target-signals-action">
                <ReferenceLink dashboard href="/signals">
                  {copy.seeSignals} <ArrowRight aria-hidden="true" />
                </ReferenceLink>
              </Button>
            </section>

            <section className="target-source-card" aria-labelledby="target-source-title">
              <FileCheck2 aria-hidden="true" />
              <div>
                <p className="card-kicker">{copy.traceability}</p>
                <h3 id="target-source-title">{copy.sourceTitle}</h3>
                <p>{copy.sourceBody}</p>
              </div>
            </section>
          </aside>
        </div>
      )}
    </div>
  )
}

interface TargetExamplesState {
  items: UnlockedFeedItem[]
  loading: boolean
  error: unknown | null
  incomplete: boolean
}

const INITIAL_TARGET_EXAMPLES: TargetExamplesState = {
  items: [],
  loading: true,
  error: null,
  incomplete: false,
}

const MAX_EXAMPLE_PAGES = 25

function TargetExamples({ targetId }: { targetId: string }) {
  const { t, locale } = useI18n()
  const copy = t.reference.targetingPage
  const mounted = useRef(false)
  const generation = useRef(0)
  const retainedItems = useRef<UnlockedFeedItem[]>([])
  const [resource, setResource] = useState<TargetExamplesState>(INITIAL_TARGET_EXAMPLES)

  const load = useCallback(async () => {
    const current = ++generation.current
    const previousItems = retainedItems.current
    const items: UnlockedFeedItem[] = []
    const seen = new Set<string>()
    const publish = (next: TargetExamplesState) => {
      retainedItems.current = next.items
      setResource(next)
    }
    setResource({ ...INITIAL_TARGET_EXAMPLES, items: previousItems })
    let offset = 0
    let pages = 0
    try {
      while (items.length < 2) {
        const page = await signals.feed({
          freshness: 'all',
          target_icp_id: targetId,
          limit: 20,
          offset,
        })
        pages += 1
        if (!mounted.current || generation.current !== current) return
        for (const item of page.items) {
          if (item.locked || seen.has(item.signal_id)) continue
          seen.add(item.signal_id)
          items.push(item)
          if (items.length === 2) break
        }
        if (items.length === 2) break
        if (page.page.scan_truncated) {
          publish({ items, loading: false, error: null, incomplete: true })
          return
        }
        if (!page.page.has_more) break
        if (pages >= MAX_EXAMPLE_PAGES) {
          publish({ items, loading: false, error: null, incomplete: true })
          return
        }
        const nextOffset = page.page.offset + page.page.limit
        if (nextOffset <= offset) {
          publish({ items, loading: false, error: null, incomplete: true })
          return
        }
        offset = nextOffset
      }
      publish({ items, loading: false, error: null, incomplete: false })
    } catch (error) {
      if (!mounted.current || generation.current !== current) return
      publish({
        items: items.length > 0 ? items : previousItems,
        loading: false,
        error,
        incomplete: true,
      })
    }
  }, [targetId])

  useEffect(() => {
    mounted.current = true
    void load()
    return () => {
      mounted.current = false
      generation.current += 1
    }
  }, [load])

  const firstMissing = resource.items.length

  return (
    <>
      {[0, 1].map((index) => {
        const signal = resource.items[index]
        if (!signal) {
          if (resource.loading) {
            return (
              <article
                aria-busy={index === firstMissing ? 'true' : undefined}
                className="target-example"
                key={`loading-${index}`}
              >
                <div><span>{t.reference.loading}</span><strong>{t.reference.missingValue}</strong></div>
                <p role={index === firstMissing ? 'status' : undefined}>{t.reference.loading}</p>
              </article>
            )
          }
          if (resource.error || resource.incomplete) {
            return (
              <article className="target-example" key={`error-${index}`}>
                <div><span>{resource.error ? t.reference.messages.loadError : copy.examplesIncomplete}</span><strong>{t.reference.missingValue}</strong></div>
                <p role={index === firstMissing ? 'alert' : undefined}>
                  {copy.examplesIncomplete}
                  {index === firstMissing ? (
                    <> <button type="button" onClick={() => void load()}>{t.reference.retry}</button></>
                  ) : null}
                </p>
              </article>
            )
          }
          return (
            <article className="target-example" key={`empty-${index}`}>
              <div><span>{t.reference.missingValue}</span><strong>{t.reference.missingValue}</strong></div>
              <p role={index === firstMissing ? 'status' : undefined}>{copy.noExampleAvailable}</p>
            </article>
          )
        }
        const location = signal.contract.location
        const territory = MVP_TERRITORIES.find((candidate) => candidate.code === location?.country)
        const country = territory
          ? territoryLabel(territory, locale)
          : location?.country
        const place = [location?.locality, location?.postal_code, country]
          .filter(Boolean)
          .join(', ') || t.reference.missingValue
        return (
          <article className="target-example is-included" key={signal.signal_id}>
            <div><span><Check aria-hidden="true" /> {copy.matches}</span><strong>{signal.company.name ?? t.reference.missingValue}</strong></div>
            <p>{interpolate(copy.exampleMatch, {
              match: signal.analysis.fit.label || t.reference.missingValue,
              location: place,
            })}</p>
          </article>
        )
      })}
      <article className="target-example">
        <div><span><X aria-hidden="true" /> {copy.outOfProfile}</span><strong>{t.reference.missingValue}</strong></div>
        <p>{copy.noOutOfProfileData}</p>
      </article>
    </>
  )
}

function TargetExamplePlaceholders() {
  const { t } = useI18n()
  const copy = t.reference.targetingPage
  return (
    <>
      {[0, 1].map((index) => (
        <article className="target-example" key={index}>
          <div><span>{t.reference.missingValue}</span><strong>{t.reference.missingValue}</strong></div>
          <p>{copy.noExampleAvailable}</p>
        </article>
      ))}
      <article className="target-example">
        <div><span><X aria-hidden="true" /> {copy.outOfProfile}</span><strong>{t.reference.missingValue}</strong></div>
        <p>{copy.noOutOfProfileData}</p>
      </article>
    </>
  )
}

function TargetingForm({
  draft,
  update,
  submit,
  firstField,
  copy,
  error,
  disabled,
}: {
  draft: ReferenceTargetingDraft
  update: (field: keyof ReferenceTargetingDraft, value: string) => void
  submit: () => void
  firstField: React.RefObject<HTMLInputElement | null>
  copy: ReturnType<typeof useI18n>['t']['reference']['targetingPage']
  error: TargetingFormError | null
  disabled: boolean
}) {
  const { t } = useI18n()
  const errorField = error?.field
  const inlineError = (field: TargetingField) => errorField === field
    ? <p id="target-form-error" className="target-field-error" role="alert">{error?.message}</p>
    : null
  return (
    <form id="target-profile-form" className="target-edit-form" onSubmit={(event) => { event.preventDefault(); submit() }}>
      <div className="target-field"><label htmlFor="profile-name">{t.reference.fields.profileName}</label><Input ref={firstField} id="profile-name" value={draft.name} required disabled={disabled} onChange={(event) => update('name', event.target.value)} /></div>
      <div className="target-field"><label htmlFor="profile-offer">{t.reference.fields.offer}</label><Textarea id="profile-offer" value={draft.offer} required disabled={disabled} onChange={(event) => update('offer', event.target.value)} /></div>
      <div className="target-field target-field-wide"><label htmlFor="profile-summary">{t.reference.fields.precision} <span>({t.common.optional})</span></label><Textarea id="profile-summary" value={draft.precision} disabled={disabled} onChange={(event) => update('precision', event.target.value)} /></div>
      <div className="target-field"><label htmlFor="profile-companies">{t.reference.fields.companiesSought}</label><Textarea id="profile-companies" value={draft.companies} required disabled={disabled} aria-invalid={errorField === 'buyer_trades' || undefined} aria-describedby={errorField === 'buyer_trades' ? 'target-form-error' : undefined} onChange={(event) => update('companies', event.target.value)} />{inlineError('buyer_trades')}</div>
      <div className="target-field"><label htmlFor="profile-territory">{t.reference.fields.commercialTerritory}</label><Input id="profile-territory" value={draft.territory} required disabled={disabled} aria-invalid={errorField === 'territories' || undefined} aria-describedby={errorField === 'territories' ? 'target-form-error' : undefined} onChange={(event) => update('territory', event.target.value)} />{inlineError('territories')}</div>
      <div className="target-field target-field-wide"><label htmlFor="profile-terms">{t.reference.fields.keywords}</label><Input id="profile-terms" value={draft.terms} required disabled={disabled} aria-invalid={errorField === 'offers' || undefined} aria-describedby={errorField === 'offers' ? 'profile-terms-help target-form-error' : 'profile-terms-help'} onChange={(event) => update('terms', event.target.value)} /><p id="profile-terms-help">{copy.separateTokens}</p>{inlineError('offers')}</div>
      <div className="target-field"><label htmlFor="profile-min-amount">{t.reference.fields.minimumContract}</label><Input id="profile-min-amount" type="number" min="0" step="1000" value={draft.minAmount} required disabled={disabled} aria-invalid={errorField === 'threshold' || undefined} aria-describedby={errorField === 'threshold' ? 'target-form-error' : undefined} onChange={(event) => update('minAmount', event.target.value)} />{inlineError('threshold')}</div>
      <div className="target-field"><label htmlFor="profile-currency">{t.reference.fields.currency}</label><select id="profile-currency" className="lifecycle-select" value={draft.currency} disabled={disabled} aria-invalid={errorField === 'threshold' || undefined} aria-describedby={errorField === 'threshold' ? 'target-form-error' : undefined} onChange={(event) => update('currency', event.target.value)}><option value="CHF">CHF</option><option value="EUR">EUR</option></select></div>
      <p className="target-edit-note">{copy.realSaveNote}</p>
    </form>
  )
}
