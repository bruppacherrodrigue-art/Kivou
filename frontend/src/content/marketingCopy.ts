import type { Locale } from '../i18n'

const copy = {
  fr: {
    brandBaseline: 'Signaux commerciaux',
    nav: {
      home: 'Accueil',
      product: 'Comment ça marche',
      example: 'Exemple de signal',
      pricing: 'Tarifs',
      contact: 'Contact',
      login: 'Se connecter',
      signup: 'Essayer gratuitement',
    },
    footer: {
      tagline:
        'Les marchés attribués deviennent des comptes à examiner, avec les faits et le calendrier sous les yeux.',
      information: 'Informations',
      sources: 'Sources officielles accessibles. Couverture européenne.',
    },
    landing: {
      eyebrow: 'Veille commerciale post-attribution',
      title: 'Repérez les entreprises qui viennent de gagner un marché public.',
      lead:
        'Kivou rassemble le marché remporté, les volumes publiés, les dates utiles et les besoins d’exécution à vérifier avant de contacter le gagnant.',
      primary: 'Voir mes 3 premiers signaux',
      secondary: 'Examiner un signal complet',
      trust: '3 signaux gratuits · Sans carte bancaire · Puis 1 nouveau signal par semaine',
      signalEyebrow: 'Signal récent',
      verified: 'Vérifié',
      awarded: 'Marché attribué',
      signalBody:
        'Plus de 700 portes et huisseries, 5,5 km de plinthes et des travaux d’agencement à Munich.',
      start: 'Début prévu',
      startDate: '28 octobre 2026',
      source: 'Source',
      signalAction: 'Consulter le signal complet',
      includedLabel: 'Dans chaque signal',
      included:
        'l’entreprise gagnante, le marché, un besoin d’exécution à vérifier, le calendrier et la source.',
      dashboardEyebrow: 'Le dashboard Kivou',
      dashboardTitle: 'Voici ce que vous voyez lorsqu’un signal remonte.',
      dashboardLead:
        'Le gagnant, le marché, les volumes, le calendrier, les questions à vérifier et la source sont réunis dans la même vue.',
      dashboardAction: 'Voir l’exemple complet',
      reading: [
        ['Fait publié', 'L’attribution, le titulaire, le périmètre et la source officielle.'],
        ['Pertinence expliquée', 'La correspondance avec votre offre, votre territoire et votre ciblage.'],
        ['Inconnues visibles', 'Ce que l’avis ne permet pas d’affirmer et qu’il reste à vérifier.'],
        ['Votre apprentissage', 'Une note personnelle, ajoutée après les faits, sans modifier la source.'],
      ],
      questionsEyebrow: 'Avant de prospecter',
      questionsTitle: 'Les questions auxquelles un signal doit répondre.',
      questions: [
        ['Entreprise', 'Qui a gagné ?', 'Le nom du titulaire et les informations publiques utiles pour l’identifier.'],
        ['Marché', 'Que doit-elle exécuter ?', 'L’objet, le montant, la localisation et les volumes disponibles.'],
        ['Analyse', 'Où votre offre peut-elle être utile ?', 'Les besoins possibles sont distingués des faits publiés et restent à confirmer.'],
        ['Calendrier', 'Quand examiner le compte ?', 'Les dates de publication et d’exécution donnent le contexte du moment.'],
      ],
      methodEyebrow: 'Comment ça marche',
      methodTitle: 'Vous définissez la cible. Kivou suit les attributions.',
      method: [
        ['Décrivez votre offre', 'Produits, entreprises cibles et territoires.'],
        ['Kivou relève les faits utiles', 'Gagnant, marché, volumes et calendrier.'],
        ['Vous gardez votre lecture', 'Approfondir le compte, l’écarter ou consigner une note.'],
      ],
      methodAction: 'Voir la méthode',
      offersEyebrow: 'Les offres',
      offersTitle: 'Commencez gratuitement, puis élargissez votre couverture si nécessaire.',
      offersLead:
        'Le contenu d’un signal reste identique. Les plans payants augmentent le nombre de profils, les pays couverts, la fréquence des alertes et l’historique.',
      offersPrimary: 'Commencer gratuitement',
      offersSecondary: 'Comparer les offres',
    },
    product: {
      eyebrow: 'Comment ça marche',
      title: 'Kivou suit ce qui se passe après l’attribution.',
      lead:
        'Vous décrivez ce que vous vendez. Kivou relève les marchés attribués qui correspondent, identifie le gagnant et rassemble les faits utiles pour décider si ce compte mérite une approche.',
      primary: 'Configurer mon profil',
      secondary: 'Voir le résultat',
      journeyEyebrow: 'Le parcours d’un signal',
      journey: [
        ['Votre profil', 'Offre, entreprises cibles et territoires.'],
        ['Une attribution', 'Un gagnant et un marché correspondant à votre couverture.'],
        ['L’analyse', 'Faits publiés, besoin possible et calendrier.'],
        ['Votre lecture', 'Approfondir, écarter ou consigner une note.'],
      ],
      whyEyebrow: 'Pourquoi après l’attribution',
      whyTitle: 'Le gagnant doit maintenant exécuter le marché.',
      whyLead:
        'Le contrat peut l’amener à mobiliser des personnes, des équipements, des matériaux, des partenaires ou des expertises. Kivou cherche les faits qui permettent d’examiner ces besoins sans les présenter comme des achats certains.',
      distinctions: [
        ['L’avis établit', 'le titulaire, l’objet, le montant, les lots et les dates disponibles.'],
        ['Kivou rapproche', 'ces faits de votre offre, de vos cibles et de vos territoires.'],
        ['Vous tranchez', 'si le compte vaut une recherche ou une prise de contact.'],
      ],
      methodEyebrow: 'La méthode Kivou',
      methodTitle: 'Cinq étapes, du ciblage au signal.',
      methodLead:
        'Le ciblage vient de vous. Les faits viennent des sources publiques. L’analyse relie les deux et indique ce qui reste à confirmer.',
      method: [
        ['Définissez votre ciblage', 'Votre offre, les entreprises que vous pouvez aider et les territoires à couvrir.'],
        ['Les attributions sont surveillées', 'Kivou suit les avis officiels correspondant à la couverture choisie.'],
        ['Les faits sont structurés', 'Gagnant, objet, montant, lieu, lots, volumes et dates lorsqu’ils sont publiés.'],
        ['La correspondance est expliquée', 'Le besoin possible est rapproché de votre activité, avec les limites de l’analyse.'],
        ['Le signal arrive dans votre veille', 'Vous disposez du contexte et de la source pour choisir la suite.'],
      ],
      caseEyebrow: 'Un cas concret',
      caseTitle: 'Des faits publiés à l’angle commercial à vérifier.',
      caseLead: 'Voici comment Kivou lit l’attribution remportée par H. Hüther GmbH à Munich.',
      facts: ['Un marché de 5,22 M€', 'Plus de 700 portes et huisseries', '5,5 km de plinthes', 'Travaux à Munich', 'Début prévu le 28 octobre 2026'],
      analysis: ['Des besoins possibles autour de l’agencement', 'Produits bois et composants compatibles', 'Vitrage et éléments d’agencement', 'Calendrier commercial relié aux dates publiées', 'Source TED disponible pour contrôle'],
      factsLabel: 'Faits publiés',
      analysisLabel: 'Kivou analyse',
      examine: 'À examiner',
      read: 'Lire l’analyse complète',
      timelineEyebrow: 'Calendrier et source',
      timelineTitle: 'Le signal montre quand les faits ont été publiés et d’où ils viennent.',
      timelineLead:
        'L’avis officiel permet de contrôler le gagnant, le montant, l’objet et les dates. L’analyse commerciale apparaît séparément afin de ne pas confondre un fait publié avec un besoin possible.',
      ctaTitle: 'Jugez Kivou sur des signaux complets.',
      ctaLead: 'Les trois premiers sont accessibles gratuitement. Vous recevez ensuite un nouveau signal chaque semaine.',
    },
    pricing: {
      eyebrow: 'Tarifs mensuels',
      title: 'Choisissez la couverture adaptée à votre prospection.',
      lead:
        'Chaque offre donne accès au même contenu dans un signal. Le nombre de profils, la géographie, la fréquence et l’historique évoluent avec le plan.',
      trust: '3 signaux gratuits · 1 utilisateur dans chaque offre · Sans carte bancaire pour commencer',
      comparisonEyebrow: 'Comparaison',
      comparisonTitle: 'Ce qui change d’une offre à l’autre.',
      unavailable: 'Les tarifs sont momentanément indisponibles. Vous pouvez néanmoins créer votre compte gratuitement.',
      ctaTitle: 'Commencez avec trois signaux complets.',
      ctaLead: 'Vous recevrez ensuite un nouveau signal chaque semaine, sans carte bancaire.',
    },
    contact: {
      title: 'Contact',
      name: 'Nom',
      email: 'E-mail professionnel',
      subject: 'Sujet',
      choose: 'Choisir un sujet',
      subjects: ['Produit et compte', 'Facturation', 'Confidentialité', 'Partenariat', 'Autre demande'],
      message: 'Message',
      send: 'Envoyer le message',
      note: 'L’envoi s’ouvre dans votre messagerie et reste sous votre contrôle.',
    },
  },
  en: {
    brandBaseline: 'Sales signals',
    nav: {
      home: 'Home', product: 'How it works', example: 'Signal example', pricing: 'Pricing', contact: 'Contact', login: 'Sign in', signup: 'Try it free',
    },
    footer: {
      tagline: 'Turn awarded contracts into accounts worth reviewing, with the facts and timing in front of you.',
      information: 'Information',
      sources: 'Official sources available. European coverage.',
    },
    landing: {
      eyebrow: 'Post-award sales intelligence',
      title: 'Spot companies that have just won a public contract.',
      lead: 'Kivou brings together the awarded contract, published volumes, key dates and delivery needs to verify before you approach the winner.',
      primary: 'See my first 3 signals', secondary: 'Review a complete signal', trust: '3 free signals · No card required · Then 1 new signal each week',
      signalEyebrow: 'Recent signal', verified: 'Verified', awarded: 'Awarded contract', signalBody: 'More than 700 doors and frames, 5.5 km of skirting and interior fit-out work in Munich.', start: 'Planned start', startDate: '28 October 2026', source: 'Source', signalAction: 'Open the complete signal',
      includedLabel: 'In every signal', included: 'the winning company, the contract, a delivery need to verify, the timeline and the source.',
      dashboardEyebrow: 'The Kivou dashboard', dashboardTitle: 'This is what you see when a signal appears.', dashboardLead: 'The winner, contract, volumes, timeline, questions to verify and source are brought together in one view.', dashboardAction: 'View the complete example',
      reading: [['Published fact','The award, contractor, scope and official source.'],['Why it fits','How it matches your offer, territory and targeting.'],['Visible unknowns','What the notice does not establish and still needs checking.'],['Your learning','A personal note added after the facts, without changing the source.']],
      questionsEyebrow: 'Before outreach', questionsTitle: 'The questions every signal should answer.',
      questions: [['Company','Who won?','The contractor and the public information needed to identify it.'],['Contract','What must it deliver?','The scope, value, location and published volumes.'],['Analysis','Where could your offer help?','Possible needs are kept separate from published facts and remain to be confirmed.'],['Timing','When should you review the account?','Publication and delivery dates provide the commercial context.']],
      methodEyebrow: 'How it works', methodTitle: 'You define the target. Kivou tracks awards.', method: [['Describe your offer','Products, target companies and territories.'],['Kivou captures the useful facts','Winner, contract, volumes and timeline.'],['You keep the judgement','Research the account, dismiss it or add a note.']], methodAction: 'See the method',
      offersEyebrow: 'Plans', offersTitle: 'Start free, then expand your coverage when you need to.', offersLead: 'Every plan provides the same signal content. Paid plans increase the number of profiles, countries, alert frequency and history.', offersPrimary: 'Start free', offersSecondary: 'Compare plans',
    },
    product: {
      eyebrow: 'How it works', title: 'Kivou follows what happens after an award.', lead: 'Describe what you sell. Kivou finds matching awarded contracts, identifies the winner and assembles the facts you need to decide whether the account deserves an approach.', primary: 'Set up my profile', secondary: 'See the result', journeyEyebrow: 'A signal’s journey',
      journey: [['Your profile','Offer, target companies and territories.'],['An award','A winner and contract within your coverage.'],['The analysis','Published facts, a possible need and timing.'],['Your judgement','Research, dismiss or add a note.']],
      whyEyebrow: 'Why post-award', whyTitle: 'The winner now has to deliver the contract.', whyLead: 'The contract may require people, equipment, materials, partners or specialist expertise. Kivou looks for facts that make those needs worth investigating without presenting them as confirmed purchases.', distinctions: [['The notice establishes','the contractor, scope, value, lots and available dates.'],['Kivou connects','those facts to your offer, targets and territories.'],['You decide','whether the account merits research or contact.']],
      methodEyebrow: 'The Kivou method', methodTitle: 'Five steps from targeting to signal.', methodLead: 'You provide the targeting. Public sources provide the facts. The analysis connects them and makes the remaining unknowns explicit.', method: [['Define your targeting','Your offer, companies you can help and territories to cover.'],['Awards are monitored','Kivou follows official notices within your chosen coverage.'],['Facts are structured','Winner, scope, value, location, lots, volumes and dates when published.'],['The match is explained','The possible need is compared with your activity, with the analysis limits shown.'],['The signal reaches your feed','You get the context and source needed to choose the next step.']],
      caseEyebrow: 'A concrete example', caseTitle: 'From published facts to a sales angle worth checking.', caseLead: 'Here is how Kivou reads the contract awarded to H. Hüther GmbH in Munich.', facts: ['A €5.22m contract','More than 700 doors and frames','5.5 km of skirting','Work in Munich','Planned start on 28 October 2026'], analysis: ['Possible interior fit-out needs','Compatible timber products and components','Glazing and fit-out elements','Commercial timing tied to published dates','TED source available for verification'], factsLabel: 'Published facts', analysisLabel: 'Kivou analysis', examine: 'Worth checking', read: 'Read the full analysis', timelineEyebrow: 'Timeline and source', timelineTitle: 'The signal shows when the facts were published and where they came from.', timelineLead: 'The official notice lets you verify the winner, value, scope and dates. The sales analysis is shown separately so a published fact is never confused with a possible need.', ctaTitle: 'Judge Kivou on complete signals.', ctaLead: 'Your first three are free. You then receive one new signal each week.',
    },
    pricing: { eyebrow: 'Monthly pricing', title: 'Choose the coverage that fits your prospecting.', lead: 'Every plan includes the same signal content. The number of profiles, geography, frequency and history expand with the plan.', trust: '3 free signals · 1 user on every plan · No card required to start', comparisonEyebrow: 'Comparison', comparisonTitle: 'What changes from one plan to another.', unavailable: 'Pricing is temporarily unavailable. You can still create a free account.', ctaTitle: 'Start with three complete signals.', ctaLead: 'You will then receive one new signal each week, with no card required.' },
    contact: { title: 'Contact', name: 'Name', email: 'Work email', subject: 'Subject', choose: 'Choose a subject', subjects: ['Product and account','Billing','Privacy','Partnership','Other request'], message: 'Message', send: 'Send message', note: 'The message opens in your email app and stays under your control.' },
  },
} as const

export function marketingCopy(locale: Locale) {
  return copy[locale]
}
