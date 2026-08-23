/* Le dictionnaire français — et la forme de référence des deux langues.
 *
 * `en.ts` est typé `typeof fr` : une clé ajoutée ici sans traduction anglaise
 * casse le typecheck. C'est le seul mécanisme qui garantit qu'aucun écran ne
 * part en production à moitié traduit.
 *
 * Le vocabulaire suit l'annexe C du design system : « besoin plausible » et
 * jamais « achat prévu », « attribution récente » et jamais « vient de gagner »
 * quand la date est inconnue, « déverrouiller le flux complet » et jamais
 * « acheter maintenant avant qu'il soit trop tard ».
 *
 * Ce qui n'est PAS ici : les libellés que l'API renvoie déjà (headline,
 * why_now, statut d'événement, libellés de besoin, raisons de fit). Les
 * traduire une seconde fois créerait deux vérités.
 */
export const fr = {
  brand: {
    name: 'Kivou',
    baseline: 'Performance commerciale sous contrôle',
    promise: 'Transformez les nouvelles attributions publiques en raisons crédibles de contacter une entreprise.',
    markAlt: 'Kivou',
  },

  common: {
    loading: 'Chargement…',
    retry: 'Réessayer',
    cancel: 'Annuler',
    save: 'Enregistrer',
    saving: 'Enregistrement…',
    saved: 'Enregistré',
    back: 'Retour',
    next: 'Suivant',
    previous: 'Précédent',
    confirm: 'Confirmer',
    close: 'Fermer',
    optional: 'facultatif',
    required: 'obligatoire',
    notAvailable: 'Non disponible',
    yes: 'Oui',
    no: 'Non',
    language: 'Langue',
    french: 'Français',
    english: 'English',
    skipToContent: 'Aller au contenu principal',
  },

  nav: {
    signals: 'Signaux',
    icps: 'Profils de ciblage',
    billing: 'Facturation',
    notifications: 'Notifications',
    logout: 'Se déconnecter',
    login: 'Se connecter',
    signup: 'Créer un compte',
    pricing: 'Tarifs',
    howItWorks: 'Comment ça marche',
    product: 'Produit',
    mainNavigation: 'Navigation principale',
    openMenu: 'Ouvrir le menu',
    closeMenu: 'Fermer le menu',
    dismissMenu: 'Fermer le menu en cliquant à côté',
    account: 'Compte',
  },

  landing: {
    heroEyebrow: 'SIGNAUX COMMERCIAUX ISSUS DES MARCHÉS PUBLICS',
    heroTitle:
      'Les entreprises qui remportent des contrats publics — et les occasions commerciales que votre équipe peut examiner.',
    heroLead:
      'Kivou identifie les entreprises gagnantes, comprend ce qu’elles devront exécuter et vous montre les occasions correspondant à ce que vous vendez.',
    heroSecondaryLead:
      'Vous ne recevez pas une liste de marchés publics. Vous recevez des raisons documentées de contacter de nouveaux prospects.',
    heroPrimary: 'Voir mes 3 signaux',
    heroSecondary: 'Découvrir un signal complet',
    heroTrust: 'Suisse + Union européenne · Sources officielles · Preuves vérifiables',
    heroCarousel: {
      regionLabel: 'Exemples de signaux commerciaux',
      eventLabel: 'CONTRAT PUBLIC DÉTECTÉ',
      opportunityLabel: 'Angle commercial plausible',
      timingLabel: 'Calendrier publié',
      sourceVerified: 'Source vérifiée',
      viewSignal: 'Voir le signal',
      previous: 'Signal précédent',
      next: 'Signal suivant',
      pause: 'Mettre le carrousel en pause',
      resume: 'Reprendre le carrousel',
      reducedMotion: 'Rotation automatique désactivée selon vos préférences de mouvement',
      indicator: 'Afficher le signal {current} sur {total}',
      slide: 'Signal {current} sur {total}',
      manualAnnouncement: 'Signal {current} sur {total} : {company}',
    },
    proofsTitle: 'Ce sur quoi Kivou s’appuie',
    proofs: {
      publicTitle: '100 % fait public',
      publicBody:
        'Nous analysons les données publiques européennes issues des avis d’attribution officiels. Aucune donnée privée.',
      documentTitle: 'Preuve documentaire',
      documentBody:
        'Chaque exigence citée renvoie à son passage source et au document qui la publie.',
      actionableTitle: 'Adéquation à votre offre',
      actionableBody:
        'Vous décrivez ce que vous vendez et où vous livrez ; Kivou explique pourquoi un signal vous concerne.',
    },
    how: {
      introEyebrow: 'SURVEILLANCE COMMERCIALE CONTINUE',
      introTitle:
        'Kivou transforme les attributions publiques en prospects à examiner selon leur calendrier.',
      introBodyOne:
        'Des entreprises remportent des contrats publics en Suisse et dans l’Union européenne. Kivou identifie les gagnants, résume ce qu’ils devront exécuter et sélectionne les occasions qui correspondent à ce que vous vendez.',
      introBodyTwo:
        'Kivou surveille ces événements, identifie les gagnants, comprend ce qu’ils devront exécuter et sélectionne uniquement les occasions correspondant à ce que vous vendez.',
      introHighlight:
        'Pas une liste de marchés publics : des raisons documentées de contacter de nouveaux prospects.',
      profileEyebrow: 'Votre profil de ciblage',
      profileTitle: 'Vous décrivez votre activité. Kivou surveille le marché pour vous.',
      profileBody:
        'Vous indiquez votre offre, vos cibles et vos régions. Kivou écarte le bruit et fait remonter les attributions utiles.',
      profileOutput: 'Votre flux de signaux personnalisés',
      profileCards: [
        {
          title: 'Votre offre',
          body: 'Produits, services, capacités.',
        },
        {
          title: 'Vos prospects',
          body: 'Entreprises recherchées.',
        },
        {
          title: 'Votre territoire',
          body: 'Pays et régions couverts.',
        },
        {
          title: 'Vos priorités',
          body: 'Secteurs, montants, besoins.',
        },
      ],
      processTitle: 'De l’attribution publique à l’action commerciale',
      processSteps: [
        {
          title: 'Kivou surveille',
          body: 'Les attributions suisses et européennes publiées sont collectées.',
        },
        {
          title: 'Kivou identifie',
          body: 'Gagnant, contrat, montant, acheteur, lieu et dates sont vérifiés.',
        },
        {
          title: 'Kivou comprend',
          body: 'Les lots, volumes et documents disponibles sont résumés.',
        },
        {
          title: 'Kivou fait correspondre',
          body: 'Le signal est comparé à votre offre, vos cibles et votre territoire.',
        },
        {
          title: 'Kivou qualifie le moment',
          body: 'La date d’attribution et le calendrier d’exécution situent le signal dans le temps.',
        },
        {
          title: 'Votre équipe agit',
          body: 'Votre commercial reçoit le prospect, le contexte, le timing et la preuve.',
        },
      ],
      dashboardEyebrow: 'DANS VOTRE DASHBOARD',
      dashboardTitle:
        'Un signal clair, directement exploitable.',
      dashboardBody:
        'L’entreprise, le contrat, les volumes, le timing, les coordonnées disponibles et la preuve officielle tiennent dans une seule vue.',
      dashboardAlt:
        'Tableau de bord Kivou montrant un signal commercial pour une entreprise gagnante, le montant du contrat, les volumes, la correspondance avec l’offre du client, les coordonnées professionnelles et la prochaine étape.',
      dashboardCaption:
        'Le prospect, le contexte et la prochaine action — réunis dans un seul signal.',
      dashboardMarkers: [
        'Entreprise identifiée',
        'Coordonnées professionnelles',
        'Timing qualifié',
        'Action recommandée',
        'Preuve officielle',
      ],
      dashboardPrimary: 'Voir un signal complet',
      dashboardSecondary: 'Recevoir mes 3 signaux',
      comparisonTitle: 'Une attribution publique n’est pas encore une occasion commerciale',
      comparisonWithoutEyebrow: 'Sans Kivou',
      comparisonWithoutTitle: 'Une donnée parmi des milliers',
      comparisonWithoutItems: [
        'avis officiel à lire',
        'titre administratif',
        'codes et références',
        'contexte commercial à reconstituer',
      ],
      comparisonWithoutConclusion:
        'Le commercial doit encore transformer la donnée en approche concrète.',
      comparisonWithEyebrow: 'Avec Kivou',
      comparisonWithTitle: 'Une raison documentée de contacter le bon prospect',
      comparisonWithItems: [
        'prospect identifié',
        'volumes résumés',
        'timing qualifié',
        'action et preuve réunies',
      ],
      comparisonWithConclusion:
        'Le commercial comprend pourquoi ce prospect mérite son attention et peut vérifier le calendrier publié.',
      questionsTitle: 'Chaque signal répond aux questions de votre équipe commerciale',
      questions: [
        {
          title: 'Qui contacter ?',
          body: 'L’entreprise gagnante du marché, clairement identifiée.',
        },
        {
          title: 'Comment la joindre ?',
          body: 'Les coordonnées professionnelles publiques et vérifiées disponibles pour cette entreprise.',
        },
        {
          title: 'Que s’est-il passé ?',
          body: 'Le contrat remporté, son montant, son objet, sa localisation et ses dates.',
        },
        {
          title: 'Que pourrais-je lui vendre ?',
          body: 'Les besoins compatibles avec votre offre, expliqués à partir des faits publiés.',
        },
        {
          title: 'Quel est le calendrier ?',
          body: 'Les dates publiées de l’attribution et de l’exécution.',
        },
        {
          title: 'Pourquoi ce prospect me correspond-il ?',
          body: 'La correspondance avec vos produits, vos cibles et votre territoire.',
        },
        {
          title: 'Sur quoi repose l’analyse ?',
          body: 'La source officielle, les faits vérifiés et les documents disponibles.',
        },
      ],
      trustTitle: 'Une analyse commerciale que vous pouvez vérifier',
      trustBodyOne:
        'Kivou distingue les faits publiés, les besoins déduits de ces faits, leur correspondance avec votre activité et les éventuelles limites documentaires.',
      trustBodyTwo:
        'Chaque signal sépare les faits vérifiés, les déductions commerciales et la source officielle. Vous gardez la décision ; Kivou accélère l’analyse.',
      trustIndicators: [
        'Fait public sourcé',
        'Besoin expliqué',
        'Correspondance personnalisée',
        'Source officielle accessible',
      ],
      pricingTitle: 'Une attribution publique peut déjà révéler votre prochain prospect',
      pricingBody:
        'Décrivez ce que vous vendez et où vous intervenez. Kivou vous montre immédiatement trois signaux complets.',
      pricingNoCard: 'Aucune carte bancaire nécessaire.',
      pricingPrimary: 'Voir mes 3 premiers signaux',
      pricingSecondary: 'Comparer les offres',
      demo: {
        previewBadge: 'Aperçu de l’expérience Kivou',
        navOverview: 'Vue d’ensemble',
        navSignals: 'Signaux',
        navCompanies: 'Entreprises',
        navAlerts: 'Alertes',
        navProfile: 'Profil de ciblage',
        navSettings: 'Paramètres',
        topTitle: 'Signaux',
        search: 'Recherche',
        activeProfile: 'Fournitures de menuiserie · Allemagne du Sud',
        territory: 'Bavière · Pertinence forte',
        account: 'Compte démo',
        selected: 'Sélectionné',
        opportunity: 'Opportunité commerciale',
        signalTitle: 'H. Hüther GmbH — marché de 5,22 M€ attribué à Munich',
        summary:
          'Plus de 700 ensembles de portes et huisseries, 5,5 km de plinthes et plusieurs équipements d’agencement figurent dans le périmètre publié.',
        verifiedEvent: 'Événement vérifié',
        goodTiming: 'Début prévu : 28 octobre 2026',
        strongFit: 'Adéquation forte',
        officialSource: 'Source officielle',
        whyRelevantTitle: 'Pourquoi ce signal vous concerne',
        whyRelevant:
          'Votre profil indique que vous fournissez des portes, de la quincaillerie ou des composants d’agencement et que vous livrez en Bavière. Les catégories, les volumes et la zone d’exécution correspondent à votre ciblage.',
        whyNowTitle: 'Calendrier publié',
        whyNow:
          'Le marché a été attribué le 14 août 2026. Le début d’exécution publié est fixé au 28 octobre 2026.',
        volumesTitle: 'Volumes publiés',
        companyTitle: 'Entreprise',
        companyVerified: 'Coordonnées professionnelles vérifiées',
        legalName: 'Raison sociale',
        address: 'Adresse',
        countryRegion: 'Pays et région',
        website: 'Site internet',
        phone: 'Téléphone professionnel',
        identifier: 'Identifiant officiel',
        status: 'Statut de vérification',
        updated: 'Dernière vérification',
        actionTitle: 'Action recommandée',
        actionBody:
          'Identifier le responsable achats, approvisionnement ou opérations et engager une prise de contact avant le démarrage du chantier.',
        prepare: 'Préparer le contact',
        save: 'Sauvegarder',
        contacted: 'Marquer contacté',
        source: 'Voir la source officielle',
      },
    },
    chainTitle: 'La chaîne de valeur Kivou',
    chainLead: 'Du fait publié à la raison d’examiner une entreprise selon son calendrier.',
    chain: {
      factTitle: 'Fait public',
      factBody: 'Publication officielle d’un marché attribué et de son gagnant.',
      requirementTitle: 'Exigence documentaire',
      requirementBody: 'Lecture des pièces du marché et extraction des exigences d’exécution.',
      needTitle: 'Besoin plausible',
      needBody: 'Ce que cette exigence peut impliquer pour le gagnant. Une hypothèse, pas un achat.',
      timingTitle: 'Timing',
      timingBody: 'À quelle distance de la décision nous sommes, et ce que cela autorise à dire.',
      actionTitle: 'Action',
      actionBody: 'Le signal arrive avec sa preuve, pour que vous décidiez de contacter ou non.',
    },
    honestyTitle: 'Ce que Kivou affirme, et ce qu’il qualifie',
    honestyAffirms: 'Kivou affirme',
    honestyAffirmsItems: [
      'Une attribution et son gagnant, lorsqu’ils sont publiés.',
      'Une exigence extraite, avec son passage source.',
      'Une date, une valeur ou un lieu lorsqu’ils sont sourcés.',
    ],
    honestyQualifies: 'Kivou qualifie',
    honestyQualifiesItems: [
      'Un besoin plausible, jamais un achat certain.',
      'Une fenêtre commerciale, et ce que la date permet d’en dire.',
      'Une adéquation possible entre ce besoin et ce que vous vendez.',
    ],
    honestyNote:
      'Kivou ne sait pas ce qu’une entreprise va acheter. Kivou montre un événement public, ce qu’il implique probablement, et la preuve qui permet d’en juger.',
    pricingEyebrow: '4 offres · Facturation mensuelle',
    pricingTitle: 'Choisissez la couverture commerciale adaptée à vos objectifs',
    pricingLead:
      'Commencez par trois signaux réels. Étendez ensuite votre couverture et votre capacité de suivi à mesure que votre prospection se développe.',
    pricingUnavailable:
      'Les tarifs sont momentanément indisponibles. La création de compte reste ouverte.',
    ctaTitle: 'Commencez par trois signaux réels',
    ctaBody:
      'Créez un compte, décrivez ce que vous vendez, et consultez trois signaux complets avec leur preuve documentaire.',
    footerTagline: 'L’intelligence des faits publics au service de votre croissance.',
    footerRights: 'Tous droits réservés.',
  },

  publicDemo: {
    navLabel: 'Exemple de signal',
    heroEyebrow: 'Opportunité commerciale documentée',
    heroTitle: '{company} a remporté un marché de {amount} à {location}',
    heroSubtitle:
      'Le descriptif publié mentionne {woodDoors} huisseries et portes bois, {steelDoors} huisseries acier et portes bois, {skirting} de plinthes, {wallCladding} de revêtement bois, {glazing} vitrages et {kitchenettes} kitchenettes.',
    heroTiming:
      'L’exécution est prévue à partir du {startDate}. Kivou permet d’identifier l’entreprise et d’examiner la pertinence d’une approche avant cette étape.',
    heroBadgeVerified: 'Événement vérifié',
    heroBadgeAwardDate: 'Date d’attribution publiée',
    heroBadgeSchedule: 'Calendrier d’exécution publié',
    heroBadgeSource: 'Source officielle disponible',
    heroMeta: 'Avis publié le {published} · Vérifié par Kivou le {verified}',
    heroPrimary: 'Voir mes 3 premiers signaux',
    heroSecondary: 'Ouvrir l’avis officiel',
    externalNewTab: '— s’ouvre dans un nouvel onglet',

    contractSnapshot: 'Le marché en bref',
    winner: 'Entreprise gagnante',
    object: 'Objet du marché',
    buyer: 'Acheteur public',
    amountLabel: 'Montant attribué',
    place: 'Lieu d’exécution',

    overviewEyebrow: 'Pourquoi cette attribution mérite un examen commercial',
    overviewTitle:
      'Un marché important fournit des faits concrets pour évaluer une occasion fournisseur.',
    overviewBody:
      '{company} a remporté un marché de {amount} à {location}. Kivou rassemble l’attribution, les volumes publiés et le calendrier pour permettre à un fournisseur d’évaluer la compatibilité avec son offre.',
    needLabel: 'Besoin commercial plausible',
    overviewHighlight: 'Attribution publiée. Volumes documentés. Entreprise identifiée.',

    volumesTitle: 'Ce que l’entreprise devra exécuter',
    volumesLead: 'Volumes publiés dans l’avis d’attribution officiel.',
    quantityWoodDoors: 'Huisseries et portes bois',
    quantitySteelDoors: 'Huisseries acier et portes bois',
    quantitySkirting: 'Plinthes',
    quantityWallCladding: 'Revêtement mural bois',
    quantityGlazing: 'Éléments vitrés',
    quantityKitchenettes: 'Kitchenettes',
    quantitiesNote: 'Ces quantités figurent dans le descriptif publié de l’avis d’attribution.',

    opportunitiesTitle: 'Opportunités commerciales associées',
    opportunitiesLead: 'Les volumes publiés font apparaître plusieurs angles de prospection possibles.',
    plausibleAngle: 'Angle commercial plausible',
    opportunityDoorsTitle: 'Portes et huisseries',
    opportunityDoorsBody:
      '{woodDoors} huisseries et portes bois ainsi que {steelDoors} huisseries acier et portes bois sont publiées. Pour un fournisseur compatible, ces volumes constituent un angle commercial plausible.',
    opportunityWoodTitle: 'Plinthes et produits bois',
    opportunityWoodBody:
      'Le descriptif publie {skirting} de plinthes et {wallCladding} de revêtement mural bois. Ces volumes peuvent intéresser un fournisseur de produits compatibles.',
    opportunityGlazingTitle: 'Vitrage',
    opportunityGlazingBody:
      '{glazing} éléments vitrés figurent dans les quantités publiées. Cette donnée fournit un angle d’examen aux fournisseurs compatibles.',
    opportunityKitchenTitle: 'Kitchenettes et agencement',
    opportunityKitchenBody:
      '{kitchenettes} kitchenettes figurent dans le descriptif publié. Cette donnée peut constituer un angle commercial pour les acteurs de l’agencement.',
    opportunitiesNote:
      'Ces angles sont déduits des volumes publiés. Ils ne constituent pas des achats futurs confirmés.',

    matchingEyebrow: 'Illustration publique',
    matchingTitle: 'Comment le matching serait évalué dans Kivou',
    matchingIntro:
      'Illustration publique : dans Kivou, la pertinence est calculée selon ce que vous vendez, vos secteurs cibles et les territoires où vous intervenez.',
    matchingReasonOne: 'Si votre offre couvre des produits compatibles avec les volumes publiés',
    matchingReasonTwo: 'Si l’importance du marché correspond à vos priorités commerciales',
    matchingReasonThree: 'Si vous intervenez dans la zone d’exécution publiée à {location}',
    matchingReasonFour: 'Si le type d’entreprise gagnante entre dans vos cibles',
    matchingReasonFive: 'Le calendrier publié peut être comparé à votre cycle commercial',
    matchingReasonSix: 'La source officielle apporte un contexte vérifiable',
    matchingConclusion:
      'Ce bloc explique le mécanisme de matching ; il ne présente pas une correspondance calculée pour le visiteur de cette page.',
    matchingNote:
      'Dans un compte Kivou, le flux est personnalisé à partir du profil de ciblage réellement renseigné.',

    timingTitle: 'Calendrier publié du marché',
    timingWhyTitle: 'Ce que ces dates permettent d’examiner',
    timingBody:
      'L’exécution est prévue à partir du {startDate}. Kivou permet d’identifier l’entreprise et d’examiner la pertinence d’une approche avant cette étape.',
    timelineAwarded: 'Marché attribué',
    timelineSigned: 'Marché signé',
    timelinePublished: 'Avis officiel publié',
    timelineStart: 'Début prévu de l’exécution',
    timelineEnd: 'Fin prévue de l’exécution',

    companyTitle: 'Entreprise identifiée',
    companyLead:
      'Les faits d’attribution et les coordonnées professionnelles sont présentés avec leurs sources respectives.',
    companyTedFactsTitle: 'Faits issus de l’avis TED',
    companyLegalName: 'Raison sociale',
    companyOfficialAddress: 'Adresse officielle',
    companyCountry: 'Pays',
    companyIdentifier: 'Identifiant officiel',
    companyContract: 'Marché remporté',
    companyBuyer: 'Acheteur public',
    companyTedSource: 'Consulter les faits dans TED',
    companyContactTitle: 'Coordonnées vérifiées sur le site public de l’entreprise',
    companyContactIntro:
      'Ces coordonnées professionnelles proviennent du site public de l’entreprise, distinct de l’avis TED.',
    companyWebsite: 'Site internet',
    companyWebsiteLink: 'Ouvrir le site internet de l’entreprise',
    companyPhone: 'Téléphone professionnel',
    companyContactVerified: 'Coordonnées vérifiées le',
    companyContactSource: 'Source de vérification',
    companyContactSourceLink: 'Ouvrir la source de vérification',

    actionEyebrow: 'Prochaine étape',
    actionTitle: 'Prochaine étape recommandée',
    actionBody: 'Cette démonstration permet d’examiner le signal sans simuler une prospection automatisée.',
    actionListTitle: 'Actions disponibles',
    actionReviewMarket: 'Examiner le marché et les volumes publiés',
    actionCheckFit: 'Vérifier leur correspondance avec votre offre',
    actionOpenNotice: 'Consulter l’avis officiel',
    actionCreateAccount: 'Créer un compte Kivou pour recevoir trois signaux personnalisés',
    actionPrimary: 'Voir mes 3 premiers signaux',
    actionSecondary: 'Ouvrir l’avis officiel',

    evidenceTitle: 'Les faits essentiels sont vérifiables',
    evidenceBody:
      'Le gagnant, l’objet du marché, le montant, le lieu, les dates et les quantités affichés proviennent de l’avis d’attribution officiel. Trois champs disposent d’une provenance technique détaillée.',
    evidenceAmount: 'Montant exact',
    evidenceCpv: 'Code CPV',
    evidenceLot: 'Référence du lot',
    evidenceReference: 'Référence du marché',
    evidenceIdentifier: 'Identifiant d’entreprise',
    evidenceSignature: 'Date de signature',
    evidenceTechnical: 'Voir les détails techniques de provenance',
    evidencePathXml: 'Chemin XML',
    evidencePathField: 'Champ d’acquisition',
    openSource: 'Consulter l’avis officiel',
    openSourceHint: 'S’ouvre sur le site officiel TED, dans un nouvel onglet.',

    coverageTitle: 'Couverture de cette analyse',
    coverageBody:
      'Aucun cahier des charges validé n’alimente cette démonstration. Le besoin commercial est donc une inférence fondée sur l’objet, le code CPV, le montant, les volumes, la localisation et les dates publiés. Cette limite ne remet pas en cause les faits de l’attribution.',
    coverageDetails: 'Voir les niveaux de vérification et d’inférence',
    coverageEvent: 'Événement public',
    coverageWinner: 'Entreprise gagnante',
    coverageAmountDates: 'Montant et dates',
    coverageQuantities: 'Quantités',
    coverageNeeds: 'Besoin commercial',
    coverageDocumentary: 'Couverture documentaire',
    coverageMode: 'Mode d’analyse',
    statusVerified: 'Vérifié',
    statusIdentified: 'Identifiée',
    statusPublished: 'Publiés',
    statusPublishedDescription: 'Publiées dans le descriptif',
    statusPlausible: 'Plausible',
    statusLimited: 'Limitée',
    statusMetadata: 'Métadonnées de l’avis',

    finalCtaTitle: 'Recevez les occasions qui correspondent à votre activité',
    finalCtaBody:
      'Décrivez ce que vous vendez et où vous intervenez. Kivou surveille les attributions publiques et vous montre les entreprises, les faits, le calendrier et les besoins plausibles correspondant à votre profil.',
    finalCtaNoCard: 'Aucune carte bancaire nécessaire.',
    finalCtaPrimary: 'Voir mes 3 premiers signaux',

    previewEyebrow: 'Exemple de signal réel',
    previewMode: 'Avis officiel vérifié',
    previewNeedLabel: 'Besoin plausible',
    previewCta: 'Voir ce signal en entier',
    previewAwarded: 'Attribué le {date}',
    previewStart: 'Exécution à partir du {date}',
  },
  auth: {
    loginTitle: 'Se connecter',
    loginLead: 'Accédez à vos signaux.',
    signupTitle: 'Créer un compte',
    signupLead: 'Vos premiers signaux réels, preuve documentaire comprise.',
    email: 'Adresse e-mail professionnelle',
    password: 'Mot de passe',
    newPassword: 'Nouveau mot de passe',
    companyName: 'Nom de votre entreprise',
    locale: 'Langue de votre compte',
    submitLogin: 'Se connecter',
    submitSignup: 'Créer mon compte',
    forgotLink: 'Mot de passe oublié ?',
    noAccount: 'Pas encore de compte ?',
    hasAccount: 'Vous avez déjà un compte ?',
    passwordHelp: 'Au moins {min} caractères.',
    forgotTitle: 'Mot de passe oublié',
    forgotLead:
      'Indiquez votre adresse. Si un compte y est associé, vous recevrez un lien de réinitialisation.',
    forgotSubmit: 'Envoyer le lien',
    forgotConfirmation:
      'Si un compte existe pour cette adresse, un lien de réinitialisation vient d’être envoyé.',
    resetTitle: 'Choisir un nouveau mot de passe',
    resetLead: 'Toutes vos sessions ouvertes seront fermées.',
    resetSubmit: 'Mettre à jour le mot de passe',
    resetTokenLabel: 'Jeton de réinitialisation',
    resetTokenHelp: 'Il figure dans le lien reçu par e-mail.',
    resetDone: 'Mot de passe mis à jour. Vous pouvez vous connecter.',
    backToLogin: 'Retour à la connexion',
    loggingOut: 'Déconnexion…',
    signupNext:
      'Ensuite, indiquez ce que vous vendez et où vous intervenez. Kivou préparera vos premiers signaux.',
    signupNoCard:
      'Aucune carte bancaire n’est nécessaire pour découvrir vos premiers signaux.',
    sessionExpired: 'Votre session a expiré. Connectez-vous à nouveau.',
  },

  onboarding: {
    title: 'Configurer votre profil de ciblage',
    lead: 'Cinq questions. Elles déterminent quels signaux vous recevrez.',
    stepOf: 'Étape {current} sur {total}',
    labelStep: 'Comment appeler ce profil ?',
    labelField: 'Nom du profil',
    labelHelp: 'Pour vous y retrouver si vous en créez plusieurs.',
    labelPlaceholder: 'Par exemple : Matériaux — Suisse romande',
    offersStep: 'Que vendez-vous ?',
    offersHelp: 'Sélectionnez au moins une catégorie. Elle détermine les besoins qui vous sont remontés.',
    secondaryOffersLabel: 'Ce que vous vendez aussi, plus occasionnellement',
    tradesStep: 'À quels corps de métier vendez-vous ?',
    tradesHelp:
      'Facultatif. Sans réponse, Kivou ne restreint pas le type d’entreprise gagnante.',
    secondaryTradesLabel: 'Corps de métier acceptés à défaut',
    territoriesStep: 'Où pouvez-vous livrer ou intervenir ?',
    territoriesHelp: 'Le lieu d’exécution du marché doit tomber dans l’un de ces pays.',
    thresholdStep: 'À partir de quel montant un marché vous intéresse-t-il ?',
    thresholdHelp:
      'Les marchés dont le montant n’est pas publié restent visibles, mais passent après ceux dont il l’est.',
    currency: 'Devise',
    minimumAmount: 'Montant minimum',
    maximumAmount: 'Montant maximum',
    summaryStep: 'Décrivez votre offre en une phrase',
    summaryHelp: 'Facultatif. Cette phrase ne filtre rien, elle vous sert de repère.',
    summaryPlaceholder: 'Par exemple : location de matériel de chantier avec livraison sous 48 h.',
    reviewStep: 'Vérifier et confirmer',
    reviewLead: 'Voici ce que Kivou retiendra de votre activité.',
    create: 'Créer mon profil et voir mes signaux',
    statusReady: 'Prêt pour les signaux',
    statusIncomplete: 'Informations manquantes',
    statusDraft: 'Brouillon',
    missingTitle: 'Il manque encore :',
    missing: {
      offers: 'ce que vous vendez',
      territories: 'où vous pouvez intervenir',
      minimum_contract_value: 'le montant minimum',
      buyer_trades: 'les corps de métier visés',
      label: 'le nom du profil',
    },
    stepOfferTitle: 'Ce que vous vendez',
    stepAudienceTitle: 'À qui et où vous vendez',
    stepThresholdTitle: 'À partir de quel montant',
    reviewTitle: 'Vérifier votre ciblage',
    summaryLabel: 'Votre offre en une phrase',
    stepIncomplete: 'Complétez cette étape pour continuer',
    savedNotFinalisedTitle: 'Votre ciblage a bien été enregistré',
    savedNotFinalisedBody:
      'Kivou n’a pas pu finaliser l’ouverture de vos signaux. Réessayez : votre ciblage ne sera pas enregistré une seconde fois.',
    finaliseRetry: 'Finaliser et voir mes signaux',
    welcomeTitle: 'Bienvenue dans Kivou',
    welcomeLead:
      'Pour recevoir des signaux, Kivou a besoin de savoir ce que vous vendez et où vous intervenez.',
  },

  activation: {
    progressLabel: 'Votre mise en route',
    stepAccount: 'Compte',
    stepTargeting: 'Ciblage',
    stepSignals: 'Signaux',
    stateDone: 'terminé',
    stateCurrent: 'étape en cours',
    stateTodo: 'à venir',
    readyTitle: 'Votre ciblage est prêt',
    countOne: '{count} signal est accessible avec votre profil.',
    countOther: '{count} signaux sont accessibles avec votre profil.',
    paidReady: 'Vos signaux sont disponibles ci-dessous.',
    noneTitle: 'Aucun signal correspondant n’est disponible pour le moment.',
    noneBody:
      'Kivou continuera à surveiller les nouvelles attributions compatibles avec votre profil.',
    firstSignal: 'Voir mon premier signal',
  },

  icp: {
    title: 'Profils de ciblage',
    lead: 'Un profil décrit ce que vous vendez et où. Il détermine les signaux que vous recevez.',
    create: 'Créer un profil',
    edit: 'Modifier',
    editTitle: 'Modifier le profil',
    listEmpty: 'Aucun profil de ciblage pour le moment.',
    listEmptyBody: 'Créez-en un pour commencer à recevoir des signaux.',
    limitLabel: 'Profils actifs',
    limitReached:
      'Votre offre {plan} autorise {limit} profil(s) actif(s). Les profils au-delà de cette limite n’alimentent plus votre flux.',
    overLimitBadge: 'Au-delà de la limite de votre offre',
    overLimitHelp:
      'Ce profil est conservé mais n’alimente plus votre flux. Passez à une offre supérieure pour le réintégrer au flux.',
    territoryLimitedBadge: 'Limité par votre offre',
    territoryLimitedHelpOne:
      'Ce profil conserve ses territoires, mais il n’alimente pas votre flux. Sélectionnez au maximum {limit} territoire pour le réactiver.',
    territoryLimitedHelpOther:
      'Ce profil conserve ses territoires, mais il n’alimente pas votre flux. Sélectionnez au maximum {limit} territoires pour le réactiver.',
    offersLabel: 'Ce que vous vendez',
    tradesLabel: 'Corps de métier visés',
    territoriesLabel: 'Territoires',
    thresholdLabel: 'Montant minimum',
    updated: 'Profil enregistré.',
    noTrades: 'Tous corps de métier',
  },

  offers: {
    materials_and_components: 'Matériaux et composants',
    equipment_rental: 'Location de matériel',
    staffing_and_labour: 'Personnel et main-d’œuvre',
    transport_and_logistics: 'Transport et logistique',
    specialist_subcontracting: 'Sous-traitance spécialisée',
    safety_equipment: 'Équipements de sécurité',
    waste_and_environmental_services: 'Déchets et services environnementaux',
  },

  trades: {
    earthworks_and_demolition: 'Terrassement et démolition',
    building_construction: 'Bâtiment',
    roads_and_civil_works: 'Routes et génie civil',
    rail_infrastructure: 'Infrastructure ferroviaire',
    special_civil_engineering: 'Génie civil spécial',
    technical_installations: 'Installations techniques',
    interior_finishing: 'Second œuvre et finitions',
    equipment_hire: 'Location d’équipement',
  },

  feed: {
    title: 'Occasions commerciales',
    lead:
      'Les entreprises et marchés correspondant à votre ciblage actif, dans l’ordre établi par Kivou.',
    countOne: '{count} signal',
    countOther: '{count} signaux',
    activeProfile: 'Profil actif',
    allProfiles: 'Tous les profils',
    freshness: 'Fraîcheur',
    freshnessNew: 'Nouveautés',
    freshnessRecentOrAging: 'Récents et plus anciens',
    freshnessAll: 'Tout l’historique',
    configureIcp: 'Configurer mon profil',
    loadMore: 'Voir plus de signaux',
    loadingMore: 'Chargement…',
    emptyTitle: 'Aucun signal pertinent pour le moment',
    emptyBody:
      'Kivou continue de surveiller les publications. Élargissez la fraîcheur ou ajustez votre profil de ciblage.',
    emptyWiden: 'Voir aussi les signaux plus anciens',
    noIcpTitle: 'Aucun profil de ciblage actif',
    noIcpBody:
      'Kivou a besoin de savoir ce que vous vendez et où vous intervenez avant de pouvoir vous montrer des signaux.',
    noIcpAction: 'Configurer mon profil',
    errorTitle: 'Les signaux n’ont pas pu être chargés',
    errorBody: 'La liste n’a pas pu être récupérée. Vous pouvez réessayer.',
    moreErrorTitle: 'Les signaux suivants n’ont pas pu être chargés',
    moreErrorBody: 'Les occasions déjà affichées restent disponibles. Vous pouvez réessayer.',
    retryMore: 'Réessayer la page suivante',
    truncatedNote:
      'La lecture a été bornée : des signaux plus anciens existent au-delà de cette page.',
    seeSignal: 'Voir le signal',
    winningCompany: 'Entreprise gagnante',
    publishedAmount: 'Montant publié',
    awardedContract: 'Marché remporté',
    publicFact: 'Fait public',
    plausibleNeed: 'Besoin plausible',
    profileMatch: 'Correspondance avec votre profil',
    timing: 'Calendrier commercial',
    plausibleNeedsShort: 'Besoins plausibles',
    aria: {
      list: 'Liste des signaux',
      updated: 'Liste des signaux mise à jour.',
    },
  },

  locked: {
    badge: 'Verrouillé',
    title: 'Étendre l’accès à votre flux',
    teaserHeadingFallback: 'Un signal détecté sur votre périmètre',
    body: 'Ces informations ne sont pas incluses dans votre accès actuel.',
    cta: 'Gérer mon accès',
    ctaShort: 'Gérer mon accès',
    country: 'Pays',
    sector: 'Secteur',
    magnitude: 'Ordre de grandeur',
    needCountOne: '{count} besoin plausible identifié',
    needCountOther: '{count} besoins plausibles identifiés',
    detailTitle: 'Ce signal est verrouillé',
    detailBody:
      'Votre accès actuel n’ouvre pas ce signal. L’accès aux signaux dépend des droits de votre offre et de sa fenêtre d’historique.',
  },

  magnitude: {
    under_50k: 'moins de 50 k',
    '50k_250k': '50 k à 250 k',
    '250k_1m': '250 k à 1 M',
    '1m_5m': '1 M à 5 M',
    over_5m: 'plus de 5 M',
  },

  discovery: {
    title: 'Votre découverte',
    grantedOne: '{count} signal réel débloqué',
    grantedOther: '{count} signaux réels débloqués',
    remainingOne: 'il reste {count} déblocage',
    remainingOther: 'il reste {count} déblocages',
    permanent:
      'Ces déblocages sont acquis définitivement. Ils ne se renouvellent pas et n’expirent pas.',
    noneYet:
      'Aucun signal éligible n’a encore été débloqué. Dès qu’un signal correspond à votre profil, il vous sera ouvert.',
    lockedRest: 'Les autres opportunités de votre flux restent verrouillées.',
    seePlans: 'Voir les offres',
  },

  detail: {
    backToFeed: 'Retour aux signaux',
    factsTitle: 'Faits publics',
    factsLead: 'Ce que la source officielle publie.',
    analysisTitle: 'Analyse Kivou',
    analysisLead: 'Ce que Kivou déduit de ces faits. Des hypothèses, pas des certitudes.',
    company: 'Entreprise gagnante',
    buyer: 'Acheteur',
    contract: 'Marché / contrat',
    lot: 'Lot',
    reference: 'Référence',
    amount: 'Montant',
    location: 'Lieu d’exécution',
    cpv: 'Code CPV',
    dates: 'Dates',
    dateAward: 'Attribution',
    dateNotification: 'Notification du contrat',
    datePublication: 'Publication',
    source: 'Source publique',
    sourceOpen: 'Ouvrir l’avis source',
    sourceSystem: 'Système source',
    noticeId: 'Identifiant d’avis',
    needsTitle: 'Besoins plausibles',
    needsEmpty: 'Aucun besoin plausible n’a été retenu pour ce marché.',
    needTargeted: 'Correspond à votre profil',
    needTiming: 'Fenêtre',
    needReasoning: 'Pourquoi cette hypothèse',
    contractReading: 'Lecture du contrat',
    contractType: 'Type de contrat',
    sector: 'Secteur',
    fitTitle: 'Adéquation avec votre profil',
    fitProfile: 'Profil concerné',
    fitReasons: 'Pourquoi ce signal vous est montré',
    whyNow: 'Pourquoi maintenant',
    errorTitle: 'Ce signal n’a pas pu être chargé',
    notFoundTitle: 'Signal introuvable',
    notFoundBody: 'Ce signal n’existe pas ou n’appartient pas à votre compte.',
  },

  evidence: {
    title: 'Preuve documentaire',
    lead: 'Chaque fait ci-dessous renvoie au document public qui l’établit.',
    publicFacts: 'Preuves des faits publiés',
    analysisInputs: 'Éléments ayant servi à l’analyse',
    empty: 'Preuve documentaire indisponible',
    emptyBody:
      'Aucun passage source n’est rattaché à ce signal. Les faits restent ceux publiés par la source, avec une confiance moindre.',
    excerpt: 'Passage source',
    retrievedAt: 'Consulté le',
    openSource: 'Ouvrir la source',
    expand: 'Afficher les preuves',
    collapse: 'Masquer les preuves',
    itemCountOne: '{count} preuve',
    itemCountOther: '{count} preuves',
  },

  feedback: {
    title: 'Votre avis sur ce signal',
    lead: 'Il nous sert à comprendre ce qui vous est utile. Il ne modifie pas le moteur.',
    relevant: 'Pertinent',
    notRelevant: 'Pas pertinent',
    reasonLabel: 'Pourquoi ce signal n’est-il pas pertinent ?',
    reasonRequired: 'Indiquez une raison pour enregistrer un avis « pas pertinent ».',
    reasons: {
      already_covered: 'Déjà couvert',
      done_internally: 'Réalisé en interne',
      wrong_customer_type: 'Mauvais type de client',
      too_late: 'Trop tard',
      wrong_need: 'Besoin erroné',
      other: 'Autre',
    },
    noteLabel: 'Précision',
    noteHelp: '{max} caractères maximum.',
    noteCount: '{count} / {max}',
    submit: 'Enregistrer mon avis',
    recorded: 'Avis enregistré.',
    contactedTitle: 'Avez-vous contacté cette entreprise ?',
    contactedLead:
      '« Contacté » signifie seulement que vous avez pris contact. Cela ne dit rien d’une réponse, d’un rendez-vous ou d’une affaire gagnée.',
    markContacted: 'J’ai contacté cette entreprise',
    contactedOn: 'Contact enregistré le {date}',
    contactedAlready: 'Contact déjà enregistré',
  },

  billing: {
    title: 'Facturation',
    lead: 'Votre offre, son statut, et la gestion de votre abonnement.',
    plansTitle: 'Offres',
    currentPlan: 'Votre offre',
    planStatus: 'Statut de l’abonnement',
    renewsOn: 'Prochain renouvellement le {date}',
    endsOn: 'Accès jusqu’au {date}',
    cancellationTitle: 'Résiliation programmée',
    cancellationAtPeriodEnd:
      'Votre abonnement prendra fin à la fin de la période en cours, le {date}.',
    cancellationOnDate: 'Votre abonnement prendra fin le {date}.',
    paymentIssue: 'Un incident de paiement est en cours sur cet abonnement.',
    managePortal: 'Gérer ma facturation',
    manageLead:
      'Moyen de paiement, factures et résiliation sont gérés dans votre portail de facturation.',
    recoverTitle: 'Accès suspendu — incident de paiement',
    recoverBody:
      'Votre abonnement existe toujours, mais l’accès payant est suspendu tant que l’incident de paiement n’est pas régularisé. Votre portail de facturation réunit votre moyen de paiement, vos factures et l’état de votre abonnement.',
    recoverCta: 'Ouvrir le portail de facturation',
    supportTitle: 'Vérification de facturation nécessaire',
    supportBody:
      'La facturation de ce compte nécessite une vérification avant toute nouvelle souscription. Écrivez-nous et nous la traiterons.',
    supportCta: 'Écrire à contact@kivou.eu',
    supportEmail: 'contact@kivou.eu',
    terminalNotice:
      'La tentative précédente n’est plus active. Vous pouvez choisir une offre et recommencer.',
    openingPortal: 'Ouverture…',
    currency: 'Devise',
    currencyLead: 'Choisissez la devise de facturation. Elle ne se déduit pas de votre langue.',
    perMonth: '/ mois',
    free: 'Gratuit',
    recommended: 'Recommandé',
    current: 'Votre offre actuelle',
    choose: 'Choisir {plan}',
    choosing: 'Ouverture du paiement…',
    publicDiscoveryCta: 'Voir mes 3 premiers signaux',
    publicPaidCta: 'Créer mon compte',
    included: 'Ce qui est inclus',
    plans: {
      discovery: 'Découverte',
      essential: 'Essential',
      pro: 'Pro',
      scale: 'Scale',
    },
    planPositioning: {
      discovery: 'Validez la pertinence de Kivou avec vos trois premiers signaux.',
      essential: 'Concentrez votre prospection sur une priorité commerciale.',
      pro: 'Suivez plusieurs priorités et agissez avec le contexte et les preuves utiles.',
      scale: 'Étendez votre couverture à davantage de marchés et de territoires.',
    },
    entitlements: {
      icpsOne: '{count} profil de ciblage',
      icpsOther: '{count} profils de ciblage',
      territoriesPerProfileOne: 'Jusqu’à {count} territoire par profil',
      territoriesPerProfileOther: 'Jusqu’à {count} territoires par profil',
      territoryMultiple: 'Plusieurs territoires par profil',
      territoryExpanded: 'Couverture territoriale étendue',
      historyWindow: 'Historique {days} jours',
      historyAll: 'Tout l’historique conservé',
      historyNone: 'Pas de fenêtre d’historique générale',
      grantedSignals: '{count} signaux réels débloqués définitivement',
      evidence: 'Preuve documentaire complète',
      filterMinimum: 'Filtres essentiels',
      filterBasic: 'Filtres de base',
      filterAdvanced: 'Filtres avancés',
      alertNone: 'Pas d’alertes e-mail',
      alertWeekly: 'Alertes e-mail hebdomadaires',
      alertDaily: 'Alertes e-mail quotidiennes',
      alertPriority: 'Alertes e-mail prioritaires',
      exportNone: 'Pas d’export',
      exportManual: 'Export limité',
      exportScheduled: 'Export étendu',
    },
    status: {
      active: 'Actif',
      trialing: 'Période d’essai',
      past_due: 'Paiement en retard',
      canceled: 'Résilié',
      incomplete: 'Incomplet',
      incomplete_expired: 'Expiré',
      unpaid: 'Impayé',
      paused: 'En pause',
      none: 'Aucun abonnement',
      /* Tout statut absent de ce dictionnaire. Rendre la chaîne Stripe brute
       * exposerait un terme technique là où `billing_action` a justement
       * décidé de traiter l'incertitude comme une vérification à faire. */
      unknown: 'À vérifier',
    },
    errors: {
      checkoutInProgressTitle: 'Un paiement est déjà ouvert',
      checkoutInProgressBody:
        'Une session de paiement est déjà ouverte pour ce compte. Terminez-la, ou réessayez après son expiration.',
      checkoutInProgressExpiry: 'Elle expire le {date}.',
      alreadySubscribedTitle: 'Cet abonnement est déjà actif',
      alreadySubscribedBody:
        'Ce compte a déjà un abonnement actif. Utilisez la gestion de facturation pour en changer.',
      unavailableTitle: 'Facturation indisponible',
      unavailableBody:
        'Le service de paiement n’est pas joignable pour le moment. Réessayez dans quelques instants.',
      noCustomerTitle: 'Aucun dossier de facturation',
      noCustomerBody:
        'Ce compte n’a pas encore de dossier de facturation. Il en aura un après un premier paiement.',
    },
  },

  checkout: {
    successTitle: 'Accès payant actif',
    successPending: 'Vérification de votre accès',
    successPendingBody:
      'Kivou vérifie l’état de votre abonnement. L’accès ne sera ouvert qu’après confirmation serveur.',
    successBody: 'Votre offre {plan} est active. Vos droits payants sont disponibles.',
    successTimeout:
      'Aucun accès payant n’a encore été confirmé. Si vous venez de terminer un paiement, la synchronisation peut prendre quelques minutes.',
    goToSignals: 'Accéder à mes signaux',
    refresh: 'Réessayer la vérification',
    returnToSignal: 'Revenir à ce signal',
    seeAllSignals: 'Voir tous mes signaux',
    seeBilling: 'Voir ma facturation',
    cancelTitle: 'Retour depuis le parcours de paiement',
    cancelBody:
      'Vous êtes revenu à Kivou depuis le parcours de paiement. Cette page ne modifie pas votre accès. Consultez votre facturation pour vérifier l’état de votre abonnement.',
    backToPlans: 'Revenir aux offres',
    backToSignals: 'Revenir à mes signaux',
    unlocked: 'Vous débloquez immédiatement',
    checking: 'Vérification de votre accès…',
  },

  notifications: {
    title: 'Notifications',
    lead: 'Les alertes e-mail que Kivou peut vous envoyer, et à quelle adresse.',
    enabled: 'Recevoir les alertes par e-mail',
    enabledHelp: 'Vous pouvez les couper à tout moment sans changer d’offre.',
    emailLabel: 'Adresse de réception',
    emailHelp: 'Elle peut différer de votre adresse de connexion.',
    cadenceLabel: 'Fréquence associée à votre offre',
    cadenceHelp: 'La fréquence dépend de votre offre. Elle ne se règle pas ici.',
    cadence: {
      none: 'Aucune alerte',
      weekly: 'Hebdomadaire',
      daily: 'Quotidienne',
      priority: 'Prioritaire',
    },
    cadenceNoneHelp:
      'L’offre Découverte n’inclut pas d’alertes e-mail. Consultez votre flux directement.',
    updated: 'Préférences enregistrées.',
    errorTitle: 'Les préférences n’ont pas pu être chargées',
    invalidEmail: 'Cette adresse n’est pas valide.',
  },

  errors: {
    genericTitle: 'Une erreur est survenue',
    genericBody: 'L’action n’a pas pu aboutir. Vous pouvez réessayer.',
    networkTitle: 'Connexion impossible',
    networkBody: 'Kivou n’a pas pu être joint. Vérifiez votre connexion, puis réessayez.',
    invalidCredentials: 'Adresse e-mail ou mot de passe incorrect.',
    emailAlreadyUsed: 'Ce compte n’a pas pu être créé.',
    unsupportedLocale: 'Cette langue n’est pas prise en charge.',
    invalidResetToken: 'Ce lien de réinitialisation n’est plus valide. Demandez-en un nouveau.',
    notFoundTitle: 'Page introuvable',
    notFoundBody: 'Cette adresse ne correspond à aucune page de Kivou.',
    targetIcpNotFound: 'Ce profil de ciblage est introuvable.',
    territoryLimitTitle: 'Limite territoriale atteinte',
    territoryLimitBodyOne:
      'Votre offre autorise {limit} territoire par profil. Réduisez votre sélection pour enregistrer ce ciblage.',
    territoryLimitBodyOther:
      'Votre offre autorise {limit} territoires par profil. Réduisez votre sélection pour enregistrer ce ciblage.',
    territoryLimitBodyFallback:
      'Votre sélection dépasse la limite territoriale de votre offre. Réduisez-la pour enregistrer ce ciblage.',
    filterNotEntitled:
      'Ce filtre demande une offre supérieure. Votre flux reste affiché sans ce filtre.',
    signalNotAccessible: 'Ce signal doit être déverrouillé avant de pouvoir être jugé.',
    validationTitle: 'Vérifiez les informations saisies',
    forbidden: 'Vous n’avez pas accès à cette ressource.',
    csrfRejected: 'La requête a été refusée. Rechargez la page, puis réessayez.',
    goHome: 'Revenir à l’accueil',
  },
}

/* Pas d'`as const` : la forme sert de CONTRAT à `en.ts`, et des types
 * littéraux y interdiraient toute traduction — « Save » ne serait pas
 * assignable au type « Enregistrer ». Ce qui doit correspondre entre les deux
 * langues, ce sont les CLÉS, pas les valeurs. */
export type Dictionary = typeof fr
