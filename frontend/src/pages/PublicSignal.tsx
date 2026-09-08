import { Fragment, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { auth } from '../api/endpoints'
import { useI18n } from '../i18n'
import { AuthShell } from '../presentation/dashboard/AuthShell'
import { useResource } from '../presentation/dashboard/resources'
import { Button } from '../presentation/dashboard/ui/button'
import styles from '../signals/components/signals.module.css'

export function PublicSignal() {
  const { hash } = useLocation()
  return <PublicSignalPreview key={hash} token={hash.slice(1)} />
}

function PublicSignalPreview({ token }: { token: string }) {
  const { amount, date } = useI18n()
  const load = useCallback(() => token ? auth.attributionPreview(token) : Promise.reject(new ApiError(400, 'invalid_input', '')), [token])
  const preview = useResource(load)
  const signal = preview.data?.signal
  const invalid = preview.error instanceof ApiError && [400, 404, 410].includes(preview.error.status)
  const facts = signal ? [
    ['Titulaire', signal.holder], ['Acheteur', signal.buyer],
    ['Montant', amount(signal.amount == null ? null : String(signal.amount), signal.currency)], ['Lieu', signal.location],
    [signal.date_label || 'Date', date(signal.date)],
  ] : []

  return <AuthShell wide eyebrow="Signal reçu par email" title="Votre aperçu de signal" description="Les faits du marché, en lecture seule.">
    {preview.loading ? <p role="status">Chargement du signal…</p> : preview.error ? <>
      <p className="form-error" role="alert">{invalid ? 'Ce lien est invalide ou expiré.' : 'Le signal n’a pas pu être chargé. Réessayez.'}</p>
      {!invalid ? <Button onClick={() => void preview.retry()}>Réessayer</Button> : null}
    </> : signal ? <article className={styles.drawer} aria-labelledby="public-signal-title">
      <p className={styles.drawerNotice}>Ce signal a été envoyé à {preview.data!.recipient_email} — connectez-vous pour l’ouvrir</p>
      <h2 id="public-signal-title" className={styles.drawerTitle}>{signal.object || 'Marché attribué'}</h2>
      <dl className={styles.facts}>{facts.map(([label, value]) => value ? <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment> : null)}</dl>
      {signal.for_you_sentence ? <section className={styles.why}><h3 className="section-label">Pour vous</h3><p>{signal.for_you_sentence}</p></section> : null}
      <div className={styles.actions}><Link className={styles.actionPrimary} to="/login">Se connecter</Link></div>
    </article> : null}
  </AuthShell>
}
