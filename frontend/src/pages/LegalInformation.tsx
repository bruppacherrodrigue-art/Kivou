import { Fragment } from 'react'
import { PublicPageMeta } from '../components/PublicPageMeta'


type Block =
  | { kind: "paragraph"; text: string }
  | { kind: "address"; lines: string[] }
  | { kind: "list"; items: string[] };
type LegalSection = {
  id: string;
  title: string;
  subsections: { title: string; blocks: Block[] }[];
};

const sections: LegalSection[] = [
  {
    "id": "mentions-legales",
    "title": "Mentions légales",
    "subsections": [
      {
        "title": "Éditeur du service",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Le site Internet Kivou et le service logiciel accessible depuis le domaine `kivou.eu`, ci-après le « Service », sont édités et exploités par :"
          },
          {
            "kind": "address",
            "lines": [
              "Rodrigue Bruppacher",
              "Rue des Champs-de-Tabac 12",
              "1950 Sion",
              "Suisse"
            ]
          },
          {
            "kind": "paragraph",
            "text": "Adresse électronique : contact@kivou.eu"
          }
        ]
      },
      {
        "title": "Hébergement",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Le Service est hébergé en Suisse par :"
          },
          {
            "kind": "address",
            "lines": [
              "Infomaniak Network SA",
              "Rue Eugène Marziano 25",
              "1227 Les Acacias (GE)",
              "Suisse"
            ]
          },
          {
            "kind": "paragraph",
            "text": "L’infrastructure principale, la base de données et les services applicatifs de Kivou sont exploités sur une infrastructure située en Suisse. Certains prestataires nécessaires, notamment Stripe pour les paiements, peuvent traiter des données dans d’autres pays conformément à leurs propres engagements et aux garanties applicables."
          }
        ]
      },
      {
        "title": "Propriété intellectuelle",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Le nom Kivou, le logiciel, l’interface, les textes, les éléments graphiques, les compilations, classifications, analyses, modèles de données et méthodes propres au Service sont protégés par les droits applicables. Les documents et informations provenant de tiers restent soumis aux droits et conditions de leurs sources respectives."
          }
        ]
      },
      {
        "title": "Contact éditorial",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Toute question concernant le site ou son contenu peut être envoyée à contact@kivou.eu."
          }
        ]
      }
    ]
  },
  {
    "id": "confidentialite",
    "title": "Politique de confidentialité",
    "subsections": [
      {
        "title": "1. Responsable du traitement",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Le responsable du traitement est :"
          },
          {
            "kind": "address",
            "lines": [
              "Rodrigue Bruppacher",
              "Rue des Champs-de-Tabac 12",
              "1950 Sion",
              "Suisse",
              "contact@kivou.eu"
            ]
          }
        ]
      },
      {
        "title": "2. Champ d’application",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Cette politique décrit le traitement des données personnelles effectué lorsque vous visitez `kivou.eu`, créez ou utilisez un compte Kivou, configurez votre ciblage, consultez ou évaluez des signaux, gérez un abonnement, recevez une alerte ou contactez Kivou."
          },
          {
            "kind": "paragraph",
            "text": "Les informations concernant uniquement une personne morale ne sont pas toujours des données personnelles. Elles peuvent cependant le devenir lorsqu’elles identifient une personne physique, par exemple un indépendant, un titulaire d’entreprise individuelle ou un interlocuteur nommé."
          }
        ]
      },
      {
        "title": "3. Données traitées",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Selon votre utilisation, Kivou peut traiter :"
          },
          {
            "kind": "list",
            "items": [
              "les données de compte et d’organisation : adresse électronique, nom d’entreprise, langue, identifiants techniques et données d’authentification protégées ;",
              "les données de ciblage commercial que vous fournissez : offre, secteurs, territoires, seuils et préférences ICP ;",
              "les données d’usage du SaaS : signaux consultés ou débloqués, notes, préférences et cadence d’alertes ;",
              "les données de facturation : plan, état d’abonnement, devise, références Stripe et informations nécessaires au suivi de la relation commerciale ;",
              "les données de support et de communication que vous choisissez de transmettre ;",
              "des données techniques de sécurité et d’exploitation, telles que des identifiants de session, horodatages et journaux nécessaires à la protection et au fonctionnement du Service ;",
              "des données provenant de sources publiques sur des marchés, organisations et, lorsque la source le contient, personnes agissant dans un cadre professionnel ;",
              "les références d’origine d’une inscription lorsqu’un lien d’attribution Kivou est utilisé."
            ]
          },
          {
            "kind": "paragraph",
            "text": "Kivou ne reçoit normalement pas le numéro complet de votre carte ni son code de sécurité. Ces données sont traitées par Stripe."
          }
        ]
      },
      {
        "title": "4. Finalités et fondements",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou traite les données nécessaires pour :"
          },
          {
            "kind": "list",
            "items": [
              "créer, sécuriser et administrer le compte ;",
              "exécuter le Service, personnaliser le feed selon le profil ICP et conserver les actions demandées ;",
              "fournir Discovery, les abonnements, la facturation et le support ;",
              "envoyer les alertes et messages transactionnels configurés ;",
              "prévenir les abus, diagnostiquer les incidents et améliorer la fiabilité du produit ;",
              "mesurer l’activation et l’usage du produit au moyen d’événements techniques limités ;",
              "respecter les obligations légales, comptables, fiscales et de défense de droits ;",
              "répondre aux demandes envoyées à Kivou."
            ]
          },
          {
            "kind": "paragraph",
            "text": "Lorsque le RGPD s’applique, ces traitements reposent, selon le cas, sur l’exécution du contrat ou de mesures précontractuelles, le respect d’une obligation légale, les intérêts légitimes de Kivou à sécuriser et améliorer son service, ou le consentement."
          }
        ]
      },
      {
        "title": "5. Sources publiques, analyses et décisions automatisées",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou analyse des informations légalement accessibles, notamment des avis et documents relatifs aux marchés publics. Le produit distingue les faits issus de sources publiques des besoins commerciaux plausibles inférés à partir de ces faits."
          },
          {
            "kind": "paragraph",
            "text": "Le classement ou la correspondance d’un signal avec un profil commercial aide un professionnel à organiser sa prospection. Kivou n’est pas conçu pour prendre à l’égard d’une personne physique une décision automatisée produisant des effets juridiques ou comparables."
          }
        ]
      },
      {
        "title": "6. Cookies et stockage local",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou utilise des mécanismes strictement nécessaires à la connexion et à la continuité des parcours :"
          },
          {
            "kind": "list",
            "items": [
              "`kivou_session`, cookie HTTP-only de session, sécurisé en production et limité à la durée de la session configurée ;",
              "`kivou_attribution`, cookie HTTP-only de première partie, limité au parcours d’inscription après l’ouverture d’un lien d’attribution Kivou et expirant selon la durée du lien signé."
            ]
          },
          {
            "kind": "paragraph",
            "text": "Kivou n’utilise aucun cookie publicitaire tiers dans cette version du Service. Le cookie d’attribution ne sert pas à personnaliser de la publicité ; il relie un lien Kivou à une inscription afin d’en mesurer l’origine."
          }
        ]
      },
      {
        "title": "7. Destinataires et prestataires",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Les données sont accessibles uniquement aux personnes et prestataires qui en ont besoin pour fournir, sécuriser ou administrer le Service, notamment :"
          },
          {
            "kind": "list",
            "items": [
              "Infomaniak Network SA pour l’hébergement en Suisse ;",
              "Stripe pour le paiement, l’abonnement, la prévention de la fraude et les obligations associées ;",
              "le prestataire de messagerie configuré par Kivou pour les alertes, la réinitialisation de mot de passe et les communications nécessaires ;",
              "les autorités ou conseils professionnels lorsque la loi ou la défense de droits l’exige."
            ]
          },
          {
            "kind": "paragraph",
            "text": "Kivou ne vend pas les données personnelles de ses utilisateurs."
          }
        ]
      },
      {
        "title": "8. Transferts internationaux",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "L’infrastructure principale de Kivou est située en Suisse. Certains prestataires, en particulier Stripe, peuvent traiter des données à l’étranger. Lorsqu’une protection adéquate n’est pas reconnue, Kivou ou le prestataire concerné applique les garanties requises par le droit applicable, telles que des clauses contractuelles reconnues, ou s’appuie sur une exception légale documentée."
          }
        ]
      },
      {
        "title": "9. Durées de conservation",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou conserve les données pendant la durée nécessaire aux finalités décrites, puis pendant les périodes imposées ou permises pour la comptabilité, la fiscalité, la sécurité, la résolution de litiges et la défense de droits."
          },
          {
            "kind": "paragraph",
            "text": "Les critères suivants s’appliquent :"
          },
          {
            "kind": "list",
            "items": [
              "les données de compte et d’usage sont conservées pendant la relation active, puis supprimées ou limitées lorsque leur conservation n’est plus nécessaire ;",
              "les données de facturation sont conservées selon les obligations comptables et fiscales applicables ;",
              "les sessions expirent selon la durée configurée par le Service ;",
              "un jeton de réinitialisation de mot de passe expire au plus tard à l’échéance configurée et n’est pas conservé en clair ;",
              "les sauvegardes suivent un cycle de rétention opérationnel contrôlé et ne servent pas à réintroduire des données supprimées dans l’usage courant."
            ]
          }
        ]
      },
      {
        "title": "10. Sécurité",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou met en œuvre des mesures techniques et organisationnelles proportionnées, notamment le chiffrement des communications, des cookies de session protégés en production, des contrôles d’accès, la séparation des environnements, la limitation des secrets et des sauvegardes contrôlées. Aucun système ne peut toutefois garantir une sécurité absolue."
          }
        ]
      },
      {
        "title": "11. Vos droits",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Selon le droit applicable, vous pouvez demander l’accès à vos données, leur rectification, leur suppression, la limitation de certains traitements, vous opposer à un traitement ou recevoir les données que vous avez fournies dans un format portable lorsque ce droit s’applique. Vous pouvez retirer un consentement pour l’avenir lorsqu’un traitement repose effectivement sur celui-ci."
          },
          {
            "kind": "paragraph",
            "text": "Adressez votre demande à contact@kivou.eu. Kivou peut demander les éléments raisonnablement nécessaires pour vérifier votre identité et protéger le compte concerné."
          },
          {
            "kind": "paragraph",
            "text": "Vous pouvez également saisir le Préposé fédéral à la protection des données et à la transparence (PFPDT) et, lorsque le RGPD s’applique, l’autorité de contrôle compétente dans l’Espace économique européen."
          }
        ]
      },
      {
        "title": "12. Suppression du compte",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "En l’absence de fonction de suppression en libre-service, une demande peut être envoyée à contact@kivou.eu. La suppression du compte et la résiliation d’un abonnement sont deux opérations distinctes. Une demande de suppression ne vaut pas automatiquement résiliation immédiate d’une période payée, et certaines données peuvent être conservées lorsque la loi ou la défense de droits l’exige."
          }
        ]
      },
      {
        "title": "13. Modifications et contact",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Cette politique peut évoluer avec le Service ou le droit applicable. La date de mise à jour est indiquée en tête de page. Pour toute question relative aux données personnelles : contact@kivou.eu."
          }
        ]
      }
    ]
  },
  {
    "id": "cgu",
    "title": "Conditions générales d’utilisation et d’abonnement",
    "subsections": [
      {
        "title": "1. Objet et acceptation",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Les présentes Conditions régissent l’accès au site, la création et l’utilisation d’un compte, les fonctionnalités gratuites, les abonnements payants et l’utilisation des signaux, analyses et preuves fournis par Kivou."
          },
          {
            "kind": "paragraph",
            "text": "En créant un compte, en souscrivant un abonnement ou en utilisant le Service, l’utilisateur confirme avoir lu et accepté les présentes Conditions."
          }
        ]
      },
      {
        "title": "2. Service réservé aux professionnels",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou est destiné exclusivement aux entreprises, indépendants, associations, organismes et autres utilisateurs agissant dans le cadre de leur activité professionnelle. Le Service n’est pas destiné aux consommateurs agissant à des fins privées ni aux mineurs."
          },
          {
            "kind": "paragraph",
            "text": "La personne qui crée un compte au nom d’une organisation confirme être autorisée à engager cette organisation."
          }
        ]
      },
      {
        "title": "3. Description du Service",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou analyse notamment des informations relatives aux marchés publics, aux adjudications, aux entreprises gagnantes et, lorsque disponibles, aux documents associés."
          },
          {
            "kind": "paragraph",
            "text": "Le Service peut fournir des faits relatifs à un marché, l’identité d’une entreprise gagnante, des dates, montants, lieux ou classifications, des preuves issues de sources publiques, des besoins commerciaux plausibles, un timing fourni par le Service et une correspondance avec le profil commercial défini par l’utilisateur."
          },
          {
            "kind": "paragraph",
            "text": "Kivou distingue les faits publics des analyses et inférences. Un besoin plausible ne signifie pas qu’une entreprise effectuera un achat, recherchera un fournisseur ou répondra à une sollicitation. Kivou ne garantit aucun contrat, vente, réponse, rendez-vous, chiffre d’affaires ou résultat commercial."
          }
        ]
      },
      {
        "title": "4. Sources publiques et vérification",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Les informations peuvent provenir de portails de marchés publics, avis officiels, documents publics, registres, sites d’entreprises ou autres sources accessibles légalement. Les sources externes peuvent être incomplètes, corrigées, retardées ou erronées."
          },
          {
            "kind": "paragraph",
            "text": "Kivou conserve autant que possible un lien ou une référence vers la source. L’utilisateur reste responsable de vérifier les informations essentielles avant une décision ou une démarche commerciale. Kivou n’est pas affilié aux administrations ou portails sources, sauf indication expresse."
          }
        ]
      },
      {
        "title": "5. Compte et sécurité",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "L’utilisateur fournit des informations exactes et à jour, protège ses identifiants et informe rapidement Kivou de tout accès non autorisé. Le partage d’un compte au-delà des droits du plan est interdit. Kivou peut demander une vérification raisonnable de l’identité professionnelle ou de l’autorité de l’utilisateur."
          }
        ]
      },
      {
        "title": "6. Plans et droits",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou peut proposer un plan gratuit et des plans payants. Les prix, devises, capacités, territoires, profils, historique, preuves, alertes et autres droits applicables sont uniquement ceux affichés par le Service au moment considéré et confirmés pendant la commande."
          }
        ]
      },
      {
        "title": "7. Souscription et paiement",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Avant de confirmer un abonnement payant, l’utilisateur peut vérifier le plan, le prix, la devise, la périodicité, les taxes éventuellement applicables, les informations de facturation et les capacités principales."
          },
          {
            "kind": "paragraph",
            "text": "Les paiements sont traités par Stripe. L’abonnement est activé lorsque le paiement est accepté et que Kivou confirme son activation. Kivou ne reçoit normalement pas le numéro complet de la carte ni son code de sécurité."
          }
        ]
      },
      {
        "title": "8. Renouvellement automatique",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Sauf indication contraire avant la commande, les abonnements payants sont mensuels et se renouvellent automatiquement. L’utilisateur autorise Stripe et Kivou à débiter le moyen de paiement enregistré à chaque échéance jusqu’à la résiliation."
          }
        ]
      },
      {
        "title": "9. Résiliation",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "L’utilisateur peut demander ou programmer la résiliation au moyen de l’action réellement proposée dans son espace de facturation ou écrire à contact@kivou.eu. La résiliation prend effet à la date confirmée par le Service, généralement à la fin de la période déjà payée."
          },
          {
            "kind": "paragraph",
            "text": "Les périodes commencées ne sont pas remboursées au prorata, sauf erreur de facturation, engagement exprès de Kivou ou disposition impérative contraire. La suppression d’un compte et la résiliation d’un abonnement sont distinctes."
          }
        ]
      },
      {
        "title": "10. Paiement échoué",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "En cas d’échec ou de retard, Kivou peut demander la mise à jour du moyen de paiement, permettre de nouvelles tentatives, limiter l’accès aux fonctions payantes ou résilier l’abonnement si le paiement n’est pas régularisé. Les montants déjà dus restent exigibles."
          }
        ]
      },
      {
        "title": "11. Modification des offres",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou peut faire évoluer ses prix, plans ou capacités. Une modification applicable à un abonnement existant est communiquée avant son entrée en vigueur et s’applique au plus tôt lors d’un renouvellement ultérieur, sous réserve du droit applicable. L’utilisateur qui la refuse peut résilier avant sa prise d’effet."
          }
        ]
      },
      {
        "title": "12. Utilisation autorisée",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "L’utilisateur peut employer les informations pour ses besoins professionnels internes : examiner des entreprises, préparer une approche, prioriser sa prospection et effectuer ses propres vérifications."
          },
          {
            "kind": "paragraph",
            "text": "L’utilisateur reste seul responsable de ses communications commerciales, de leur contenu, fréquence, base juridique et conformité dans le pays du destinataire."
          }
        ]
      },
      {
        "title": "13. Utilisations interdites",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Il est interdit notamment :"
          },
          {
            "kind": "list",
            "items": [
              "d’utiliser Kivou à des fins illégales, frauduleuses, trompeuses ou discriminatoires ;",
              "de présenter une inférence comme un fait certain ;",
              "d’envoyer des communications interdites ou d’ignorer une opposition ;",
              "de harceler une personne ou une organisation ;",
              "d’extraire ou aspirer massivement la base de données ;",
              "de contourner un paywall, quota ou contrôle technique ;",
              "de revendre ou redistribuer systématiquement les signaux sans autorisation ;",
              "de partager un accès avec une personne non autorisée ;",
              "de procéder à de l’ingénierie inverse, sonder, perturber ou attaquer l’infrastructure ;",
              "de construire un service concurrent en copiant les données, classifications, modèles ou présentations propres à Kivou ;",
              "d’utiliser les signaux pour prendre à l’égard d’une personne physique une décision produisant des effets juridiques ou comparables, notamment en matière d’emploi, de crédit, d’assurance ou de logement."
            ]
          }
        ]
      },
      {
        "title": "14. Données fournies par l’utilisateur",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "L’utilisateur conserve les droits qu’il détient sur ses informations et autorise Kivou à les traiter dans la mesure nécessaire pour fournir et sécuriser le Service, configurer le profil commercial, exécuter les préférences et améliorer la fiabilité au moyen de données agrégées ou anonymisées. Il garantit être autorisé à transmettre ces données."
          }
        ]
      },
      {
        "title": "15. Disponibilité",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou met en œuvre des efforts raisonnables pour assurer la disponibilité et la sécurité du Service. Des interruptions peuvent résulter d’une maintenance, mise à jour, panne, incident de sécurité, défaillance d’un fournisseur ou événement hors du contrôle raisonnable de Kivou. Sauf engagement distinct, aucun niveau de service spécifique n’est garanti."
          }
        ]
      },
      {
        "title": "16. Suspension ou fermeture",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou peut limiter, suspendre ou fermer un compte en cas de non-paiement, violation des Conditions, abus, utilisation illicite, risque de sécurité, contournement, obligation légale ou atteinte au Service ou à des tiers. Lorsque la situation le permet, Kivou informe l’utilisateur et lui permet de remédier au problème."
          }
        ]
      },
      {
        "title": "17. Absence de garantie commerciale",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou ne garantit pas l’exhaustivité des marchés publics, l’exactitude absolue des sources externes, l’existence d’un achat futur, la disponibilité d’un budget, l’absence de fournisseurs déjà engagés, la réponse d’un prospect, un contrat, un chiffre d’affaires ou un retour sur investissement."
          }
        ]
      },
      {
        "title": "18. Responsabilité",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Aucune disposition ne limite une responsabilité qui ne peut légalement être exclue, notamment en cas de faute intentionnelle ou grave."
          },
          {
            "kind": "paragraph",
            "text": "Dans la mesure permise, Kivou n’est pas responsable des décisions prises sur la seule base d’un signal, des erreurs ou retards d’une source externe, des communications envoyées par l’utilisateur, de la réaction d’un tiers, des pertes indirectes ou des pertes résultant d’un usage non conforme."
          },
          {
            "kind": "paragraph",
            "text": "Dans la mesure permise, la responsabilité totale résultant d’une faute légère est limitée au montant effectivement payé à Kivou au cours des douze mois précédant l’événement à l’origine de la demande."
          }
        ]
      },
      {
        "title": "19. Force majeure",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou n’est pas responsable d’un retard ou d’une inexécution résultant d’un événement échappant raisonnablement à son contrôle, notamment une catastrophe, panne générale de réseau, cyberattaque majeure, décision d’autorité, conflit, grève générale ou indisponibilité critique d’un fournisseur essentiel."
          }
        ]
      },
      {
        "title": "20. Modification des Conditions",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Kivou peut modifier les Conditions pour tenir compte du droit, du Service, de la sécurité, d’un fournisseur ou d’une correction. Les changements importants sont communiqués par un moyen approprié avant leur entrée en vigueur. En cas de refus, l’utilisateur peut cesser d’utiliser le Service et résilier avant leur prise d’effet."
          }
        ]
      },
      {
        "title": "21. Droit applicable, juridiction et langue",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Les Conditions sont régies par le droit suisse. Sous réserve des fors impératifs, les tribunaux ordinaires de Sion, canton du Valais, sont compétents."
          },
          {
            "kind": "paragraph",
            "text": "Les versions française et anglaise visent le même sens. En cas de divergence d’interprétation, la version française prévaut."
          }
        ]
      },
      {
        "title": "22. Contact",
        "blocks": [
          {
            "kind": "paragraph",
            "text": "Toute question relative au Service, à un abonnement ou aux présentes Conditions peut être envoyée à contact@kivou.eu."
          }
        ]
      }
    ]
  }
];

