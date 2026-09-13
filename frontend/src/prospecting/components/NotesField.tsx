import { useId } from 'react'
import { useI18n } from '../../i18n'
import type { NoteIdentity } from '../queryKeys'
import { usePersistedNote, type NoteStore } from '../usePersistedNote'
import styles from '../Prospecting.module.css'

export function NotesField({ store, identity }: { store: NoteStore; identity: NoteIdentity }) {
  const note = usePersistedNote(store, identity)
  const { locale } = useI18n()
  const id = useId()
  const french = locale === 'fr'
  const label = identity.kind === 'signal'
    ? french ? 'Vos notes sur ce signal' : 'Your notes on this signal'
    : french ? 'Vos notes sur cette entreprise' : 'Your company notes'
  const status = {
    loading: french ? 'Chargement…' : 'Loading…',
    idle: french ? 'Sauvegarde automatique dans votre compte' : 'Automatically saved to your account',
    dirty: french ? 'Modifications en attente' : 'Changes pending',
    saving: french ? 'Enregistrement…' : 'Saving…',
    saved: french ? 'Enregistré' : 'Saved',
    error: french ? 'Enregistrement non confirmé' : 'Save not confirmed',
    conflict: french ? 'Une autre version a été enregistrée' : 'Another version was saved',
  }[note.status]
  return <section className={styles.notesSection} aria-labelledby={`${id}-label`}>
    <h3><label id={`${id}-label`} htmlFor={id}>{label}</label></h3>
    <textarea id={id} className={styles.notes} maxLength={2000} value={note.draft}
      onChange={(event) => note.setDraft(event.target.value)}
      placeholder={french ? 'Interlocuteur, prochaine étape, points à retenir…' : 'Contact, next step, things to remember…'}
      aria-describedby={`${id}-status`} />
    <div className={styles.noteMeta}>
      <span id={`${id}-status`} role="status">{status}</span>
      <span>{note.draft.length.toLocaleString(french ? 'fr-FR' : 'en-GB')} / 2 000</span>
    </div>
    {note.status === 'error' && <button type="button" className={styles.textButton} onClick={() => void note.retry()}>{french ? 'Réessayer' : 'Retry'}</button>}
    {note.status === 'conflict' && <div className={styles.conflict}>
      <p>{french ? 'Votre brouillon est conservé. Comparez les deux textes avant de choisir.' : 'Your draft is preserved. Compare both versions before choosing.'}</p>
      {note.conflict ? <>
        <strong>{french ? 'Version enregistrée' : 'Saved version'}</strong>
        <pre>{note.conflict.note || (french ? 'Note vide' : 'Empty note')}</pre>
        <div className={styles.actions}>
          <button type="button" className={styles.button} onClick={note.acceptServer}>{french ? 'Reprendre la version enregistrée' : 'Use saved version'}</button>
          <button type="button" className={styles.primary} onClick={() => void note.overwriteDraft()}>{french ? 'Enregistrer mon texte' : 'Save my text'}</button>
        </div>
      </> : <button type="button" className={styles.button} onClick={() => void note.retry()}>{french ? 'Recharger la version enregistrée' : 'Reload saved version'}</button>}
    </div>}
  </section>
}
