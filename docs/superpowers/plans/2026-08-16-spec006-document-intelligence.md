# SPEC-006 — Tender Document Intelligence

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:test-driven-development` pour chaque tâche.

**Goal:** Retrouver les documents d'un marché depuis l'award, mesurer honnêtement leur accessibilité, et extraire des exigences d'exécution dont chacune porte un extrait source exact.

**Architecture:** Couche `signals.documents`, au-dessus de `ContractUnderstanding`. `Evidence` (SPEC-005) est réutilisé avec `source_kind="tender_document"`. Contenu brut et intelligence sont strictement séparés.

**Spec:** SPEC-006 (superviseur, 2026-08-16)

## Global Constraints

- `ContractAward`, `PublicEvent`, `Money`, `Company`, `AwardeeParty`, `Provenance`, `ContractUnderstanding`, `Evidence` : **interdiction de modifier**.
- Aucun besoin commercial, aucun Need Graph, aucun Apollo, aucun SaaS.
- Aucun contournement d'authentification, aucun scraping, aucun navigateur.
- Aucune base de données, aucun embedding, aucun vector store.
- Toute intelligence dérivée porte `document-intelligence-v0.1`.
- **Aucune exigence sans extrait source retrouvable** dans le texte du document.

## Ce que le spike a établi (mesures réelles, avant toute ligne de code)

| Mesure | Résultat |
|---|---|
| Awards TED → procédure → avis d'appel d'offres | 19/22 procédures liées via `procedure-identifier` |
| Avis d'appel d'offres publiant une URL BT-15 | **19/19** |
| URL BT-15 menant à un **fichier téléchargeable** | **1/19**, puis **1/39** sur un second échantillon indépendant |
| Le reste | pages d'accueil de **~30 portails nationaux** (FR, NO, LU, HU, LT, BE, CH, SE, NL, AT, IE, RO, HR, FI, BG, EE, DE, ES, PL, PT…) |
| SIMAP | `auth_required` — établi en SPEC-003, aucun endpoint public |
| Formats réellement rencontrés | **ZIP, PDF, DOCX, XLSX, XML** |

**Conséquence architecturale majeure : TED n'héberge pas les documents.** Il publie un pointeur vers un portail national. `external` n'est donc pas un échec, c'est l'état normal — et le modèle doit le dire au lieu de le confondre avec « pas de document ».

Deux dossiers réels récupérés, qui servent de fixtures :

- **SI** (`565982-2026`) — ZIP 15,7 Mo : `Dokumentacija v zvezi z oddajo.docx` (996 paragraphes), 2 XLSX de bordereaux, 4 PDF de plans, `ESPD.xml` ;
- **PT** (`566160-2026`) — ZIP 1,3 Mo : `1_Caderno_encargos_AE.pdf` (30 pages, cahier des charges), `2_Programa_Procedimento_AE.pdf`, un **ZIP imbriqué** (`espd-request.zip`), 3 PDF d'annonces.

## File Structure

```
src/signals/documents/model.py          TenderDocument, DocumentAccessStatus, DocumentKind
src/signals/documents/requirements.py   ExecutionRequirement, RequirementType, Modality
src/signals/documents/discovery.py      award → procédure → avis → références documentaires
src/signals/documents/fetch.py          téléchargement sûr : limites, hash, cache
src/signals/documents/archive.py        ZIP sûr : traversal, bombe, récursion, exécutables
src/signals/documents/extract.py        PDF/DOCX/XLSX/HTML/TXT → TextBlock[]
src/signals/documents/intelligence.py   exigences + validation d'extrait + protocole de modèle
src/signals/documents/live_smoke.py
tests/test_document_model.py
tests/test_document_extraction.py
tests/test_document_intelligence.py
tests/test_document_adversarial.py
tests/test_document100_benchmark.py
tests/fixtures/documents/               documents réels réduits + archives forgées de sécurité
```

## Tâches

### Task 1 — modèle documentaire et états d'accès
Tests : un statut `auth_required` n'est jamais un « pas de document » ; un document récupéré porte son `content_hash` ; deux fichiers de même nom et de hash différents restent distincts ; aucun versioning inventé.

### Task 2 — téléchargement sûr
Tests : limite de taille respectée → `too_large` ; 403 → `auth_required` ; 404 → `not_found` ; erreur réseau → `download_failed` ; le cache évite un second téléchargement du même URL ; le hash est celui des octets bruts.

### Task 3 — archives sûres
Tests : `../../evil` rejeté ; bombe zip stoppée par la limite d'expansion ; récursion bornée ; `.exe`/`.dll` listés mais jamais ouverts ; ZIP imbriqué réel du dossier PT traité à profondeur 1.

### Task 4 — extraction de texte
Tests sur les documents RÉELS : PDF page par page (`page 4`), DOCX paragraphe par paragraphe, XLSX feuille!cellule, HTML nettoyé, page vide → aucun bloc. `unsupported` explicite pour les formats non traités.

### Task 5 — exigences et validation
Tests : une exigence sans extrait retrouvable est **rejetée** ; l'extrait n'est jamais paraphrasé ; la négation, l'option et l'historique ne produisent pas d'obligation ; quantité et unité extraites déterministiquement.

### Task 6 — Document-100
Tests : couverture mesurée par statut, aucune relation award→tender inventée, un dossier sans document produit un résultat vide explicite.

### Task 7 — adversarial (A–L)
Injection de prompt, historique, négation, option, citation externe, tableau, répétition, page vide, scan sans texte, document énorme, traversal ZIP, exécutable en archive.
