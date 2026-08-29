import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import type { CompanyProfile } from '../api/types'
import {
  AUTHENTICATED,
  COMPANY_PROFILE,
  ME,
  mockApi,
  renderApp,
} from '../test/harness'

const PATH = '/app/companies/cmp_0123456789abcdefghijklmnop'
const ENDPOINT = '/companies/cmp_0123456789abcdefghijklmnop'

afterEach(() => vi.unstubAllGlobals())

function companyRoutes(profile: CompanyProfile = COMPANY_PROFILE) {
  return { [`GET ${ENDPOINT}`]: { body: profile } }
}

describe('fiche entreprise officielle', () => {
  it('rend la valeur commerciale, les faits officiels, les actions et les sources en français', async () => {
    mockApi(companyRoutes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Constructions Bertrand SA' }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelectorAll('main')).toHaveLength(1)
    expect(screen.getByText('12 rue des Ateliers, 31270 Villeneuve')).toBeInTheDocument()
    expect(screen.getByText('SIRET')).toBeInTheDocument()
    expect(screen.getByText('12345678900011')).toBeInTheDocument()
    expect(screen.getAllByText('Avis public')).not.toHaveLength(0)
    expect(screen.getByText('23 août 2026')).toBeInTheDocument()

    const external = screen.getByRole('link', { name: /Ouvrir le site de l’entreprise/ })
    expect(external).toHaveAttribute('href', 'https://constructions-bertrand.example/entreprise')
    expect(external).toHaveAttribute('target', '_blank')
    expect(external).toHaveAttribute('rel', expect.stringContaining('noopener'))

    const related = screen.getByRole('region', { name: 'Signaux Kivou liés' })
    expect(within(related).getByText(/1.240.000.€/)).toBeInTheDocument()
    expect(within(related).getByRole('link', { name: 'Examiner le signal' })).toHaveAttribute(
      'href',
      '/app/signals/sig_unlocked_1',
    )
    expect(screen.getByText('Matériaux ou composants')).toBeInTheDocument()
    expect(screen.getByText('Très bon pour votre profil')).toBeInTheDocument()

    expect(
      screen.queryByRole('complementary', {
        name: 'Pourquoi cette entreprise mérite votre attention',
      }),
    ).not.toBeInTheDocument()
    const context = screen.getByRole('region', {
      name: 'Pourquoi cette entreprise mérite votre attention',
    })
    expect(
      within(context).getByRole('heading', { name: 'Pourquoi cette entreprise mérite votre attention' }),
    ).toBeInTheDocument()
    const sources = screen.getByRole('region', { name: 'Sources et couverture' })
    expect(within(sources).getByRole('heading', { name: 'Sources et couverture' })).toBeInTheDocument()
  })

  it('masque les champs absents et résume une couverture partielle une seule fois', async () => {
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
    mockApi(companyRoutes(partial))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    expect(screen.queryByText('Adresse officielle')).not.toBeInTheDocument()
    expect(screen.queryByText('Identifiants officiels')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /site de l’entreprise/ })).not.toBeInTheDocument()
    expect(screen.getAllByText(/Certaines informations officielles ne sont pas publiées/)).toHaveLength(1)
    expect(document.body.textContent).not.toContain('Non disponible')
  })

  it('refuse défensivement une URL externe qui ne respecte pas HTTPS', async () => {
    const unsafe = {
      ...COMPANY_PROFILE,
      official_identity: {
        ...COMPANY_PROFILE.official_identity,
        website_url: 'javascript:alert(1)',
      },
    }
    mockApi(companyRoutes(unsafe))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    expect(screen.queryByRole('link', { name: /site de l’entreprise/ })).not.toBeInTheDocument()
  })

  it('refuse défensivement une adresse IP locale même sous HTTPS', async () => {
    const unsafe = {
      ...COMPANY_PROFILE,
      official_identity: {
        ...COMPANY_PROFILE.official_identity,
        website_url: 'https://127.0.0.1/admin',
      },
    }
    mockApi(companyRoutes(unsafe))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    expect(screen.queryByRole('link', { name: /site de l’entreprise/ })).not.toBeInTheDocument()
  })

  it('rend le même degré de certitude en anglais', async () => {
    const englishSession = {
      status: 'authenticated' as const,
      me: { ...ME, locale: 'en' },
    }
    mockApi(companyRoutes())
    renderApp(<AppRoutes />, { session: englishSession, route: PATH, locale: 'en' })

    await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    expect(screen.getAllByText('Public notice')).not.toHaveLength(0)
    expect(screen.getByText('23 August 2026')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Why this company deserves attention' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Review signal' })).not.toHaveLength(0)
  })

  it('rend une fiche inaccessible comme un état produit sans révéler de faits', async () => {
    mockApi({
      [`GET ${ENDPOINT}`]: {
        status: 404,
        body: { detail: { code: 'company_not_found', message: 'entreprise introuvable' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Fiche entreprise inaccessible' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Retour aux signaux' })).toHaveAttribute(
      'href',
      '/app/signals',
    )
    expect(document.body.textContent).not.toContain('Constructions Bertrand')
  })

  it('conserve un état d’erreur compact lorsque le service est indisponible', async () => {
    mockApi({
      [`GET ${ENDPOINT}`]: {
        status: 503,
        body: { detail: { code: 'service_unavailable', message: 'indisponible' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'La fiche entreprise n’a pas pu être chargée',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Retour aux signaux' })).toHaveAttribute(
      'href',
      '/app/signals',
    )
    expect(document.body.textContent).not.toContain('Constructions Bertrand')
  })

  it('redirige une session expirée vers la connexion', async () => {
    mockApi({
      [`GET ${ENDPOINT}`]: {
        status: 401,
        body: { detail: { code: 'not_authenticated', message: 'session expirée' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(await screen.findByText(/session a expiré/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Se connecter' })).toBeInTheDocument()
  })

  it('présente un chargement structuré et des actions accessibles au clavier', async () => {
    const user = userEvent.setup()
    let resolveRequest: ((response: Response) => void) | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveRequest = resolve
          }),
      ),
    )
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    expect(screen.getByRole('status', { name: 'Chargement…' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Chargement…' })).toBeInTheDocument()
    resolveRequest?.(
      new Response(JSON.stringify(COMPANY_PROFILE), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })

    await user.tab()
    await waitFor(() => expect(document.activeElement).toHaveAttribute('href', '#kivou-main'))

    const backLinks = screen.getAllByRole('link', { name: 'Retour aux signaux' })
    const reviewLinks = screen.getAllByRole('link', { name: 'Examiner le signal' })
    const external = screen.getByRole('link', { name: /Ouvrir le site de l’entreprise/ })

    backLinks[0].focus()
    expect(backLinks[0]).toHaveFocus()
    await user.tab()
    expect(reviewLinks[0]).toHaveFocus()
    await user.tab()
    expect(backLinks[1]).toHaveFocus()
    await user.tab()
    expect(external).toHaveFocus()
  })

  it('ne lit ni n’écrit aucun fait d’entreprise dans sessionStorage', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem')
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    mockApi(companyRoutes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: PATH })

    await screen.findByRole('heading', { name: 'Constructions Bertrand SA' })
    expect(getItem).not.toHaveBeenCalled()
    expect(setItem).not.toHaveBeenCalled()
  })
})
