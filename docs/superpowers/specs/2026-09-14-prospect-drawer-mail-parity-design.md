# Parité mail–drawer du prospect — design validé

Date : 2026-09-14
Statut : validé

## Objectif

Lorsqu'un prospect ouvre un signal depuis un mail Kivou, le drawer doit tenir
exactement la promesse commerciale du mail. Les surfaces client doivent aussi
présenter le même nom d'entreprise, la même horloge factuelle et la même
cohorte d'atterrissage.

## Cause observée

Le mail assisté courant est rendu depuis `prospect_target`, mais
`routes_attribution` ne cherche la phrase personnalisée que dans l'ancien
artefact `acquisition_personalization_artifact`. L'absence de résultat fait
retomber le drawer sur `api/commercial_context.py`, qui reconstruit une phrase
à partir des catégories moteur. C'est la source de l'ancienne formulation de
positionnement, des assemblages de catégories et des références techniques.

## Contrat de rédaction

- Le renderer de mail expose une fonction pure unique pour la phrase famille :
  fait général relu dans le catalogue, puis « et vous êtes {métier} à
  {ville} ».
- Le mail appelle cette fonction ; l'atterrissage retrouve la phrase exacte
  déjà enregistrée dans `prospect_target.mail_text` par l'empreinte du jeton.
  Cette liaison survit aux rematérialisations techniques du signal.
- Le drawer du signal promis affiche cette phrase. En l'absence d'une phrase
  de mail fiable, il affiche uniquement le repli déterministe fondé sur les
  faits du marché.
- Le drawer ne fabrique plus de texte depuis les catégories moteur ou les
  offres du profil. Le module `api/commercial_context.py` est retiré.
- Une phrase destinée au client ne contient jamais une référence de lot, un
  code CPV, une clé moteur ni l'ancienne formulation de positionnement.
- La recherche finale de cette formulation historique doit retourner zéro
  occurrence dans le dépôt suivi.

## Identité entreprise

`normalize_holder_name`, déjà utilisé par le mail, devient l'unique fonction
de présentation du nom du titulaire sur les surfaces client : Aujourd'hui,
liste et drawer Signaux, annuaire, liste de prospection et dossier entreprise.
Ainsi, par exemple,
`CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD` devient `CMCD`
partout.

Les valeurs sources et les identifiants légaux restent inchangés en base afin
de préserver la preuve, la recherche et la résolution d'identité. Seule leur
projection client est normalisée.

## Dates et lieux

- La carte et le badge du drawer préfèrent la date d'attribution et affichent
  « Attribué le … ».
- La date de publication BOAMP reste un fait du calendrier, libellé sans
  jargon : « Avis publié le … ».
- La commune est rendue en casse française normale et accompagnée du
  département lorsqu'il est connu, par exemple « Saint-Ondras (Isère) ».
- Les replis existants restent valables lorsqu'une date d'attribution, une
  commune ou un département ne sont pas publiés ; aucune donnée n'est inventée.

## Cohorte d'atterrissage

Le backend impose une sélection stricte : le signal appât, puis au
plus deux procédures distinctes de la même famille commerciale et du même
département. Il expose explicitement la taille attendue et la taille réellement
matérialisée de cette cohorte.

Le lien ouvre directement le drawer de l'appât. La liste visible derrière
contient l'appât et les voisins disponibles. Si la cohorte contient moins de
trois signaux, une seule ligne non interactive « Vos prochains signaux
arriveront ici » représente l'inventaire à venir. Un voisin disponible n'est
jamais masqué.

Cette ligne est propre au premier feed provisoire : elle ne devient ni un faux
signal, ni un compteur, ni un élément paginé.

## Validation et mise en production

La validation locale reste ciblée :

1. tests unitaires du générateur partagé et du repli factuel ;
2. tests API de l'atterrissage avec zéro, un et deux voisins ;
3. tests frontend du nom CMCD, de « Attribué le », du lieu et de la ligne
   d'attente ;
4. recherche statique des chaînes interdites ;
5. après déploiement, parcours Playwright de production avec un jeton QA,
   capture du drawer ouvert et assertions sur l'absence des chaînes interdites.

Le jeton et les cookies de session ne doivent apparaître ni dans les captures,
ni dans les journaux, ni dans le compte rendu.
