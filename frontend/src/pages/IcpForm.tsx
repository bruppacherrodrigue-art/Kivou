import { useMemo, useState } from 'react'
import { useI18n } from '../i18n'
import { Button } from '../components/Button'
import { Callout } from '../components/Surfaces'
import {
  CheckboxGroup,
  CheckboxOption,
  SelectField,
  TextAreaField,
  TextField,
} from '../components/FormField'
import { fieldError } from '../api/errorCopy'
import { BUYER_TRADES, OFFER_KINDS } from '../api/types'
import {
  MVP_TERRITORIES,
  MVP_THRESHOLD_CURRENCIES,
  territoryLabel,
} from '../api/capabilities'
import type { BuyerTrade, OfferKind, TargetIcpInput } from '../api/types'
import styles from './IcpForm.module.css'

/* Le formulaire de profil de ciblage.
 *
 * Les cinq questions et LEURS OPTIONS viennent de `signals.accounts.icp_input` :
 * sept catégories d'offre, huit corps de métier, des territoires en ISO 3166-1
 * alpha-2, un seuil monétaire. Rien n'est inventé — une option absente du
 * `Literal` backend ferait échouer la requête en 422, et surtout n'aurait
 * aucune traduction vers le modèle moteur.
 *
 * Le vocabulaire moteur — `NeedCategory`, `TradeDomain`, `geography_basis`,
 * `unknown_value_policy`, `source_modes_allowed` — n'apparaît nulle part :
 * ce sont des décisions produit à valeur unique, et §12 interdit de les
 * exposer. Elles ne sont donc pas demandées.
 */

export interface IcpFormValue {
  label: string
  input: TargetIcpInput
}

export function emptyIcpValue(): IcpFormValue {
  return {
    label: '',
    input: {
      offer_summary: '',
      offers: [],
      secondary_offers: [],
      buyer_trades: [],
      secondary_buyer_trades: [],
      territories: [],
      minimum_contract_value: null,
    },
  }
}

/** Ce qui empêche encore d'enregistrer un profil EXPLOITABLE.
 *  La règle reproduit `TargetIcpInput.missing_fields()` — elle sert à guider la
 *  saisie, pas à décider : le backend reste seul juge du statut. */
export function missingFields(value: IcpFormValue): string[] {
  const missing: string[] = []
  if (value.input.offers.length === 0) missing.push('offers')
  if (value.input.territories.length === 0) missing.push('territories')
  if (value.input.minimum_contract_value === null) missing.push('minimum_contract_value')
  if (value.input.secondary_buyer_trades.length > 0 && value.input.buyer_trades.length === 0) {
    missing.push('buyer_trades')
  }
  return missing
}

