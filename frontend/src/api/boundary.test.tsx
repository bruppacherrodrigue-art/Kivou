import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AppRoutes } from '../App'
import { ApiError, request } from './client'
import { fr } from '../i18n/fr'
import { en } from '../i18n/en'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

/* SPEC-015 §32, §34, §46 — la frontière d'API, la localisation et ce que le
 * navigateur n'a pas le droit de porter. */

afterEach(() => vi.unstubAllGlobals())

describe('frontière HTTP', () => {
  it('joint toujours le cookie de session et n’ajoute jamais de jeton', async () => {
    const handler = mockApi({ 'GET /me': { body: { user_id: 'usr_1' } } })
    await request('/me')

    const [, init] = handler.mock.calls[0]
    expect(init?.credentials).toBe('same-origin')
    const headers = (init?.headers ?? {}) as Record<string, string>
    // Aucun porteur : l'authentification est le cookie HttpOnly, pas un en-tête.
    expect(headers).not.toHaveProperty('Authorization')
    expect(JSON.stringify(headers).toLowerCase()).not.toContain('bearer')
  })

  it('n’utilise que des URL relatives — même origine en production', async () => {
    const handler = mockApi({ 'GET /billing/plans': { body: {} } })
    await request('/billing/plans')

    const [url] = handler.mock.calls[0]
    expect(String(url).startsWith('/')).toBe(true)
    expect(String(url)).not.toMatch(/^https?:\/\//)
  })

  it('proxyfie la frontière entreprise vers l’API en développement', () => {
    const viteConfig = readFileSync(join(process.cwd(), 'vite.config.ts'), 'utf8')

    expect(viteConfig).toContain("'/companies'")
  })

  it('traduit un code d’erreur stable, sans laisser passer le message serveur', async () => {
    mockApi({
      'POST /billing/checkout': {
        status: 409,
        body: {
          detail: {
            code: 'checkout_in_progress',
            message: 'un paiement est déjà en cours pour ce compte',
            expires_at: '2026-08-18T12:30:00+00:00',
          },
        },
      },
    })

    await expect(
      request('/billing/checkout', { method: 'POST', body: { plan: 'pro', currency: 'chf' } }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'checkout_in_progress',
      extra: { expires_at: '2026-08-18T12:30:00+00:00' },
    })
  })

  it('reconstruit les erreurs par champ d’un 422 pydantic', async () => {
    mockApi({
      'POST /auth/signup': {
        status: 422,
        body: {
          detail: [
            { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
          ],
        },
      },
    })

    const error = await request('/auth/signup', { method: 'POST', body: {} }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('validation_error')
    expect((error as ApiError).fields).toEqual([
      { field: 'email', message: 'value is not a valid email address' },
    ])
  })

  it('transforme une panne réseau en état produit, pas en exception brute', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    )

    const error = await request('/me').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('network_error')
    expect((error as ApiError).status).toBe(0)
  })

  it('invalide la session sur un 401 et ramène à la connexion, une seule fois', async () => {
    mockApi({
      'GET /signals': {
        status: 401,
        body: { detail: { code: 'not_authenticated', message: 'authentification requise' } },
      },
      'GET /billing/status': {
        status: 401,
        body: { detail: { code: 'not_authenticated', message: 'authentification requise' } },
      },
      'GET /target-icps': {
        status: 401,
        body: { detail: { code: 'not_authenticated', message: 'authentification requise' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    // Plusieurs appels échouent en même temps ; un seul retour à la connexion.
    expect(
      await screen.findByRole('heading', { name: 'Retrouver vos signaux' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/session a expiré/i)).toBeInTheDocument())
  })
})

describe('ce que le navigateur ne porte jamais', () => {
  it('n’envoie aucun account_id, sur aucune route', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await waitFor(() => expect(recordedCalls.length).toBeGreaterThan(0))
    for (const call of recordedCalls) {
      expect(call.search.get('account_id')).toBeNull()
      expect(JSON.stringify(call.body ?? {})).not.toContain('account_id')
    }
  })

  it('ne contient aucun secret dans le code source du frontend', () => {
    const root = join(process.cwd(), 'src')
    // Les motifs visent des SECRETS, pas des noms de domaine : `sk_live`,
    // `whsec_`, un mot de passe SMTP ou une clé Stripe n'ont rien à faire dans
    // un bundle servi au navigateur.
    const forbidden = [
      /sk_live_[A-Za-z0-9]/,
      /sk_test_[A-Za-z0-9]/,
      /rk_live_[A-Za-z0-9]/,
      /whsec_[A-Za-z0-9]/,
      /SMTP_PASSWORD\s*[:=]\s*['"][^'"$]/,
      /import\.meta\.env\.VITE_\w*(SECRET|KEY|TOKEN|PASSWORD)/i,
    ]

    for (const file of walk(root)) {
      const content = readFileSync(file, 'utf8')
      for (const pattern of forbidden) {
        expect(content, `${file} contient un secret`).not.toMatch(pattern)
      }
    }
  })
})

describe('localisation FR / EN', () => {
  it('porte systématiquement les libellés exacts du dashboard de référence', () => {
    expect(fr.reference.headings).toEqual({
      monitoringSummary: 'Résumé de la veille',
      documentedAwards: 'Marchés attribués',
      savedProfile: 'Profil enregistré',
      otherDocumentedAwards: 'Autres marchés attribués',
      awardedContracts: 'Marchés attribués',
      selectedSignal: 'Signal sélectionné',
      commercialBrief: 'Le signal en quatre points',
      marketDetails: 'Détails du marché',
      questionsBeforeContact: 'Questions avant de contacter l’entreprise',
      signalNote: 'Note sur ce signal',
      linkedCompanies: 'Entreprises liées aux signaux',
      company: 'Entreprise',
      associatedAwards: 'Attributions associées à l’entreprise',
      publishedIdentity: 'Identité publiée',
      sourceAssertions: 'Ce que la source permet d’affirmer',
      usefulRoles: 'Fonctions utiles avant contact',
      targetProfile: 'Profil cible',
      matchingLogic: 'Logique de correspondance',
      matchingExamples: 'Exemples de correspondance',
      tedTraceability: 'Chaque avis TED reste consultable',
      accountInformation: 'Informations du compte',
      displayAccess: 'Affichage et accès',
      mainInformation: 'Informations principales',
      security: 'Sécurité',
      resetAccess: 'Réinitialiser l’accès',
      subscription: 'Abonnement',
      notifications: 'Notifications',
      notificationDelivery: 'Réception des nouveaux signaux',
      support: 'Une question sur votre compte ?',
    })
    expect(en.reference.headings).toEqual({
      monitoringSummary: 'Monitoring summary',
      documentedAwards: 'Documented awards',
      savedProfile: 'Saved profile',
      otherDocumentedAwards: 'Other documented awards',
      awardedContracts: 'Awarded contracts',
      selectedSignal: 'Selected signal',
      commercialBrief: 'The signal in four points',
      marketDetails: 'Contract details',
      questionsBeforeContact: 'Questions before contacting the company',
      signalNote: 'Note on this signal',
      linkedCompanies: 'Companies linked to signals',
      company: 'Company',
      associatedAwards: 'Awards associated with the company',
      publishedIdentity: 'Published identity',
      sourceAssertions: 'What the source lets us assert',
      usefulRoles: 'Useful roles before contact',
      targetProfile: 'Target profile',
      matchingLogic: 'Matching logic',
      matchingExamples: 'Matching examples',
      tedTraceability: 'Every TED notice remains available',
      accountInformation: 'Account information',
      displayAccess: 'Display and access',
      mainInformation: 'Main information',
      security: 'Security',
      resetAccess: 'Reset access',
      subscription: 'Subscription',
      notifications: 'Notifications',
      notificationDelivery: 'New signal delivery',
      support: 'A question about your account?',
    })

    expect(fr.reference.fields).toEqual({
      award: 'Attribution',
      plannedStart: 'Début prévu',
      location: 'Lieu',
      offerSummary: 'Offre',
      targetCompanies: 'Entreprises cibles',
      territory: 'Territoire',
      amount: 'Montant total du marché',
      awardDate: 'Date d’attribution',
      signalDateAward: 'Date d’attribution',
      signalDateNotification: 'Date de notification',
      signalDatePublication: 'Date de publication',
      execution: 'Période d’exécution',
      buyer: 'Acheteur public',
      signalBuyer: 'Acheteur',
      signalAwardee: 'Entreprise attributaire',
      signalTargetRoleUnavailable: 'Rôle cible non disponible',
      officialTitle: 'Titre officiel de la source',
      whyNow: 'Pourquoi maintenant',
      offerCoverage: 'Ce que l’offre peut couvrir',
      roleToFind: 'Fonction à rechercher',
      unknown: 'Ce qui reste inconnu',
      publishedScope: 'Périmètre publié',
      officialSource: 'Source officielle',
      profileName: 'Nom du profil',
      offer: 'Ce que vous vendez',
      precision: 'Précision utile',
      companiesSought: 'Entreprises recherchées',
      commercialTerritory: 'Territoire commercial',
      keywords: 'Mots-clés surveillés',
      minimumContract: 'Montant minimum du marché',
      minimumAmount: 'Montant minimum',
      currency: 'Devise',
      observedEvent: 'Événement observé',
      company: 'Entreprise',
      country: 'Pays',
      identifier: 'Identifiant publié',
      professionalEmail: 'Adresse professionnelle',
      language: 'Langue',
      timezone: 'Fuseau horaire',
      users: 'Utilisateurs',
      state: 'État',
      recipient: 'Adresse de réception',
      frequency: 'Fréquence',
      targetProfiles: 'Profils cibles',
      territories: 'Territoires',
      alerts: 'Alertes',
      history: 'Historique',
      export: 'Export',
    })
    expect(Object.keys(en.reference.fields)).toEqual(Object.keys(fr.reference.fields))

    expect(fr.reference.statuses).toEqual({
      activeProfile: 'Profil actif',
      publishedAward: 'Attribution publiée sur TED',
      noNote: 'Aucune note',
      noteSaved: 'Note enregistrée',
      active: 'Actif',
      noSubscription: 'Aucun abonnement',
      accessibleWithEssential: 'Accessible avec Essential',
      noteAdded: 'Note ajoutée',
      reviewFirst: 'À examiner d’abord',
      documentedSignal: 'Signal',
    })
    expect(Object.keys(en.reference.statuses)).toEqual(Object.keys(fr.reference.statuses))

    expect({
      missingValue: fr.reference.missingValue,
      retry: fr.reference.retry,
      save: fr.reference.save,
      saving: fr.reference.saving,
      saved: fr.reference.saved,
    }).toEqual({
      missingValue: '—',
      retry: 'Réessayer',
      save: 'Enregistrer',
      saving: 'Enregistrement…',
      saved: 'Enregistré',
    })
    expect(fr.reference.messages).toEqual({
      loadError: 'Les informations n’ont pas pu être chargées.',
      profileLoadError: 'Le profil cible n’a pas pu être chargé.',
      billingLoadError: 'L’offre n’a pas pu être chargée.',
      refreshing: 'Actualisation des données…',
      refreshFailed: 'L’actualisation a échoué. Les données affichées peuvent être anciennes.',
      retryProfile: 'Réessayer le chargement du profil cible',
      retryBilling: 'Réessayer le chargement de l’offre',
      saveError: 'Les modifications n’ont pas pu être enregistrées.',
      noteLoadError: 'La note n’a pas pu être chargée.',
      noteError: 'La note n’a pas pu être enregistrée.',
      empty: 'Aucune donnée publiée.',
    })
    expect(en.reference.messages).toEqual({
      loadError: 'The information could not be loaded.',
      profileLoadError: 'The target profile could not be loaded.',
      billingLoadError: 'The plan could not be loaded.',
      refreshing: 'Refreshing data…',
      refreshFailed: 'The refresh failed. The displayed data may be out of date.',
      retryProfile: 'Try loading the target profile again',
      retryBilling: 'Try loading the plan again',
      saveError: 'The changes could not be saved.',
      noteLoadError: 'The note could not be loaded.',
      noteError: 'The note could not be saved.',
      empty: 'No published data.',
    })
  })

  it('les deux dictionnaires portent exactement les mêmes clés', () => {
    const missing: string[] = []
    compare(fr, en, '', missing)
    expect(missing).toEqual([])
  })

  it('ne traduit aucun code machine', () => {
    // Les codes restent identiques d'une langue à l'autre : ils désignent une
    // valeur du backend, pas un libellé.
    expect(Object.keys(fr.feedback.reasons)).toEqual(Object.keys(en.feedback.reasons))
    expect(Object.keys(fr.offers)).toEqual(Object.keys(en.offers))
    expect(Object.keys(fr.trades)).toEqual(Object.keys(en.trades))
    expect(Object.keys(fr.notifications.cadence)).toEqual(Object.keys(en.notifications.cadence))
  })

  it('rend l’interface en anglais quand la locale du compte le demande', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...AUTHENTICATED.me!, locale: 'en' } },
      route: '/app/signals',
      locale: 'fr',
    })

    // La locale du COMPTE l'emporte sur celle de l'interface publique.
    expect(await screen.findByRole('heading', { name: 'Signals' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('en')
  })
})

function walk(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...walk(full))
    else if (/\.(ts|tsx|css)$/.test(entry.name)) files.push(full)
  }
  return files
}

function compare(left: unknown, right: unknown, path: string, missing: string[]) {
  if (typeof left !== 'object' || left === null) return
  for (const key of Object.keys(left as Record<string, unknown>)) {
    const here = path ? `${path}.${key}` : key
    const value = (right as Record<string, unknown> | null)?.[key]
    if (value === undefined) {
      missing.push(here)
      continue
    }
    compare((left as Record<string, unknown>)[key], value, here, missing)
  }
}
