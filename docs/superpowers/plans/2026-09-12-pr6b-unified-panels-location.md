# PR6b Unified Panels and Client Location Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer sur staging un drawer Signal et un panneau Entreprise uniques, une localisation client fiable et trois états Contact explicites, puis attendre l’OK visuel avant tout test.

**Architecture:** Les routes montent un seul composant canonique par objet et la navigation remplace les panneaux au lieu de les empiler. Le backend persiste une projection de lieu distincte du fait source et remet l’enrichissement annuaire existant en file via une route idempotente ; la recherche de décideur reste déclenchée uniquement par clic.

**Tech Stack:** React 19, TypeScript, React Router, CSS Modules, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Playwright pour les captures après déploiement.

---

### Task 1: Canonicaliser les panneaux

**Files:**
- Create: `frontend/src/companies/CompanyPanel.tsx`
- Modify: `frontend/src/signals/components/SignalDrawer.tsx`
- Modify: `frontend/src/companies/CompaniesPage.tsx`
- Modify: `frontend/src/companies/DirectoryCompanyPage.tsx`
- Delete: `frontend/src/companies/CompanyDrawer.tsx`
- Delete: `frontend/src/companies/CompanyProfileV2.tsx`

- [ ] **Step 1: Déplacer le rendu commun dans `CompanyPanel`**

Créer une seule API de composant :

```tsx
type CompanyPanelProps = {
  mode: 'holder' | 'full'
  profile: CompanyProfile | DirectoryCompanyProfile
  returnHref?: string
  onContactStatus?: (status: CompanyContactStatus) => Promise<void> | void
}

export function CompanyPanel(props: CompanyPanelProps) {
  return props.mode === 'holder'
    ? <HolderCompanyContent {...props} />
    : <FullCompanyContent {...props} />
}
```

Les helpers restent privés au fichier ; aucun second composant exporté ne porte
la responsabilité d’une fiche ou d’un panneau.

- [ ] **Step 2: Supprimer définitivement le rendu historique de `SignalDrawer`**

Retirer le prop `redesigned`, `Fact`, `MatchDots` et tout le bloc de repli. Le
composant conserve uniquement le rendu décisionnel et accepte :

```tsx
returnToCompany?: { href: string; name: string } | null
```

- [ ] **Step 3: Brancher toutes les routes sur les composants canoniques**

`CompaniesPage`, `DirectoryCompanyPage`, `SignalsFeed` et `Dashboard` importent
uniquement `CompanyPanel` ou `SignalDrawer`. Supprimer les anciens fichiers et
leurs imports.

- [ ] **Step 4: Commit de structure**

```bash
git add frontend/src/companies frontend/src/signals/components/SignalDrawer.tsx frontend/src/pages
git commit -m "refactor(client): unifier les panneaux signal et entreprise"
```

### Task 2: Remplacer l’empilement par la navigation

**Files:**
- Modify: `frontend/src/companies/CompanyPanel.tsx`
- Modify: `frontend/src/pages/SignalsFeed.tsx`

- [ ] **Step 1: Naviguer depuis un marché**

Chaque marché déclenche :

```tsx
navigate(`/app/signals/${encodeURIComponent(market.signal_id)}`, {
  state: { returnToCompany: { href: companyHref, name: companyName } },
})
```

- [ ] **Step 2: Afficher le retour dans le drawer**

`SignalsFeed` lit `location.state.returnToCompany`, ouvre la clé portée par la
route et rend un lien texte :

```tsx
<Link to={returnToCompany.href}>← Retour à {returnToCompany.name}</Link>
```

- [ ] **Step 3: Éliminer tout état local de signal dans la fiche**

Supprimer `selectedSignal`, `openSignal` et le calque de drawer de l’ancien
composant Entreprise.

- [ ] **Step 4: Commit de navigation**

```bash
git add frontend/src
git commit -m "fix(client): naviguer entre entreprise et signal sans empilement"
```

### Task 3: Persister le lieu client résolu

**Files:**
- Create: `src/signals/ingestion/client_location.py`
- Create: `src/signals/persistence/migrations/versions/0058_client_location.py`
- Modify: `src/signals/domain/values.py`
- Modify: `src/signals/persistence/schema.py`
- Modify: `src/signals/persistence/materialization.py`
- Modify: `src/signals/persistence/repository.py`
- Modify: `src/signals/feed/view.py`
- Modify: `src/signals/feed/factual_display.py`
- Modify: source connector mappings that expose a structured buyer address

- [ ] **Step 1: Définir le résolveur unique**

```python
def resolve_client_location(*, execution, buyers) -> ResolvedClientLocation | None:
    if city := human_city(execution):
        return ResolvedClientLocation(location=with_department(execution), basis="execution_city")
    if city := first_buyer_city(buyers):
        return ResolvedClientLocation(location=with_department(city), basis="buyer_city")
    if department := execution_department(execution):
        return ResolvedClientLocation(location=department, basis="department")
    return None
```

`human_city` rejette les valeurs techniques et les codes seuls.

- [ ] **Step 2: Ajouter la projection sans écraser le fait source**

La migration ajoute `contract_award.client_location JSON` et
`client_location_basis VARCHAR(32)`. La persistance calcule ces champs à partir
de l’événement et du contrat au premier enregistrement.

- [ ] **Step 3: Employer la projection dans toutes les réponses client**

