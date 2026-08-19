import { useId } from 'react'
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import styles from './FormField.module.css'

/* Champs de formulaire — label PERMANENT, aide et erreur distinctes.
 *
 * Le placeholder n'est jamais le seul label (directive §9) : il disparaît à la
 * saisie, et un champ rempli devient alors impossible à identifier. Aide et
 * erreur sont deux éléments séparés, tous deux reliés par `aria-describedby`,
 * parce qu'un message d'erreur qui remplace l'aide fait perdre l'instruction
 * au moment précis où elle est utile.
 */

interface FieldShellProps {
  label: string
  help?: ReactNode
  error?: string | null
  optional?: boolean
  optionalLabel?: string
  children: (ids: { inputId: string; describedBy: string | undefined; invalid: boolean }) => ReactNode
}

export function FieldShell({
  label,
  help,
  error,
  optional,
  optionalLabel,
  children,
}: FieldShellProps) {
  const inputId = useId()
  const helpId = `${inputId}-help`
  const errorId = `${inputId}-error`
  const describedBy = [help ? helpId : null, error ? errorId : null].filter(Boolean).join(' ')

  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={inputId}>
        {label}
        {optional ? <span className={styles.optional}> — {optionalLabel}</span> : null}
      </label>
      {children({ inputId, describedBy: describedBy || undefined, invalid: Boolean(error) })}
      {help ? (
        <p className={styles.help} id={helpId}>
          {help}
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} id={errorId}>
          {/* Le signe n'est pas décoratif : il porte l'état sans dépendre de la
              couleur seule (§38). */}
          <span aria-hidden="true">▲</span> {error}
        </p>
      ) : null}
    </div>
  )
}

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> & {
  label: string
  help?: ReactNode
  error?: string | null
  optional?: boolean
  optionalLabel?: string
}

export function TextField({
  label,
  help,
  error,
  optional,
  optionalLabel,
  ...rest
}: TextFieldProps) {
  return (
    <FieldShell
      label={label}
      help={help}
      error={error}
      optional={optional}
      optionalLabel={optionalLabel}
    >
      {({ inputId, describedBy, invalid }) => (
        <input
          id={inputId}
          className={`${styles.input} ${invalid ? styles.inputInvalid : ''}`}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          {...rest}
        />
      )}
    </FieldShell>
  )
}

type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> & {
  label: string
  help?: ReactNode
  error?: string | null
  children: ReactNode
}

export function SelectField({ label, help, error, children, ...rest }: SelectFieldProps) {
  return (
    <FieldShell label={label} help={help} error={error}>
      {({ inputId, describedBy, invalid }) => (
        <select
          id={inputId}
          className={`${styles.input} ${styles.select} ${invalid ? styles.inputInvalid : ''}`}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          {...rest}
        >
          {children}
        </select>
      )}
    </FieldShell>
  )
}

type TextAreaFieldProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> & {
  label: string
  help?: ReactNode
  error?: string | null
  optional?: boolean
  optionalLabel?: string
}

export function TextAreaField({
  label,
  help,
  error,
  optional,
  optionalLabel,
  ...rest
}: TextAreaFieldProps) {
  return (
    <FieldShell
      label={label}
      help={help}
      error={error}
      optional={optional}
      optionalLabel={optionalLabel}
    >
      {({ inputId, describedBy, invalid }) => (
        <textarea
          id={inputId}
          className={`${styles.input} ${styles.textarea} ${invalid ? styles.inputInvalid : ''}`}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          {...rest}
        />
      )}
    </FieldShell>
  )
}

/** Un groupe de cases à cocher présenté comme un vrai `fieldset`.
 *  L'intitulé du groupe est une `legend`, ce qu'aucun `div` ne remplace pour
 *  un lecteur d'écran. */
export function CheckboxGroup({
  legend,
  help,
  error,
  children,
}: {
  legend: string
  help?: ReactNode
  error?: string | null
  children: ReactNode
}) {
  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.legend}>{legend}</legend>
      {help ? <p className={styles.help}>{help}</p> : null}
      <div className={styles.options}>{children}</div>
      {error ? (
        <p className={styles.error}>
          <span aria-hidden="true">▲</span> {error}
        </p>
      ) : null}
    </fieldset>
  )
}

export function CheckboxOption({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className={`${styles.option} ${checked ? styles.optionChecked : ''}`}>
      <input
        type="checkbox"
        className={styles.checkbox}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  )
}

export function Switch({
  label,
  help,
  checked,
  onChange,
  disabled,
}: {
  label: string
  help?: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  const id = useId()
  const helpId = `${id}-help`
  return (
    <div className={styles.switchRow}>
      <input
        id={id}
        type="checkbox"
        // `role="switch"` remplace la sémantique native de la case : ARIA exige
        // alors un `aria-checked` explicite, car l'état coché du DOM n'est plus
        // celui que la technologie d'assistance lit.
        role="switch"
        aria-checked={checked}
        className={styles.switchInput}
        checked={checked}
        disabled={disabled}
        aria-describedby={help ? helpId : undefined}
        onChange={(event) => onChange(event.target.checked)}
      />
      <div className={styles.switchText}>
        <label htmlFor={id} className={styles.switchLabel}>
          {label}
        </label>
        {help ? (
          <p className={styles.help} id={helpId}>
            {help}
          </p>
        ) : null}
      </div>
    </div>
  )
}
