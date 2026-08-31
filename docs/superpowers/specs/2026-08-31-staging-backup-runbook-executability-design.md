# Staging rollout runbook executability

## Contexte

Le rollout Card Intelligence du SHA `c8ea78ce4cffe4053213db9421dfb05fbbab0a72`
a produit une sauvegarde PostgreSQL valide, puis la section 3 du runbook s'est
arrêtée avant la restauration scratch. Le shell SSH démarre dans
`/home/ubuntu`, non traversable par `kivou`, tandis que
`/srv/kivou/backups` appartient à `kivou` en mode `700`. Le `find` exécuté
avec `sudo -u kivou` échoue en restaurant son répertoire initial et les deux
`stat` exécutés comme utilisateur SSH ne peuvent pas atteindre le dump.

La migration n'a pas été lancée, aucune base scratch ne subsiste et staging
reste en `0027_signal_notes`.

## Décision

Conserver la topologie et l'ordre du runbook. Au début de chaque shell SSH des
sections 3 à 6, se placer explicitement dans `/srv/kivou`, répertoire accessible
aux identités opérateur, `kivou` et `postgres`. Exécuter les lectures de
métadonnées du dump avec `sudo -u kivou`, comme les contrôles SHA, TOC et le
flux de restauration déjà prévus.

Cette correction est préférée à une reprise manuelle non versionnée et à une
modification des permissions du répertoire de sauvegardes. Elle ne change ni
le schéma, ni les releases, ni les services, ni les données.

## Périmètre

- Modifier uniquement le runbook staging et son test d'architecture.
- Ajouter `cd /srv/kivou` après `set -euo pipefail` dans les shells distants des
  sections sauvegarde, préparation/migration backend, blue/green et frontend.
- Lire le propriétaire, le mode et la taille du dump sous `sudo -u kivou`.
- Ne pas modifier `ops/bin/kivou-backup.sh`, dont le mode privé `700` est voulu.
- Ne pas toucher à la production.

## Vérification

Le test de non-régression doit échouer sur le runbook actuel en démontrant que
la section 3 ne fixe pas un répertoire de travail accessible et que ses `stat`
du dump ne sont pas exécutés comme `kivou`. Après correction, il doit vérifier
les mêmes invariants pour tous les shells distants concernés, puis la suite
complète `tests/test_card_presentation_runbook.py`, Ruff et la CI GitHub doivent
être vertes avant fusion.

Le déploiement reprendra exclusivement depuis le nouveau SHA final fusionné de
`main`, avec une nouvelle CI push verte. La sauvegarde déjà créée reste une
preuve de diagnostic ; une sauvegarde fraîche sera refaite par le runbook
corrigé avant la migration `0027_signal_notes -> 0028_card_presentation`.
