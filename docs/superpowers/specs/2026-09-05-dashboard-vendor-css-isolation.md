# Isolation du CSS vendor du dashboard

## Contexte et décision

La PR4 a déplacé l'ancienne surface de référence vers `presentation/dashboard/` sans préserver entièrement son isolation PostCSS. Tailwind v4 a alors émis son preflight, son thème et ses utilitaires dans le bundle global. Le premier correctif a supprimé le preflight pour protéger le marketing, mais a aussi retiré des règles attendues par la sidebar, la navigation et le bandeau plan.

Cette PR **rétablit le mécanisme antérieur à PR4** : le CSS vendor du dashboard est compilé dans une entrée distincte puis chaque sélecteur est préfixé sous `html[data-kivou-surface="dashboard"]`. Ce n'est pas une nouvelle architecture. La séparation de cette entrée et son préfixage sont un invariant ; un futur déplacement de fichiers ne doit jamais les supprimer.

## Construction CSS

`presentation/dashboard/dashboard-vendor.css` contient uniquement les imports Tailwind, `tw-animate-css` et shadcn. Son premier commentaire indique :

> préfixé sous html[data-kivou-surface=dashboard] par le plugin PostCSS ; ne jamais importer globalement

Le plugin PostCSS reconnaît cette entrée par son nom, après expansion par Tailwind, et préfixe toutes ses règles ordinaires. Il transforme `:root` et `html` en racine de surface, `body` en descendant de cette racine, préserve les sélecteurs déjà préfixés et ne préfixe pas les étapes internes des `@keyframes`. `app-shell.css` ne contient plus aucun import vendor. `main.tsx` charge l'entrée vendor séparément avant `app-shell.css`.

## Variables

Les variables génériques consommées par plusieurs feuilles (`--canvas`, `--surface`, `--surface-subtle`, `--container`, couleurs, bordures et typographies associées) possèdent une valeur de base dans `tokens.css/:root`. `marketing.css` et `app-shell.css` gardent leurs valeurs propres comme surcharges sous `html[data-kivou-surface="public"]` et `html[data-kivou-surface="dashboard"]`. Une page sans surface conserve ainsi des valeurs valides, sans permettre à une surface d'en recolorer une autre.

## Contrats automatisés

Un test construit réellement le frontend et analyse le CSS produit. Il échoue si le preflight ou les utilitaires `.container`, `.grid`, `.flex`, `.hidden`, `.absolute` et `.w-full` apparaissent sans le préfixe dashboard. Il échoue aussi si aucune règle vendor préfixée n'est présente. Les keyframes et déclarations `@font-face`, qui ne sont pas des sélecteurs de surface, restent autorisées.

Les tests fonctionnels vérifient que la sidebar, le bandeau plan et la navigation `/app` sont rendus. Les goldens desktop 1440 px et mobile 390 px couvrent accueil, tarifs, légal, login, signup, onboarding, Aujourd'hui, Signaux et Entreprises. Les surfaces publiques sont contrôlées visuellement contre `83ffc7b`; les surfaces dashboard contre `7365d92`. Les différences de contenu intentionnelles postérieures à ces SHA sont distinguées des différences de style.

## Livraison

La PR reste limitée à la configuration PostCSS, aux feuilles CSS, aux tests et aux goldens correspondants. Après une CI verte, son SHA explicite est déployé sur staging par `kivou-deploy.sh`, puis les neuf routes sont recapturées et la présence des composants `/app` est vérifiée dans Chromium.
