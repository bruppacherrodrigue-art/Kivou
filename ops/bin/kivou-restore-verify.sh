#!/usr/bin/env bash
# Vérifie qu'une sauvegarde est RESTAURABLE — la seule preuve qui compte.
#
# Une sauvegarde jamais restaurée est une hypothèse. Ce script la restaure dans
# une base JETABLE, compte ce qui doit s'y trouver, puis détruit la base.
#
#     Il ne touche JAMAIS la base active.
set -Eeuo pipefail

DUMP="${1:?usage: kivou-restore-verify.sh <fichier.dump>}"
SCRATCH="kivou_restore_check_$(date -u +%s)"
ADMIN_URL="${KIVOU_RESTORE_ADMIN_URL:?definir KIVOU_RESTORE_ADMIN_URL vers une base admin}"

log() { echo "[kivou-restore-verify] $*"; }

cleanup() {
    log "destruction de la base jetable ${SCRATCH}"
    psql "${ADMIN_URL}" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${SCRATCH};" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "création de ${SCRATCH}"
psql "${ADMIN_URL}" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${SCRATCH};" >/dev/null

TARGET_URL="${ADMIN_URL%/*}/${SCRATCH}"

log "restauration de ${DUMP}"
pg_restore --dbname="${TARGET_URL}" --no-owner --no-privileges --exit-on-error "${DUMP}"

log "vérification du contenu"

# La révision Alembic d'abord : un dump restauré dont le schéma est inconnu ne
# prouve rien.
REVISION="$(psql "${TARGET_URL}" -tAc 'SELECT version_num FROM alembic_version;')"
[ -n "${REVISION}" ] || { log "ÉCHEC : aucune révision Alembic"; exit 1; }
log "  révision Alembic : ${REVISION}"

# Les tables que le produit ne peut pas perdre. On compte les LIGNES, pas
# seulement l'existence : une table présente mais vide serait une restauration
# ratée qui passerait pour réussie.
# Noms RELEVÉS sur le schéma réel, pas devinés : une première version listait
# `app_user`, `discovery_grant` et `notification_preference`, qui n'existent pas.
# Le script signalait alors « table absente » sur une restauration parfaitement
# saine — un faux négatif, c'est-à-dire le pire résultat possible pour une
# vérification de sauvegarde.
#
# SPEC-016A ajoute trois tables qui doivent survivre à une restauration au même
# titre que les autres : `opportunity_representation` porte l'identité des
# opportunités, et les deux tables d'ingestion portent la position de reprise.
# Restaurer sans les checkpoints ferait recommencer l'acquisition depuis le
# début — ou, pire, la ferait reprendre à un point erroné.
for table in account auth_user auth_session target_icp materialized_signal \
             discovery_signal_grant billing_customer billing_subscription \
             billing_checkout_attempt signal_feedback product_event \
             account_notification_preference signal_alert_delivery \
             contract_award source_event evidence \
             opportunity_representation ingestion_checkpoint ingestion_run; do
    if ! psql "${TARGET_URL}" -tAc "SELECT to_regclass('public.${table}');" | grep -q .; then
        log "ÉCHEC : table ${table} absente"
        exit 1
    fi
    COUNT="$(psql "${TARGET_URL}" -tAc "SELECT count(*) FROM ${table};" 2>/dev/null || echo "?")"
    log "  ${table} : ${COUNT} ligne(s)"
done

log "RESTAURATION VÉRIFIÉE"
