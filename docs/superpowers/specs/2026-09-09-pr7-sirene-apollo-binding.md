# PR7 — identité SIRENE et résolution Apollo

Le fournisseur d’une cible est identifié par son SIREN, issu de SIRENE. Le
nom légal, la ville, le code NAF, l’effectif et le domaine éventuellement
publié restent les faits de référence. Apollo n’est jamais utilisé pour
constituer le vivier d’entreprises.

`company_research` reçoit cette identité SIRENE et effectue une recherche
bornée par nom légal, ville et domaine si disponible. Le résultat est écrit
dans `sirene_apollo_binding` : SIREN, identifiant Apollo éventuel, instant,
méthode et score de confiance, avec un état `resolved` ou `unresolved`.
Une cible sans résolution est écartée. `contact_discovery` lit uniquement le
binding résolu ; il ne reçoit plus un identifiant Apollo nu. Les lignes
Apollo-first historiques sont conservées dans leur table d’origine et
marquées `legacy`; aucune migration rétroactive d’identité n’est effectuée.

La migration est additive et réversible. Les clés SIREN sont uniques, les
scores sont bornés et la méthode est une valeur contrôlée. Les tests valident
le contrat réel : requête de recherche, binding persistant, rejet unresolved,
puis recherche d’un décideur vérifié.
