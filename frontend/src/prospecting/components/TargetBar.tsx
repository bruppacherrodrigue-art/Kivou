import { useState } from 'react'
import { Link } from 'react-router-dom'
import { SlidersHorizontal, Target } from 'lucide-react'
import type { OfferKind } from '../../api/types'
import { useI18n } from '../../i18n'
import { useProspecting } from '../ProspectingProvider'
import type { ConsultationState } from '../routeState'
import { formatAmount } from '../adapters'
import { DetailFrame } from './DetailFrame'
import styles from '../Prospecting.module.css'

export function TargetBar({ independent = false }: { independent?: boolean }) {
  const p = useProspecting()
  const { locale, t } = useI18n()
  const fr = locale === 'fr'
  const [editing, setEditing] = useState(false)
  if (independent) return <div className={styles.targetBar}><div className={styles.targetSummary}><Target aria-hidden="true" /><span>{fr ? 'Annuaire complet · Explorez les entreprises au-delà de votre profil cible.' : 'Full directory · Explore companies beyond your target profile.'}</span></div></div>
  if (p.profilesError != null) return <div className={styles.error} role="alert">{fr ? 'Votre profil cible ne peut pas être chargé.' : 'Your target profile could not load.'}<button className={styles.textButton} onClick={() => void p.refreshProfiles()}>{fr ? 'Réessayer' : 'Retry'}</button></div>
  if (!p.profile || !p.selection) return p.profilesLoading ? <p className={styles.muted} role="status">{fr ? 'Chargement du profil cible…' : 'Loading target profile…'}</p> : null
  const selection = p.selection
  const offer = selection.offerCategory ? t.offers[selection.offerCategory as OfferKind] : null
  const zone = selection.subdivisionCode ? p.targetOptions.zones.find((item) => item.code === selection.subdivisionCode)?.label ?? selection.subdivisionCode : null
  const threshold = selection.minAmount && selection.amountCurrency ? formatAmount({ value: selection.minAmount, currency: selection.amountCurrency }, locale) : null
  return <>
    <div className={styles.targetBar}>
      <div className={styles.targetSummary}><Target aria-hidden="true" /><span>{fr ? 'Profil cible' : 'Target profile'}{' · '}<strong>{p.profile.label}</strong></span>{offer && <span>{offer}</span>}{zone && <span>{zone}</span>}{threshold && <span>{fr ? 'Dès' : 'From'} {threshold}</span>}</div>
      <button className={styles.textButton} onClick={() => setEditing(true)}><SlidersHorizontal aria-hidden="true" />{fr ? 'Ajuster' : 'Adjust'}</button>
    </div>
    {p.invalidParameters.length > 0 && <p className={styles.error} role="status">{fr ? 'Certains filtres ont été réinitialisés pour correspondre à votre profil et à votre abonnement.' : 'Some filters were reset to match your profile and subscription.'} <button className={styles.textButton} onClick={p.acknowledgeInvalidParameters}>{fr ? 'Compris' : 'Got it'}</button></p>}
    {editing && <TargetEditor initial={selection} onClose={() => setEditing(false)} />}
  </>
}

