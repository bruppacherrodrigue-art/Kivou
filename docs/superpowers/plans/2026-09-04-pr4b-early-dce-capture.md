# Early DCE Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capturer les dossiers au stade de l’appel d’offres, les conserver de façon bornée, puis les rattacher sûrement aux attributions ultérieures.

**Architecture:** Un job `tender-notices` séparé réutilise les connecteurs et le pipeline documentaire, sans classification, et persiste son résultat dans `procedure_documents`. L’ingestion d’une attribution résout ensuite une jointure forte ou quarantinée ; seules les jointures fortes chargent les blocs dans la chaîne documentaire existante. La commande quotidienne accepte aussi `--since/--until`, ce qui permet le replay de mesure sans autre script.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy Core, Alembic batch SQLite/PostgreSQL, pytest, CLI d’ingestion existante.

---

### 1. Domaine et parsers d’avis

- [ ] Ajouter `tender_notice` à `EventType`, puis écrire des tests RED sur des fixtures réelles BOAMP eForms AAPC, TED et SIMAP : provenance, acheteur, objet, CPV, date limite, URLs et références explicites, sans `ContractAward`.
- [ ] Étendre les parsers existants avec un résultat `TenderNotice` minimal et factuel ; BOAMP continue d’écarter FNSimple/MAPA, TED lit BT-15 et SIMAP conserve `referencingPubId` sans contourner l’authentification.
- [ ] Vérifier les tests connecteurs ciblés, Ruff, puis committer domaine + parsers + fixtures.

### 2. Stockage durable, quota et rétention

- [ ] Écrire les tests RED du schéma et du dépôt : idempotence, blocs localisés bornés, statuts d’accès, empreintes, taille archivée, date limite, hébergeur, lien d’attribution, `review_required`, confirmation et total de stockage.
- [ ] Ajouter `procedure_documents` au schéma des faits et la migration `0036` en mode batch, puis un dépôt dédié qui sérialise les blocs sans dépasser les limites existantes.
- [ ] Implémenter le quota global configurable : contrôle transactionnel avant écriture et arrêt propre du job ; purger seulement les procédures non jointes douze mois après leur date limite, sans purge automatique quand cette date est absente.
- [ ] Vérifier migration upgrade/downgrade SQLite, compilation PostgreSQL et tests de bornes, puis committer stockage + migration.

### 3. Capture documentaire sans classification

- [ ] Écrire les tests RED d’un orchestrateur recevant des références et des clients HTTP factices : http(s) seulement, User-Agent Kivou, taille/profondeur/exécutables bornés, `auth_required` terminal, archive + extraction, zéro appel de classifieur.
- [ ] Composer `discovery → DocumentFetcher → archive.expand → extract_text`, persister chaque tentative et ses blocs, et arrêter entre deux procédures sur kill switch, SIGTERM ou quota atteint.
- [ ] Vérifier les tests documentaires existants et nouveaux, puis committer l’orchestrateur.

### 4. Job quotidien et replay identique

- [ ] Écrire les tests RED CLI/runtime pour `python -m signals.ingestion tender-notices --source boamp|ted|simap --since YYYY-MM-DD --until YYYY-MM-DD`, checkpoint séparé, cadence lente configurable, `--max-records`, kill switch et codes de sortie propres.
- [ ] Ajouter les acquisitions AAPC aux clients existants et brancher le job séparé ; les options de fenêtre pilotent aussi bien le quotidien que le replay.
- [ ] Vérifier hors réseau le curseur, la reprise idempotente, les erreurs et l’arrêt, puis committer job + configuration opératoire.

### 5. Jointure et classification différée

- [ ] Écrire les tests RED des trois modes : lien explicite, identifiant de procédure, empreinte normalisée `(acheteur, objet, CPV)` ; ce dernier persiste `review_required` mais retourne toujours zéro bloc au pipeline client.
- [ ] Implémenter le résolveur ordonné et la confirmation founder ; une jointure forte charge les blocs stockés et exécute `classification → requirements` avec les moteurs existants avant `ContractUnderstanding`, comme un téléchargement immédiat.
- [ ] Maintenir `AUTO_DOCUMENT_REQUIREMENTS_ENABLED=False` : les résultats sont calculés et traçables mais ne deviennent pas des faits clients sans décision de politique distincte.
- [ ] Vérifier jointure, quarantaine et non-régression ingestion/matérialisation, puis committer.

### 6. Mesure, validation et livraison

- [ ] Ajouter une requête de rapport lisant exclusivement `procedure_documents` et testée sur données figées : AAPC, taux téléchargé par PLACE/achatpublic/Maximilien/autres, taille moyenne, couverture estimée à trois mois.
- [ ] Déployer la branche sur staging via `kivou-deploy.sh`, lancer la commande quotidienne avec la fenêtre réelle des sept derniers jours, puis écrire `docs/reports/2026-09-04-early-dce-capture.md` avec le tableau issu de la table.
- [ ] Lancer une seule validation finale complète hors ligne, corriger toute régression, ouvrir la PR vers `main`, vérifier sa CI une fois et redéployer le SHA final si le rapport l’a modifié.

