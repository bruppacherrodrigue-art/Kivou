import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import type { CompanyProfile } from '../api/types'
import {
  AUTHENTICATED,
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNLOCKED_DETAIL as BASE_DETAIL,
  UNLOCKED_ITEM as BASE_ITEM,
  callsTo,
  factualFallbackPresentation,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

const PRESENTATION = factualFallbackPresentation({
  artifactId: 'd'.repeat(64),
  headline: 'Attribution documentée pour des travaux publics',
  awardSummary: 'La commune a attribué des travaux documentés à Constructions Bertrand SA.',
  headlineEvidenceRefs: ['source:company-headline'],
  awardSummaryEvidenceRefs: ['source:company-award-summary'],
})
const PUBLISHED_ITEM = {
  ...BASE_ITEM,
  company_key: COMPANY_PROFILE.company_key,
  presentation: PRESENTATION,
  contract: { ...BASE_ITEM.contract, title: 'TITRE ADMINISTRATIF INTERDIT' },
  event: {
    ...BASE_ITEM.event,
    headline: 'HEADLINE EVENT INTERDITE',
    why_now: 'URGENCE EVENT INTERDITE',
  },
  analysis: {
    ...BASE_ITEM.analysis,
    fit: { ...BASE_ITEM.analysis.fit, reasons: ['RAISON ANALYSIS INTERDITE'] },
  },
}
const PUBLISHED_DETAIL = {
  ...BASE_DETAIL,
  ...PUBLISHED_ITEM,
  presentation: PRESENTATION,
}

const PATH = `/app/companies/${COMPANY_PROFILE.company_key}?signal=${PUBLISHED_ITEM.signal_id}`
const ENDPOINT = `/companies/${COMPANY_PROFILE.company_key}`
const SUMMARY = PRESENTATION.content.award_summary

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function authorizedRoutes(profile: CompanyProfile = COMPANY_PROFILE) {
  return {
    'GET /signals': { body: feedPage([PUBLISHED_ITEM, LOCKED_ITEM], { freshness: 'all' }) },
    [`GET /signals/${PUBLISHED_ITEM.signal_id}`]: { body: PUBLISHED_DETAIL },
    [`GET ${ENDPOINT}`]: { body: profile },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  }
}

describe('fiche entreprise officielle dans le workspace autorisé', () => {
  it('traverse la route profonde seulement après le feed déverrouillé porteur de la clé', async () => {
    const routes = readFileSync(join(process.cwd(), 'src/App.tsx'), 'utf8')
    expect(routes).toContain('<Route path="companies/:companyKey" element={<Companies />} />')
    mockApi(authorizedRoutes())

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByText('Adresse officielle')
    expect(screen.getByRole('heading', { level: 2, name: SUMMARY })).toBeVisible()
    const feedCall = callsTo('/signals', 'GET')[0]
    const companyCall = callsTo(ENDPOINT, 'GET')[0]
    expect(recordedCalls.indexOf(feedCall)).toBeLessThan(recordedCalls.indexOf(companyCall))
    expect(callsTo(`/signals/${PUBLISHED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('rend en français le contexte de l’attribution depuis les champs déjà autorisés', async () => {
    mockApi(authorizedRoutes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByText(COMPANY_PROFILE.official_identity.address!)
    expect(screen.getByRole('heading', { level: 2, name: SUMMARY })).toBeVisible()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelectorAll('main')).toHaveLength(1)
    expect(screen.getByText('12 rue des Ateliers, 31270 Villeneuve')).toBeVisible()
    expect(screen.getAllByText('France')).not.toHaveLength(0)
    expect(screen.getAllByText(/4 août 2026/)).not.toHaveLength(0)
    expect(screen.getAllByText(/1.240.000.€/)).not.toHaveLength(0)
    expect(document.body).not.toHaveTextContent(PUBLISHED_DETAIL.event.why_now)
    expect(document.body).not.toHaveTextContent(PUBLISHED_DETAIL.contract.title!)
    expect(document.body).not.toHaveTextContent(PUBLISHED_DETAIL.event.headline)
    expect(document.body).not.toHaveTextContent(PUBLISHED_DETAIL.analysis.fit.reasons[0])
    expect(screen.getByRole('region', { name: 'Faits essentiels' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Autres attributions de cette entreprise' })).toBeVisible()
    expect(document.querySelectorAll('.company-identity-list > div')).toHaveLength(3)
    expect(screen.getByText('Aucune action commerciale n’est publiée pour cette attribution.')).toBeVisible()
    expect(screen.getByRole('link', { name: /Ouvrir le signal/ })).toHaveAttribute(
      'href',
      `/app/signals/${PUBLISHED_ITEM.signal_id}?presentation_artifact_id=${PRESENTATION.artifact_id}`,
    )
    expect(screen.queryByText('Pourquoi cette entreprise mérite votre attention')).not.toBeInTheDocument()
    expect(screen.queryByText('Sources et couverture')).not.toBeInTheDocument()
  })

  it.each([
    ['publication', '2026-08-20', 'Avis publié le 20 août 2026'],
    ['notification', '2026-08-21', 'Notification du marché le 21 août 2026'],
  ] as const)('présente la date %s comme telle, jamais comme une attribution', async (clock, eventDate, statement) => {
    const datedItem = {
      ...PUBLISHED_ITEM,
      event: { ...PUBLISHED_ITEM.event, clock, date: eventDate },
      contract: {
        ...PUBLISHED_ITEM.contract,
        dates: { ...PUBLISHED_ITEM.contract.dates, award: '2026-08-04' },
      },
    }
    mockApi({
      ...authorizedRoutes(),
      'GET /signals': { body: feedPage([datedItem], { freshness: 'all' }) },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByText(COMPANY_PROFILE.official_identity.address!)
    expect(screen.getAllByText(statement)).not.toHaveLength(0)
    expect(screen.queryByText('Attribuée le 4 août 2026')).not.toBeInTheDocument()
    const machineDate = document.querySelector(`time[datetime="${eventDate}"]`)
    expect(machineDate).toHaveTextContent(statement)
  })

  it('garde les champs absents honnêtes et annonce une couverture partielle une seule fois', async () => {
    const partial: CompanyProfile = {
      ...COMPANY_PROFILE,
      official_identity: {
        ...COMPANY_PROFILE.official_identity,
        country: null,
        address: null,
        identifiers: [],
        website_url: null,
      },
      coverage: {
        related_signals_complete: false,
        unavailable_fields: ['official_country', 'official_address', 'official_identifiers'],
      },
    }
    mockApi(authorizedRoutes(partial))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByText('Adresse officielle')
    expect(screen.getByText('Adresse officielle').nextElementSibling).toHaveTextContent('Non publié')
    expect(screen.getByText('Pays officiel').nextElementSibling).toHaveTextContent('Non publié')
    expect(screen.queryByText('Identifiants officiels')).not.toBeInTheDocument()
    expect(screen.getAllByRole('status').filter((node) => /Certaines informations officielles/.test(node.textContent ?? ''))).toHaveLength(1)
  })

  it.each([
    ['une URL HTTPS', 'https://constructions-bertrand.example/entreprise'],
    ['une URL locale interdite', 'https://127.0.0.1/admin'],
  ])('n’invente aucun contrôle de site externe pour %s', async (_label, websiteUrl) => {
    mockApi(authorizedRoutes({
      ...COMPANY_PROFILE,
      official_identity: { ...COMPANY_PROFILE.official_identity, website_url: websiteUrl },
    }))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByText(COMPANY_PROFILE.official_identity.address!)
    expect(screen.queryByRole('link', { name: /site de l’entreprise/i })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Preuves et source officielle' })).toBeVisible()
  })

  it('rend le même degré de certitude et les actions réelles en anglais', async () => {
    mockApi(authorizedRoutes())
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: PATH,
      locale: 'en',
    })

    await screen.findByText(COMPANY_PROFILE.official_identity.address!)
    expect(screen.getByText(/BOAMP/)).toBeVisible()
    expect(screen.getAllByText(/4 August 2026/)).not.toHaveLength(0)
    expect(screen.getByRole('heading', { name: 'Other awards for this company' })).toBeVisible()
    expect(screen.getByRole('link', { name: /Open signal/ })).toHaveAttribute(
      'href',
      `/app/signals/sig_unlocked_1?presentation_artifact_id=${PRESENTATION.artifact_id}`,
    )
    expect(screen.getByText('No commercial action is published for this award.')).toBeVisible()
  })

  it('rend une révocation 404 sans révéler les faits ni proposer un faux retry', async () => {
    mockApi({
      ...authorizedRoutes(),
      [`GET ${ENDPOINT}`]: {
        status: 404,
        body: { detail: { code: 'company_not_found', message: 'entreprise introuvable' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(await screen.findByRole('heading', { name: 'Fiche entreprise inaccessible' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('12 rue des Ateliers')
  })

  it('réessaie localement une panne 503 sans relire le feed ni les détails autorisés', async () => {
    const user = userEvent.setup()
    let attempts = 0
    mockApi({
      ...authorizedRoutes(),
      [`GET ${ENDPOINT}`]: () => {
        attempts += 1
        return attempts === 1
          ? { status: 503, body: { detail: { code: 'service_unavailable' } } }
          : { body: COMPANY_PROFILE }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(await screen.findByRole('alert')).toHaveTextContent('La fiche entreprise n’a pas pu être chargée')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    const heading = await screen.findByRole('heading', { name: SUMMARY })
    expect(heading).toBeVisible()
    await waitFor(() => expect(heading).toHaveFocus())
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${PUBLISHED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(ENDPOINT, 'GET')).toHaveLength(2)
  })

  it('redirige un 401 du profil autorisé vers la connexion', async () => {
    mockApi({
      ...authorizedRoutes(),
      [`GET ${ENDPOINT}`]: {
        status: 401,
        body: { detail: { code: 'not_authenticated', message: 'session expirée' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(await screen.findByRole('heading', { name: 'Retrouver vos signaux' })).toBeVisible()
  })

  it('présente un chargement structuré puis une action clavier nommée', async () => {
    let resolveProfile!: (response: { body: CompanyProfile }) => void
    mockApi({
      ...authorizedRoutes(),
      [`GET ${ENDPOINT}`]: () => new Promise((resolve) => { resolveProfile = resolve }),
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    const loading = await screen.findByRole('status', { name: SUMMARY })
    expect(loading).toHaveTextContent('Chargement')
    await waitFor(() => expect(resolveProfile).toBeTypeOf('function'))
    await act(async () => {
      resolveProfile({ body: COMPANY_PROFILE })
      await Promise.resolve()
    })
    const action = await screen.findByRole('link', { name: /Ouvrir le signal/ })
    action.focus()
    expect(action).toHaveFocus()
  })

  it('ne lit ni n’écrit aucun fait d’entreprise dans le stockage navigateur', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem')
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    mockApi(authorizedRoutes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByRole('heading', { name: SUMMARY })
    expect(getItem).not.toHaveBeenCalled()
    expect(setItem).not.toHaveBeenCalled()
  })
})
