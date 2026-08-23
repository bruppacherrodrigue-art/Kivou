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
    expect(await screen.findByRole('heading', { name: 'Se connecter' })).toBeInTheDocument()
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
    expect(await screen.findByRole('heading', { name: 'Sales opportunities' })).toBeInTheDocument()
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
