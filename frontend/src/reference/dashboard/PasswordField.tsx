import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Input } from './ui/input'

export function PasswordField({
  id,
  label,
  value,
  autoComplete,
  onChange,
  hint,
  minLength = 12,
  invalid = false,
}: {
  id: string
  label: string
  value: string
  autoComplete: string
  onChange: (value: string) => void
  hint?: string
  minLength?: number
  invalid?: boolean
}) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="form-field">
      <label htmlFor={id}>{label}</label>
      <div className="password-control">
        <Input
          id={id}
          type={visible ? 'text' : 'password'}
          autoComplete={autoComplete}
          value={value}
          required
          minLength={minLength}
          aria-invalid={invalid || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className="password-toggle"
          aria-label={visible ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </button>
      </div>
      {hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  )
}
