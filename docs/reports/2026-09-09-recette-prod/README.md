# Recette production — 9 septembre 2026

SHA déployé par `ops/bin/kivou-deploy.sh` :

- staging : `1300e731303f2f258563b1bf664f6e6bfe0924d7`, readiness port 8000 OK ;
- production : `1300e731303f2f258563b1bf664f6e6bfe0924d7`, readiness port 8000 OK.

## Contrats réels

`GET /dashboard` production, avec le compte de recette : 200, trois cartes ;
les trois phrases utilisent le repli canonique et aucune ne contient
`peut concerner votre activité` ou `attribué le`.

Une tentative ciblée du job a été acceptée par SMTP (`result=sent`,
`signals=1`, `detail=smtp_submission_accepted`), mais le message reçu à
02:54 UTC prouve que la correction 4 n'est pas validée : il contenait encore
l'ancien texte d'événement. La preuve de contenu après correction reste à
prendre.

## Recette Playwright

Un seul contexte authentifié a couvert Aujourd'hui, son drawer, Signaux, son
drawer, Entreprises avec panneau et note, Réglages, puis déconnexion vers
Connexion. Les captures et les HTML rendus sont les fichiers de ce dossier.

Preuve DOM produite par :

```sh
for f in docs/reports/2026-09-09-recette-prod/*.html; do
  printf '%s ' "$(basename "$f")"
  rg -o '<main|data-page|Se déconnecter|complementary|textarea|Connexion' "$f" \
    | sort | uniq -c
done
```

Résultat : `today.html` et `today-drawer.html` portent `data-page` et deux
`<main>` ; `signals.html` et `signals-drawer.html` portent `data-page` et un
`<main>` ; `companies.html` porte deux `<main>` et `Se déconnecter` ;
`settings.html` porte un `<main>` et `Se déconnecter` ;
`logout-login.html` porte un `<main>` et `Connexion`.

Les corrections 1 à 3 étaient déjà présentes dans `main` via #187 et sont
confirmées ici après déploiement réel. La correction 4 reste ouverte jusqu'à
la réception vérifiée d'un mail produit par `kivou-alerts`. La correction 5
est couverte par les captures de ce dossier.
