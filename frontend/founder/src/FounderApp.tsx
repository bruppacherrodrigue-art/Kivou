import { useEffect, useState } from 'react'

interface FounderSession {
  version: 'founder-session-v1'
  service: 'kivou-founder-control'
  environment: 'PRODUCTION'
  operator_email: string
  read_only: true
  generated_at: string
}

type SessionState =
  | { status: 'loading' }
  | { status: 'ready'; session: FounderSession }
  | { status: 'error'; message: string }

export function FounderApp() {
  const [state, setState] = useState<SessionState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    void fetch('/api/founder/session', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 401 || response.status === 403
              ? 'Accès refusé par la frontière Founder.'
              : 'Le service Founder est indisponible.',
          )
        }
        return (await response.json()) as FounderSession
      })
      .then((session) => setState({ status: 'ready', session }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'Le service Founder est indisponible.',
        })
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="founder-shell">
      <header className="founder-header">
        <a className="founder-brand" href="/" aria-label="Kivou Control — accueil">
          <span className="founder-mark" aria-hidden="true">K</span>
          <span>
            <strong>Kivou</strong>
            <small>Control</small>
          </span>
        </a>
        <div className="founder-environment">
          <span className="founder-environment-dot" aria-hidden="true" />
          Production
        </div>
      </header>

      <main className="founder-main">
        <section className="founder-intro" aria-labelledby="founder-title">
          <p className="founder-eyebrow">Interface privée du fondateur</p>
          <h1 id="founder-title">Console fondateur</h1>
          <p>
            Une surface indépendante du SaaS client, protégée par Cloudflare Access
            et conçue pour lire les données opérationnelles de Kivou sans jamais les modifier.
          </p>
        </section>

        {state.status === 'loading' ? (
          <section className="founder-state" aria-live="polite">
            <span className="founder-loader" aria-hidden="true" />
            <p>Vérification de l’accès sécurisé…</p>
          </section>
        ) : null}

        {state.status === 'error' ? (
          <section className="founder-state founder-state-error" role="alert">
            <strong>Connexion impossible</strong>
            <p>{state.message}</p>
          </section>
        ) : null}

        {state.status === 'ready' ? <Foundation session={state.session} /> : null}
      </main>
    </div>
  )
}

function Foundation({ session }: { session: FounderSession }) {
  return (
    <>
      <section className="founder-access-card" aria-labelledby="founder-access-title">
        <div>
          <p className="founder-section-label">Frontière d’accès</p>
          <h2 id="founder-access-title">Session Founder validée</h2>
          <p>
            Cette première fondation ne contient aucune commande, aucune écriture
            et aucune route du produit client.
          </p>
        </div>
        <dl className="founder-access-details">
          <div>
            <dt>Opérateur</dt>
            <dd>{session.operator_email}</dd>
          </div>
          <div>
            <dt>Environnement</dt>
            <dd>{session.environment}</dd>
          </div>
          <div>
            <dt>Accès aux données</dt>
            <dd>Lecture seule</dd>
          </div>
          <div>
            <dt>Vérifié le</dt>
            <dd>{formatDate(session.generated_at)}</dd>
          </div>
        </dl>
      </section>

      <section className="founder-modules" aria-labelledby="founder-modules-title">
        <div className="founder-section-heading">
          <div>
            <p className="founder-section-label">Fondation</p>
            <h2 id="founder-modules-title">Une seule console, des modules progressifs</h2>
          </div>
          <span className="founder-readonly">Lecture seule</span>
        </div>
        <div className="founder-module-grid">
          <Module title="À traiter" description="Incidents, anomalies et décisions nécessitant ton attention." />
          <Module title="Business" description="Funnel, paiements, MRR, rétention et performance par wedge." />
          <Module title="Qualité" description="Feedbacks, signaux incohérents et motifs de rejet observés." />
          <Module title="Système" description="Santé, ingestion, Policy Gateway, Hermes et files d’échec." />
        </div>
        <p className="founder-foundation-note">
          Les modules seront reliés aux read models de production dans la seconde PR.
          Aucun chiffre de démonstration n’est affiché.
        </p>
      </section>
    </>
  )
}

function Module({ title, description }: { title: string; description: string }) {
  return (
    <article className="founder-module">
      <span aria-hidden="true" />
      <h3>{title}</h3>
      <p>{description}</p>
    </article>
  )
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'Date indisponible'
  return new Intl.DateTimeFormat('fr-CH', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Zurich',
  }).format(parsed)
}
