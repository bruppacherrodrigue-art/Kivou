import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'

import { AppRoutes } from '../App'
import { SessionProvider } from '../auth/SessionProvider'
import { I18nProvider } from '../i18n'
import { CATALOGUE, mockApi, renderApp, UNAUTHENTICATED } from '../test/harness'

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.hash}`}</output>
}

function HistoryBack() {
  const navigate = useNavigate()
  return <button type="button" onClick={() => navigate(-1)}>Historique précédent</button>
}

function renderWithHistory(entries: string[]) {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <I18nProvider initialLocale="fr">
        <SessionProvider initialState={UNAUTHENTICATED}>
          <AppRoutes />
          <LocationProbe />
          <HistoryBack />
        </SessionProvider>
      </I18nProvider>
    </MemoryRouter>,
  )
}

describe('informations légales exactes de la référence', () => {
  it('rend la route canonique avec les trois sections et ancres validées', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/informations-legales',
      session: UNAUTHENTICATED,
    })

    expect(screen.getByRole('heading', { level: 1, name: 'Informations légales et contractuelles' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    const mentions = container.querySelector<HTMLElement>('#mentions-legales')!
    const privacy = container.querySelector<HTMLElement>('#confidentialite')!
    const terms = container.querySelector<HTMLElement>('#cgu')!
    expect(mentions).toHaveAttribute('tabindex', '-1')
    expect(privacy).toHaveAttribute('tabindex', '-1')
    expect(terms).toHaveAttribute('tabindex', '-1')
    expect(within(mentions).getByRole('heading', { level: 2, name: 'Mentions légales' })).toBeInTheDocument()
    expect(within(privacy).getByRole('heading', { level: 2, name: 'Politique de confidentialité' })).toBeInTheDocument()
    expect(within(terms).getByRole('heading', { level: 2, name: 'Conditions générales d’utilisation et d’abonnement' })).toBeInTheDocument()
    expect(mentions.compareDocumentPosition(privacy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(privacy.compareDocumentPosition(terms) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('propose exactement le sommaire source', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/informations-legales', session: UNAUTHENTICATED })
    const contents = screen.getByRole('navigation', { name: 'Sommaire juridique' })
    expect(within(contents).getByRole('link', { name: 'Mentions légales' })).toHaveAttribute('href', '#mentions-legales')
    expect(within(contents).getByRole('link', { name: 'Confidentialité' })).toHaveAttribute('href', '#confidentialite')
    expect(within(contents).getByRole('link', { name: 'Conditions générales' })).toHaveAttribute('href', '#cgu')
  })

  it.each([
    ['/mentions-legales', '/informations-legales#mentions-legales', 'mentions-legales'],
    ['/confidentialite', '/informations-legales#confidentialite', 'confidentialite'],
    ['/cgu', '/informations-legales#cgu', 'cgu'],
  ])('redirige %s vers la bonne section et lui donne le focus', async (legacy, canonical, id) => {
    mockApi({})
    renderApp(<><AppRoutes /><LocationProbe /></>, { route: legacy, session: UNAUTHENTICATED })
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(canonical))
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById(id)))
  })

  it('ne piège pas le bouton précédent dans une redirection historique', async () => {
    mockApi({})
    const user = userEvent.setup()
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    try {
      renderWithHistory(['/contact', '/mentions-legales'])
      await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/informations-legales#mentions-legales'))
      await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
      await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/contact'))
      expect(screen.getByRole('heading', { level: 1, name: 'Contact' })).toBeInTheDocument()
    } finally {
      scrollTo.mockRestore()
    }
  })

  it('publie le document français validé sans contenu interne', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/informations-legales', session: UNAUTHENTICATED })
    const page = container.textContent ?? ''
    for (const clause of [
      'Rodrigue Bruppacher',
      'Rue des Champs-de-Tabac 12',
      'Infomaniak Network SA',
      'Rue Eugène Marziano 25',
      'Stripe',
      'kivou_session',
      'kivou_attribution',
      'En l’absence de fonction de suppression en libre-service',
      'La suppression du compte et la résiliation d’un abonnement sont deux opérations distinctes.',
    ]) expect(page).toContain(clause)
    expect(page).not.toContain('Contrat de publication')
    expect(page).not.toContain('Supprimer mon compte')
  })

  it('reste le document français exact avec initialLocale="en"', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/informations-legales',
      locale: 'en',
      session: UNAUTHENTICATED,
    })
    expect(screen.getByRole('heading', { level: 2, name: 'Politique de confidentialité' })).toBeInTheDocument()
    expect(container).not.toHaveTextContent('Privacy Policy')
    expect(document.documentElement.lang).toBe('fr')
  })

  it('définit les métadonnées exactes et la canonique', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/informations-legales', session: UNAUTHENTICATED })
    expect(document.title).toBe('Informations légales et contractuelles | Kivou')
    expect(document.querySelector('meta[name="description"]')).toHaveAttribute('content', 'Consultez les mentions légales, la politique de confidentialité et les Conditions générales de Kivou.')
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', 'https://kivou.eu/informations-legales')
  })
})

describe('page Contact exacte', () => {
  it('préserve le contrat mailto natif, les champs et le texte source', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/contact', session: UNAUTHENTICATED })
    const form = container.querySelector('form')!
    expect(form).toHaveClass('glass', 'contact-form')
    expect(form).toHaveAttribute('action', 'mailto:contact@kivou.eu?subject=Contact%20Kivou')
    expect(form).toHaveAttribute('method', 'post')
    expect(form).toHaveAttribute('enctype', 'text/plain')
    expect(screen.getByRole('textbox', { name: 'Nom' })).toHaveAttribute('name', 'Nom')
    expect(screen.getByRole('textbox', { name: 'E-mail professionnel' })).toHaveAttribute('name', 'E-mail')
    expect(screen.getByRole('combobox', { name: 'Sujet' })).toHaveAttribute('name', 'Sujet')
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveAttribute('name', 'Message')
    expect(screen.getByRole('button', { name: 'Envoyer le message' })).toBeInTheDocument()
    expect(screen.getByText('L’envoi s’ouvre dans votre messagerie et reste sous votre contrôle.')).toBeInTheDocument()
  })
})

describe('footer public exact', () => {
  it('contient les destinations et le texte de la référence', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/contact', session: UNAUTHENTICATED })
    const footer = screen.getByRole('contentinfo')
    for (const [name, href] of [
      ['Comment ça marche', '/produit'],
      ['Exemple de signal', '/exemple-de-signal'],
      ['Tarifs', '/tarifs'],
      ['Créer un compte', '/signup?plan=discovery'],
      ['Se connecter', '/login'],
      ['Nous contacter', '/contact'],
      ['Mentions légales', '/informations-legales#mentions-legales'],
      ['Confidentialité', '/informations-legales#confidentialite'],
      ['Conditions générales', '/informations-legales#cgu'],
    ] as const) expect(within(footer).getByRole('link', { name })).toHaveAttribute('href', href)
    expect(within(footer).getByText('Sources officielles accessibles. Couverture européenne.')).toBeInTheDocument()
    expect(within(footer).queryByText(/^FR$|^EN$/)).not.toBeInTheDocument()
  })
})

describe('navigation SPA du shell public', () => {
  it('ferme le menu mobile même quand la destination est la route courante', async () => {
    mockApi({})
    const user = userEvent.setup()
    renderApp(<AppRoutes />, { route: '/contact', session: UNAUTHENTICATED })
    const menu = document.querySelector<HTMLDetailsElement>('details.mobile-menu')!
    await user.click(menu.querySelector('summary')!)
    expect(menu.open).toBe(true)

    const mobileNav = within(menu).getByRole('navigation', { name: 'Navigation mobile' })
    await user.click(within(mobileNav).getByRole('link', { name: 'Contact' }))
    await waitFor(() => expect(menu.open).toBe(false))
  })

  it('revient en haut lors d’un changement de pathname sans hash', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const user = userEvent.setup()
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    try {
      const view = renderApp(<><AppRoutes /><LocationProbe /></>, {
        route: '/tarifs',
        session: UNAUTHENTICATED,
      })
      const finalCta = view.container.querySelector<HTMLElement>('.pricing-page .final-cta')!
      await user.click(within(finalCta).getByRole('link', { name: 'Voir un signal' }))

      await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/exemple-de-signal'))
      expect(scrollTo).toHaveBeenCalledWith(0, 0)
    } finally {
      scrollTo.mockRestore()
    }
  })

  it('ferme le menu sur une destination hash et laisse HashTarget défiler et focaliser', async () => {
    mockApi({})
    const user = userEvent.setup()
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    try {
      renderApp(<><AppRoutes /><LocationProbe /></>, {
        route: '/informations-legales',
        session: UNAUTHENTICATED,
      })
      const menu = document.querySelector<HTMLDetailsElement>('details.mobile-menu')!
      await user.click(menu.querySelector('summary')!)
      expect(menu.open).toBe(true)

      const target = document.getElementById('cgu')!
      const scrollIntoView = vi.fn()
      Object.defineProperty(target, 'scrollIntoView', { configurable: true, value: scrollIntoView })
      const footer = screen.getByRole('contentinfo')
      await user.click(within(footer).getByRole('link', { name: 'Conditions générales' }))

      await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/informations-legales#cgu'))
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' }))
      expect(document.activeElement).toBe(target)
      expect(scrollTo).not.toHaveBeenCalled()
      expect(menu.open).toBe(false)
    } finally {
      scrollTo.mockRestore()
    }
  })
})