`StoredAward` recharge la projection. `feed.view` et `factual_display` rendent
la même localisation ; le frontend ne choisit plus entre plusieurs champs.

- [ ] **Step 4: Ajouter un backfill borné de recette**

Ajouter une commande acceptant explicitement `--account-id` et `--limit`, sans
appel externe, afin de recalculer les seuls signaux des comptes de recette.

- [ ] **Step 5: Commit du lieu**

```bash
git add src/signals
git commit -m "fix(signals): persister un lieu client affichable"
```

### Task 4: Remettre l’enrichissement annuaire en file sans quota

**Files:**
- Modify: `src/signals/companies/enrichment.py`
- Modify: `src/signals/api/routes_companies.py`
- Modify: `src/signals/api/errors.py`
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/companies/CompanyPanel.tsx`

- [ ] **Step 1: Exposer une remise en file idempotente**

Ajouter une fonction limitée aux signaux accessibles du compte qui replace en
`pending` les jobs absents, partiels ou réessayables, sans appeler le fournisseur.

- [ ] **Step 2: Ajouter la route client**

```python
@router.post("/companies/{company_key}/directory-enrichment")
def queue_company_directory_enrichment(company_key: str, request: Request) -> dict[str, object]:
    # vérifie propriété, remet en file, journalise et renvoie queued/already_ready
```

- [ ] **Step 3: Déclencher la route une fois depuis `CompanyPanel`**

Pour un plan Essentiel et un annuaire incomplet, un effet React idempotent
appelle la route et affiche toujours :

```text
Contact en cours de recherche — revenez dans une heure
```

Aucun appel à `contactLookup` n’est effectué par cet effet.

- [ ] **Step 4: Rendre les états fournisseur explicites**

Quand le service est absent ou que le lookup est `failed`, afficher :

```text
Service temporairement indisponible, réessayez plus tard
```

Journaliser un événement structuré avec `company_key`, `account_id` et le code
d’erreur déjà persisté, sans données personnelles.

- [ ] **Step 5: Commit des états Contact**

```bash
git add src/signals frontend/src
git commit -m "fix(companies): expliciter et amorcer les états contact"
```

### Task 5: Hiérarchiser les actions et préparer l’aperçu

**Files:**
- Modify: `frontend/src/companies/CompaniesPage.module.css`
- Modify: `frontend/src/signals/components/signals.module.css`
- Modify: `frontend/src/companies/CompanyPanel.tsx`
- Modify: `frontend/src/signals/components/SignalDrawer.tsx`

- [ ] **Step 1: Garantir une seule action primaire**

Le bouton primaire est exclusivement « Trouver le décideur » ou le lien du mur
Découverte. Les actions de suivi utilisent le style secondaire. Les sources
sont des liens sans fond ni bordure après le groupe d’actions.

- [ ] **Step 2: Construire sans lancer les tests**

```bash
npm --prefix frontend run build
```

Attendu : build Vite terminé sans erreur. Aucun `vitest`, `pytest`, lint ou
golden n’est lancé à cette étape, conformément à la validation maquette-d’abord.

- [ ] **Step 3: Commit de l’aperçu**

```bash
git add frontend/src
git commit -m "fix(client): clarifier la hiérarchie des actions"
```

### Task 6: Déployer staging et capturer RAZEL-BEC

**Files:**
- Output only: `output/playwright/pr6b-ux-preview/`

- [ ] **Step 1: Identifier les données RAZEL-BEC**

Lire les comptes de recette et les signaux accessibles, sans modifier les
secrets ni imprimer les mots de passe. Exécuter le backfill borné du lieu et
remettre l’enrichissement annuaire RAZEL-BEC en file si nécessaire.

- [ ] **Step 2: Prévenir puis déployer la branche sur staging**

Utiliser `ops/bin/kivou-deploy.sh staging <SHA>` avec le flag commun activé.

- [ ] **Step 3: Capturer les deux comptes**

Pour Essentiel et Découverte, capturer Signaux, Entreprises et la fiche
RAZEL-BEC en 1440 px et 390 px. Ajouter une capture 2560 px des deux écrans
larges pour vérifier le conteneur centré.

- [ ] **Step 4: Présenter les captures et attendre l’OK**

Ne lancer aucun test, aucune CI, aucune fusion et aucun déploiement production.

### Task 7: Après l’OK seulement — tests et livraison

**Files:**
- Modify: `frontend/src/signals/components/SignalDrawer.test.tsx`
- Modify/Create: `frontend/src/companies/CompanyPanel.test.tsx`
- Modify: `frontend/src/signals/feed.test.tsx`
- Modify: `tests/test_saas_company_api.py`
- Modify/Create: tests ciblés du lieu et de la remise en file
- Modify: goldens Playwright Signaux et Entreprises

- [ ] **Step 1: Écrire les tests du contrat validé**

Couvrir l’unicité des composants, la navigation avec retour, les lieux
techniques absents, les trois états Contact, le non-débit de quota lors de la
remise en file et l’unique bouton primaire.

- [ ] **Step 2: Lancer uniquement les tests ciblés**

Exécuter les fichiers frontend concernés, les tests backend du lieu et des
entreprises, le contrat quatre canaux, puis les quatre goldens concernés.

- [ ] **Step 3: Vérifier CI, fusionner et déployer depuis `main`**

La fusion et la production restent conditionnées à la CI verte et à une
nouvelle vérification du SHA exact.
