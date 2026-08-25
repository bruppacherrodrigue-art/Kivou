# Kivou — Road to LIVE

**Statut de référence : 23 août 2026**  
**Branche de référence : `main`**  
**SHA audité : `cbcf41218635dd43c37d421895a5e842338371e3`**

## 1. Objet

Ce document fixe le chemin minimal pour mettre Kivou en production avec un SaaS client fonctionnel, fiable et commercialisable.

La priorité reste :

> **Data → Signal → SaaS transactionnel → Paiement → Livraison → Rétention**

Le travail décrit ici concerne le SaaS, son exploitation et sa mise en ligne. Il ne doit pas modifier l’Acquisition Engine, Hermes, Instantly, Apollo, le moteur de signaux ou les politiques internes de prospection.

## 2. État acquis

Les éléments suivants sont intégrés dans `main` et protégés par la CI :

- tarifs publics et paywall ;
- checkout Stripe TEST, portail, retours de paiement et récupération ;
- onboarding et gestion des profils ICP ;
- versionnement du matching et invalidation des anciennes correspondances ;
- limites territoriales appliquées côté serveur ;
- feed connecté orienté valeur commerciale ;
- détail connecté fonctionnel avec faits, inférences, preuves et feedback ;
- trois déblocages Discovery permanents ;
- préférences d’alertes ;
- alertes e-mail et réinitialisation de mot de passe câblées sur SMTP ;
- analytics produit serveur ;
- expérience publique, exemple de signal et tarifs bilingues ;
- protections des signaux verrouillés et autorité serveur de facturation.

Les chantiers SaaS nº1, nº2 et nº3 sont clôturés. Avant LIVE, Kivou doit également livrer une fiche entreprise exploitable et un dashboard connecté orienté action. Le chantier de détail connecté reste nécessaire, mais son ordonnancement doit tenir compte de ces deux priorités produit.

## 3. Règles de travail

- Partir du dernier `origin/main` et travailler sur une branche dédiée.
- Une mission = une PR ciblée ; ne pas mélanger les gates.
- Aucun push forcé, reset destructif ou écrasement de travail existant.
- Ne jamais contourner un test, une règle de sécurité ou une autorité serveur.
- Ne pas modifier les prix, droits ou actions de facturation depuis le frontend.
- Ne pas exposer de données ou fonctions de l’Acquisition Engine dans le SaaS.
- Aucun appel Instantly, Apollo, campagne, lead ou e-mail d’acquisition.
- Aucun paiement Stripe LIVE ni déploiement sans autorisation explicite.
- FR et EN doivent conserver le même niveau de certitude et les mêmes fonctions.
- Toute donnée affichée doit provenir d’un contrat existant ou d’une source juridique validée.

## 4. Gates obligatoires avant LIVE

### RTL-01 — Informations légales, contact et footer public

