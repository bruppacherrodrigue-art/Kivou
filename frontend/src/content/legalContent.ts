/* Public copy transcribed from docs/LEGAL_CONTENT.md.
 *
 * The source document also contains publication instructions, factual review
 * notes and pre-LIVE checks. Those internal sections deliberately do not enter
 * this browser bundle. Keeping the public clauses in a typed module makes the
 * long bilingual document maintainable without weakening the i18n contract. */

export type PublicLegalLocale = 'fr' | 'en'
export type LegalSectionId = 'mentions-legales' | 'confidentialite' | 'cgu'

export type LegalBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; items: string[] }
  | { kind: 'address'; lines: string[] }

export interface LegalSubsection {
  title: string
  blocks: LegalBlock[]
}

export interface LegalSection {
  id: LegalSectionId
  title: string
  subsections: LegalSubsection[]
}

export interface LegalPageContent {
  eyebrow: string
  title: string
  updated: string
  introduction: string
  contentsLabel: string
  contents: Array<{ id: LegalSectionId; label: string }>
  backToContents: string
  metaTitle: string
  metaDescription: string
  sections: LegalSection[]
}

const fr: LegalPageContent = {
  eyebrow: 'INFORMATIONS PUBLIQUES',
  title: 'Informations légales et contractuelles',
  updated: 'Dernière mise à jour : 23 août 2026',
  introduction:
    'Cette page regroupe les mentions légales, la politique de confidentialité et les Conditions générales d’utilisation et d’abonnement de Kivou.',
  contentsLabel: 'Sommaire juridique',
  contents: [
    { id: 'mentions-legales', label: 'Mentions légales' },
    { id: 'confidentialite', label: 'Confidentialité' },
    { id: 'cgu', label: 'Conditions générales' },
  ],
  backToContents: 'Retour au sommaire',
  metaTitle: 'Informations légales et contractuelles — Kivou',
  metaDescription:
    'Consultez les mentions légales, la politique de confidentialité et les Conditions générales de Kivou.',
  sections: [
    {
      id: 'mentions-legales',
      title: 'Mentions légales',
      subsections: [
        {
          title: 'Éditeur du service',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Le site Internet Kivou et le service logiciel accessible depuis le domaine `kivou.eu`, ci-après le « Service », sont édités et exploités par :',
            },
            {
              kind: 'address',
              lines: ['Rodrigue Bruppacher', 'Rue des Champs-de-Tabac 12', '1950 Sion', 'Suisse'],
            },
            { kind: 'paragraph', text: 'Adresse électronique : contact@kivou.eu' },
          ],
        },
        {
          title: 'Hébergement',
          blocks: [
            { kind: 'paragraph', text: 'Le Service est hébergé en Suisse par :' },
            {
              kind: 'address',
              lines: [
                'Infomaniak Network SA',
                'Rue Eugène Marziano 25',
                '1227 Les Acacias (GE)',
                'Suisse',
              ],
            },
            {
              kind: 'paragraph',
              text: 'L’infrastructure principale, la base de données et les services applicatifs de Kivou sont exploités sur une infrastructure située en Suisse. Certains prestataires nécessaires, notamment Stripe pour les paiements, peuvent traiter des données dans d’autres pays conformément à leurs propres engagements et aux garanties applicables.',
            },
          ],
        },
        {
          title: 'Propriété intellectuelle',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Le nom Kivou, le logiciel, l’interface, les textes, les éléments graphiques, les compilations, classifications, analyses, modèles de données et méthodes propres au Service sont protégés par les droits applicables. Les documents et informations provenant de tiers restent soumis aux droits et conditions de leurs sources respectives.',
            },
          ],
        },
        {
          title: 'Contact éditorial',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Toute question concernant le site ou son contenu peut être envoyée à contact@kivou.eu.',
            },
          ],
        },
      ],
    },
    {
      id: 'confidentialite',
      title: 'Politique de confidentialité',
      subsections: [
        {
          title: '1. Responsable du traitement',
          blocks: [
            { kind: 'paragraph', text: 'Le responsable du traitement est :' },
            {
              kind: 'address',
              lines: [
                'Rodrigue Bruppacher',
                'Rue des Champs-de-Tabac 12',
                '1950 Sion',
                'Suisse',
                'contact@kivou.eu',
              ],
            },
          ],
        },
        {
          title: '2. Champ d’application',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Cette politique décrit le traitement des données personnelles effectué lorsque vous visitez `kivou.eu`, créez ou utilisez un compte Kivou, configurez votre ciblage, consultez ou évaluez des signaux, gérez un abonnement, recevez une alerte ou contactez Kivou.',
            },
            {
              kind: 'paragraph',
              text: 'Les informations concernant uniquement une personne morale ne sont pas toujours des données personnelles. Elles peuvent cependant le devenir lorsqu’elles identifient une personne physique, par exemple un indépendant, un titulaire d’entreprise individuelle ou un interlocuteur nommé.',
            },
          ],
        },
        {
          title: '3. Données traitées',
          blocks: [
            { kind: 'paragraph', text: 'Selon votre utilisation, Kivou peut traiter :' },
            {
              kind: 'list',
              items: [
                'les données de compte et d’organisation : adresse électronique, nom d’entreprise, langue, identifiants techniques et données d’authentification protégées ;',
                'les données de ciblage commercial que vous fournissez : offre, secteurs, territoires, seuils et préférences ICP ;',
                'les données d’usage du SaaS : signaux consultés ou débloqués, feedback, statut contacté, préférences et cadence d’alertes ;',
                'les données de facturation : plan, état d’abonnement, devise, références Stripe et informations nécessaires au suivi de la relation commerciale ;',
                'les données de support et de communication que vous choisissez de transmettre ;',
                'des données techniques de sécurité et d’exploitation, telles que des identifiants de session, horodatages et journaux nécessaires à la protection et au fonctionnement du Service ;',
                'des données provenant de sources publiques sur des marchés, organisations et, lorsque la source le contient, personnes agissant dans un cadre professionnel ;',
                'les références d’origine d’une inscription lorsqu’un lien d’attribution Kivou est utilisé.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Kivou ne reçoit normalement pas le numéro complet de votre carte ni son code de sécurité. Ces données sont traitées par Stripe.',
            },
          ],
        },
        {
          title: '4. Finalités et fondements',
          blocks: [
            { kind: 'paragraph', text: 'Kivou traite les données nécessaires pour :' },
            {
              kind: 'list',
              items: [
                'créer, sécuriser et administrer le compte ;',
                'exécuter le Service, personnaliser le feed selon le profil ICP et conserver les actions demandées ;',
                'fournir Discovery, les abonnements, la facturation et le support ;',
                'envoyer les alertes et messages transactionnels configurés ;',
                'prévenir les abus, diagnostiquer les incidents et améliorer la fiabilité du produit ;',
                'mesurer l’activation et l’usage du produit au moyen d’événements techniques limités ;',
                'respecter les obligations légales, comptables, fiscales et de défense de droits ;',
                'répondre aux demandes envoyées à Kivou.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Lorsque le RGPD s’applique, ces traitements reposent, selon le cas, sur l’exécution du contrat ou de mesures précontractuelles, le respect d’une obligation légale, les intérêts légitimes de Kivou à sécuriser et améliorer son service, ou le consentement lorsqu’il est effectivement demandé. Kivou n’utilise pas le consentement comme fondement si aucun mécanisme réel de consentement n’est proposé.',
            },
          ],
        },
        {
          title: '5. Sources publiques, analyses et décisions automatisées',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou analyse des informations légalement accessibles, notamment des avis et documents relatifs aux marchés publics. Le produit distingue les faits issus de sources publiques des besoins commerciaux plausibles inférés à partir de ces faits.',
            },
            {
              kind: 'paragraph',
              text: 'Le classement ou la correspondance d’un signal avec un profil commercial aide un professionnel à organiser sa prospection. Kivou n’est pas conçu pour prendre à l’égard d’une personne physique une décision automatisée produisant des effets juridiques ou comparables.',
            },
          ],
        },
        {
          title: '6. Cookies et stockage local',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou utilise des mécanismes strictement nécessaires à la connexion et à la continuité des parcours :',
            },
            {
              kind: 'list',
              items: [
                '`kivou_session`, cookie HTTP-only de session, sécurisé en production et limité à la durée de la session configurée ;',
                '`kivou_attribution`, cookie HTTP-only de première partie, limité au parcours d’inscription après l’ouverture d’un lien d’attribution Kivou et expirant selon la durée du lien signé.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Kivou n’utilise aucun cookie publicitaire tiers dans cette version du Service. Le cookie d’attribution ne sert pas à personnaliser de la publicité ; il relie un lien Kivou à une inscription afin d’en mesurer l’origine.',
            },
          ],
        },
        {
          title: '7. Destinataires et prestataires',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Les données sont accessibles uniquement aux personnes et prestataires qui en ont besoin pour fournir, sécuriser ou administrer le Service, notamment :',
            },
            {
              kind: 'list',
              items: [
                'Infomaniak Network SA pour l’hébergement en Suisse ;',
                'Stripe pour le paiement, l’abonnement, la prévention de la fraude et les obligations associées ;',
                'le prestataire de messagerie configuré par Kivou pour les alertes, la réinitialisation de mot de passe et les communications nécessaires ;',
                'les autorités ou conseils professionnels lorsque la loi ou la défense de droits l’exige.',
              ],
            },
            { kind: 'paragraph', text: 'Kivou ne vend pas les données personnelles de ses utilisateurs.' },
          ],
        },
        {
          title: '8. Transferts internationaux',
          blocks: [
            {
              kind: 'paragraph',
              text: 'L’infrastructure principale de Kivou est située en Suisse. Certains prestataires, en particulier Stripe, peuvent traiter des données à l’étranger. Lorsqu’une protection adéquate n’est pas reconnue, Kivou ou le prestataire concerné applique les garanties requises par le droit applicable, telles que des clauses contractuelles reconnues, ou s’appuie sur une exception légale documentée.',
            },
          ],
        },
        {
          title: '9. Durées de conservation',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou conserve les données pendant la durée nécessaire aux finalités décrites, puis pendant les périodes imposées ou permises pour la comptabilité, la fiscalité, la sécurité, la résolution de litiges et la défense de droits.',
            },
            { kind: 'paragraph', text: 'Les critères suivants s’appliquent :' },
            {
              kind: 'list',
              items: [
                'les données de compte et d’usage sont conservées pendant la relation active, puis supprimées ou limitées lorsque leur conservation n’est plus nécessaire ;',
                'les données de facturation sont conservées selon les obligations comptables et fiscales applicables ;',
                'les sessions expirent selon la durée configurée par le Service ;',
                'un jeton de réinitialisation de mot de passe expire au plus tard à l’échéance configurée et n’est pas conservé en clair ;',
                'les sauvegardes suivent un cycle de rétention opérationnel contrôlé et ne servent pas à réintroduire des données supprimées dans l’usage courant.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Aucune durée chiffrée autre que celle effectivement configurée ou légalement validée ne doit être ajoutée à la page.',
            },
          ],
        },
        {
          title: '10. Sécurité',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou met en œuvre des mesures techniques et organisationnelles proportionnées, notamment le chiffrement des communications, des cookies de session protégés en production, des contrôles d’accès, la séparation des environnements, la limitation des secrets et des sauvegardes contrôlées. Aucun système ne peut toutefois garantir une sécurité absolue.',
            },
          ],
        },
        {
          title: '11. Vos droits',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Selon le droit applicable, vous pouvez demander l’accès à vos données, leur rectification, leur suppression, la limitation de certains traitements, vous opposer à un traitement ou recevoir les données que vous avez fournies dans un format portable lorsque ce droit s’applique. Vous pouvez retirer un consentement pour l’avenir lorsqu’un traitement repose effectivement sur celui-ci.',
            },
            {
              kind: 'paragraph',
              text: 'Adressez votre demande à contact@kivou.eu. Kivou peut demander les éléments raisonnablement nécessaires pour vérifier votre identité et protéger le compte concerné.',
            },
            {
              kind: 'paragraph',
              text: 'Vous pouvez également saisir le Préposé fédéral à la protection des données et à la transparence (PFPDT) et, lorsque le RGPD s’applique, l’autorité de contrôle compétente dans l’Espace économique européen.',
            },
          ],
        },
        {
          title: '12. Suppression du compte',
          blocks: [
            {
              kind: 'paragraph',
              text: 'En l’absence de fonction de suppression en libre-service, une demande peut être envoyée à contact@kivou.eu. La suppression du compte et la résiliation d’un abonnement sont deux opérations distinctes. Une demande de suppression ne vaut pas automatiquement résiliation immédiate d’une période payée, et certaines données peuvent être conservées lorsque la loi ou la défense de droits l’exige.',
            },
          ],
        },
        {
          title: '13. Modifications et contact',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Cette politique peut évoluer avec le Service ou le droit applicable. La date de mise à jour est indiquée en tête de page. Pour toute question relative aux données personnelles : contact@kivou.eu.',
            },
          ],
        },
      ],
    },
    {
      id: 'cgu',
      title: 'Conditions générales d’utilisation et d’abonnement',
      subsections: [
        {
          title: '1. Objet et acceptation',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Les présentes Conditions régissent l’accès au site, la création et l’utilisation d’un compte, les fonctionnalités gratuites, les abonnements payants et l’utilisation des signaux, analyses et preuves fournis par Kivou.',
            },
            {
              kind: 'paragraph',
              text: 'En créant un compte, en souscrivant un abonnement ou en utilisant le Service, l’utilisateur confirme avoir lu et accepté les présentes Conditions.',
            },
          ],
        },
        {
          title: '2. Service réservé aux professionnels',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou est destiné exclusivement aux entreprises, indépendants, associations, organismes et autres utilisateurs agissant dans le cadre de leur activité professionnelle. Le Service n’est pas destiné aux consommateurs agissant à des fins privées ni aux mineurs.',
            },
            {
              kind: 'paragraph',
              text: 'La personne qui crée un compte au nom d’une organisation confirme être autorisée à engager cette organisation.',
            },
          ],
        },
        {
          title: '3. Description du Service',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou analyse notamment des informations relatives aux marchés publics, aux adjudications, aux entreprises gagnantes et, lorsque disponibles, aux documents associés.',
            },
            {
              kind: 'paragraph',
              text: 'Le Service peut fournir des faits relatifs à un marché, l’identité d’une entreprise gagnante, des dates, montants, lieux ou classifications, des preuves issues de sources publiques, des besoins commerciaux plausibles, un timing fourni par le Service et une correspondance avec le profil commercial défini par l’utilisateur.',
            },
            {
              kind: 'paragraph',
              text: 'Kivou distingue les faits publics des analyses et inférences. Un besoin plausible ne signifie pas qu’une entreprise effectuera un achat, recherchera un fournisseur ou répondra à une sollicitation. Kivou ne garantit aucun contrat, vente, réponse, rendez-vous, chiffre d’affaires ou résultat commercial.',
            },
          ],
        },
        {
          title: '4. Sources publiques et vérification',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Les informations peuvent provenir de portails de marchés publics, avis officiels, documents publics, registres, sites d’entreprises ou autres sources accessibles légalement. Les sources externes peuvent être incomplètes, corrigées, retardées ou erronées.',
            },
            {
              kind: 'paragraph',
              text: 'Kivou conserve autant que possible un lien ou une référence vers la source. L’utilisateur reste responsable de vérifier les informations essentielles avant une décision ou une démarche commerciale. Kivou n’est pas affilié aux administrations ou portails sources, sauf indication expresse.',
            },
          ],
        },
        {
          title: '5. Compte et sécurité',
          blocks: [
            {
              kind: 'paragraph',
              text: 'L’utilisateur fournit des informations exactes et à jour, protège ses identifiants et informe rapidement Kivou de tout accès non autorisé. Le partage d’un compte au-delà des droits du plan est interdit. Kivou peut demander une vérification raisonnable de l’identité professionnelle ou de l’autorité de l’utilisateur.',
            },
          ],
        },
        {
          title: '6. Plans et droits',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou peut proposer un plan gratuit et des plans payants. Les prix, devises, capacités, territoires, profils, historique, preuves, alertes et autres droits applicables sont uniquement ceux affichés par le Service au moment considéré et confirmés pendant la commande.',
            },
            {
              kind: 'paragraph',
              text: 'Ce document ne promet aucun export, filtre avancé, recherche de décideur, CRM ou autre fonction qui n’est pas réellement exerçable dans le produit.',
            },
          ],
        },
        {
          title: '7. Souscription et paiement',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Avant de confirmer un abonnement payant, l’utilisateur peut vérifier le plan, le prix, la devise, la périodicité, les taxes éventuellement applicables, les informations de facturation et les capacités principales.',
            },
            {
              kind: 'paragraph',
              text: 'Les paiements sont traités par Stripe. L’abonnement est activé lorsque le paiement est accepté et que Kivou confirme son activation. Kivou ne reçoit normalement pas le numéro complet de la carte ni son code de sécurité.',
            },
          ],
        },
        {
          title: '8. Renouvellement automatique',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Sauf indication contraire avant la commande, les abonnements payants sont mensuels et se renouvellent automatiquement. L’utilisateur autorise Stripe et Kivou à débiter le moyen de paiement enregistré à chaque échéance jusqu’à la résiliation.',
            },
          ],
        },
        {
          title: '9. Résiliation',
          blocks: [
            {
              kind: 'paragraph',
              text: 'L’utilisateur peut demander ou programmer la résiliation au moyen de l’action réellement proposée dans son espace de facturation ou écrire à contact@kivou.eu. La résiliation prend effet à la date confirmée par le Service, généralement à la fin de la période déjà payée.',
            },
            {
              kind: 'paragraph',
              text: 'Les périodes commencées ne sont pas remboursées au prorata, sauf erreur de facturation, engagement exprès de Kivou ou disposition impérative contraire. La suppression d’un compte et la résiliation d’un abonnement sont distinctes.',
            },
          ],
        },
        {
          title: '10. Paiement échoué',
          blocks: [
            {
              kind: 'paragraph',
              text: 'En cas d’échec ou de retard, Kivou peut demander la mise à jour du moyen de paiement, permettre de nouvelles tentatives, limiter l’accès aux fonctions payantes ou résilier l’abonnement si le paiement n’est pas régularisé. Les montants déjà dus restent exigibles.',
            },
          ],
        },
        {
          title: '11. Modification des offres',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou peut faire évoluer ses prix, plans ou capacités. Une modification applicable à un abonnement existant est communiquée avant son entrée en vigueur et s’applique au plus tôt lors d’un renouvellement ultérieur, sous réserve du droit applicable. L’utilisateur qui la refuse peut résilier avant sa prise d’effet.',
            },
          ],
        },
        {
          title: '12. Utilisation autorisée',
          blocks: [
            {
              kind: 'paragraph',
              text: 'L’utilisateur peut employer les informations pour ses besoins professionnels internes : examiner des entreprises, préparer une approche, prioriser sa prospection et effectuer ses propres vérifications.',
            },
            {
              kind: 'paragraph',
              text: 'L’utilisateur reste seul responsable de ses communications commerciales, de leur contenu, fréquence, base juridique et conformité dans le pays du destinataire.',
            },
          ],
        },
        {
          title: '13. Utilisations interdites',
          blocks: [
            { kind: 'paragraph', text: 'Il est interdit notamment :' },
            {
              kind: 'list',
              items: [
                'd’utiliser Kivou à des fins illégales, frauduleuses, trompeuses ou discriminatoires ;',
                'de présenter une inférence comme un fait certain ;',
                'd’envoyer des communications interdites ou d’ignorer une opposition ;',
                'de harceler une personne ou une organisation ;',
                'd’extraire ou aspirer massivement la base de données ;',
                'de contourner un paywall, quota ou contrôle technique ;',
                'de revendre ou redistribuer systématiquement les signaux sans autorisation ;',
                'de partager un accès avec une personne non autorisée ;',
                'de procéder à de l’ingénierie inverse, sonder, perturber ou attaquer l’infrastructure ;',
                'de construire un service concurrent en copiant les données, classifications, modèles ou présentations propres à Kivou ;',
                'd’utiliser les signaux pour prendre à l’égard d’une personne physique une décision produisant des effets juridiques ou comparables, notamment en matière d’emploi, de crédit, d’assurance ou de logement.',
              ],
            },
          ],
        },
        {
          title: '14. Données fournies par l’utilisateur',
          blocks: [
            {
              kind: 'paragraph',
              text: 'L’utilisateur conserve les droits qu’il détient sur ses informations et autorise Kivou à les traiter dans la mesure nécessaire pour fournir et sécuriser le Service, configurer le profil commercial, exécuter les préférences et améliorer la fiabilité au moyen de données agrégées ou anonymisées. Il garantit être autorisé à transmettre ces données.',
            },
          ],
        },
        {
          title: '15. Disponibilité',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou met en œuvre des efforts raisonnables pour assurer la disponibilité et la sécurité du Service. Des interruptions peuvent résulter d’une maintenance, mise à jour, panne, incident de sécurité, défaillance d’un fournisseur ou événement hors du contrôle raisonnable de Kivou. Sauf engagement distinct, aucun niveau de service spécifique n’est garanti.',
            },
          ],
        },
        {
          title: '16. Suspension ou fermeture',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou peut limiter, suspendre ou fermer un compte en cas de non-paiement, violation des Conditions, abus, utilisation illicite, risque de sécurité, contournement, obligation légale ou atteinte au Service ou à des tiers. Lorsque la situation le permet, Kivou informe l’utilisateur et lui permet de remédier au problème.',
            },
          ],
        },
        {
          title: '17. Absence de garantie commerciale',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou ne garantit pas l’exhaustivité des marchés publics, l’exactitude absolue des sources externes, l’existence d’un achat futur, la disponibilité d’un budget, l’absence de fournisseurs déjà engagés, la réponse d’un prospect, un contrat, un chiffre d’affaires ou un retour sur investissement.',
            },
          ],
        },
        {
          title: '18. Responsabilité',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Aucune disposition ne limite une responsabilité qui ne peut légalement être exclue, notamment en cas de faute intentionnelle ou grave.',
            },
            {
              kind: 'paragraph',
              text: 'Dans la mesure permise, Kivou n’est pas responsable des décisions prises sur la seule base d’un signal, des erreurs ou retards d’une source externe, des communications envoyées par l’utilisateur, de la réaction d’un tiers, des pertes indirectes ou des pertes résultant d’un usage non conforme.',
            },
            {
              kind: 'paragraph',
              text: 'Dans la mesure permise, la responsabilité totale résultant d’une faute légère est limitée au montant effectivement payé à Kivou au cours des douze mois précédant l’événement à l’origine de la demande.',
            },
          ],
        },
        {
          title: '19. Force majeure',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou n’est pas responsable d’un retard ou d’une inexécution résultant d’un événement échappant raisonnablement à son contrôle, notamment une catastrophe, panne générale de réseau, cyberattaque majeure, décision d’autorité, conflit, grève générale ou indisponibilité critique d’un fournisseur essentiel.',
            },
          ],
        },
        {
          title: '20. Modification des Conditions',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou peut modifier les Conditions pour tenir compte du droit, du Service, de la sécurité, d’un fournisseur ou d’une correction. Les changements importants sont communiqués par un moyen approprié avant leur entrée en vigueur. En cas de refus, l’utilisateur peut cesser d’utiliser le Service et résilier avant leur prise d’effet.',
            },
          ],
        },
        {
          title: '21. Droit applicable, juridiction et langue',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Les Conditions sont régies par le droit suisse. Sous réserve des fors impératifs, les tribunaux ordinaires de Sion, canton du Valais, sont compétents.',
            },
            {
              kind: 'paragraph',
              text: 'Les versions française et anglaise visent le même sens. En cas de divergence d’interprétation, la version française prévaut.',
            },
          ],
        },
        {
          title: '22. Contact',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Toute question relative au Service, à un abonnement ou aux présentes Conditions peut être envoyée à contact@kivou.eu.',
            },
          ],
        },
      ],
    },
  ],
}