function InlineText({ text }: { text: string }) {
  return <>{text.split(/(`[^`]+`|contact@kivou\.eu)/g).map((part, index) => {
    if (part === "contact@kivou.eu") return <a href="mailto:contact@kivou.eu" key={index}>{part}</a>;
    if (part.startsWith("`") && part.endsWith("`")) {
      const value = part.slice(1, -1);
      return value === "kivou.eu" ? <a href="https://kivou.eu" key={index}>{value}</a> : <code key={index}>{value}</code>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  })}</>;
}

function LegalBlock({ block }: { block: Block }) {
  if (block.kind === "paragraph") return <p><InlineText text={block.text} /></p>;
  if (block.kind === "address") return <address>{block.lines.map((line, index) => <Fragment key={line}>{index > 0 && <br />}{line}</Fragment>)}</address>;
  return <ul>{block.items.map((item) => <li key={item}><InlineText text={item} /></li>)}</ul>;
}

export function LegalInformation() {
  return (
    <>
      <PublicPageMeta
        title="Informations légales et contractuelles | Kivou"
        description="Consultez les mentions légales, la politique de confidentialité et les Conditions générales de Kivou."
        canonicalPath="/informations-legales"
      />
      <main id="main" tabIndex={-1}>
        <header className="legal-hero container">
          <p className="eyebrow">INFORMATIONS PUBLIQUES</p>
          <h1>Informations légales et contractuelles</h1>
          <p className="lead">Cette page regroupe les mentions légales, la politique de confidentialité et les Conditions générales d’utilisation et d’abonnement de Kivou.</p>
          <p className="legal-updated">Dernière mise à jour : 26 août 2026</p>
        </header>
        <div className="container legal-layout">
          <nav className="glass legal-toc" id="sommaire" aria-label="Sommaire juridique">
            <strong>Sommaire juridique</strong>
            <ol><li><a href="#mentions-legales">Mentions légales</a></li><li><a href="#confidentialite">Confidentialité</a></li><li><a href="#cgu">Conditions générales</a></li></ol>
          </nav>
          <article className="legal-content">
            {sections.map((section, index) => (
              <section className="legal-section" id={section.id} tabIndex={-1} key={section.id}>
                <span className="legal-number">{String(index + 1).padStart(2, "0")}</span>
                <h2>{section.title}</h2>
                {section.subsections.map((subsection) => (
                  <div className="legal-subsection" key={subsection.title}>
                    <h3>{subsection.title}</h3>
                    {subsection.blocks.map((block, blockIndex) => <LegalBlock block={block} key={blockIndex} />)}
                  </div>
                ))}
                <a className="back-top" href="#sommaire">Retour au sommaire ↑</a>
              </section>
            ))}
          </article>
        </div>
      </main>
    </>
  );
}
