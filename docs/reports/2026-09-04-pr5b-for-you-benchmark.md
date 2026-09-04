# PR5b — benchmark staging « Pour vous »

Date : 4 septembre 2026  
SHA : `13c51d9421a3514bf7328c2cb42566286d25ef13`  
Fournisseur : OpenRouter, modèle `anthropic/claude-sonnet-4.6`

## Exécution bornée

Commande quotidienne, utilisée ici une seule fois avec la fenêtre du benchmark :

```text
python -m signals.personalization.for_you_backfill --limit 50 --since 2026-08-01
```

| Tentées | Acceptées | Rejetées | Replis | Taux de rejet | Durée | Concurrence | Plafond journalier |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 | 30 | 20 | 20 | 40 % | 22,5 s | 4 | 50 |

Motifs persistés : `invented_number` 17, `too_many_words` 2,
`invented_name_or_place` 1. Les rejets ont conservé le repli immédiatement
visible ; aucun second appel n'a été lancé.

## Vingt phrases acceptées et persistées

1. Ce marché porte sur la location et la maintenance d'un traceur grand format, d'une station de travail et d'un logiciel RIP sur quatre ans.
2. Ce marché de voiries et espaces verts à Strasbourg pourrait nécessiter un approvisionnement en matériaux de construction.
3. Un marché de construction à Bois-Colombes porte sur la restructuration d'un groupe scolaire et la création d'un centre administratif.
4. Ce marché porte sur l'entretien et la réfection de toitures terrasses et lignes de vie en Val-de-Marne.
5. Ce marché de travaux d'entretien routier dans le Pas-de-Calais pourrait nécessiter une fourniture de matériaux et composants pour chantiers.
6. Un marché de rénovation énergétique avec géothermie à Rollot pourrait nécessiter la location de matériel de chantier.
7. Un accord-cadre de travaux de voirie dans les Yvelines recherche des fournisseurs de matériaux et composants pour des chantiers routiers.
8. Ce marché porte sur la réhabilitation du réseau d'assainissement départemental du Val-de-Marne, avec des besoins en matériaux et composants.
9. Ce marché d'éclairage public dans les Bouches-du-Rhône peut nécessiter un approvisionnement en matériaux de construction.
10. Ce marché de charpente-couverture à Lent (Ain) pourrait nécessiter des matériaux et composants adaptés à vos offres.
11. Une mission de maîtrise d'œuvre pour la réhabilitation du centre de loisirs Jules Verne en Seine-Saint-Denis recherche des sous-traitants spécialisés.
12. Ce marché de travaux d'entretien routier dans le Pas-de-Calais pourrait nécessiter un approvisionnement en matériaux de construction.
13. Ce marché porte sur l'entretien et la réfection de toitures terrasses et lignes de vie en Val-de-Marne.
14. Ce marché de VRD à Strasbourg porte sur des aménagements extérieurs d'un local commercial, avec un besoin en matériaux de construction.
15. La Piscine de la Butte-aux-Cailles à Paris fait l'objet de travaux d'extension, de rénovation et de construction d'une salle de sport.
16. Le titulaire de ce marché de réhabilitation d'égouts en Val-de-Marne pourrait avoir besoin de matériaux de construction.
17. Un marché de travaux d'aménagements extérieurs à Strasbourg pourrait nécessiter une fourniture de matériaux et composants.
18. Un marché de revêtements de sols en Val-de-Marne pourrait nécessiter une fourniture de matériaux et composants adaptés.
19. Un marché de travaux de revêtement de rues dans l'Eure pourrait nécessiter un approvisionnement en matériaux de construction.
20. La réhabilitation de la charcuterie de Lescar en centre socio-culturel inclut des travaux de chauffage, ventilation et plomberie sanitaire.

## Chemin clic → dashboard

Le test d'intégration PR5 a été chronométré trois fois, sans appel fournisseur :
`0,552 s`, `0,467 s`, `0,453 s`. La médiane est `0,467 s`, contre `0,424 s`
en PR5, soit `+43 ms` (`+10,1 %`). La génération OpenRouter reste donc hors
du chemin synchrone et le parcours reste très inférieur à la borne de 60 s.

Le SHA a été déployé par `kivou-deploy.sh` après sauvegarde, répétition Alembic
sur copie jetable et readiness réussies. Le timer staging est actif ; le plafond
du jour étant atteint, il ne peut pas produire d'appel supplémentaire avant le
jour suivant.
