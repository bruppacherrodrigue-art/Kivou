# PR4 — Aujourd’hui et vocabulaire produit

## But

Faire de `/app` l’écran d’action quotidien de Kivou : résumer les nouveaux signaux, permettre d’ouvrir ou d’ignorer les trois priorités, rappeler les titulaires déjà contactés et afficher l’activité de la semaine, sans défilement à 1280 × 800.

## Contrat de page

`TodayDashboard` lit `GET /dashboard`, le profil cible actif et les informations de plan déjà chargées par le shell. Une première visite affiche « Vos premiers signaux » ; sinon le titre reprend `new_since_last_visit` et le jour local de `last_seen_at`. Le sous-titre associe `strong_matches`, le nom du profil actif et ses zones. Une donnée absente est rendue « — ».

Les trois cartes utilisent les cartes signal complètes de `top3`. Elles montrent titulaire, `MatchDots`, objet tronqué sur une ligne, montant, lieu, date et la première raison de `analysis.fit.reasons`. « Ouvrir » superpose `SignalDrawer`. « Ignorer » envoie `PUT /signals/{key}/feedback` avec `relevance=not_relevant`, retire immédiatement la carte et recharge le dashboard afin que le signal prioritaire suivant la remplace. L’erreur restaure la carte et reste visible.

Sans carte, la page explique qu’aucun nouveau signal prioritaire n’attend et renvoie vers `/app/signals`. Les listes inférieures affichent `to_follow_up` avec un lien vers `/app/companies/{key}` et les quatre compteurs `week`. Elles se placent côte à côte sur bureau et s’empilent sur petit écran.

## Shell et vocabulaire

La navigation devient, dans cet ordre : Aujourd’hui, Signaux, Entreprises, Profil cible, Alertes, Réglages. Le bandeau inférieur résume « Plan {nom} · {ouverts}/{quota} signaux ce mois · {secteur} · {zones} ». Les textes visibles du shell, de la landing, des tarifs, de l’onboarding et des mails transactionnels utilisent exclusivement signal, titulaire et profil cible. Les termes bannis sont retirés lorsqu’ils portent le sens produit ; les usages linguistiques sans ce sens sont recensés plutôt que modifiés aveuglément.

## Suppression de l’ancienne référence

`frontend/src/reference/` et `dashboard-reference.css` disparaissent. Les primitives réellement utilisées sont déplacées sans changement fonctionnel vers `components/`, `hooks/`, `layouts/` ou `styles/`. La démo Phase A et son branchement par variable d’environnement sont supprimés, car aucune route publique ni lien de landing ne l’expose.

## Backend

`GET /companies/{key}` ajoute `city`, dérivée des mêmes signaux accessibles que la liste d’entreprises. Aucun autre contrat backend ne change.

## Vérification

Les anciens skips PR4 sont remplacés par des tests du bandeau, des trois cartes, du remplacement après Ignorer, des deux listes et des états vides. Les goldens Aujourd’hui bureau/mobile et le menu mobile sont régénérés. Les tests backend du profil entreprise couvrent `city`. Les suites ciblées guident l’implémentation ; une seule validation complète frontend/backend et la CI décisionnelle précèdent la fusion et le déploiement staging via `kivou-deploy.sh`.
