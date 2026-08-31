import { PublicPageMeta } from '../components/PublicPageMeta'

export function Contact() {
  return (
    <>
      <PublicPageMeta
        title="Contact | Kivou"
        description="Écrivez à Kivou."
        canonicalPath="/contact"
      />
      <main id="main" className="contact-page" tabIndex={-1}>
        <section className="contact-form-wrap container" aria-labelledby="contact-title">
          <h1 id="contact-title">Contact</h1>
          <form className="glass contact-form" action="mailto:contact@kivou.eu?subject=Contact%20Kivou" method="post" encType="text/plain">
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="contact-name">Nom</label>
                <input id="contact-name" name="Nom" type="text" autoComplete="name" required />
              </div>
              <div className="form-field">
                <label htmlFor="contact-email">E-mail professionnel</label>
                <input id="contact-email" name="E-mail" type="email" autoComplete="email" required />
              </div>
            </div>
            <div className="form-field">
              <label htmlFor="contact-subject">Sujet</label>
              <select id="contact-subject" name="Sujet" defaultValue="" required>
                <option value="" disabled>Choisir un sujet</option>
                <option>Produit et compte</option>
                <option>Facturation</option>
                <option>Confidentialité</option>
                <option>Partenariat</option>
                <option>Autre demande</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="contact-message">Message</label>
              <textarea id="contact-message" name="Message" rows={8} required />
            </div>
            <button className="btn primary" type="submit">Envoyer le message</button>
            <p className="form-note">L’envoi s’ouvre dans votre messagerie et reste sous votre contrôle.</p>
          </form>
        </section>
      </main>
    </>
  )
}
