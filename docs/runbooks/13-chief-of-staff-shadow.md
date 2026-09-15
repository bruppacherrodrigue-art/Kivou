# Chief of Staff SHADOW — génération et diagnostic

Ce runbook ne vaut pas autorisation d'activation. La V1 n'envoie rien et ne
modifie aucune donnée métier.

## Préparer

Vérifier le head Alembic attendu, le pin dans
`src/signals/supervisor/hermes.lock.toml`, puis la configuration séparée :

```bash
uv run python -m signals.chief_of_staff status
uv run python -m signals.supervisor health
```

Une configuration absente doit afficher `NOT_CONFIGURED`. Ne jamais copier une
clé dans la ligne de commande ou les logs.

## Démonstration hors ligne

```bash
uv run python -m signals.chief_of_staff demo --database-url sqlite+pysqlite:///./chief-of-staff-demo.db
```

La commande charge les fixtures, simule le fournisseur, valide et persiste un
rapport, puis affiche des références non sensibles. Elle ne contacte aucun
fournisseur.

## Génération sûre

Le dry-run est la valeur par défaut :

```bash
uv run python -m signals.chief_of_staff generate --cadence daily --at 2026-09-15T05:30:00Z
```

`--persist` autorise uniquement la ligne append-only après validation. Codes de
sortie : `0` succès/rapport déjà présent, `2` configuration ou contexte
invalide, `3` verrou occupé, `4` budget refusé, `5` fournisseur indisponible,
`6` rapport rejeté.

## Diagnostic

1. Confirmer `SHADOW`, pin et profil.
2. Confirmer la présence des faits et leurs statuts sans afficher de PII.
3. Vérifier le journal modèle : réservation puis `succeeded` ou `failed`.
4. Pour un rapport rejeté, conserver uniquement le code de validation ; ne pas
   persister la réponse brute.
5. Pour un verrou occupé, attendre le cycle courant ; ne pas tuer le processus.

## Planification proposée, non activée

Les unités livrées sont des exemples désactivés. Une cadence quotidienne après
la clôture des ingestions Zurich peut être évaluée, mais l'heure définitive,
l'installation et `systemctl enable` exigent une autorisation séparée.

## Rollback

Désactiver la future unité si elle a été autorisée, remettre l'artefact applicatif
précédent et conserver tables, rapports et journal modèle. Ne jamais downgrader
automatiquement la base ni supprimer l'audit.
