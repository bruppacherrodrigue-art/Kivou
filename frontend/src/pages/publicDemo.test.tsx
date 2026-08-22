import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AppRoutes } from '../App'
import { landingHeroSignals } from '../content/landingHeroSignals'
import { publicDemoSignal } from '../content/publicDemoSignal'
import { en } from '../i18n/en'
import { fr } from '../i18n/fr'
import { CATALOGUE, mockApi, recordedCalls, renderApp, UNAUTHENTICATED } from '../test/harness'

/* La démonstration publique doit vendre l'avance commerciale avant d'exposer
 * ses garde-fous. Ces tests verrouillent cet ordre sans jamais relâcher la
 * distinction entre faits publiés, opportunités plausibles et limites. */

afterEach(() => vi.unstubAllGlobals())

describe('démonstration publique de signal', () => {
  it('se rend entièrement sans session, et n’appelle aucun point d’entrée client', async () => {
    // Le fournisseur de session sonde `/me` au montage de l'application. Ce
    // que la page doit garantir n'est pas l'absence de cet appel, mais son
    // caractère NON BLOQUANT : ici la sonde échoue, et la page se rend quand
    // même, entièrement.
    mockApi({ 'GET /me': { status: 401, body: { code: 'not_authenticated' } } })
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'H. Hüther GmbH vient de remporter un chantier de 5,22 M€ à Munich',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Contrat signé. Exécution à venir. Moment pertinent pour se positionner.')).toBeInTheDocument()

    // Aucune donnée de compte n'est demandée pour une surface publique.
    const clientRoutes = recordedCalls.filter((call) =>
      ['/signals', '/target-icps', '/billing/plans', '/notification-preferences'].some((path) =>
        call.url.startsWith(path),
      ),
    )
    expect(clientRoutes).toHaveLength(0)
  })

  it('n’a qu’un seul h1', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('affiche les faits publiés et leur source officielle, sûrement ouverte', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })

    expect(await screen.findByText(publicDemoSignal.winner.legalName)).toBeInTheDocument()
    expect(screen.getByText(publicDemoSignal.buyer.legalName)).toBeInTheDocument()
    expect(screen.getByText('80335 München · Allemagne')).toBeInTheDocument()

    for (const source of screen.getAllByRole('link', { name: /preuve officielle|avis officiel/i })) {
      expect(source).toHaveAttribute('href', publicDemoSignal.sourceUrl)
      expect(source).toHaveAttribute('target', '_blank')
      expect(source.getAttribute('rel')).toContain('noopener')
      expect(source.getAttribute('rel')).toContain('noreferrer')
    }
  })

  it('présente les sections dans l’ordre opportunité, pertinence, timing, action, preuve, limites', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    const text = container.textContent ?? ''
    const markers = [
      'Pourquoi ce prospect mérite votre attention',
      'Opportunités commerciales associées',
      'Pourquoi le timing est favorable',
      'Transformez le signal en prise de contact',
      'Les faits essentiels sont vérifiables',
      'Couverture de cette analyse',
    ]
    const positions = markers.map((marker) => text.indexOf(marker))

    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
  })

  it('rend les volumes commerciaux dominants tout en conservant les désignations source', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    for (const [value, label, source] of [
      ['497', 'Huisseries et portes bois', 'Holzzarge Holzblatt'],
      ['234', 'Huisseries acier et portes bois', 'Stahlzarge Holzblatt'],
      ['5 485 m', 'Plinthes', 'Sockelleisten'],
      ['425 m²', 'Revêtement mural bois', 'Holzwandverkleidung'],
      ['24', 'Éléments vitrés', 'Verglasungen'],
      ['13', 'Kitchenettes', 'Teeküchen'],
    ]) {
      expect(screen.getByText(value)).toBeInTheDocument()
      expect(screen.getByText(label)).toBeInTheDocument()
      expect(screen.getByText(source)).toBeInTheDocument()
    }
    expect(screen.getByText(/ne sont pas présentées comme un extrait de cahier des charges/i)).toBeInTheDocument()
  })

  it('expose quatre angles commerciaux qualifiés une seule fois comme inférences', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    for (const title of [
      'Portes, huisseries et quincaillerie',
      'Plinthes et produits bois',
      'Vitrage',
      'Kitchenettes et agencement',
    ]) {
      expect(screen.getByRole('heading', { level: 3, name: title })).toBeInTheDocument()
    }
    expect((text.match(/pas des achats futurs confirmés/g) ?? [])).toHaveLength(1)
  })

  it('montre le matching, la chronologie et une prochaine action sans inventer de décideur', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    for (const item of [
      'votre offre correspond aux catégories publiées',
      'les volumes sont suffisamment importants pour justifier une prospection',
      'la zone d’exécution se trouve dans votre territoire commercial',
      'l’exécution n’a pas encore commencé',
    ]) {
      expect(screen.getByText(item)).toBeInTheDocument()
    }
    expect(text).toContain('Maintenant')
    expect(text).toContain('28 octobre 2026')
    expect(text).toContain('identifier le responsable achats, approvisionnement, travaux ou opérations')
    expect(text).not.toMatch(/responsable\s+[A-ZÀ-Ý][a-zà-ÿ]+\s+[A-ZÀ-Ý][a-zà-ÿ]+/)
  })

  it('relègue les limites après la preuve sans badge global de confiance réduite', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    expect(text.indexOf('Les faits essentiels sont vérifiables')).toBeLessThan(
      text.indexOf('Couverture de cette analyse'),
    )
    expect(text).toContain('Aucun cahier des charges complet validé n’a été utilisé')
    expect(text).toContain('Couverture documentaire')
    expect(text).toContain('Partielle')
    expect(text).not.toMatch(/confiance réduite/i)
  })

  it('relie tous les CTA aux parcours existants', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    for (const name of [
      'Voir mes 3 signaux',
      'Recevoir des signaux adaptés à mon activité',
      'Créer mon profil de ciblage',
      'Voir mes 3 premiers signaux',
    ]) {
      expect(screen.getByRole('link', { name })).toHaveAttribute('href', '/signup')
    }
    expect(screen.getByRole('link', { name: 'Comment Kivou sélectionne mes prospects' })).toHaveAttribute(
      'href',
      '/#comment',
    )
  })
})

