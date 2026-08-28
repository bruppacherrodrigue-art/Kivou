import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AppRoutes } from '../App'
import { publicDemoSignal, type PublicDemoSignal } from '../content/publicDemoSignal'
import { en } from '../i18n/en'
import { fr } from '../i18n/fr'
import { mockApi, recordedCalls, renderApp } from '../test/harness'
import { PublicSignalDemo } from './PublicSignalDemo'

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

    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
      publicDemoSignal.winner.legalName,
    )

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

    expect((await screen.findAllByText(publicDemoSignal.winner.legalName)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(publicDemoSignal.contract.title).length).toBeGreaterThan(0)
    expect(screen.getAllByText(publicDemoSignal.buyer.legalName).length).toBeGreaterThan(0)
    expect(screen.getAllByText(new RegExp(publicDemoSignal.contract.locality)).length).toBeGreaterThan(0)

    for (const source of screen.getAllByRole('link', { name: /preuve officielle|avis officiel/i })) {
      expect(source).toHaveAttribute('href', publicDemoSignal.sourceUrl)
      expect(source).toHaveAttribute('target', '_blank')
      expect(source.getAttribute('rel')).toContain('noopener')
      expect(source.getAttribute('rel')).toContain('noreferrer')
    }
  })

  it('présente les sections dans l’ordre opportunité, pertinence, timing, preuve, limites, vérification', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    const text = container.textContent ?? ''
    const markers = [
      'Pourquoi cette attribution mérite un examen commercial',
      'Opportunités commerciales associées',
      'Calendrier publié du marché',
      'Les faits essentiels sont vérifiables',
      'Couverture de cette analyse',
      'Ce que vous pouvez vérifier maintenant',
    ]
    const positions = markers.map((marker) => text.indexOf(marker))

    expect(positions.every((position) => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
  })

  it('rend les volumes commerciaux dominants tout en conservant les désignations source', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    for (const publishedQuantity of publicDemoSignal.contract.publishedQuantities) {
      const [source, value] = publishedQuantity.split(' : ')
      expect(screen.getByText(value)).toBeInTheDocument()
      expect(screen.getByText(source)).toBeInTheDocument()
    }
    expect(screen.getByText(publicDemoSignal.need.statement.fr)).toBeInTheDocument()
    expect(screen.getByText(publicDemoSignal.need.reasoning.fr)).toBeInTheDocument()
  })

  it('qualifie tous les angles comme plausibles, sans transformer les volumes en achats', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    expect(screen.getAllByText('Angle commercial plausible')).toHaveLength(4)
    expect((text.match(/ne constituent pas des achats futurs confirmés/g) ?? [])).toHaveLength(1)
    expect(text).not.toMatch(/signal fort|signal ciblé|besoin opérationnel clairement associé/i)
    expect(text).not.toMatch(/quincaillerie/i)
  })

  it('présente le matching comme une illustration et jamais comme le profil calculé du visiteur', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    expect(text).toContain(
      'Illustration publique : dans Kivou, la pertinence est calculée selon ce que vous vendez, vos secteurs cibles et les territoires où vous intervenez.',
    )
    expect(text).toContain('il ne présente pas une correspondance calculée pour le visiteur')
    expect(text).not.toContain('votre offre correspond aux catégories publiées')
    expect(text).not.toContain('la zone d’exécution se trouve dans votre territoire commercial')
    expect(text).not.toContain('l’entreprise gagnante correspond à votre cible')
  })

  it('affiche les cinq dates absolues sans maintenant ni qualification automatique du timing', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''
    const timingSection = screen.getByRole('heading', { name: 'Calendrier publié du marché' }).closest('section')!

    for (const value of Object.values(publicDemoSignal.timing)) {
      const formatted = new Intl.DateTimeFormat('fr-FR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }).format(new Date(value))
      expect(text).toContain(formatted)
    }
    expect(within(timingSection).getAllByRole('listitem')).toHaveLength(5)
    for (const label of [
      'Marché attribué',
      'Marché signé',
      'Avis officiel publié',
      'Début prévu de l’exécution',
      'Fin prévue de l’exécution',
    ]) {
      expect(within(timingSection).getByText(label)).toBeInTheDocument()
    }
    expect(timingSection.textContent ?? '').not.toMatch(/maintenant|timing favorable|attribution récente|fenêtre de prospection est ouverte/i)
    expect(text).toContain('L’exécution est prévue à partir du 28 octobre 2026')
  })

  it('affiche l’entreprise identifiée et distingue TED des coordonnées du site public', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })

    const companySection = screen.getByRole('heading', { name: 'Entreprise identifiée' }).closest('section')!
    for (const value of [
      publicDemoSignal.winner.legalName,
      publicDemoSignal.winner.address,
      publicDemoSignal.winner.identifier.value,
      publicDemoSignal.contract.title,
      publicDemoSignal.buyer.legalName,
      publicDemoSignal.winner.phone!,
    ]) {
      expect(within(companySection).getAllByText(value).length).toBeGreaterThan(0)
    }
    expect(within(companySection).getByText('Faits issus de l’avis TED')).toBeInTheDocument()
    expect(within(companySection).getByText('Informations disponibles sur le site public de l’entreprise')).toBeInTheDocument()
    const companyLinks = [
      within(companySection).getByRole('link', { name: /site internet/i }),
      within(companySection).getByRole('link', { name: /source de vérification/i }),
    ]
    expect(companyLinks[0]).toHaveAttribute('href', publicDemoSignal.winner.website!)
    expect(companyLinks[1]).toHaveAttribute('href', publicDemoSignal.winner.contactVerificationSource!)
    for (const link of companyLinks) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link.getAttribute('rel')).toContain('noopener')
      expect(link.getAttribute('rel')).toContain('noreferrer')
    }
    expect(companySection.textContent).not.toMatch(/e-mail|linkedin|responsable achats/i)
  })

  it('retire la prospection simulée et ne propose que les actions réellement disponibles', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''

    expect(text).not.toContain('Exemple d’angle commercial')
    expect(text).not.toContain('Nous avons identifié le marché')
    expect(text).not.toMatch(/identifier le responsable|préparer le contact|générer.*message|sauvegarder.*crm/i)
    expect(screen.getAllByRole('link', { name: 'Voir mes 3 premiers signaux' }).length).toBeGreaterThan(0)
    for (const signup of screen.getAllByRole('link', { name: 'Voir mes 3 premiers signaux' })) {
      expect(signup).toHaveAttribute('href', '/signup?plan=discovery')
    }
    const official = screen.getAllByRole('link', { name: /avis officiel/i })
    expect(official.length).toBeGreaterThan(0)
    for (const source of official) {
      expect(source).toHaveAttribute('href', publicDemoSignal.sourceUrl)
      expect(source).toHaveAttribute('target', '_blank')
      expect(source.getAttribute('rel')).toContain('noopener')
      expect(source.getAttribute('rel')).toContain('noreferrer')
    }
  })

  it('utilise les rawValue des trois preuves et garde les chemins techniques repliés', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const evidence = screen.getByRole('heading', { name: 'Les faits essentiels sont vérifiables' }).closest('section')!

    for (const piece of publicDemoSignal.evidence) {
      expect(within(evidence).getAllByText(piece.rawValue).length).toBeGreaterThan(0)
    }
    const details = within(evidence).getByText('Voir les détails techniques de provenance').closest('details')!
    expect(details.open).toBe(false)
    for (const piece of publicDemoSignal.evidence) {
      expect(within(details).getByText(piece.path)).toBeInTheDocument()
      expect(within(details).getByText(piece.rawValue)).toBeInTheDocument()
    }
  })

  it('relègue une seule limite documentaire précise après la preuve et avant les questions', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    await screen.findByRole('heading', { level: 1 })
    const text = container.textContent ?? ''
    const evidence = text.indexOf('Les faits essentiels sont vérifiables')
    const coverage = text.indexOf('Couverture de cette analyse')
    const questions = text.indexOf('Ce que vous pouvez vérifier maintenant')

    expect(evidence).toBeGreaterThanOrEqual(0)
    expect(evidence).toBeLessThan(coverage)
    expect(coverage).toBeLessThan(questions)
    expect((text.match(/Aucun cahier des charges validé n’alimente cette démonstration/g) ?? [])).toHaveLength(1)
    expect(text).toContain('Besoin commercialPlausible')
    expect(text).toContain('Couverture documentaireLimitée')
    expect(text).toContain('Mode d’analyseMétadonnées de l’avis')
    expect(text).not.toMatch(/partielle|confiance réduite/i)
  })

  it('construit les faits depuis la fixture et non depuis les dictionnaires', async () => {
    const variant: PublicDemoSignal = {
      ...publicDemoSignal,
      winner: { ...publicDemoSignal.winner, legalName: 'Fixture Projection GmbH' },
      contract: {
        ...publicDemoSignal.contract,
        locality: 'Teststadt',
        amount: '1234567.89',
      },
      timing: { ...publicDemoSignal.timing, startDate: '2028-01-02' },
      evidence: publicDemoSignal.evidence.map((piece) =>
        piece.labelKey === 'evidenceLot' ? { ...piece, rawValue: 'LOT-FIXTURE-42' } : piece,
      ),
    }
    mockApi({})
    renderApp(<PublicSignalDemo signal={variant} />, { route: '/exemple-de-signal' })

    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Fixture Projection GmbH')
    expect(screen.getAllByText(/Teststadt/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/2 janvier 2028/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('LOT-FIXTURE-42').length).toBeGreaterThan(0)
    expect(screen.queryByText('LOT-0000')).not.toBeInTheDocument()

    const dictionaries = JSON.stringify({ fr: fr.publicDemo, en: en.publicDemo })
    for (const forbiddenFact of [
      publicDemoSignal.winner.legalName,
      publicDemoSignal.contract.amount,
      publicDemoSignal.contract.locality,
      publicDemoSignal.contract.reference,
      publicDemoSignal.contract.title,
      publicDemoSignal.winner.address,
      publicDemoSignal.winner.identifier.value,
      '5,22 M€',
      '€5.22m',
      '28 octobre 2026',
      '28 October 2026',
    ]) {
      expect(dictionaries).not.toContain(forbiddenFact)
    }
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
        title: 'Tischlerarbeiten Innentueren und Moebel',
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
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
      publicDemoSignal.winner.legalName,
    )
    expect(screen.getByText('Pourquoi cette attribution mérite un examen commercial')).toBeInTheDocument()

    // Bascule RÉELLE de la locale, par le sélecteur de l'interface.
    await user.click(screen.getByRole('button', { name: 'EN' }))

    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(
      publicDemoSignal.winner.legalName,
    )
    expect(screen.getByText('Why this award merits a commercial review')).toBeInTheDocument()
    expect(screen.queryByText('Pourquoi cette attribution mérite un examen commercial')).not.toBeInTheDocument()
  })

  it('laisse les faits sources dans leur forme d’origine après bascule', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/exemple-de-signal' })
    const user = userEvent.setup()
    await screen.findAllByText(publicDemoSignal.winner.legalName)

    await user.click(screen.getByRole('button', { name: 'EN' }))

    // Un nom d'entreprise ne se traduit pas.
    expect((await screen.findAllByText(publicDemoSignal.winner.legalName)).length).toBeGreaterThan(0)
    expect(screen.getAllByText(publicDemoSignal.contract.title).length).toBeGreaterThan(0)
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
    expect(within(evidence).getAllByText('Montant exact').length).toBeGreaterThan(0)
    expect(within(evidence).getAllByText('Code CPV').length).toBeGreaterThan(0)
    expect(within(evidence).getAllByText('Référence du lot').length).toBeGreaterThan(0)

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
