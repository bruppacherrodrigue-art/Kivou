import type { FormEvent } from 'react'
import { Button } from '../components/Button'
import { PublicPageMeta } from '../components/PublicPageMeta'
import { marketingCopy } from '../content/marketingCopy'
import { useI18n } from '../i18n'
import styles from './Contact.module.css'

const CONTACT_EMAIL = 'contact@kivou.eu'

export function Contact() {
  const { locale } = useI18n()
  const copy = marketingCopy(locale).contact

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const name = String(data.get('name') ?? '')
    const email = String(data.get('email') ?? '')
    const subject = String(data.get('subject') ?? copy.title)
    const message = String(data.get('message') ?? '')
    const body = `${message}\n\n${copy.name}: ${name}\n${copy.email}: ${email}`
    window.location.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
  }

  return (
    <article className={styles.page}>
      <PublicPageMeta
        title={`${copy.title} — Kivou`}
        description={locale === 'fr' ? 'Contactez l’équipe Kivou.' : 'Contact the Kivou team.'}
        canonicalPath="/contact"
      />
      <div className={styles.inner}>
        <header className={styles.introduction}>
          <p className={styles.eyebrow}>Kivou</p>
          <h1>{copy.title}</h1>
        </header>
        <form className={styles.form} onSubmit={submit}>
          <div className={styles.fieldsRow}>
            <label>{copy.name}<input name="name" type="text" autoComplete="name" required /></label>
            <label>{copy.email}<input name="email" type="email" autoComplete="email" required /></label>
          </div>
          <label>{copy.subject}
            <select name="subject" defaultValue="" required>
              <option value="" disabled>{copy.choose}</option>
              {copy.subjects.map((subject) => <option key={subject} value={subject}>{subject}</option>)}
            </select>
          </label>
          <label>{copy.message}<textarea name="message" rows={8} required /></label>
          <div className={styles.submitRow}>
            <Button type="submit" size="lg">{copy.send}</Button>
            <p>{copy.note}</p>
          </div>
        </form>
      </div>
    </article>
  )
}