describe('hero de la page d’accueil', () => {
  it('montre le premier signal, les CTA fixes et sa source vérifiée', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    const signalTitle = screen.getByRole('heading', {
      level: 2,
      name: landingHeroSignals[0].headline.fr,
    })
    const card = signalTitle.closest('article')!
    expect(screen.getAllByRole('link', { name: fr.landing.heroPrimary })[0]).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(screen.getByRole('link', { name: fr.landing.heroSecondary })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
    expect(within(card).getByRole('link', { name: fr.landing.heroCarousel.viewSignal })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
    expect(within(card).getByText(/TED · Source vérifiée/)).toBeInTheDocument()
  })

  it('ne porte pas la mesure technique de couverture documentaire', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    screen.getByRole('heading', { level: 2, name: landingHeroSignals[0].headline.fr })
    const text = container.textContent ?? ''

    // Le premier écran commercial n'a pas à annoncer une confiance réduite :
    // les FAITS de l'attribution sont vérifiés, seule l'inférence repose sur
    // les métadonnées. La limite est dite sur la fiche complète.
    expect(text).not.toContain('Couverture de cette analyse')
    expect(text).not.toContain('Aucun cahier des charges complet validé')
    expect(text).not.toMatch(/confiance réduite/i)
    // Mais la valeur commerciale reste séparée des faits par un bloc nommé.
    expect(text).toContain(fr.landing.heroCarousel.opportunityLabel)
  })

  it('conserve la couverture documentaire sur la fiche complète, après la valeur', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    // Ne pas en faire le message du hero ne veut pas dire la masquer : elle
    // doit rester entière là où elle éclaire.
    expect(text).toContain('Couverture de cette analyse')
    expect(text).toContain('Aucun cahier des charges complet validé')
    expect(text.indexOf('Contrat signé. Exécution à venir.')).toBeLessThan(
      text.indexOf('Couverture de cette analyse'),
    )
  })

  it('en anglais aussi, le hero affirme et la fiche relègue les limites', async () => {
    mockApi({})
    const home = renderApp(<AppRoutes />, { route: '/', locale: 'en', session: UNAUTHENTICATED })
    screen.getByRole('heading', { level: 2, name: landingHeroSignals[0].headline.en })
    expect(home.container.textContent).toContain(en.landing.heroCarousel.sourceVerified)
    expect(home.container.textContent).not.toContain('Coverage of this analysis')
    expect(home.container.textContent).not.toMatch(/reduced confidence/i)
    home.unmount()

    const demo = renderApp(<AppRoutes />, { route: '/exemple-de-signal', locale: 'en' })
    await screen.findByRole('heading', { level: 1 })
    const text = demo.container.textContent ?? ''
    expect(text).toContain('Contract signed. Performance ahead. A relevant time to engage.')
    expect(text).toContain('Coverage of this analysis')
    expect(text.indexOf('Contract signed. Performance ahead.')).toBeLessThan(
      text.indexOf('Coverage of this analysis'),
    )
  })

  it('annonce le contrat détecté sans promesse garantie', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    screen.getByRole('heading', { level: 2, name: landingHeroSignals[0].headline.fr })
    const text = container.textContent ?? ''

    expect(text).toContain(fr.landing.heroCarousel.eventLabel)
    expect(text).not.toMatch(/achat garanti|commande garantie/i)
  })

  it('sépare le fait publié de l’occasion commerciale Kivou', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    const card = screen
      .getByRole('heading', { level: 2, name: landingHeroSignals[0].headline.fr })
      .closest('article')!
    expect(within(card).getByText(fr.landing.heroCarousel.opportunityLabel)).toBeInTheDocument()
    expect(within(card).getByText(landingHeroSignals[0].opportunity.fr)).toBeInTheDocument()
    expect(card).not.toHaveTextContent(/va acheter|achat garanti/i)
  })
})