const en: LegalPageContent = {
  eyebrow: 'PUBLIC INFORMATION',
  title: 'Legal and contractual information',
  updated: 'Last updated: 23 August 2026',
  introduction:
    'This page contains Kivou’s legal notice, Privacy Policy and Terms of Use and Subscription.',
  contentsLabel: 'Legal contents',
  contents: [
    { id: 'mentions-legales', label: 'Legal notice' },
    { id: 'confidentialite', label: 'Privacy' },
    { id: 'cgu', label: 'Terms' },
  ],
  backToContents: 'Back to contents',
  metaTitle: 'Legal and contractual information — Kivou',
  metaDescription: 'Read Kivou’s legal notice, Privacy Policy and Terms of Use and Subscription.',
  sections: [
    {
      id: 'mentions-legales',
      title: 'Legal notice',
      subsections: [
        {
          title: 'Service operator',
          blocks: [
            {
              kind: 'paragraph',
              text: 'The Kivou website and software service available through `kivou.eu`, hereinafter the “Service”, are published and operated by:',
            },
            {
              kind: 'address',
              lines: ['Rodrigue Bruppacher', 'Rue des Champs-de-Tabac 12', '1950 Sion', 'Switzerland'],
            },
            { kind: 'paragraph', text: 'Email: contact@kivou.eu' },
          ],
        },
        {
          title: 'Hosting',
          blocks: [
            { kind: 'paragraph', text: 'The Service is hosted in Switzerland by:' },
            {
              kind: 'address',
              lines: [
                'Infomaniak Network SA',
                'Rue Eugène Marziano 25',
                '1227 Les Acacias (GE)',
                'Switzerland',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Kivou’s main infrastructure, database and application services are operated on infrastructure located in Switzerland. Necessary providers, including Stripe for payments, may process data in other countries under their own commitments and the applicable safeguards.',
            },
          ],
        },
        {
          title: 'Intellectual property',
          blocks: [
            {
              kind: 'paragraph',
              text: 'The Kivou name, software, interface, texts, graphics, compilations, classifications, analyses, data models and proprietary methods are protected by applicable rights. Third-party documents and information remain subject to the rights and terms applicable to their respective sources.',
            },
          ],
        },
        {
          title: 'Editorial contact',
          blocks: [
            { kind: 'paragraph', text: 'Questions about the website or its content may be sent to contact@kivou.eu.' },
          ],
        },
      ],
    },
    {
      id: 'confidentialite',
      title: 'Privacy Policy',
      subsections: [
        {
          title: '1. Controller',
          blocks: [
            { kind: 'paragraph', text: 'The controller is:' },
            {
              kind: 'address',
              lines: [
                'Rodrigue Bruppacher',
                'Rue des Champs-de-Tabac 12',
                '1950 Sion',
                'Switzerland',
                'contact@kivou.eu',
              ],
            },
          ],
        },
        {
          title: '2. Scope',
          blocks: [
            {
              kind: 'paragraph',
              text: 'This Policy describes personal data processing when you visit `kivou.eu`, create or use a Kivou account, configure targeting, review or rate signals, manage a subscription, receive an alert or contact Kivou.',
            },
            {
              kind: 'paragraph',
              text: 'Information relating only to a legal entity is not always personal data. It may become personal data where it identifies an individual, such as a self-employed person, sole trader or named professional contact.',
            },
          ],
        },
        {
          title: '3. Data processed',
          blocks: [
            { kind: 'paragraph', text: 'Depending on your use, Kivou may process:' },
            {
              kind: 'list',
              items: [
                'account and organisation data: email address, company name, language, technical identifiers and protected authentication data;',
                'targeting data you provide: offer, sectors, territories, thresholds and ICP preferences;',
                'SaaS usage data: signals reviewed or unlocked, feedback, contacted status, preferences and alert cadence;',
                'billing data: plan, subscription status, currency, Stripe references and information needed to manage the commercial relationship;',
                'support and communication data you choose to send;',
                'technical security and operational data, such as session identifiers, timestamps and logs required to protect and operate the Service;',
                'public-source data concerning contracts, organisations and, where the source contains it, individuals acting in a professional capacity;',
                'signup origin references when a Kivou attribution link is used.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Kivou does not normally receive your full payment card number or security code. Stripe processes those data.',
            },
          ],
        },
        {
          title: '4. Purposes and legal grounds',
          blocks: [
            { kind: 'paragraph', text: 'Kivou processes data as needed to:' },
            {
              kind: 'list',
              items: [
                'create, secure and administer accounts;',
                'deliver the Service, personalise the feed according to the ICP and preserve requested actions;',
                'provide Discovery, subscriptions, billing and support;',
                'send configured alerts and transactional messages;',
                'prevent abuse, diagnose incidents and improve product reliability;',
                'measure activation and product use through limited technical events;',
                'comply with legal, accounting and tax obligations and establish or defend legal claims;',
                'answer requests sent to Kivou.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Where the GDPR applies, processing relies, as appropriate, on performance of a contract or pre-contractual steps, compliance with a legal obligation, Kivou’s legitimate interests in securing and improving the Service, or consent where it is actually requested. Kivou does not claim consent as a legal ground where no real consent mechanism is provided.',
            },
          ],
        },
        {
          title: '5. Public sources, analysis and automated decisions',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou analyses lawfully accessible information, including public procurement notices and documents. The product distinguishes public-source facts from plausible commercial needs inferred from those facts.',
            },
            {
              kind: 'paragraph',
              text: 'Signal ranking and matching help professionals organise prospecting. Kivou is not designed to make decisions about individuals that produce legal or similarly significant effects.',
            },
          ],
        },
        {
          title: '6. Cookies and local storage',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou uses mechanisms required for authentication and journey continuity:',
            },
            {
              kind: 'list',
              items: [
                '`kivou_session`, an HTTP-only session cookie, secure in production and limited to the configured session duration;',
                '`kivou_attribution`, a first-party HTTP-only cookie limited to signup after a Kivou attribution link is opened and expiring according to the signed link duration.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'Kivou does not use third-party advertising cookies in this version of the Service. The attribution cookie is not used to personalise advertising; it links a Kivou link to a signup in order to measure its origin.',
            },
          ],
        },
        {
          title: '7. Recipients and providers',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Data are available only to people and providers that need them to deliver, secure or administer the Service, including:',
            },
            {
              kind: 'list',
              items: [
                'Infomaniak Network SA for hosting in Switzerland;',
                'Stripe for payments, subscriptions, fraud prevention and related obligations;',
                'the email provider configured by Kivou for alerts, password resets and necessary communications;',
                'authorities or professional advisers where required by law or to establish or defend legal claims.',
              ],
            },
            { kind: 'paragraph', text: 'Kivou does not sell its users’ personal data.' },
          ],
        },
        {
          title: '8. International transfers',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou’s main infrastructure is located in Switzerland. Some providers, particularly Stripe, may process data abroad. Where adequate protection is not recognised, Kivou or the relevant provider applies safeguards required by applicable law, such as recognised contractual clauses, or relies on a documented legal exception.',
            },
          ],
        },
        {
          title: '9. Retention',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou keeps data for as long as needed for the purposes described and then for periods required or permitted for accounting, tax, security, dispute resolution and the establishment or defence of claims.',
            },
            { kind: 'paragraph', text: 'The following criteria apply:' },
            {
              kind: 'list',
              items: [
                'account and usage data are retained during the active relationship, then deleted or restricted when no longer needed;',
                'billing data are retained as required by applicable accounting and tax rules;',
                'sessions expire according to the duration configured by the Service;',
                'password reset tokens expire no later than the configured deadline and are not retained in plain text;',
                'backups follow a controlled operational retention cycle and are not used to reintroduce deleted data into ordinary use.',
              ],
            },
            {
              kind: 'paragraph',
              text: 'No numeric period other than one actually configured or legally validated may be added to the page.',
            },
          ],
        },
        {
          title: '10. Security',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou applies proportionate technical and organisational measures, including encrypted communications, protected production session cookies, access controls, environment separation, secret minimisation and controlled backups. No system can guarantee absolute security.',
            },
          ],
        },
        {
          title: '11. Your rights',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Depending on applicable law, you may request access, rectification, erasure, restriction of certain processing, object to processing or receive data you provided in a portable format where that right applies. You may withdraw consent for future processing where processing actually relies on consent.',
            },
            {
              kind: 'paragraph',
              text: 'Send requests to contact@kivou.eu. Kivou may request information reasonably necessary to verify your identity and protect the relevant account.',
            },
            {
              kind: 'paragraph',
              text: 'You may also contact the Swiss Federal Data Protection and Information Commissioner and, where the GDPR applies, the competent supervisory authority in the European Economic Area.',
            },
          ],
        },
        {
          title: '12. Account deletion',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Where no self-service deletion function is available, send a request to contact@kivou.eu. Account deletion and subscription cancellation are separate operations. A deletion request does not automatically terminate a paid period immediately, and some data may be retained where required by law or to establish or defend legal claims.',
            },
          ],
        },
        {
          title: '13. Changes and contact',
          blocks: [
            {
              kind: 'paragraph',
              text: 'This Policy may change with the Service or applicable law. The update date appears at the top of the page. Privacy questions may be sent to contact@kivou.eu.',
            },
          ],
        },
      ],
    },
    {
      id: 'cgu',
      title: 'Terms of Use and Subscription',
      subsections: [
        {
          title: '1. Purpose and acceptance',
          blocks: [
            {
              kind: 'paragraph',
              text: 'These Terms govern access to the website, account creation and use, free features, paid subscriptions and use of signals, analyses and evidence provided by Kivou.',
            },
            {
              kind: 'paragraph',
              text: 'By creating an account, purchasing a subscription or using the Service, the user confirms having read and accepted these Terms.',
            },
          ],
        },
        {
          title: '2. Professional use only',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou is intended exclusively for businesses, self-employed professionals, associations, organisations and other users acting in the course of professional activities. It is not intended for consumers acting for private purposes or for minors.',
            },
            {
              kind: 'paragraph',
              text: 'A person creating an account for an organisation confirms being authorised to bind that organisation.',
            },
          ],
        },
        {
          title: '3. Service description',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou analyses information about public contracts, awards, winning companies and, where available, related documents.',
            },
            {
              kind: 'paragraph',
              text: 'The Service may provide contract facts, the identity of a winning company, dates, amounts, locations or classifications, public-source evidence, plausible commercial needs, timing supplied by the Service and matching with the user’s commercial profile.',
            },
            {
              kind: 'paragraph',
              text: 'Kivou distinguishes public facts from analysis and inference. A plausible need does not mean that a company will purchase, seek a supplier or respond to an approach. Kivou does not guarantee a contract, sale, reply, meeting, revenue or commercial result.',
            },
          ],
        },
        {
          title: '4. Public sources and verification',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Information may come from public procurement portals, official notices, public documents, registers, company websites and other lawfully accessible sources. External sources may be incomplete, corrected, delayed or inaccurate.',
            },
            {
              kind: 'paragraph',
              text: 'Where possible, Kivou keeps a link or reference to the source. Users remain responsible for verifying material information before making a decision or commercial approach. Kivou is not affiliated with source authorities or portals unless expressly stated.',
            },
          ],
        },
        {
          title: '5. Account and security',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Users provide accurate, current information, protect credentials and promptly notify Kivou of unauthorised access. Account sharing beyond plan rights is prohibited. Kivou may reasonably verify professional identity or authority.',
            },
          ],
        },
        {
          title: '6. Plans and entitlements',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou may offer a free plan and paid plans. Applicable prices, currencies, capacities, territories, profiles, history, evidence, alerts and other entitlements are only those displayed by the Service at the relevant time and confirmed during checkout.',
            },
            {
              kind: 'paragraph',
              text: 'These Terms do not promise exports, advanced filters, decision-maker search, CRM functions or any other capability that cannot actually be used in the product.',
            },
          ],
        },
        {
          title: '7. Subscription and payment',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Before confirming a paid subscription, users can review the plan, price, currency, frequency, any applicable taxes, billing information and main capabilities.',
            },
            {
              kind: 'paragraph',
              text: 'Stripe processes payments. A subscription is activated when payment is accepted and Kivou confirms activation. Kivou does not normally receive the full card number or security code.',
            },
          ],
        },
        {
          title: '8. Automatic renewal',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Unless stated otherwise before checkout, paid subscriptions are monthly and renew automatically. The user authorises Stripe and Kivou to charge the saved payment method on each due date until cancellation.',
            },
          ],
        },
        {
          title: '9. Cancellation',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Users may request or schedule cancellation through the action actually provided in the billing area or by emailing contact@kivou.eu. Cancellation takes effect on the date confirmed by the Service, generally at the end of the paid period.',
            },
            {
              kind: 'paragraph',
              text: 'Started periods are not refunded pro rata except for a billing error, an express Kivou commitment or a mandatory legal requirement. Account deletion and subscription cancellation are separate operations.',
            },
          ],
        },
        {
          title: '10. Failed payment',
          blocks: [
            {
              kind: 'paragraph',
              text: 'If payment fails or is overdue, Kivou may request an updated method, allow further attempts, limit paid features or terminate the subscription if payment is not regularised. Amounts already due remain payable.',
            },
          ],
        },
        {
          title: '11. Changes to plans',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou may change prices, plans or capacities. A change affecting an existing subscription will be communicated before taking effect and will apply no earlier than a later renewal, subject to applicable law. Users who reject it may cancel before it takes effect.',
            },
          ],
        },
        {
          title: '12. Permitted use',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Users may use information for internal professional purposes: review companies, prepare an approach, prioritise prospecting and perform their own checks.',
            },
            {
              kind: 'paragraph',
              text: 'Users remain solely responsible for commercial communications, including their content, frequency, legal basis and compliance in the recipient’s country.',
            },
          ],
        },
        {
          title: '13. Prohibited use',
          blocks: [
            { kind: 'paragraph', text: 'Users must not:' },
            {
              kind: 'list',
              items: [
                'use Kivou for unlawful, fraudulent, misleading or discriminatory purposes;',
                'present an inference as a confirmed fact;',
                'send prohibited communications or disregard an objection;',
                'harass a person or organisation;',
                'scrape or extract the database in bulk;',
                'bypass a paywall, quota or technical control;',
                'systematically resell or redistribute signals without authorisation;',
                'share access with an unauthorised person;',
                'reverse engineer, probe, disrupt or attack the infrastructure;',
                'build a competing service by copying Kivou’s proprietary data, classifications, models or presentation;',
                'use signals to make decisions about an individual that produce legal or similarly significant effects, including in employment, credit, insurance or housing.',
              ],
            },
          ],
        },
        {
          title: '14. User-provided data',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Users retain their rights in submitted information and authorise Kivou to process it as needed to provide and secure the Service, configure the commercial profile, apply preferences and improve reliability through aggregated or anonymised data. Users warrant that they may lawfully provide those data.',
            },
          ],
        },
        {
          title: '15. Availability',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou uses reasonable efforts to maintain availability and security. Interruptions may result from maintenance, updates, failures, security incidents, provider failures or events reasonably outside Kivou’s control. No specific service level is guaranteed unless separately agreed.',
            },
          ],
        },
        {
          title: '16. Suspension or closure',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou may limit, suspend or close an account for non-payment, breach, abuse, unlawful use, security risk, circumvention, legal obligations or harm to the Service or third parties. Where circumstances allow, Kivou will inform the user and provide an opportunity to remedy the issue.',
            },
          ],
        },
        {
          title: '17. No guarantee of commercial outcomes',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou does not guarantee complete public procurement coverage, absolute accuracy of external sources, a future purchase, an available budget, absence of existing suppliers, a prospect’s response, a contract, revenue or return on investment.',
            },
          ],
        },
        {
          title: '18. Liability',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Nothing limits liability that cannot lawfully be excluded, including liability for intentional misconduct or gross negligence.',
            },
            {
              kind: 'paragraph',
              text: 'To the extent permitted, Kivou is not liable for decisions based solely on a signal, errors or delays from external sources, user communications, third-party reactions, indirect loss or loss resulting from non-compliant use.',
            },
            {
              kind: 'paragraph',
              text: 'To the extent permitted, total liability arising from ordinary negligence is limited to the amount actually paid to Kivou during the twelve months before the event giving rise to the claim.',
            },
          ],
        },
        {
          title: '19. Force majeure',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou is not liable for delay or failure caused by an event reasonably outside its control, including disaster, widespread network failure, major cyberattack, government action, conflict, general strike or critical unavailability of an essential provider.',
            },
          ],
        },
        {
          title: '20. Changes to the Terms',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Kivou may amend the Terms to reflect applicable law, the Service, security, a provider change or a correction. Material changes will be communicated appropriately before taking effect. Users who reject a change may stop using the Service and cancel before it takes effect.',
            },
          ],
        },
        {
          title: '21. Governing law, jurisdiction and language',
          blocks: [
            {
              kind: 'paragraph',
              text: 'The Terms are governed by Swiss law. Subject to mandatory jurisdiction, the ordinary courts of Sion, Canton of Valais, have jurisdiction.',
            },
            {
              kind: 'paragraph',
              text: 'The French and English versions are intended to have the same meaning. If interpretation differs, the French version prevails.',
            },
          ],
        },
        {
          title: '22. Contact',
          blocks: [
            {
              kind: 'paragraph',
              text: 'Questions about the Service, a subscription or these Terms may be sent to contact@kivou.eu.',
            },
          ],
        },
      ],
    },
  ],
}

export const legalContent: Record<PublicLegalLocale, LegalPageContent> = { fr, en }
