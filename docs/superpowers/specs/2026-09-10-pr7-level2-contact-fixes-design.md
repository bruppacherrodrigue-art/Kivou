# PR7 — corrections du contact niveau 2

Le fournisseur reste identifié par son SIREN. La découverte du domaine et la résolution Apollo
sont deux résultats indépendants : une cible possédant un domaine reste exploitable même si Apollo
ne connaît pas son organisation. Apollo est tenté en niveau 1 lorsqu'un binding existe ; sinon le
runtime passe directement au niveau 2.

Un domaine Serper est accepté seulement s'il n'appartient ni au secteur public français ni à un
annuaire, et si au moins un mot significatif de la raison sociale apparaît dans le domaine ou dans
le titre du résultat. Le niveau 2 charge l'accueil et au plus une page de contact. Il collecte les
adresses dans l'ordre suivant : liens `mailto:`, adresses littérales du texte nettoyé, puis sélection
par le modèle parmi ces faits publiés. Le modèle reçoit `max_tokens=1000` et retourne strictement
`{email, dirigeant, confiance}`. L'adresse doit appartenir au domaine du site ou à un domaine mail
explicitement cohérent avec lui, puis posséder un MX. Un formulaire seul produit le motif
`pas d'adresse publiée`.

Le dirigeant vient exclusivement de Recherche d'entreprises. Seuls gérant, président, directeur
général et variantes opérationnelles sont conservés ; les commissaires aux comptes sont exclus.
Les compteurs du replay distinguent domaine valide, binding Apollo, contacts niveau 1 et niveau 2,
validation MX et chaque motif d'écart. Le timer reste arrêté et aucun message n'est envoyé.