describe('navigation publique', () => {
  it('ouvre et referme un menu accessible au clavier', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    const toggle = await screen.findByRole('button', { name: fr.nav.openMenu })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)
    const panel = document.getElementById('kivou-public-menu')!
    expect(within(panel).getByRole('link', { name: fr.publicDemo.navLabel })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )

    await user.keyboard('{Escape}')
    expect(document.getElementById('kivou-public-menu')).not.toBeInTheDocument()
  })
})

describe('données de démonstration', () => {
  it('conserve exactement les faits du signal TED 568562-2026', () => {
    expect(publicDemoSignal).toMatchObject({
      noticeId: '568562-2026',
      sourceUrl: 'https://ted.europa.eu/en/notice/568562-2026/xml',
      lastVerifiedAt: '2026-08-20',
      winner: {
        legalName: 'H. Hüther GmbH',
        identifier: { value: 'DE115302781' },
      },
      buyer: { legalName: 'Staatl. Bauamt München 1' },
      contract: {
        title: 'Tischlerarbeiten Innentüren und Möbel',
        reference: '26-000.723.722',
        cpv: '45420000',
        amount: '5219043.35',
        currency: 'EUR',
        locality: 'München',
        postalCode: '80335',
        publishedQuantities: [
          'Holzzarge Holzblatt : 497',
          'Stahlzarge Holzblatt : 234',
          'Sockelleisten : 5 485 m',
          'Holzwandverkleidung : 425 m²',
          'Verglasungen : 24',
          'Teeküchen : 13',
        ],
      },
      timing: {
        awardDate: '2026-08-14',
        signatureDate: '2026-08-14',
        publishedAt: '2026-08-17',
        startDate: '2026-10-28',
        endDate: '2027-10-29',
      },
    })
  })

  it('n’expose aucun champ lié à un compte client', () => {
    const keys = JSON.stringify(publicDemoSignal).toLowerCase()

    for (const forbidden of [
      'icp',
      'score',
      'band',
      'feedback',
      'grant',
      'billing',
      'account_id',
      'target_icp',
    ]) {
      expect(keys).not.toContain(`"${forbidden}"`)
    }
  })

  it('porte une source et une date de vérification exploitables', () => {
    expect(publicDemoSignal.sourceUrl).toMatch(/^https:\/\/ted\.europa\.eu\//)
    expect(publicDemoSignal.lastVerifiedAt).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(publicDemoSignal.documentary.mode).toBe('metadata_fallback')
    expect(publicDemoSignal.documentary.validatedRequirement).toBe(false)
  })

  it('a une date d’attribution réelle, antérieure au début d’exécution', () => {
    const award = new Date(publicDemoSignal.timing.awardDate)
    const start = new Date(publicDemoSignal.timing.startDate)

    expect(Number.isNaN(award.getTime())).toBe(false)
    // Sans vraie date d'attribution, le hero n'aurait pas le droit de parler
    // de « nouvelle attribution ».
    expect(award.getTime()).toBeLessThan(start.getTime())
  })
})

describe('dictionnaires', () => {
  it('couvre les mêmes clés publicDemo en français et en anglais', () => {
    expect(Object.keys(en.publicDemo).sort()).toEqual(Object.keys(fr.publicDemo).sort())
  })

  it('ne laisse aucune chaîne publicDemo vide', () => {
    for (const dictionary of [fr.publicDemo, en.publicDemo]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(typeof value === 'string' && value.trim().length > 0, key).toBe(true)
      }
    }
  })
})


describe('localisation de la démonstration', () => {
  it('bascule réellement tout le discours commercial en anglais', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    const user = userEvent.setup()

    // Français d'abord — l'état de départ doit être vérifié, sinon la bascule
    // pourrait passer alors que rien n'a jamais été français.
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'H. Hüther GmbH vient de remporter un chantier de 5,22 M€ à Munich',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Pourquoi ce prospect mérite votre attention')).toBeInTheDocument()

    // Bascule RÉELLE de la locale, par le sélecteur de l'interface.
    await user.click(screen.getByRole('button', { name: 'EN' }))

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'H. Hüther GmbH has just won a €5.22m contract in Munich',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Why this prospect deserves your attention')).toBeInTheDocument()
    expect(screen.queryByText('Pourquoi ce prospect mérite votre attention')).not.toBeInTheDocument()
  })

  it('laisse les faits sources dans leur forme d’origine après bascule', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    const user = userEvent.setup()
    await screen.findByText(publicDemoSignal.winner.legalName)

    await user.click(screen.getByRole('button', { name: 'EN' }))

    // Un nom d'entreprise ne se traduit pas.
    expect(await screen.findByText(publicDemoSignal.winner.legalName)).toBeInTheDocument()
    expect(screen.getByText(publicDemoSignal.contract.title)).toBeInTheDocument()
  })
})

