# PR5b — benchmark staging « Pour vous »

## Rejeu v6 — verdict de pertinence séparé

Date : 5 septembre 2026

SHA : `e2974df80badedb99fe152dfc33f811276a80727`

Les 50 couples v5 ont été repris à l'identique sur les trois profils (17/17/16).
Le prompt système impose l'objet JSON à trois champs et `model_fit=none` sert le
repli sans compter comme rejet de rédaction. Le nom de l'acheteur vérifié et le
référentiel de sigles métier alimentent le lexique du validateur.

| Bande demandée | Bande persistée | Couples | Rejets | Taux de rejet | `model_fit=none` | Taux `none` |
|---|---|---:|---:|---:|---:|---:|
| strong | strong | 48 | 1 | 2,08 % | 42 | 87,5 % |
| medium | promising | 2 | 1 | 50 % | 0 | 0 % |
| weak | weak | 0 | 0 | — | 0 | — |

Total : 50 tentatives, 5 phrases générées, 42 replis `model_fit=none`, deux
rejets `invalid_shape` et un autre repli. Le taux de rejet global est 4 % ; la
cible de moins de 15 % sur strong est atteinte. Aucun doublon de conséquence
normalisée n'a été observé.

Les deux sorties rejetées avaient bien `fit:none`, mais forçaient malgré tout
une conséquence au lieu de `null`. Les 87,5 % de `none` sur la bande strong
orientent le prochain diagnostic vers le matching, pas vers le parseur.

Phrases générées :

1. Travaux électricité CFO bâtiment Phitem à Isère (105 k€) : bardage métallique complémentaire pour l'enveloppe du bâtiment.
2. Travaux démolition désamiantage déplombage bâtiments à Bouches-du-Rhône (600 k€) : lot déplombage ouvre chantiers plomberie connexes.
3. Dévoiement réseaux humides tramway à Bouches-du-Rhône (6,8 M€) : réseaux humides déplacés demandent raccordements plomberie spécialisés.
4. Doublage, cloisons et faux-plafonds à Isère (116,8 k€) : bardage métallique complémentaire envisageable sur façades intérieures.
5. Travaux d'étanchéité bâtiment hospitalier à Vaucluse (320,8 k€) : chantier en Vaucluse compatible avec votre zone plomberie.

Date : 5 septembre 2026

SHA : `c8236544c3ff301adf18792f506f83ba10679e3a`

Fournisseur : OpenRouter, modèle configuré sur staging

## Exécution bornée

Le timer a été arrêté avant la préparation. Le contrôle SQL pré-lancement a
confirmé 50 signaux distincts : bardage métallique · Isère `17`, CVC plomberie
· PACA `17`, espaces verts · Nord `16`. Le worker a ensuite reçu uniquement ces
50 identifiants, avec une concurrence de 4, puis le timer a été réactivé.

| Tentées | Acceptées | Rejetées | Replis | Taux de rejet | Doublons conséquence |
|---:|---:|---:|---:|---:|---:|
| 50 | 18 | 32 | 32 | 64 % | 0 |

Motifs : `invalid_content` 18, `invalid_shape` 10,
`invented_name_or_place` 4 (`IRS`, `CVC`, `VR`, `MOA`).

## Cinq réponses brutes rejetées

1. `Je dois construire la phrase selon le gabarit, mais la réponse doit être uniquement un objet JSON avec short_object et consequence. Analyse : Objet CPV : Travaux de construction (45000000) à Mons-en-Baroeul…`
2. `Je détecte une incohérence majeure : le profil concerne des travaux de couverture/bardage métallique, sans aucun lien avec la maintenance de matériel neurochirurgical…`
3. `````json {"short_object":"étanchéité bâtiment IRS Cavaillon Luberon","consequence":"vos équipes plomberie couvrent déjà le Vaucluse"} `````
4. `````json {"short_object":"maîtrise d'œuvre reconstruction après sinistre","consequence":"la reconstruction du Patio implique des travaux de plomberie"} `````
5. `````json {"short_object":"réhabilitation plomberie chauffage ventilation bâtiment","consequence":"votre bardage métallique complète les travaux de second œuvre"} `````

Les réponses brutes rejetées sont persistées, tronquées à 2 000 caractères et
expirent après 30 jours. `invalid_shape` désigne seulement les dix réponses ne
contenant aucun objet `{short_object, consequence}` exploitable.

## Vingt phrases effectivement servies

1. Réhabilitation cloisons faux-plafonds bâtiment Phitem à Isère (116,8 k€) : travaux de cloisonnement proches de votre zone Isère.
2. AMO réhabilitation ports de plaisance à Bouches-du-Rhône (600 k€) : travaux portuaires peuvent inclure interventions plomberie spécialisée.
3. Gros œuvre et charpente bois à Nord (3,3 M€) : abords verts du site à aménager durablement.
4. Nettoyage du littoral en Occitanie à Alpes-Maritimes (2 M€) : mobilisation terrain éloignée de votre zone plomberie.
5. Maintenance copieurs multifonctions région à Bouches-du-Rhône (200 k€) : secteur éloigné de votre offre plomberie CVC.
6. Maintenance équipements dialyse HEMOTECH à Isère (94 k€) : bardage métallique sans lien avec la dialyse.
7. Entretien véhicules lourds Iveco Nord à Nord (200 k€) : flotte de livraison maintenue pour vos chantiers verts.
8. Analyses de biologie médicale externalisées à Isère (750 k€) : décalage total avec votre activité de bardage métallique.
9. Maintenance équipements et logiciels médicaux IBA à Isère (250 k€) : contrat médical éloigné de votre bardage métallique.
10. DALKIA a gagné exploitation chauffage ventilation eau chaude à BAILLEUL (185,5 k€) : contrat long terme ouvre chantiers verts adjacents.
11. Dévoiement réseaux humides tramway à Bouches-du-Rhône (6,8 M€) : vos équipes plomberie interviennent sur canalisations eaux pluviales.
12. Maintenance équipements froids restauration universitaire à Nord (250 k€) : secteur froid éloigné de vos espaces verts.
13. Création salle d'assises criminelle urgente à Bouches-du-Rhône (177,3 k€) : finitions intérieures exigeantes ouvrent opportunités sous-traitance plomberie.
14. Dératisation et désinsectisation bases militaires à Alpes-Maritimes (123,7 k€) : marché hors plomberie, sans lien avec votre activité.
15. Société Autocars Lolli a gagné transport scolaire par autocar à Douai à Douai (1 M€, juin 2026) : un prestataire local cherche des espaces verts entretenus.
16. Hébergement cloud et services associés à Bouches-du-Rhône (2,5 M€) : sous-traitance technique possible pour vos installations CVC.
17. Travaux électricité CFO bâtiment Phitem à Isère (105 k€) : chantier en Isère compatible avec votre bardage métallique.
18. PAPREC NORD NORMANDIE a gagné collecte DNDAE et déchets inertes (280 k€) : vos chantiers verts génèrent ces flux à évacuer.
19. Ce signal correspond à votre profil cible. *(repli)*
20. Ce signal correspond à votre profil cible. *(repli)*

Le taux dépasse la cible de 15 %. Les sorties montrent que la persistance et le
diagnostic fonctionnent, mais que la qualité fournisseur reste insuffisante ;
les 32 rejets ont servi immédiatement leur repli sans bloquer le signal.
