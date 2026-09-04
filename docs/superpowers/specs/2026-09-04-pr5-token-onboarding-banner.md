# PR5 — jeton, onboarding et bandeaux

## Résultat attendu

Le lien d'un cold mail ouvre un compte Découverte sur le signal effectivement choisi par le decision engine. Ce compte peut lire ce signal et au plus cinq signaux voisins de même zone et secteur, sans consommer son quota. Un bandeau explique que le profil cible est provisoire et mène à une confirmation en une page. Après confirmation, le profil est actif, le feed est matérialisé et Aujourd'hui est non vide.

## Contrats

- Le runtime reconstruit toujours `AttributionTokenPayload.opportunity_key` depuis le `signal_ref` de l'opportunité sélectionnée. Le champ reste facultatif à la vérification pour accepter les anciens jetons, qui arrivent sur `/app/signals`.
- Au clic, le backend crée le profil brouillon puis matérialise une copie propre au compte du signal promis et jusqu'à cinq voisins partageant pays/zone et CPV/secteur. Ces accès provisoires sont explicitement enregistrés et ne débitent pas une ouverture Discovery.
- `/a/{token}` redirige vers `/app/signals/{signal_key}` quand la promesse est matérialisable. Aucun signal appartenant à un autre compte n'est exposé directement.
- Le journal d'atterrissage conserve uniquement l'empreinte SHA-256 du jeton, jamais le jeton brut, ainsi que compte, opportunité, signal principal et horodatages du clic, de l'ouverture du signal, du début/achèvement de confirmation et du premier dashboard non vide.
- L'onboarding propose une page : zones multiples, secteur CPV lisible et phrase « Ce que vous vendez ». Il met à jour le profil brouillon existant au lieu d'en créer un second.
- `GET /dashboard` est l'unique contrat du shell pour `profile` et `plan`. `profile` contient `name`, `sector_label`, `zone_labels`; `plan` contient `name`, `opened`, `quota`, `period_end`.

## Interface

Le tableau Signaux montre, tant que le profil est brouillon : « Ces signaux viennent d'un profil provisoire. Confirmez-le en 30 secondes pour recevoir les vôtres. » et « Confirmer mon profil ». Après confirmation, ce bandeau disparaît. La redirection vers Aujourd'hui porte l'état de première activation et affiche « Vos premiers signaux ».

## Validation

Tests hors ligne ciblés puis suite décisionnelle unique : émission runtime, clic, bon drawer et six accès maximum, confirmation, dashboard non vide et top 3 cohérent; contrats dashboard et shell; onboarding et bandeaux. Le staging est déployé avec `ops/bin/kivou-deploy.sh`; le parcours chronométré doit rester sous 60 secondes.
