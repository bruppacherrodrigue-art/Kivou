# PR5b — benchmark staging « Pour vous »

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