export function IcpFields({
  value,
  onChange,
  error,
  showLabel = true,
}: {
  value: IcpFormValue
  onChange: (next: IcpFormValue) => void
  error?: unknown
  showLabel?: boolean
}) {
  const { t, locale } = useI18n()
  const threshold = value.input.minimum_contract_value

  const [currency, setCurrency] = useState(threshold?.currency ?? 'EUR')
  const [minimum, setMinimum] = useState(
    threshold ? String(threshold.minimum_amount) : '',
  )

  // La liste vit dans `api/capabilities` : c'est une décision produit, pas un
  // détail de rendu (CLOSEOUT §4).
  const territories = useMemo(
    () =>
      MVP_TERRITORIES.map((territory) => ({
        code: territory.code,
        label: territoryLabel(territory, locale),
      })),
    [locale],
  )

  function patch(next: Partial<TargetIcpInput>) {
    onChange({ ...value, input: { ...value.input, ...next } })
  }

  function toggle<T extends string>(list: readonly T[], item: T): T[] {
    return list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item]
  }

  function commitThreshold(nextCurrency: string, nextMinimum: string) {
    const parsed = Number(nextMinimum.replace(',', '.'))
    if (nextMinimum.trim() === '' || Number.isNaN(parsed) || parsed < 0) {
      patch({ minimum_contract_value: null })
      return
    }
    patch({
      minimum_contract_value: {
        currency: nextCurrency,
        minimum_amount: parsed,
        maximum_amount: null,
      },
    })
  }

  return (
    <div className={styles.fields}>
      {showLabel ? (
        <TextField
          label={t.onboarding.labelField}
          value={value.label}
          required
          placeholder={t.onboarding.labelPlaceholder}
          help={t.onboarding.labelHelp}
          onChange={(event) => onChange({ ...value, label: event.target.value })}
          error={fieldError(error, 'label')}
        />
      ) : null}

      <CheckboxGroup legend={t.onboarding.offersStep} help={t.onboarding.offersHelp}>
        {OFFER_KINDS.map((offer) => (
          <CheckboxOption
            key={offer}
            label={t.offers[offer]}
            checked={value.input.offers.includes(offer)}
            onChange={() => patch({ offers: toggle(value.input.offers, offer) as OfferKind[] })}
          />
        ))}
      </CheckboxGroup>

      <CheckboxGroup legend={t.onboarding.tradesStep} help={t.onboarding.tradesHelp}>
        {BUYER_TRADES.map((trade) => (
          <CheckboxOption
            key={trade}
            label={t.trades[trade]}
            checked={value.input.buyer_trades.includes(trade)}
            onChange={() =>
              patch({ buyer_trades: toggle(value.input.buyer_trades, trade) as BuyerTrade[] })
            }
          />
        ))}
      </CheckboxGroup>

      <CheckboxGroup legend={t.onboarding.territoriesStep} help={t.onboarding.territoriesHelp}>
        {territories.map((territory) => (
          <CheckboxOption
            key={territory.code}
            label={territory.label}
            checked={value.input.territories.includes(territory.code)}
            onChange={() => patch({ territories: toggle(value.input.territories, territory.code) })}
          />
        ))}
      </CheckboxGroup>

      <fieldset className={styles.thresholdSet}>
        <legend className={styles.thresholdLegend}>{t.onboarding.thresholdStep}</legend>
        <p className={styles.thresholdHelp}>{t.onboarding.thresholdHelp}</p>
        <div className={styles.thresholdRow}>
          <SelectField
            label={t.onboarding.currency}
            value={currency}
            onChange={(event) => {
              setCurrency(event.target.value)
              commitThreshold(event.target.value, minimum)
            }}
          >
            {MVP_THRESHOLD_CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </SelectField>

          <TextField
            label={t.onboarding.minimumAmount}
            type="number"
            min={0}
            step={1000}
            inputMode="numeric"
            value={minimum}
            onChange={(event) => {
              setMinimum(event.target.value)
              commitThreshold(currency, event.target.value)
            }}
          />
        </div>
      </fieldset>

      <TextAreaField
        label={t.onboarding.summaryStep}
        value={value.input.offer_summary}
        optional
        optionalLabel={t.common.optional}
        placeholder={t.onboarding.summaryPlaceholder}
        help={t.onboarding.summaryHelp}
        onChange={(event) => patch({ offer_summary: event.target.value })}
      />
    </div>
  )
}

/** L'état de complétude, dit dans les mots du client — jamais `draft`,
 *  `icp_incomplete` ou `ready_for_signals` bruts. */
export function CompletenessNotice({ missing }: { missing: string[] }) {
  const { t } = useI18n()

  if (missing.length === 0) {
    return <Callout tone="success" title={t.onboarding.statusReady} />
  }

  return (
    <Callout tone="warning" title={t.onboarding.statusIncomplete}>
      <span>{t.onboarding.missingTitle} </span>
      {missing
        .map((field) => t.onboarding.missing[field as keyof typeof t.onboarding.missing] ?? field)
        .join(', ')}
    </Callout>
  )
}

export function IcpSubmit({
  label,
  loading,
  disabled,
  onClick,
}: {
  label: string
  loading: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <Button size="lg" loading={loading} disabled={disabled} onClick={onClick}>
      {label}
    </Button>
  )
}