function TargetEditor({ initial, onClose }: { initial: ConsultationState; onClose: () => void }) {
  const p = useProspecting()
  const { locale, t } = useI18n()
  const fr = locale === 'fr'
  const [draft, setDraft] = useState(initial)
  const policy = p.policies.find((item) => item.targetIcpId === draft.targetIcpId)
  const caps = p.consultationCapabilities
  const changeProfile = (targetIcpId: string) => {
    const next = p.policies.find((item) => item.targetIcpId === targetIcpId)
    setDraft({ targetIcpId, offerCategory: null, subdivisionCode: null, minAmount: next?.defaultMinAmount ?? null, amountCurrency: next?.defaultAmountCurrency ?? null })
  }
  return <DetailFrame compact title={fr ? 'Ajuster ma consultation' : 'Adjust my view'} onClose={onClose}>
    <h2>{fr ? 'Concentrez votre prospection' : 'Focus your prospecting'}</h2>
    <p className={styles.muted}>{fr ? 'Ces réglages s’appliquent à Aujourd’hui, Signaux et votre prospection. Votre profil cible reste inchangé.' : 'These settings apply to Today, Signals and your prospects. Your target profile stays unchanged.'}</p>
    <form onSubmit={(event) => { event.preventDefault(); p.setSelection(draft); onClose() }}>
      <div className={styles.form}>
        <div className={`${styles.field} ${styles.fullWidth}`}><label htmlFor="consultation-profile">{fr ? 'Profil cible' : 'Target profile'}</label><select id="consultation-profile" value={draft.targetIcpId} onChange={(event) => changeProfile(event.target.value)}>{p.profiles.map((profile) => <option key={profile.target_icp_id} value={profile.target_icp_id}>{profile.label}</option>)}</select></div>
        {caps.canChooseOffer && <div className={`${styles.field} ${styles.fullWidth}`}><label htmlFor="consultation-offer">{fr ? 'Offre à privilégier' : 'Offer to prioritise'}</label><select id="consultation-offer" value={draft.offerCategory ?? ''} onChange={(event) => setDraft({ ...draft, offerCategory: event.target.value || null })}><option value="">{fr ? 'Toutes les offres du profil' : 'All profile offers'}</option>{policy?.offers.map((offer) => <option value={offer} key={offer}>{t.offers[offer as OfferKind]}</option>)}</select></div>}
        {caps.canChooseSubdivision && <div className={`${styles.field} ${styles.fullWidth}`}><label htmlFor="consultation-zone">{fr ? 'Zone à privilégier' : 'Priority area'}</label><select id="consultation-zone" value={draft.subdivisionCode ?? ''} onChange={(event) => setDraft({ ...draft, subdivisionCode: event.target.value || null })}><option value="">{fr ? 'Tout le territoire du profil' : 'Full profile territory'}</option>{policy?.subdivisions.map((code) => <option value={code} key={code}>{p.targetOptions.zones.find((zone) => zone.code === code)?.label ?? code}</option>)}</select></div>}
        {caps.canChooseAmount && <><div className={styles.field}><label htmlFor="consultation-amount">{fr ? 'Montant minimum' : 'Minimum amount'}</label><input id="consultation-amount" inputMode="decimal" pattern="[0-9]+([.][0-9]+)?" maxLength={80} value={draft.minAmount ?? ''} onChange={(event) => setDraft({ ...draft, minAmount: event.target.value || null, amountCurrency: draft.amountCurrency ?? 'EUR' })} /></div><div className={styles.field}><label htmlFor="consultation-currency">{fr ? 'Devise' : 'Currency'}</label><select id="consultation-currency" value={draft.amountCurrency ?? 'EUR'} onChange={(event) => setDraft({ ...draft, amountCurrency: event.target.value })}>{policy?.currencies.map((value) => <option key={value}>{value}</option>)}</select></div></>}
      </div>
      {!caps.canChooseOffer && <p className={styles.muted}>{fr ? 'La sélection Découverte suit votre profil cible. Les filtres avancés sont inclus dans les abonnements.' : 'Your Discovery selection follows your target profile. Subscriptions include advanced filters.'}</p>}
      <div className={styles.actions}><button className={styles.primary} type="submit">{fr ? 'Appliquer à ma consultation' : 'Apply to my view'}</button><button className={styles.textButton} type="button" onClick={() => { p.resetSelection(); onClose() }}>{fr ? 'Réinitialiser' : 'Reset'}</button></div>
    </form>
    <p className={styles.caption}><Link className={styles.textButton} to="/app/icps" onClick={onClose}>{fr ? 'Modifier durablement mon profil cible →' : 'Edit my target profile →'}</Link></p>
  </DetailFrame>
}