**Issue : [#30](https://github.com/bruppacherrodrigue-art/Kivou/issues/30)**  
**Priorité : P0-LIVE**

Créer de vraies pages publiques et indexables à partir de `docs/LEGAL_CONTENT.md` :

- `/informations-legales`, page canonique unique avec sommaire ;
- ancres accessibles `#mentions-legales`, `#confidentialite` et `#cgu` ;
- alias compatibles `/mentions-legales`, `/confidentialite` et `/cgu`, conduisant chacun à la bonne section ;
- `/contact`, avec `contact@kivou.eu` et sans formulaire ou délai de réponse inventé ;
- footer public complet : produit, compte, contact, mentions légales, confidentialité et CGU ;
- versions FR et EN cohérentes ;
- liens accessibles depuis toutes les surfaces publiques et les surfaces de paiement nécessaires ;
- tests prouvant que ces routes ne rendent pas le composant `NotFound` ;
- navigation par ancre, déplacement du focus et retour arrière vérifiés ;
- vérification finale des URL légales du portail Stripe LIVE, sans modifier LIVE avant validation.

Ne jamais inventer une identité juridique, un numéro IDE/TVA, un registre, une adresse, une durée de conservation, un sous-traitant ou une base légale.

**Gate :** les URL rendent un contenu Kivou réel, accessible et validé ; le footer permet d’atteindre chaque information ; les liens Stripe peuvent ensuite être contrôlés.

### RTL-02 — Stabiliser les tests de signature Stripe

**Issue : [#42](https://github.com/bruppacherrodrigue-art/Kivou/issues/42)**  
**Priorité : P1 urgente avant le 25 août 2026**

- supprimer la dépendance des tests à un timestamp absolu proche ;
- conserver la tolérance de sécurité Stripe inchangée ;
- conserver un test de rejet des événements trop anciens ;
- répéter les tests aux frontières temporelles ;
- ne pas modifier Stripe LIVE.

**Gate :** la suite reste déterministe quelle que soit la date d’exécution.

### RTL-03 — Sauvegardes versionnées et reproductibles

**Issue : [#39](https://github.com/bruppacherrodrigue-art/Kivou/issues/39)**  
**Priorité : P0-OPS**

- porter le runtime minimal de sauvegarde sur `main` ;
- versionner le script et les unités systemd nécessaires ;
- conserver `flock`, permissions strictes, contrôle de taille et rétention après succès ;
- vérifier les dumps avec `pg_restore --list` ;
- ne jamais journaliser l’URL de base ou son mot de passe ;
- conserver la sauvegarde staging existante de 18,9 MB ;
- effectuer un test de restauration contrôlé sur une base isolée avant LIVE.

**Gate :** un checkout propre de `main` suffit pour produire et vérifier une sauvegarde automatique.

### RTL-04 — Vérité des plans et changement d’abonnement

**Issues : [#27](https://github.com/bruppacherrodrigue-art/Kivou/issues/27) et [#29](https://github.com/bruppacherrodrigue-art/Kivou/issues/29)**  
**Priorité : P0-LIVE**

- rendre `upgrade_to` cohérent avec la vraie fenêtre d’historique de chaque plan ;
- conserver la décision côté serveur ;
- ne recommander qu’un plan qui ouvrirait réellement le signal ;
- fournir un changement Essential / Pro / Scale sans second abonnement ;
- définir devise, prorata, upgrade, downgrade et résiliation programmée ;
- isoler une configuration Stripe Portal Kivou ;
- exclure tout produit/prix extérieur au catalogue Kivou ;
- valider toutes les transitions en Stripe TEST avant toute activation LIVE.

**Gate :** aucun parcours ne promet un déblocage ou un changement de formule que le serveur et Stripe n’exécutent pas réellement.

### RTL-05 — E-mails transactionnels et alertes opérationnelles

**Priorité : P0-LIVE**

- configurer `KIVOU_PUBLIC_APP_URL` et SMTP sur l’environnement cible ;
- installer et versionner le timer `cron` ou `systemd` de `python -m signals.alerts` ;
- configurer SPF, DKIM et DMARC ;
- tester une réinitialisation de mot de passe réelle ;
- tester une alerte client réelle et ses liens profonds ;
- vérifier désinscription via les préférences, cadences, idempotence et reprise après erreur ;
- ne jamais utiliser les alertes client comme canal d’acquisition.

**Gate :** un utilisateur reçoit effectivement les e-mails attendus et peut contrôler ses préférences.

**État au 24 août 2026 : livré en PR brouillon ; validation staging en attente.**

- origine publique HTTPS, SMTP explicite, liens transactionnels FR/EN et reset
  à usage unique validés localement ;
- alertes account-scoped avec lease durable, retry borné, suppression après
  perte de droits et protection contre les doublons déterministes ;
- service et timer systemd versionnés, mais non installés sur staging ;
- aucun envoi réel, aucune écriture DNS et aucune action production effectués ;
- SPF/DKIM/DMARC et les deux messages réels restent des gates staging.

### RTL-06 — Fiche entreprise et coordonnées vérifiées

**Priorité : P0-PRODUCT**

Créer une véritable surface SaaS consacrée à l’entreprise gagnante :

- route client et navigation cohérente depuis le feed et le détail d’un signal ;
- raison sociale, pays, identifiants officiels et adresse officielle lorsqu’ils sont publiés ;
- marchés remportés et signaux du compte liés à cette entreprise ;
- téléphone, e-mail et site uniquement lorsqu’ils proviennent d’une source autorisée, vérifiée et traçable ;
- provenance, date de vérification et statut de chaque coordonnée ;
- distinction claire entre faits publics, données de registre, coordonnées vérifiées et inférences ;
- états honnêtes lorsque certaines coordonnées ne sont pas disponibles ;
- aucune coordonnée inventée ou déduite d’un format supposé ;
- aucune exposition directe de `company_research`, Apollo, Contact Discovery ou d’une donnée du moteur d’acquisition ;
- aucun contact personnel sans base, provenance et finalité produit validées.

Si le contrat SaaS actuel ne contient pas les champs nécessaires, effectuer d’abord un audit des données réellement persistées et définir le plus petit contrat API client sûr. Cette évolution appartient à la couche SaaS et ne doit pas modifier le fonctionnement du moteur de signaux.

**Gate :** depuis un signal, le client accède à une fiche entreprise concrète et peut utiliser au moins une coordonnée réellement vérifiée lorsqu’elle existe, sans confusion sur sa provenance ni fuite de données internes.

**État au 23 août 2026 :**

- **Fiche entreprise officielle : livrée en PR.**
- **Enrichissement Apollo : différé jusqu’à obtention d’un accord contractuel écrit.**

Apollo ne bloque pas le lancement du SaaS. La fiche officielle apporte déjà
une valeur concrète à partir des avis publics et des signaux Kivou accessibles ;
un enrichissement fournisseur pourra devenir une extension séparée après
validation contractuelle, produit, sécurité, provenance et coût.

**Tranche livrée en PR — fiche officielle :**

- route protégée depuis le détail d’un signal déverrouillé, avec une clé Kivou opaque ;
- identité, adresse, identifiants, site HTTPS et date d’observation issus de l’avis public lorsqu’ils sont publiés ;
- signaux liés, besoins plausibles, correspondance ICP et timing limités aux matérialisations courantes encore accessibles au compte ;
- autorisation réévaluée à chaque lecture selon le compte, le plan, Discovery, la révision ICP et l’invalidation ;
- aucune intégration Apollo, aucune donnée personnelle et aucune dépendance à l’Acquisition Engine ;
- coût fournisseur et cache fournisseur nuls pour cette tranche.

Cette tranche livre la surface et le contrat client sûrs. Elle ne transforme pas une coordonnée absente en donnée vérifiée et ne clôt donc pas, à elle seule, les futurs travaux éventuels sur des coordonnées d’organisation autorisées.

### RTL-07 — Dashboard connecté orienté action

**Priorité : P0-PRODUCT**

Créer un accueil SaaS connecté qui aide immédiatement le client à décider quoi faire :

- résumé du profil ICP actif et accès à sa modification ;
- occasions nouvelles ou prioritaires fournies dans l’ordre du serveur ;
- accès direct aux prochains signaux à examiner ;
- état Discovery ou abonnement provenant de `GET /billing/status` ;
- déblocages utilisés et restants selon les valeurs exactes du serveur ;
- statut des alertes et cadence réellement applicable ;
- actions réelles : examiner un signal, ouvrir une fiche entreprise, corriger son ciblage, gérer ses alertes ou sa formule ;
- états vide, chargement, erreur partielle et reprise ;
- aucune métrique calculée dans le navigateur lorsqu’elle exige une autorité serveur ;
- aucun MRR, campagne, lead, mailbox, taux de réponse ou indicateur interne de l’Acquisition Engine ;
- aucune carte décorative sans décision ou action associée.

Réutiliser autant que possible les API SaaS existantes. Si un agrégat manque réellement, créer un contrat account-scoped minimal et testé, sans lire ni exposer les tables internes d’acquisition.

**Gate :** après connexion, le client comprend son état, voit ce qui mérite son attention et peut atteindre sa prochaine action en un clic.

**État au 23 août 2026 : dashboard connecté livré en PR.**

La tranche livrée compose uniquement les contrats SaaS existants dans
`/app/dashboard`. Elle conserve l’ordre serveur des occasions et de tous les
ICP actifs, les valeurs Discovery exactes, l’action de facturation décidée par
le serveur, et la séparation entre activation des alertes et cadence permise
par la formule. La fiche entreprise n’est proposée qu’après le détail du
premier signal déclaré accessible par le serveur. Aucun endpoint agrégé,
calcul de priorité, contrat de la PR nº58, stockage navigateur ou accès à
l’Acquisition Engine n’est ajouté.

Les erreurs restent locales à chaque bloc et les actions conduisent aux
surfaces SaaS existantes : détail du signal, feed, fiche entreprise, ciblages,
alertes et facturation. RTL-07 ne sera déclaré terminé qu’après fusion dans
`main` et CI verte sur le SHA final de `main`.

### RTL-08 — Déploiement staging du `main` retenu

**Priorité : P0-RELEASE**

- sauvegarder avant déploiement ;
- déployer un SHA exact de `main` ;
- appliquer les migrations une seule fois avant redémarrage ;
- vérifier le SHA réellement servi ;
- exécuter le parcours complet FR et EN : inscription, onboarding, feed, détail, Discovery, paywall, checkout TEST, retour, portail, alertes, feedback et reset ;
- vérifier 1440, 1024, 768, 390 et 320 px ;
- vérifier routes publiques, routes protégées et absence de fuite d’un signal verrouillé.

**Gate :** le staging exécute le SHA audité et le parcours SaaS complet fonctionne avec les vrais services de staging.

### RTL-09 — Préflight production

**Priorité : P0-LIVE**

- configuration production distincte de staging ;
- PostgreSQL, origine autorisée, cookie `Secure`, domaine et TLS ;
- secrets Stripe LIVE, webhook Kivou, portail Kivou et URL de retour exactes ;
- décision fiscale documentée avant activation de Stripe Tax ;
- SMTP, DNS d’envoi et timer d’alertes ;
- sauvegarde et restauration validées ;
- journalisation, rotation, espace disque et surveillance minimale ;
- stratégie support et traitement manuel des incidents ;
- aucun secret ou identifiant Stripe dans le frontend, les logs ou Git.

**Gate :** checklist signée avec preuves, sans action LIVE implicite.

### RTL-10 — Mise en production et go/no-go

**Priorité : P0-LAUNCH**

- sauvegarde immédiatement avant déploiement ;
- déploiement du SHA approuvé ;
- migrations contrôlées ;
- smoke tests publics et authentifiés ;
- premier paiement LIVE uniquement avec autorisation explicite et montant contrôlé ;
- vérification de l’abonnement, des droits, du portail et du webhook ;
- surveillance renforcée après lancement ;
- décision go/no-go documentée avant le démarrage de la prospection à volume.

**Gate final :** un prospect peut créer son compte, confirmer son ICP, examiner de vrais signaux, payer, obtenir ses droits et recevoir les prochains signaux sans intervention technique.

## 5. Travaux SaaS après fermeture des gates LIVE

### SaaS-04 — Détail des signaux connectés

Refondre la hiérarchie existante sans reconstruire les contrats :

> Entreprise → montant → marché → fait vérifié → besoin plausible → correspondance ICP → timing → action → preuve → limites

### SaaS-07 — Alertes

Après l’industrialisation LIVE, améliorer uniquement l’expérience de consultation et la compréhension des cadences, sans promettre du temps réel.

### SaaS-08 — États vides, erreurs et aide

Auditer toutes les routes, conserver les données déjà chargées lors d’une erreur locale et fournir un accès support réel.

### SaaS-11 — Audit FR/EN

Contrôler route par route la parité fonctionnelle, la certitude des formulations, les formats, l’accessibilité et le responsive.

### SaaS-12 — Analytics et gate de validation

Conserver l’analytics produit serveur comme autorité. Ajouter seulement les vues et procédures nécessaires au pilotage de l’activation, des contacts, des paiements, des alertes et de la rétention.

## 6. Éléments explicitement hors de cette Road to LIVE

- modification du Signal Engine, Need Graph, matching ou scoring ;
- Hermes, Campaign Factory ou boucle d’apprentissage ;
- Apollo, Instantly, Supplier Discovery, Contact Discovery ou Company Research ;
- landings outbound contextualisées ;
- CRM complet, application mobile et collaboration avancée ;
- export et filtres non exerçables ;
- dashboard décoratif ;
- correction de la course `personalization_service` de l’issue #33 dans une mission SaaS.

## 7. Contrôles minimaux de chaque PR

Backend, si concerné :

```bash
uv run ruff check .
uv run pytest
```

Frontend, si concerné :

```bash
cd frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

Git et livraison :

```bash
git diff --check
git status --short
```

Chaque compte rendu doit fournir le SHA de départ, les fichiers modifiés, les validations exécutées, le résultat de la CI, le SHA déployé le cas échéant et les limites restantes.
