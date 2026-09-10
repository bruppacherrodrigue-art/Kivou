# PR7 Contact Waterfall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trouver un domaine et un contact nominatif vérifié pour les fournisseurs SIRENE sans envoyer de message.

**Architecture:** Le binding SIREN journalise le domaine et la résolution Apollo. ContactDiscovery orchestre Apollo puis un fournisseur web borné. Une commande de mesure traite le stock complet hors timer.

**Tech Stack:** Python 3.12, Pydantic, httpx, SQLAlchemy/Alembic, dnspython, OpenRouter, Serper.

---

### Task 1: Domaine et binding

**Files:** `src/signals/company_research/domain.py`, `binding.py`, `apollo.py`, schéma et migration, tests associés.

- [ ] Écrire les tests rouges pour priorité Annuaire, filtrage Serper et journal du binding.
- [ ] Implémenter la résolution bornée et la migration.
- [ ] Écrire puis satisfaire les tests domaine d’abord, nom+ville en repli.

### Task 2: Contact web niveau 2

**Files:** `src/signals/contact_discovery/web.py`, `providers.py`, `deliverability.py`, contrats/service/store, schéma et migration, tests associés.

- [ ] Écrire les tests rouges pour deux pages maximum, JSON strict et preuve littérale.
- [ ] Implémenter l’extracteur OpenRouter et la validation du dirigeant public.
- [ ] Écrire puis satisfaire les tests MX/SMTP sans DATA et rejet générique sans nom.
- [ ] Brancher le repli après Apollo sans contact.

### Task 3: Familles et mesure

**Files:** `ops/config/supplier-families.yaml`, CLI runtime, faux fournisseurs, tests.

- [ ] Écrire les tests rouges pour `25.11Z`, `43.99C` et la famille sous-traitants gros œuvre.
- [ ] Mettre à jour le YAML et le profil de familles.
- [ ] Ajouter la commande de mesure et son tableau par famille.

### Task 4: Livraison

- [ ] Exécuter les tests ciblés, Ruff et les tests de migration.
- [ ] Pousser la PR et attendre la CI verte.
- [ ] Fusionner, déployer staging puis production avec le timer arrêté.
- [ ] Rejouer le cycle et la mesure, puis restituer le tableau demandé.

