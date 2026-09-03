# Source du jeu CPV 2008

Le fichier `data/cpv_2008.json` est généré depuis un export CSV de la
nomenclature CPV 2008 (« Common Procurement Vocabulary »), le vocabulaire
commun des marchés publics de l'Office des publications de l'Union
européenne.

- **Portail source :** OpenDataSoft public, jeu `nomenclature-cpv`, qui
  republie la nomenclature officielle CPV 2008.
- **URL d'export utilisée :**
  `https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/nomenclature-cpv/exports/csv?delimiter=%3B&limit=-1`
- **Date de récupération :** 2026-09-03.
- **Format source :** CSV, séparateur `;`, BOM UTF-8, colonnes
  `code;de;en;es;fr;pt;code_short` (9 454 lignes de données). `code` est le
  CPV complet avec chiffre de contrôle (`19724000-7`), `code_short` sa forme
  à 8 chiffres — c'est cette dernière qui sert de clé dans le jeu généré, car
  c'est la forme persistée par `contract_award.cpv_main`.

## Régénération

```
python -m signals.domain.cpv_labels.import_cpv <csv> src/signals/domain/cpv_labels/data/cpv_2008.json
```

Le script ne conserve que les colonnes `fr` et `en` (le produit est
bilingue) et trie les codes. Il ne tourne jamais en test : le CSV source
n'est pas committé (il est gros et régénérable), seul le JSON produit l'est.
