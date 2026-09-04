# Capture précoce des DCE — replay BOAMP du 28 août au 3 septembre 2026

## Protocole

Le 4 septembre 2026, staging a exécuté la commande du job quotidien avec une
fenêtre historique :

```text
python -m signals.ingestion tender-notices --source boamp --since 2026-08-28 --until 2026-09-03
```

La commande a ingéré 674 avis d'appel à la concurrence et persisté 663 URL dans
`procedure_documents`. Les métriques ci-dessous ont ensuite été recalculées par
`capture_report()` depuis les lignes persistées, reliées aux avis par identifiant
BOAMP et filtrées sur leur date de publication.

## Résultats

| Hébergeur | Téléchargés | URL observées | Taux |
|---|---:|---:|---:|
| PLACE | 0 | 125 | 0,0 % |
| achatpublic | 0 | 69 | 0,0 % |
| Maximilien | 0 | 38 | 0,0 % |
| Autres | 0 | 431 | 0,0 % |

Taille moyenne par dossier effectivement téléchargé : **0 octet**. Répartition
des statuts : 649 `external`, 3 `auth_required`, 9 `download_failed` et 2
`not_found`. Aucun accès protégé n'a été contourné.

## Estimation à trois mois

Le proxy reproductible est la part des AAPC de la fenêtre ayant au moins un
document `available`; il estime donc la borne de couverture des futures
attributions par les dossiers capturés aujourd'hui. Il vaut **0 / 674 = 0,0 %**.
Ce n'est pas une cohorte d'attributions observée trois mois plus tard : il faudra
recalculer la couverture réelle après maturation. Le résultat montre surtout que
les URL BOAMP publiées pointent vers des pages de consultation externes plutôt
que vers des archives directement téléchargeables avec les règles actuelles.