describe('promesse de preuve', () => {
  it('annonce des champs sélectionnés, jamais une couverture exhaustive', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = (container.textContent ?? '').toLowerCase()

    expect(text).toContain('les faits essentiels sont vérifiables')
    // La promesse exhaustive ne doit pas revenir sans couverture exhaustive.
    for (const forbidden of [
      'chaque fait renvoie',
      'chaque champ renvoie',
      'tous les faits sont sourcés',
    ]) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('présente des libellés humains et replie les chemins techniques', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    const evidence = screen.getByText('Les faits essentiels sont vérifiables').closest('section')!
    expect(within(evidence).getByText('Montant exact')).toBeInTheDocument()
    expect(within(evidence).getByText('Code CPV')).toBeInTheDocument()
    expect(within(evidence).getByText('Référence du lot')).toBeInTheDocument()

    // Repliés par défaut : ils servent à l'audit, pas à la lecture.
    const details = screen.getByText('Voir les détails techniques de provenance').closest('details')!
    expect(details.open).toBe(false)
  })

  it('ne qualifie de « chemin XML » que les chemins qui en sont', () => {
    for (const piece of publicDemoSignal.evidence) {
      if (piece.pathKind === 'xml') {
        expect(piece.path).toMatch(/^[a-z]+:[A-Za-z]/)
      } else {
        expect(piece.path).not.toMatch(/^[a-z]+:[A-Za-z]/)
      }
    }
  })
})

describe('menu mobile', () => {
  it('est un panneau non modal : il ne promet pas un piège de focus', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: fr.nav.openMenu }))

    const panel = document.getElementById('kivou-public-menu')!
    expect(panel).toBeInTheDocument()
    // Annoncer une modale sans inerter le reste de la page ferait mentir le
    // lecteur d'écran.
    expect(panel.getAttribute('role')).not.toBe('dialog')
    expect(panel.hasAttribute('aria-modal')).toBe(false)
  })

  it('rend le focus au bouton menu à la fermeture par Échap', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    const toggle = await screen.findByRole('button', { name: fr.nav.openMenu })
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.keyboard('{Escape}')

    expect(document.getElementById('kivou-public-menu')).not.toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    // Sans restitution, l'utilisateur au clavier repart du début du document.
    expect(document.activeElement).toBe(toggle)
  })

  it('rend le focus au bouton menu à la fermeture par le scrim', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    const toggle = await screen.findByRole('button', { name: fr.nav.openMenu })
    await user.click(toggle)
    await user.click(screen.getByRole('button', { name: fr.nav.dismissMenu }))

    expect(document.activeElement).toBe(toggle)
  })
})

describe('navigation par ancres', () => {
  it('atteint la section et lui donne le focus depuis la page d’accueil', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('link', { name: fr.nav.howItWorks }))

    await waitFor(() => expect(document.activeElement?.id).toBe('comment'))
  })

  it('atteint la section tarifs depuis la page de démonstration', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('link', { name: fr.nav.pricing }))

    // La cible n'existe pas encore au clic : la page d'accueil doit d'abord
    // être montée. C'est exactement ce que le composant d'ancre attend.
    await waitFor(() => expect(document.activeElement?.id).toBe('tarifs'))
  })

  it('garde une cible tarifs atteignable quand le catalogue est indisponible', async () => {
    // Facturation en panne : la section doit rester, sinon `/#tarifs` devient
    // un lien mort et le visiteur clique dans le vide.
    mockApi({ 'GET /billing/plans': { status: 503, body: { code: 'billing_unavailable' } } })
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('link', { name: fr.nav.pricing }))

    await waitFor(() => expect(document.activeElement?.id).toBe('tarifs'))
    expect(screen.getByText(fr.landing.pricingUnavailable)).toBeInTheDocument()
  })
})


describe('bandeau de preuve de la page d’accueil', () => {
  it('résume la couverture géographique et la preuve officielle', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const text = container.textContent ?? ''

    expect(text).toContain(fr.landing.heroTrust)
  })

  it('dit la même chose en anglais', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, {
      route: '/',
      locale: 'en',
      session: UNAUTHENTICATED,
    })
    const text = container.textContent ?? ''

    expect(text).toContain(en.landing.heroTrust)
  })
})
