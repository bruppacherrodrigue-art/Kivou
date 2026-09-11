# Contrat API — Prospection assistée Founder

Date : 11 septembre 2026  
Version : `founder-prospection-actions-v1`

Ce contrat est la frontière partagée entre la page Prospection et le service
applicatif d'actions. Toutes les routes exigent l'identité Founder existante.
Les mutations utilisent `expected_version` pour refuser une écriture périmée.

## Cible renvoyée

`ProspectTargetV1` contient :

- `target_id: UUID`, `version: int`, `status: pending_review | approved | rejected | sent` ;
- `company: {siren, name, city, employees, family}` ;
- `director: {name, title, source: registry | manual} | null` ;
- `email: {address, source: apollo | site | manual, verification_status: mx_verified | mx_failed}` ;
- `signal: {opportunity_key, holder, subject, amount_minor_units, currency, location, decision_date}` ;
- `mail: {subject, text, html, attribution_url, unsubscribe_url, word_count}` ;
- `delivery: {status, instantly_id, sent_at, opened_at, clicked_at, replied_at,
  bounced_at, unsubscribed_at, reply_classification, instantly_credit_units,
  instantly_request_count}` ;
- `created_at`, `updated_at`, `approved_at`, `approved_by`.

`mail.text` et `mail.html` sont définitifs. Si aucun dirigeant n'est connu, ils
contiennent déjà `Bonjour,`; la console ne construit ni ne modifie le message.

## Routes

### Liste

`GET /api/founder/actions/prospection/list`

Query :

- `status`: optionnel, parmi `pending_review`, `approved`, `rejected`, `sent` ;
- `page`: entier positif, défaut `1` ;
- `page_size`: entier de 1 à 25, défaut `25`.

Réponse `200` :

```json
{
  "version": "founder-prospection-actions-v1",
  "generated_at": "2026-09-11T10:00:00Z",
  "daily_counts": {"prepared": 25, "approved": 5, "rejected": 2, "sent": 0},
  "daily_cap": 25,
  "kill_switch_active": false,
  "items": [],
  "pagination": {"page": 1, "page_size": 25, "total_items": 25, "total_pages": 1}
}
```

### Valider

`POST /api/founder/actions/prospection/approve`

Entrée : `{"target_id":"UUID","expected_version":1}`. La transition autorisée
est `pending_review -> approved`. Réponse `200` :
`{"version":"founder-prospection-actions-v1","target": ProspectTargetV1}`.

### Corriger

`POST /api/founder/actions/prospection/correct`

Entrée :

```json
{
  "target_id": "UUID",
  "expected_version": 1,
  "changes": {
    "email_address": "direction@example.fr",
    "director_name": "Alice Martin",
    "company_name": "Entreprise Exemple"
  }
}
```

Au moins un champ est requis. Chaque ancienne valeur est conservée dans
l'historique. Une adresse corrigée reçoit la source `manual`, est revérifiée MX
et provoque la réémission du jeton lié à l'adresse. Le statut de revue ne change
pas. Réponse `200` :

```json
{
  "version": "founder-prospection-actions-v1",
  "target": {},
  "token_reissued": true,
  "email_reverified": true,
  "directory_updated": true
}
```

### Écarter

`POST /api/founder/actions/prospection/reject`

Entrée :

```json
{
  "target_id": "UUID",
  "expected_version": 1,
  "reason": "wrong_company | wrong_address | off_topic | other",
  "comment": "texte optionnel"
}
```

`other` exige un commentaire. La transition autorisée est
`pending_review | approved -> rejected`. `wrong_address` invalide l'adresse
dans `supplier_directory`; `wrong_company` marque la famille de cette entreprise
à revoir. La réponse `200` contient `target` et
`directory_effect: email_invalidated | family_review_required | none`.

### Envoyer

`POST /api/founder/actions/prospection/send`

Entrée :

```json
{
  "request_id": "UUID",
  "targets": [{"target_id": "UUID", "expected_version": 2}]
}
```

Le lot contient de 1 à 25 cibles. Avant tout appel Instantly, le service verrouille
les lignes et vérifie : kill switch absent, statut `approved`, adresse absente de
la suppression, `email.verification_status == mx_verified`, versions attendues
et plafond journalier de 25. Un lot invalide ne produit aucun appel fournisseur.

Chaque succès passe à `sent` et conserve l'identifiant Instantly, l'heure,
`instantly_credit_units` et `instantly_request_count`. Un échec fournisseur reste
`approved` avec son erreur journalisée. `request_id` rend les reprises
idempotentes. Réponse `200` :

```json
{
  "version": "founder-prospection-actions-v1",
  "request_id": "UUID",
  "results": [{"target_id": "UUID", "status": "sent", "instantly_id": "id"}],
  "daily_sent_count": 5,
  "daily_remaining": 20
}
```

## Erreurs

Toutes les erreurs utilisent
`{"detail":{"code":"CODE","message":"message","target_ids":[]}}`.

- `404 TARGET_NOT_FOUND` ;
- `409 TARGET_VERSION_CONFLICT`, `INVALID_TARGET_STATUS`, `KILL_SWITCH_ACTIVE`,
  `DAILY_SEND_CAP_EXCEEDED`, `REQUEST_ID_CONFLICT` ;
- `422 EMAIL_NOT_MX_VERIFIED`, `EMAIL_SUPPRESSED`, `INVALID_REJECTION_REASON` ;
- `502 INSTANTLY_SEND_FAILED` si aucun élément du lot n'a pu être confié au
  fournisseur.

## Écriture PostgreSQL

L'API d'actions utilise le rôle `kivou_founder_rw`. Il peut lire les projections
nécessaires et écrire uniquement `prospect_target`, les tables d'historique et
d'envoi de cette fenêtre, ainsi que les colonnes de correction de
`supplier_directory`. Le rôle Founder de lecture existant reste inchangé.
