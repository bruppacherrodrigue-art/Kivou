import { useId, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { ManualContactView } from '../../api/types'
import { useI18n } from '../../i18n'
import { useCompanyActions, type ActionableCompany } from '../useCompanyActions'
import styles from '../Prospecting.module.css'

export function UserContactForm({ company, initial, onCancel, onSaved }: {
  company: ActionableCompany
  initial: ManualContactView
  onCancel: () => void
  onSaved: (contact: ManualContactView) => void
}) {
  const { locale } = useI18n()
  const fr = locale === 'fr'
  const id = useId()
  const actions = useCompanyActions(company)
  const values = (value: ManualContactView) => ({ name: value.contact?.name ?? '', role: value.contact?.role ?? '', email: value.contact?.email ?? '', phone: value.contact?.phone ?? '' })
  const [draft, setDraft] = useState(() => values(initial))
  const [revision, setRevision] = useState(initial.revision)
  const [validation, setValidation] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [acceptedConflict, setAcceptedConflict] = useState<number | null>(null)
  const operation = useRef<'save' | 'delete'>('save')
  const conflict = actions.contactConflict?.revision === acceptedConflict ? null : actions.contactConflict
  const save = async (expectedRevision: number) => {
    operation.current = 'save'
    setValidation(null)
    if (!draft.name.trim() || (!draft.email.trim() && !draft.phone.trim())) {
      setValidation(fr ? 'Renseignez un nom et un email ou un téléphone.' : 'Enter a name and an email or phone number.')
      return
    }
    try {
      const result = await actions.saveContact({ name: draft.name.trim(), role: draft.role.trim() || null, email: draft.email.trim() || null, phone: draft.phone.trim() || null, expected_revision: expectedRevision })
      onSaved(result)
    } catch { /* The action exposes the error and keeps this draft intact. */ }
  }
  const remove = async (expectedRevision: number) => {
    operation.current = 'delete'
    try { onSaved(await actions.deleteContact(expectedRevision)) } catch { /* Compare conflicts before retrying. */ }
  }
  const submit = (event: FormEvent) => { event.preventDefault(); void save(revision) }
  const fields = [
    { name: 'name' as const, label: fr ? 'Nom du contact' : 'Contact name', type: 'text', max: 120 },
    { name: 'role' as const, label: fr ? 'Fonction' : 'Role', type: 'text', max: 120 },
    { name: 'email' as const, label: fr ? 'Email professionnel' : 'Work email', type: 'email', max: 254 },
    { name: 'phone' as const, label: fr ? 'Téléphone' : 'Phone', type: 'tel', max: 40 },
  ]
  const genericError = !!actions.error && !conflict && !(actions.error instanceof ApiError && actions.error.status === 409 && acceptedConflict !== null)
  return <section aria-labelledby={`${id}-title`}>
    <h3 id={`${id}-title`}>{fr ? 'Votre interlocuteur' : 'Your contact'}</h3>
    <p className={styles.muted}>{fr ? 'Enregistrez les coordonnées que vous connaissez. Aucun message ni recherche payante ne sera déclenché.' : 'Save contact details you already know. No message or paid search will be triggered.'}</p>
    <form onSubmit={submit}>
      <div className={styles.form}>{fields.map((field) => <div className={styles.field} key={field.name}>
        <label htmlFor={`${id}-${field.name}`}>{field.label}</label>
        <input id={`${id}-${field.name}`} type={field.type} maxLength={field.max} required={field.name === 'name'} autoComplete="off" value={draft[field.name]}
          disabled={actions.pending !== null} onChange={(event) => setDraft((value) => ({ ...value, [field.name]: event.target.value }))} />
      </div>)}</div>
      {validation && <p className={styles.error} role="alert">{validation}</p>}
      {genericError && <div className={styles.error} role="alert">
        <p>{fr ? 'Le contact n’a pas été enregistré. Votre saisie est conservée.' : 'The contact was not saved. Your draft is preserved.'}</p>
        {actions.error instanceof ApiError && actions.error.fields.map((field) => <p key={field.field}>{field.message}</p>)}
      </div>}
      {conflict && <div className={styles.conflict} role="alert">
        <p>{fr ? 'Ce contact a changé. Comparez la version enregistrée avec votre saisie.' : 'This contact has changed. Compare the saved version with your draft.'}</p>
        <strong>{conflict.contact?.name ?? (fr ? 'Contact supprimé' : 'Contact deleted')}</strong>
        {conflict.contact && <p>{[conflict.contact.role, conflict.contact.email, conflict.contact.phone].filter(Boolean).join(' · ')}</p>}
        <div className={styles.actions}>
          <button type="button" className={styles.button} disabled={actions.pending !== null} onClick={() => { setDraft(values(conflict)); setRevision(conflict.revision); setAcceptedConflict(conflict.revision); setConfirmDelete(false) }}>{fr ? 'Reprendre la version enregistrée' : 'Use saved version'}</button>
          <button type="button" className={styles.primary} disabled={actions.pending !== null} onClick={() => void (operation.current === 'delete' ? remove(conflict.revision) : save(conflict.revision))}>
            {operation.current === 'delete' ? fr ? 'Supprimer le contact enregistré' : 'Delete saved contact' : fr ? 'Enregistrer mes modifications' : 'Save my changes'}
          </button>
        </div>
      </div>}
      {confirmDelete && !conflict && <div className={styles.conflict}>
        <p>{fr ? 'Supprimer votre contact personnel ? Les coordonnées publiques de l’entreprise resteront inchangées.' : 'Delete your personal contact? The company’s public details will remain unchanged.'}</p>
        <button type="button" className={styles.button} disabled={actions.pending !== null} onClick={() => void remove(revision)}>{fr ? 'Confirmer la suppression' : 'Confirm deletion'}</button>
      </div>}
      <div className={styles.actions}>
        <button type="button" className={styles.textButton} disabled={actions.pending !== null} onClick={onCancel}>{fr ? 'Annuler' : 'Cancel'}</button>
        {initial.contact && <button type="button" className={styles.textButton} disabled={actions.pending !== null} onClick={() => setConfirmDelete(true)}>{fr ? 'Supprimer ce contact' : 'Delete this contact'}</button>}
        <button className={styles.primary} type="submit" disabled={actions.pending !== null || !!conflict}>{actions.pending ? fr ? 'Enregistrement…' : 'Saving…' : fr ? 'Enregistrer le contact' : 'Save contact'}</button>
      </div>
    </form>
  </section>
}
