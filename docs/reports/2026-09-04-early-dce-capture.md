# Capture précoce des DCE — replay BOAMP du 28 août au 4 septembre 2026

## Protocole

Le 4 septembre 2026, staging a exécuté exactement la commande du job quotidien,
avec une fenêtre historique :

```text
python -m signals.ingestion tender-notices --source boamp --since 2026-08-28 --until 2026-09-04
```

La commande s'est terminée normalement en 1 h 10 min 45 s : **780 AAPC**
ingérés, **219 nouvelles lignes documentaires** et **768 URL uniques** observées.
Les métriques ci-dessous viennent de `procedure_documents`, via
`capture_report()` ; elles ne proviennent pas d'un compteur en mémoire. Les
statuts des refus configurés ont été remis à niveau sur cette fenêtre après la
correction de l'upsert des tentatives sans contenu.

## Résultats par hébergeur

| Hébergeur | URL | Téléchargés | URL observées | Taux | Bloqués | Motifs | Taille moyenne/dossier | Exigences classifiées/dossier |
|---|---|---:|---:|---:|---:|---|---:|---:|
| PLACE | https://www.marches-publics.gouv.fr | 47 | 138 | 34,1 % | 0 | — | 7 055 000 o | 0,0 |
| achatpublic | https://marchesonline.achatpublic.com | 0 | 81 | 0,0 % | 81 | `robots_disallowed` | 0 o | 0,0 |
| Maximilien | https://marches.maximilien.fr | 29 | 49 | 59,2 % | 0 | — | 7 813 729 o | 0,0 |
| marches-publics.info | https://www.marches-publics.info | 0 | 211 | 0,0 % | 211 | `captcha` | 0 o | 0,0 |
| Marchés Sécurisés | https://www.marches-securises.fr | 0 | 64 | 0,0 % | 64 | `cgu_automation` | 0 o | 0,0 |
| Mégalis Bretagne | https://marches.megalis.bretagne.bzh | 9 | 24 | 37,5 % | 0 | — | 11 444 344 o | 0,0 |
| DEMAT AMPA | https://demat-ampa.fr | 10 | 14 | 71,4 % | 0 | — | 5 750 523 o | 0,0 |
| XMarchés | https://www.xmarches.fr | 0 | 13 | 0,0 % | 13 | `captcha` | 0 o | 0,0 |
| Autres | https://port-arcachon.e-marchespublics.com | 32 | 174 | 18,4 % | 1 | `host_circuit_open` | 11 800 804 o | 0,0 |

Au total, **127 AAPC sur 780** disposent d'au moins un document téléchargé,
soit un proxy de couverture à trois mois de **16,3 %**. La taille moyenne des
dossiers effectivement téléchargés est de **8 644 906 octets**.

Les exigences classifiées sont à zéro comme attendu : ce replay capture les
dossiers à l'AAPC, tandis que la classification est différée jusqu'à la jointure
forte avec une attribution. Une jointure `review_required` ne nourrit jamais le
`ContractUnderstanding` client.

Les avertissements observés concernaient uniquement quelques PDF mal formés. Le
rapport a été rendu borné en mémoire après qu'une première lecture incluant les
archives binaires a été tuée à 3,1 Go ; la requête finale ne sélectionne que les
colonnes scalaires nécessaires et a consommé moins de 1 Mo selon systemd.
