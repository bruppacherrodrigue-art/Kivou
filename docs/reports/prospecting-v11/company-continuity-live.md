# Entreprises : continuité des données et livraison live

## État

Implémentation locale et revues indépendantes terminées. Validation intégrée et
répétitions opérateur en cours. **Aucune activation staging ou production n'est
encore revendiquée.** Le plan HTML approuvé reste inchangé ; le complément
`docs/superpowers/plans/2026-09-14-company-continuity-live.md` suit cette livraison.

## Code et limites préservées

- Signaux et dossiers Entreprises partagent les coordonnées BOAMP attribuées au
  bon titulaire/établissement. Pas de contacts acheteur, de nouveau panneau
  Entreprise imbriqué, ni d'idée d'approche. Découverte reçoit uniquement les
  disponibilités réelles ; les valeurs premium sont retirées au serveur.
- Les demandes d'enrichissement sont durables, dédupliquées par SIREN, avec
  limite atomique de cinq demandes actives par compte et cent au total. Ce n'est
  pas un quota payant supplémentaire. Les budgets existants et les recherches
  nominatives restent distincts. Aucun fournisseur n'est appelé par un GET.
- Les résultats incomplets conservent les faits connus et leurs dates. Le dossier
  ouvert est actualisé sans perdre un brouillon de contact personnel.
- Le miroir production → staging exporte seulement les colonnes publiques
  autorisées, sans données client ni traces brutes. Il respecte les corrections,
  retraits, horloges locales et demandes de retrait. Un changement réel de domaine
  invalide seulement l'ancien rattachement Apollo et son cache devenu obsolète.
- L'annuaire se rafraîchit lorsqu'il est visible et inactif ; les filtres sont
  conservés. Les trente fixtures auditées disposent d'une quarantaine récupérable,
  par manifeste exact. Cette opération n'a pas encore été exécutée sur staging.

## Histoires et revues

La production a évolué vers `4c3bc6373e7bc2c1b24c413b6c7db523a44e15ba` pendant la
préparation. Les deux intégrations `87be689` et `b634605` conservent les évolutions
de production, dont le ciblage multi-signaux. Les migrations déjà déployées ne
sont pas réécrites. La jonction0061 conserve0058_model_call_budget et0060_boamp_notice_facts ;
0062 ajoute les demandes durables,0063 les métadonnées du miroir. Les nouvelles
migrations refusent un downgrade destructeur.

Le contrôle suivant a constaté la production sur
`543793c7df22adfa1ff96a09d91df854ff9f1cfa` (audit des SIREN dupliqués dans la
file de prospection). Cette évolution est conservée par la fusion `b2dcea8`.
La relance ciblage et contrats nginx/production a réussi **154 tests**.

Revues SPEC et qualité distinctes : raccord des migrations, contacts, demandes
durables et miroir. Les constats ont été reproduits avant correction : fraîcheur
par champ, retraits source, normalisation Decimal, révocation Apollo, brouillons,
horloge de fin réelle et pagination après changement de filtre. La vérification
supplémentaire du teaser téléphone seul a confirmé le comportement déjà correct.

## Preuves locales déjà acquises

- Frontend complet : **768 tests / 74 fichiers** ; **32 tests visuels**.
- TypeScript, ESLint, builds client et console fondateur réussis. L'avertissement
  existant de taille du bundle client reste présent ; ce n'est pas un échec de build.
- Migrations :287 pass /27 skips PostgreSQL facultatifs avant répétitions réelles.
- Contacts :43 tests ciblés relancés par l'intégrateur, tous réussis.
- Enrichissement :87 pass /1 xfail historique sur le lot élargi ;34 tests ciblés
  après la dernière correction de cache. Le lot UI de l'auteur compte30 tests.
- Miroir/quarantaine/protections opérateur :64 tests réussis après corrections.
- Copie hors réseau :24 nouveaux tests réussis, plus l'ancien helper58 pass /20
  skips PostgreSQL facultatifs. La relecture intégrateur a également été effectuée.

Les résultats qui se recouvrent ne sont pas additionnés. La première exécution
backend complète a saturé `/dev/shm` et ne constitue pas une preuve verte. Une
exécution sur `/tmp` et la CI exacte complètent la validation. L'intégration du
dernier ciblage pendant cette première collecte a aussi rendu une assertion
collectée obsolète ; le lot de ciblage frais a réussi76 tests. Le contrat nginx
a été adapté explicitement à la production V11 et à son seul alias catalogue.

La seconde suite backend, sur `/tmp`, s'est terminée avec **6 725 pass,
65 skips, 1 xfail et 2 échecs** : l'ancienne assertion nginx collectée avant sa
correction, et l'oubli du nouveau module dans l'allowlist des migrations
exhaustives. Les lots frais correspondants passent (154 tests ci-dessus ;
12 tests configuration/migration après reproduction RED et correction).
La CI `34822774471` sur `c40bae9` a réussi le frontend et trois shards backend ;
le quatrième a retrouvé uniquement cet oubli d'allowlist. Une CI complète du
candidat corrigé reste requise ; ces résultats ne sont pas présentés comme une
suite complète verte.

## Portes restantes avant activation

1. CI du candidat exact et contrôles intégrés terminés.
2. Copies PostgreSQL des deux schémas déployés, empreintes de toutes les lignes
   privées et des tables catalogue/budgets/faits existantes, migration et replay.
3. Ancien artefact réellement servi derrière le garde fermé sur la copie, puis
   retour au candidat sans downgrade ni perte des nouvelles écritures.
4. Sauvegarde retenue, configurations nginx/unités et limites fournisseurs
   vérifiées ; recette staging avant promotion du même code en production.
5. Santé, trois onglets, droits Découverte/abonnements, console fondateur et
   tâches planifiées réellement vérifiés après activation.

La production possède une clé Serper configurée ; staging n'en expose pas dans
ses fichiers d'environnement vérifiés. Le bouton d'enrichissement reste fermé par
défaut jusqu'au raccordement et à la vérification effective du worker. Aucun
budget, campagne, tarif ni volume d'envoi n'a été modifié par cette livraison.
