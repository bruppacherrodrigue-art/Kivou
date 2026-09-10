# PR7 Level 2 Contact Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à toute cible SIRENE avec un domaine valide d'atteindre le niveau 2 et mesurer précisément la cascade sur les 75 cibles production.

**Architecture:** Le binding Apollo devient facultatif au niveau fournisseur. La résolution de domaine, l'extraction d'adresses publiées, la sélection d'un dirigeant public opérationnel et la vérification MX restent des composants bornés et testables séparément.

**Tech Stack:** Python 3.12, Pydantic, httpx, dnspython, pytest, OpenRouter, Serper.

---

### Task 1: Apollo facultatif

**Files:** `src/signals/acquisition_runtime/composition.py`, `tests/test_acquisition_runtime_composition.py`.

- [ ] Écrire un test rouge où un binding non résolu mais doté d'un domaine conserve le fournisseur.
- [ ] Faire retourner vrai à `resolve_supplier` lorsqu'un domaine valide est persisté.
- [ ] Exécuter uniquement le test ciblé et confirmer son passage.

### Task 2: Domaine Serper strict

**Files:** `src/signals/company_research/domain.py`, `tests/test_company_domain_resolution.py`.

- [ ] Écrire des tests rouges pour `.gouv.fr`, préfixes mairie, annuaires et faux rapprochement JACQUET/Certines.
- [ ] Centraliser le rejet des domaines publics, annuaires et résultats sans mot significatif.
- [ ] Exécuter les tests domaine ciblés.

### Task 3: Adresse publiée et dirigeant opérationnel

**Files:** `src/signals/contact_discovery/web.py`, `providers.py`, `deliverability.py`, `tests/test_contact_waterfall.py`.

- [ ] Écrire les tests rouges pour adresse textuelle, formulaire seul, filtrage des CAC, JSON `{email, dirigeant, confiance}` et `max_tokens=1000`.
- [ ] Extraire les adresses littérales, filtrer les dirigeants et valider la cohérence des domaines mail.
- [ ] Ajouter un contrôle MX séparé et conserver SMTP comme information complémentaire sans envoi.
- [ ] Exécuter les tests contact ciblés.

### Task 4: Annuaire fournisseur réutilisable

**Files:** `src/signals/supplier_directory/`, `src/signals/persistence/schema.py`, migration `0048`, composition et services de découverte.

- [ ] Écrire les tests rouges du schéma, de l'union des familles, de la fraîcheur 90 jours et de la réutilisation avant réseau.
- [ ] Persister l'identité, le domaine, les dirigeants et le contact avec une date par groupe de champs.
- [ ] Journaliser les appels Serper/Apollo évités et alimenter l'annuaire après chaque observation.
- [ ] Écrire le test rouge d'opposition, puis effacer les coordonnées et créer la suppression campagne dans une transaction.

### Task 5: Mesure et livraison

**Files:** commande de mesure existante et tests CLI associés si son contrat change.

- [ ] Vérifier que tous les appels OpenRouter du runtime déclarent un `max_tokens` explicite.
- [ ] Exécuter Ruff et les tests ciblés une seule fois.
- [ ] Pousser la PR, obtenir une CI verte, fusionner et déployer avec le timer arrêté.
- [ ] Vérifier le solde OpenRouter puis rejouer les 75 et restituer le tableau demandé.
