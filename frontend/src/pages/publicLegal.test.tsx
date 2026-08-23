import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'

import { AppRoutes } from '../App'
import { SessionProvider } from '../auth/SessionProvider'
import { legalContent } from '../content/legalContent'
import { I18nProvider } from '../i18n'
import type { Locale } from '../i18n'
import { mockApi, renderApp, UNAUTHENTICATED } from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.hash}`}</output>
}

function HistoryBack() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Historique précédent
    </button>
  )
}

function renderWithHistory(entries: string[], locale: Locale = 'fr') {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <I18nProvider initialLocale={locale}>
        <SessionProvider initialState={UNAUTHENTICATED}>
          <AppRoutes />
          <LocationProbe />
          <HistoryBack />
        </SessionProvider>
      </I18nProvider>
    </MemoryRouter>,
  )
}

describe('informations légales publiques', () => {
  it('rend la route canonique avec un seul h1 et les trois sections dans le bon ordre', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/informations-legales',
      session: UNAUTHENTICATED,
    })

    expect(screen.queryByText('Page introuvable')).not.toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 1, name: 'Informations légales et contractuelles' }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)

    const mentions = container.querySelector<HTMLElement>('#mentions-legales')!
    const privacy = container.querySelector<HTMLElement>('#confidentialite')!
    const terms = container.querySelector<HTMLElement>('#cgu')!

    expect(mentions).toHaveAttribute('tabindex', '-1')
    expect(privacy).toHaveAttribute('tabindex', '-1')
    expect(terms).toHaveAttribute('tabindex', '-1')
    expect(within(mentions).getByRole('heading', { level: 2, name: 'Mentions légales' })).toBeInTheDocument()
    expect(
      within(privacy).getByRole('heading', { level: 2, name: 'Politique de confidentialité' }),
    ).toBeInTheDocument()
    expect(
      within(terms).getByRole('heading', {
        level: 2,
        name: 'Conditions générales d’utilisation et d’abonnement',
      }),
    ).toBeInTheDocument()
    expect(mentions.compareDocumentPosition(privacy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(privacy.compareDocumentPosition(terms) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('propose un sommaire utilisant exactement les trois ancres canoniques', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/informations-legales', session: UNAUTHENTICATED })

    const contents = screen.getByRole('navigation', { name: 'Sommaire juridique' })
    expect(within(contents).getByRole('link', { name: 'Mentions légales' })).toHaveAttribute(
      'href',
      '/informations-legales#mentions-legales',
    )
    expect(within(contents).getByRole('link', { name: 'Confidentialité' })).toHaveAttribute(
      'href',
      '/informations-legales#confidentialite',
    )
    expect(within(contents).getByRole('link', { name: 'Conditions générales' })).toHaveAttribute(
      'href',
      '/informations-legales#cgu',
    )
  })

  it.each([
    ['/mentions-legales', '/informations-legales#mentions-legales', 'mentions-legales'],
    ['/confidentialite', '/informations-legales#confidentialite', 'confidentialite'],
    ['/cgu', '/informations-legales#cgu', 'cgu'],
  ])('redirige %s vers la bonne section et lui donne le focus', async (legacy, canonical, id) => {
    mockApi({})
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: legacy, session: UNAUTHENTICATED },
    )

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(canonical))
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById(id)))
  })

  it('ne piège pas le bouton précédent dans la redirection d’une ancienne URL', async () => {
    mockApi({})
    const user = userEvent.setup()
    renderWithHistory(['/contact', '/mentions-legales'])

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/informations-legales#mentions-legales',
      ),
    )
    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/contact'))
    expect(screen.getByRole('heading', { level: 1, name: 'Contactez-nous' })).toBeInTheDocument()
  })

  it('conserve l’ancre active et le focus lors du passage en anglais', async () => {
    mockApi({})
    const user = userEvent.setup()
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/informations-legales#confidentialite', session: UNAUTHENTICATED },
    )

    await waitFor(() => expect(document.activeElement?.id).toBe('confidentialite'))
    await user.click(screen.getByRole('button', { name: 'EN' }))

    expect(screen.getByTestId('location')).toHaveTextContent(
      '/informations-legales#confidentialite',
    )
    await waitFor(() => expect(document.activeElement?.id).toBe('confidentialite'))
    expect(
      screen.getByRole('heading', { level: 2, name: 'Privacy Policy' }),
    ).toBeInTheDocument()
  })

  it('publie uniquement le contenu public validé et les identités vérifiées', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/informations-legales',
      session: UNAUTHENTICATED,
    })
    const page = container.textContent ?? ''

    expect(page).toContain('Rodrigue Bruppacher')
    expect(page).toContain('Rue des Champs-de-Tabac 12')
    expect(page).toContain('Infomaniak Network SA')
    expect(page).toContain('Rue Eugène Marziano 25')
    expect(page).toContain('Stripe')
    expect(page).toContain('kivou_session')
    expect(page).toContain('kivou_attribution')
    expect(page).toContain('En l’absence de fonction de suppression en libre-service')
    expect(page).toContain('La suppression du compte et la résiliation d’un abonnement sont deux opérations distinctes.')

    for (const internalHeading of [
      'Contrat de publication',
      'Informations factuelles validées',
      'Footer public attendu',
      'Vérifications juridiques avant LIVE',
      'Sources de vérification',
    ]) {
      expect(page).not.toContain(internalHeading)
    }
    expect(page).not.toContain('Supprimer mon compte')
    expect(page).not.toContain('Export inclus')
    expect(page).not.toContain('Filtres avancés inclus')
  })

  it('rend les mêmes sections et actions juridiques en anglais', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/informations-legales',
      locale: 'en',
      session: UNAUTHENTICATED,
    })

    expect(
      screen.getByRole('heading', { level: 1, name: 'Legal and contractual information' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Legal notice' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Privacy Policy' })).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 2, name: 'Terms of Use and Subscription' }),
    ).toBeInTheDocument()
    expect(container.querySelectorAll('section[id]')).toHaveLength(3)
    expect(container.textContent).toContain('Where no self-service deletion function is available')
    expect(container.textContent).toContain('Account deletion and subscription cancellation are separate operations.')
    expect(document.documentElement.lang).toBe('en')
  })

  it('conserve la parité des clauses entre la source publique française et anglaise', () => {
    expect(legalContent.fr.sections.map((section) => section.id)).toEqual(
      legalContent.en.sections.map((section) => section.id),
    )
    expect(legalContent.fr.sections.map((section) => section.subsections.length)).toEqual([
      4, 13, 22,
    ])
    expect(legalContent.en.sections.map((section) => section.subsections.length)).toEqual([
      4, 13, 22,
    ])
    expect(legalContent.fr.sections.map((section) => section.subsections.length)).toEqual(
      legalContent.en.sections.map((section) => section.subsections.length),
    )
  })

  it('définit des métadonnées et une URL canonique propres à la page', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/informations-legales', session: UNAUTHENTICATED })

    expect(document.title).toBe('Informations légales et contractuelles — Kivou')
    expect(document.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      expect.stringContaining('mentions légales'),
    )
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      'https://kivou.eu/informations-legales',
    )
  })
})

describe('page Contactez-nous', () => {
  it('rend une vraie page sans formulaire, téléphone ou promesse de délai', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/contact', session: UNAUTHENTICATED })

    expect(screen.queryByText('Page introuvable')).not.toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByRole('heading', { level: 1, name: 'Contactez-nous' })).toBeInTheDocument()
    for (const category of [
      'Produit et compte',
      'Facturation',
      'Confidentialité',
      'Partenariats et questions générales',
    ]) {
      expect(screen.getByRole('heading', { level: 2, name: category })).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: 'Écrire à contact@kivou.eu' })).toHaveAttribute(
      'href',
      'mailto:contact@kivou.eu',
    )
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Voir mes 3 premiers signaux' })).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(container.querySelector('form')).toBeNull()
    expect(container.querySelector('a[href^="tel:"]')).toBeNull()
    expect(container.textContent).not.toMatch(/réponse sous|répondons? en|24 heures|48 heures/i)
  })

  it('conserve exactement les mêmes catégories et actions en anglais', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/contact',
      locale: 'en',
      session: UNAUTHENTICATED,
    })

    expect(screen.getByRole('heading', { level: 1, name: 'Contact us' })).toBeInTheDocument()
    for (const category of [
      'Product and account',
      'Billing',
      'Privacy',
      'Partnerships and general enquiries',
    ]) {
      expect(screen.getByRole('heading', { level: 2, name: category })).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: 'Email contact@kivou.eu' })).toHaveAttribute(
      'href',
      'mailto:contact@kivou.eu',
    )
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'See my first 3 signals' })).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(container.querySelector('form')).toBeNull()
  })
})

describe('footer public complet', () => {
  it('contient toutes les destinations demandées avec une hiérarchie de liens honnête', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/contact', session: UNAUTHENTICATED })

    const footer = screen.getByRole('contentinfo')
    const expectedLinks = [
      ['Accueil', '/'],
      ['Exemple de signal', '/exemple-de-signal'],
      ['Comment ça marche', '/#comment'],
      ['Tarifs', '/#tarifs'],
      ['Voir mes 3 premiers signaux', '/signup'],
      ['Se connecter', '/login'],
      ['Contactez-nous', '/contact'],
      ['Mentions légales', '/informations-legales#mentions-legales'],
      ['Confidentialité', '/informations-legales#confidentialite'],
      ['Conditions générales', '/informations-legales#cgu'],
    ] as const

    for (const [name, href] of expectedLinks) {
      expect(within(footer).getByRole('link', { name: `${name} — pied de page` })).toHaveAttribute(
        'href',
        href,
      )
    }
    expect(within(footer).getByText(/Tous droits réservés/)).toBeInTheDocument()
    expect(within(footer).getByText(/Performance commerciale sous contrôle/)).toBeInTheDocument()
    expect(within(footer).getByRole('group', { name: 'Langue du pied de page' })).toBeInTheDocument()
    expect(within(footer).getByRole('button', { name: 'EN — pied de page' })).toBeInTheDocument()
    expect(footer.querySelector('a[href*="twitter"], a[href*="linkedin"], a[href^="tel:"]')).toBeNull()
  })

  it.each([
    '/',
    '/exemple-de-signal',
    '/informations-legales',
    '/contact',
    '/login',
    '/signup',
    '/forgot-password',
    '/reset-password',
  ])('reste présent sur la surface publique %s', (route) => {
    mockApi({})
    const view = renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
    view.unmount()
  })

  it('offre les mêmes destinations en anglais', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/contact', locale: 'en', session: UNAUTHENTICATED })

    const footer = screen.getByRole('contentinfo')
    expect(within(footer).getByRole('link', { name: 'Home — footer' })).toHaveAttribute('href', '/')
    expect(within(footer).getByRole('link', { name: 'Signal example — footer' })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
    expect(within(footer).getByRole('link', { name: 'See my first 3 signals — footer' })).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(within(footer).getByRole('link', { name: 'Contact us — footer' })).toHaveAttribute(
      'href',
      '/contact',
    )
    expect(within(footer).getByRole('link', { name: 'Legal notice — footer' })).toHaveAttribute(
      'href',
      '/informations-legales#mentions-legales',
    )
    expect(within(footer).getByText(/All rights reserved/)).toBeInTheDocument()
    expect(within(footer).getByRole('group', { name: 'Footer language' })).toBeInTheDocument()
  })
})
