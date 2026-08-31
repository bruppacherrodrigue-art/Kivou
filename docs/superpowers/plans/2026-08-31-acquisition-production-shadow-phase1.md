# Acquisition en production, phase 1 — plan d'implémentation

> **Pour les agents :** SOUS-SKILL REQUISE — utiliser `superpowers:subagent-driven-development` (recommandé) ou `superpowers:executing-plans` pour exécuter ce plan tâche par tâche. Les étapes sont des cases à cocher (`- [ ]`).

**But :** faire tourner la chaîne d'acquisition en production, en `SHADOW`, sans qu'aucun chemin d'envoi n'existe dans cet environnement.

**Architecture :** le runtime livré est un banc d'essai de staging verrouillé par ses types. On ouvre un second environnement `PRODUCTION` en gardant toutes les bornes de volume, on remplace l'allowlist d'opérateur par une sélection déterministe d'une opportunité française par cycle, et on rend la liaison de destinataire QA structurellement impossible hors staging. Le chemin staging reste fonctionnellement identique.

**Pile :** Python 3.12, Pydantic v2, SQLAlchemy Core, Alembic, pytest, systemd, `uv`.

**Spec :** `docs/superpowers/specs/2026-08-31-acquisition-production-shadow-phase1-design.md`

## Contraintes globales

- Socle : `origin/main` à `c8ea78c`. Rebaser avant de commencer.
- **Aucune migration.** La phase 1 n'ajoute ni ne modifie aucune table. La tête reste `0028_card_presentation`.
- **Le staging ne change pas de comportement.** Toute modification d'un chemin `STAGING` doit être une extension, jamais une substitution. La garantie mécanique porte sur trois artefacts : `src/signals/acquisition_runtime/transport.py`, `src/signals/operations/qa_policy_window.py` et `tests/test_acquisition_runtime_execution.py`, qui gardent un diff nul.
- **Un test qui affirme « la production est impossible » n'est pas un test de comportement staging** : c'est un test de périmètre, périmé par conception. Deux existent et changent — `test_capability_rejects_environment_registry_and_dependency_drift` (santé) et `test_runtime_is_staging_only` (config). Les amender ne viole pas la contrainte ci-dessus.
- `maximum_suppliers` et `maximum_contacts` restent `Literal[1]`. Aucune tâche ne les touche.
- `mode` reste `Literal[RuntimeExecutionMode.SHADOW]`. Aucune tâche ne l'élargit.
- `transport.py` n'est **pas modifié**. Son garde est déjà correct ; on ajoute la preuve.
- Aucun secret, aucune adresse, aucun objet fournisseur brut, aucun prompt ni réponse de modèle dans un journal, un message d'exception ou une sortie de CLI.
- Les commandes lisent `KIVOU_DATABASE_URL` depuis l'environnement ; jamais d'URL ni d'horloge en argument.
- Tests : `uv run pytest`. Lint : `uv run ruff check`. **Pas de contrôle de types** : `mypy` n'est pas une dépendance de ce projet.

### Réconciliation de nommage, à lire avant la tâche 1

Le champ `AcquisitionRuntimeDeployment.qa_scope` porte le triplet pays / langue / wedge, choisi par l'opérateur, que la production utilise à l'identique. **Il garde son nom.** Le renommer ferait bouger `execution.py`, `composition.py` et `qa_policy_window.py` sans bénéfice.

Ce que la spec appelle « aucun champ QA en production » désigne précisément trois champs, qui deviennent interdits en production : `qa_recipient_identity_hmac`, `qa_recipient_key_version`, `qa_provider_mutations_capable` — plus les deux variables d'environnement `KIVOU_ACQUISITION_QA_RECIPIENT` et `KIVOU_ACQUISITION_QA_RECIPIENT_KEY`.

---

## Structure des fichiers

| Fichier | Responsabilité | Tâches |
| --- | --- | --- |
| `src/signals/acquisition_runtime/contracts.py` | ouvre `PRODUCTION` dans les contrats, interdit les champs QA hors staging | 1 |
| `src/signals/acquisition_runtime/config.py` | charge une configuration de production, refuse toute trace de QA | 2 |
| `src/signals/acquisition_runtime/cli.py` | refuse `--allow-qa-provider-mutations` en production | 3 |
| `src/signals/acquisition_runtime/selection.py` *(créé)* | choisit une opportunité française par cycle, de façon déterministe | 5 |
| `src/signals/acquisition_runtime/execution.py` | câble la sélection en production, garde le chemin staging | 6 |
| `tests/test_acquisition_runtime_production_invariants.py` *(créé)* | verrouille les invariants 5 et 6 de la spec | 7 |
| `src/signals/operations/policy_bootstrap.py` *(créé)* | écrit le premier contrôle Policy d'un environnement | 8 |
| `src/signals/operations/cli.py` | expose `bootstrap-policy-control` | 8 |
| `ops/systemd/kivou-acquisition-production.{service,timer}` *(créés)* | unités de production | 9 |
| `ops/examples/acquisition-production.{env,json}.example` *(créés)* | gabarits non déployables | 9 |
| `docs/runbooks/12-acquisition-production-shadow.md` *(créé)* | procédure d'installation et de retour arrière | 9 |

---

### Task 1 : ouvrir `PRODUCTION` dans les contrats

**Files:**
- Modify: `src/signals/acquisition_runtime/contracts.py`
- Test: `tests/test_acquisition_runtime_contracts_production.py` *(créé)*

**Interfaces:**
- Consomme : rien.
- Produit : `ACQUISITION_PRODUCTION_SCHEMA_VERSION = "acquisition-production-v1"` ; `AcquisitionRuntimeDeployment` acceptant les deux `schema_version` ; `AcquisitionRuntimeConfig.environment: Literal["STAGING", "PRODUCTION"]` ; `RuntimeCapabilityEvidence.environment: Literal["STAGING", "PRODUCTION"]` et `qa_only: bool`.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_acquisition_runtime_contracts_production.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.acquisition_runtime.contracts import (
    ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
    AcquisitionRuntimeDeployment,
)

LIMITS = {
    "maximum_cycle_cost": "10.00",
    "maximum_suppliers": 1,
    "maximum_contacts": 1,
    "maximum_provider_operations": 4,
    "maximum_wall_seconds": 900,
    "lease_seconds": 1200,
}
SCOPE = {"country": "FR", "language": "fr", "wedge": "construction"}


def _production_document(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": ACQUISITION_PRODUCTION_SCHEMA_VERSION,
        "mode": "SHADOW",
        "qa_scope": SCOPE,
        "limits": LIMITS,
    }
    value.update(updates)
    return value


def test_production_deployment_omits_every_qa_binding() -> None:
    deployment = AcquisitionRuntimeDeployment.model_validate(_production_document())
    assert deployment.schema_version == ACQUISITION_PRODUCTION_SCHEMA_VERSION
    assert deployment.qa_only is False
    assert deployment.qa_recipient_identity_hmac is None
    assert deployment.qa_recipient_key_version is None
    assert deployment.qa_provider_mutations_capable is False
    assert deployment.allowed_opportunity_keys == ()


@pytest.mark.parametrize(
    "field, value",
    [
        ("qa_recipient_identity_hmac", "0" * 64),
        ("qa_recipient_key_version", "qa-recipient-key-v1"),
        ("qa_provider_mutations_capable", True),
        ("allowed_opportunity_keys", ["opportunity-001"]),
    ],
)
def test_production_deployment_rejects_any_qa_binding(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AcquisitionRuntimeDeployment.model_validate(
            _production_document(**{field: value})
        )


def test_staging_deployment_still_requires_its_qa_binding() -> None:
    with pytest.raises(ValidationError):
        AcquisitionRuntimeDeployment.model_validate(
            {
                "schema_version": ACQUISITION_RUNTIME_SCHEMA_VERSION,
                "mode": "SHADOW",
                "qa_scope": SCOPE,
                "limits": LIMITS,
            }
        )
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_runtime_contracts_production.py -v`
Attendu : ÉCHEC avec `ImportError: cannot import name 'ACQUISITION_PRODUCTION_SCHEMA_VERSION'`.

- [ ] **Étape 3 : implémenter**

Dans `contracts.py`, ajouter la constante sous `ACQUISITION_RUNTIME_SCHEMA_VERSION` :

```python
ACQUISITION_PRODUCTION_SCHEMA_VERSION = "acquisition-production-v1"
```

Remplacer la déclaration de `AcquisitionRuntimeDeployment` par :

```python
class AcquisitionRuntimeDeployment(_FrozenModel):
    schema_version: Literal[
        "acquisition-runtime-v1", "acquisition-production-v1"
    ] = ACQUISITION_RUNTIME_SCHEMA_VERSION
    mode: Literal[RuntimeExecutionMode.SHADOW] = RuntimeExecutionMode.SHADOW
    qa_only: bool = False
    allowed_opportunity_keys: tuple[OpaqueRef, ...] = Field(
        default=(), max_length=8
    )
    qa_scope: RuntimeQaScope
    qa_recipient_identity_hmac: Fingerprint | None = Field(default=None, repr=False)
    qa_recipient_key_version: OpaqueRef | None = None
    qa_provider_mutations_capable: bool = False
    limits: AcquisitionRuntimeLimits

    @property
    def is_production(self) -> bool:
        return self.schema_version == ACQUISITION_PRODUCTION_SCHEMA_VERSION

    @model_validator(mode="after")
    def bindings_match_schema(self) -> AcquisitionRuntimeDeployment:
        if len(self.allowed_opportunity_keys) != len(
            set(self.allowed_opportunity_keys)
        ):
            raise ValueError("runtime opportunity allowlist must be unique")
        qa_bindings = (
            self.qa_recipient_identity_hmac,
            self.qa_recipient_key_version,
        )
        if self.is_production:
            if (
                any(item is not None for item in qa_bindings)
                or self.qa_only
                or self.qa_provider_mutations_capable
                or self.allowed_opportunity_keys
            ):
                raise ValueError("production runtime forbids every QA binding")
            return self
        if (
            any(item is None for item in qa_bindings)
            or not self.qa_only
            or not self.qa_provider_mutations_capable
            or not self.allowed_opportunity_keys
        ):
            raise ValueError("staging runtime requires its complete QA binding")
        return self
```

Élargir ensuite les deux littéraux d'environnement :

```python
class RuntimeCapabilityEvidence(_FrozenModel):
    environment: Literal["STAGING", "PRODUCTION"]
    mode: Literal[RuntimeExecutionMode.SHADOW] = RuntimeExecutionMode.SHADOW
    qa_only: bool
    ...


class AcquisitionRuntimeConfig(_FrozenModel):
    environment: Literal["STAGING", "PRODUCTION"]
    deployment_path: Path
    deployment: AcquisitionRuntimeDeployment = Field(repr=False)
    qa_recipient: SecretStr | None = Field(default=None, repr=False)
    qa_recipient_hmac_key: SecretStr | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def recipient_matches_environment(self) -> AcquisitionRuntimeConfig:
        has_recipient = (
            self.qa_recipient is not None or self.qa_recipient_hmac_key is not None
        )
        if self.environment == "PRODUCTION" and has_recipient:
            raise ValueError("production runtime forbids a fallback recipient")
        if self.environment == "STAGING" and not (
            self.qa_recipient is not None and self.qa_recipient_hmac_key is not None
        ):
            raise ValueError("staging runtime requires its QA recipient binding")
        return self
```

Ajouter `ACQUISITION_PRODUCTION_SCHEMA_VERSION` à `__all__`.

Adapter `normalized_qa_recipient()` pour lever explicitement quand la boîte est absente :

```python
    def normalized_qa_recipient(self) -> str:
        if self.qa_recipient is None:
            raise ValueError("runtime has no QA recipient")
        return str(
            TypeAdapter(EmailStr).validate_python(
                self.qa_recipient.get_secret_value()
            )
        ).strip().casefold()
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_acquisition_runtime_contracts_production.py tests/test_acquisition_runtime_config.py tests/test_acquisition_runtime_transport.py -v`
Attendu : tout passe. Le fichier `test_acquisition_runtime_config.py` **n'est pas modifié** : c'est la preuve que le staging n'a pas bougé.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/acquisition_runtime/contracts.py tests/test_acquisition_runtime_contracts_production.py
git commit -m "feat(acquisition): ouvrir un déploiement de production sans liaison QA"
```

---

### Task 2 : charger une configuration de production

**Files:**
- Modify: `src/signals/acquisition_runtime/config.py:67-92`
- Test: `tests/test_acquisition_runtime_config_production.py` *(créé)*

**Interfaces:**
- Consomme : `AcquisitionRuntimeDeployment`, `AcquisitionRuntimeConfig` (tâche 1).
- Produit : `load_runtime_config()` acceptant `KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION` et renvoyant un `AcquisitionRuntimeConfig` sans destinataire.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_acquisition_runtime_config_production.py
from __future__ import annotations

import json

import pytest

from signals.acquisition_runtime.config import (
    RuntimeConfigurationError,
    load_runtime_config,
)
from signals.acquisition_runtime.contracts import (
    ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    ACQUISITION_RUNTIME_SCHEMA_VERSION,
)

DOCUMENT = {
    "schema_version": ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    "mode": "SHADOW",
    "qa_scope": {"country": "FR", "language": "fr", "wedge": "construction"},
    "limits": {
        "maximum_cycle_cost": "10.00",
        "maximum_suppliers": 1,
        "maximum_contacts": 1,
        "maximum_provider_operations": 4,
        "maximum_wall_seconds": 900,
        "lease_seconds": 1200,
    },
}


def _write(tmp_path, document: dict[str, object]):
    path = tmp_path / "acquisition-production.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _environment(path, **updates: str) -> dict[str, str]:
    value = {
        "KIVOU_ACQUISITION_ENVIRONMENT": "PRODUCTION",
        "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
    }
    value.update(updates)
    return value


def test_production_configuration_loads_without_any_recipient(tmp_path) -> None:
    path = _write(tmp_path, DOCUMENT)
    config = load_runtime_config(_environment(path))
    assert config.environment == "PRODUCTION"
    assert config.qa_recipient is None
    assert config.qa_recipient_hmac_key is None
    assert config.deployment.is_production is True


@pytest.mark.parametrize(
    "name",
    ["KIVOU_ACQUISITION_QA_RECIPIENT", "KIVOU_ACQUISITION_QA_RECIPIENT_KEY"],
)
def test_production_refuses_to_start_when_a_fallback_recipient_is_present(
    tmp_path, name: str
) -> None:
    path = _write(tmp_path, DOCUMENT)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path, **{name: "someone@example.com"}))
    assert error.value.code == "PRODUCTION_FORBIDS_FALLBACK_RECIPIENT"


def test_production_rejects_a_staging_shaped_document(tmp_path) -> None:
    path = _write(
        tmp_path, {**DOCUMENT, "schema_version": ACQUISITION_RUNTIME_SCHEMA_VERSION}
    )
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path))
    assert error.value.code == "WRONG_DEPLOYMENT_SCHEMA"


def test_staging_rejects_a_production_shaped_document(tmp_path) -> None:
    path = _write(tmp_path, DOCUMENT)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(
            {
                "KIVOU_ACQUISITION_ENVIRONMENT": "STAGING",
                "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
                "KIVOU_ACQUISITION_QA_RECIPIENT": "qa@example.com",
                "KIVOU_ACQUISITION_QA_RECIPIENT_KEY": "key",
            }
        )
    assert error.value.code == "WRONG_DEPLOYMENT_SCHEMA"


def test_an_unknown_environment_is_still_refused(tmp_path) -> None:
    path = _write(tmp_path, DOCUMENT)
    with pytest.raises(RuntimeConfigurationError) as error:
        load_runtime_config(_environment(path, KIVOU_ACQUISITION_ENVIRONMENT="UNCONFIGURED"))
    assert error.value.code == "WRONG_ENVIRONMENT"
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_runtime_config_production.py -v`
Attendu : ÉCHEC, `RuntimeConfigurationError: ... WRONG_ENVIRONMENT` sur le premier test.

- [ ] **Étape 3 : implémenter**

Remplacer `load_runtime_config` par :

```python
def _load_production(
    source: Mapping[str, str], path: Path, deployment: AcquisitionRuntimeDeployment
) -> AcquisitionRuntimeConfig:
    for name in (
        "KIVOU_ACQUISITION_QA_RECIPIENT",
        "KIVOU_ACQUISITION_QA_RECIPIENT_KEY",
    ):
        # PRÉSENCE, pas véracité : `KIVOU_ACQUISITION_QA_RECIPIENT=` déclaré vide
        # par une substitution de gabarit ratée doit refuser le démarrage, pas
        # passer pour une absence. La spec dit « seulement présents ».
        if name in source:
            raise RuntimeConfigurationError("PRODUCTION_FORBIDS_FALLBACK_RECIPIENT")
    if not deployment.is_production:
        raise RuntimeConfigurationError("WRONG_DEPLOYMENT_SCHEMA")
    try:
        return AcquisitionRuntimeConfig(
            environment="PRODUCTION",
            deployment_path=path,
            deployment=deployment,
        )
    except (TypeError, ValueError, ValidationError):
        raise RuntimeConfigurationError("NOT_CONFIGURED") from None


def _load_staging(
    source: Mapping[str, str], path: Path, deployment: AcquisitionRuntimeDeployment
) -> AcquisitionRuntimeConfig:
    if deployment.is_production:
        raise RuntimeConfigurationError("WRONG_DEPLOYMENT_SCHEMA")
    recipient = _required(source, "KIVOU_ACQUISITION_QA_RECIPIENT")
    key = _required(source, "KIVOU_ACQUISITION_QA_RECIPIENT_KEY")
    try:
        config = AcquisitionRuntimeConfig(
            environment="STAGING",
            deployment_path=path,
            deployment=deployment,
            qa_recipient=recipient,
            qa_recipient_hmac_key=key,
        )
        normalized = config.normalized_qa_recipient()
    except (TypeError, ValueError, ValidationError):
        raise RuntimeConfigurationError("NOT_CONFIGURED") from None
    observed = _identity_hmac(normalized, key)
    assert deployment.qa_recipient_identity_hmac is not None
    if not hmac.compare_digest(observed, deployment.qa_recipient_identity_hmac):
        raise RuntimeConfigurationError("QA_RECIPIENT_BINDING_MISMATCH")
    return config


def load_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> AcquisitionRuntimeConfig:
    source = os.environ if environ is None else environ
    environment = _required(source, "KIVOU_ACQUISITION_ENVIRONMENT")
    if environment not in {"STAGING", "PRODUCTION"}:
        raise RuntimeConfigurationError("WRONG_ENVIRONMENT")
    path = Path(_required(source, "KIVOU_ACQUISITION_RUNTIME_CONFIG"))
    deployment = _deployment(path)
    if environment == "PRODUCTION":
        return _load_production(source, path, deployment)
    return _load_staging(source, path, deployment)
```

Mettre à jour le docstring du module : `"""Strict acquisition runtime configuration loader for staging and production."""`

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_acquisition_runtime_config_production.py tests/test_acquisition_runtime_config.py -v`
Attendu : tout passe, sans avoir touché le fichier de test du staging.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/acquisition_runtime/config.py tests/test_acquisition_runtime_config_production.py
git commit -m "feat(acquisition): charger une configuration de production sans destinataire de repli"
```

---

### Task 2B : ouvrir `PRODUCTION` dans le module de connectivité

**Files:**
- Modify: `src/signals/acquisition_connectivity/contracts.py:100` et `:187`
- Modify: `src/signals/acquisition_connectivity/config.py:80-85`
- Modify: `src/signals/acquisition_connectivity/service.py:275`
- Test: `tests/test_acquisition_connectivity_production.py` *(créé)*

**Pourquoi cette tâche existe.** Elle ne figurait pas au plan initial. `build_runtime_execution_composition` exige un `AcquisitionConnectivityConfig`, et `python -m signals.acquisition_runtime check-dependencies` — la commande que le runbook de production fait tourner — passe par ce module. Or `load_connectivity_config` lève `WRONG_ENVIRONMENT` hors `STAGING`, le préflight de `service.py` refuse de même, et les deux contrats portent `Literal["STAGING"]`. Sans cette tâche, les tâches 6 et 9 sont impossibles.

**Interfaces:**
- Consomme : rien des tâches précédentes.
- Produit : `load_connectivity_config()` acceptant `PRODUCTION` ; `AcquisitionConnectivityConfig.environment: Literal["STAGING", "PRODUCTION"]`.

**Ce qui ne change pas.** Le préflight garde toutes ses autres exigences : Policy en `SHADOW`, `read_only`, coupe-circuit armé. Ce sont précisément les propriétés du contrôle d'amorçage de la tâche 8, donc l'ouverture est cohérente et n'affaiblit rien. Le document de déploiement de connectivité — référence de workspace Instantly et trois mailboxes — garde exactement la même forme dans les deux environnements : il n'y a pas ici de champ propre à la QA.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_acquisition_connectivity_production.py
from __future__ import annotations

import pytest

from signals.acquisition_connectivity.config import load_connectivity_config
from signals.acquisition_connectivity.contracts import ConnectivityFailure


def test_production_connectivity_configuration_loads(production_connectivity_environment) -> None:
    config = load_connectivity_config(production_connectivity_environment)
    assert config.environment == "PRODUCTION"


def test_staging_connectivity_configuration_still_loads(staging_connectivity_environment) -> None:
    config = load_connectivity_config(staging_connectivity_environment)
    assert config.environment == "STAGING"


@pytest.mark.parametrize("value", ["production", "LOCAL", "", "UNCONFIGURED"])
def test_unknown_environments_are_still_refused(
    staging_connectivity_environment, value: str
) -> None:
    values = dict(staging_connectivity_environment)
    values["KIVOU_ACQUISITION_ENVIRONMENT"] = value
    with pytest.raises(ConnectivityFailure):
        load_connectivity_config(values)
```

> Construire les deux fixtures d'environnement localement, en reprenant le montage de `tests/test_acquisition_connectivity_config.py` — mêmes variables, même document de déploiement, seul `KIVOU_ACQUISITION_ENVIRONMENT` change. Relever au passage le nom exact de l'exception et du code d'erreur : la CLI et le service peuvent ne pas lever le même type.

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_connectivity_production.py -v`
Attendu : ÉCHEC sur le premier test, `WRONG_ENVIRONMENT`.

- [ ] **Étape 3 : implémenter**

Dans `contracts.py`, élargir les deux littéraux :

```python
    environment: Literal["STAGING", "PRODUCTION"] = "STAGING"
```

```python
    environment: Literal["STAGING", "PRODUCTION"]
```

Dans `config.py`, accepter les deux environnements et transmettre celui qui a été lu — ne pas réécrire une valeur en dur :

```python
    environment = _required(source, "KIVOU_ACQUISITION_ENVIRONMENT")
    if environment not in {"STAGING", "PRODUCTION"}:
        raise ConnectivityFailure(ConnectivityErrorCode.WRONG_ENVIRONMENT)
    shadow_path = _absolute_path(source, "KIVOU_ACQUISITION_SHADOW_CONFIG")
    return AcquisitionConnectivityConfig(
        environment=environment,
        ...
    )
```

Dans `service.py`, remplacer le refus du préflight :

```python
        if self._config.environment not in {"STAGING", "PRODUCTION"}:
            raise ConnectivityFailure(ConnectivityErrorCode.WRONG_ENVIRONMENT)
```

Ne toucher à aucune autre exigence du préflight.

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_acquisition_connectivity_production.py tests/test_acquisition_connectivity_config.py tests/test_acquisition_connectivity_service.py tests/test_acquisition_connectivity_architecture.py -q`
Attendu : tout passe, y compris les tests de connectivité préexistants, non modifiés.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/acquisition_connectivity tests/test_acquisition_connectivity_production.py
git commit -m "feat(acquisition): ouvrir la connectivité fournisseur à l'environnement de production"
```

---

### Task 3 : refuser la porte de mutation QA en production

**Files:**
- Modify: `src/signals/acquisition_runtime/cli.py:92-132`
- Test: `tests/test_acquisition_runtime_cli.py` *(étendu)*

**Interfaces:**
- Consomme : `load_runtime_config` (tâche 2).
- Produit : `main(["run-once", "--allow-qa-provider-mutations"])` renvoie `2` et imprime `status=INVALID_ARGUMENTS` quand l'environnement vaut `PRODUCTION`.

- [ ] **Étape 1 : écrire le test qui échoue**

Ajouter à la fin de `tests/test_acquisition_runtime_cli.py` :

```python
def test_production_refuses_the_qa_mutation_gate(monkeypatch, capsys) -> None:
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "PRODUCTION")
    called = False

    def execute(_allow: bool):
        nonlocal called
        called = True
        raise AssertionError("the runtime must not be reached")

    from signals.acquisition_runtime.cli import main

    code = main(["run-once", "--allow-qa-provider-mutations"], execute=execute)
    assert code == 2
    assert called is False
    assert "status=INVALID_ARGUMENTS" in capsys.readouterr().err


def test_staging_still_accepts_the_qa_mutation_gate(monkeypatch) -> None:
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    seen: list[bool] = []

    from signals.acquisition_runtime.contracts import RuntimeRunResult, RuntimeRunStatus
    from signals.acquisition_runtime.cli import main

    def execute(allow: bool) -> RuntimeRunResult:
        seen.append(allow)
        return RuntimeRunResult(status=RuntimeRunStatus.COMPLETED)

    assert main(["run-once", "--allow-qa-provider-mutations"], execute=execute) == 0
    assert seen == [True]
```

> Avant d'écrire l'étape 3, ouvrir `src/signals/acquisition_runtime/contracts.py` et confirmer le nom exact du statut terminal et la valeur de `exit_code` associée. Remplacer `RuntimeRunStatus.COMPLETED` par la valeur réelle si elle diffère, dans le test comme dans l'implémentation.

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_runtime_cli.py -k production_refuses -v`
Attendu : ÉCHEC — le code de retour vaut `0` ou `1`, pas `2`.

- [ ] **Étape 3 : implémenter**

Dans `cli.py`, juste après `assert arguments.command == "run-once"` :

```python
    if bool(arguments.allow_qa_provider_mutations) and (
        (os.environ.get("KIVOU_ACQUISITION_ENVIRONMENT") or "").strip().upper()
        == "PRODUCTION"
    ):
        print("status=INVALID_ARGUMENTS", file=sys.stderr)
        return 2
```

Ajouter `import os` en tête de module et compléter l'aide de l'argument :

```python
    run_once.add_argument(
        "--allow-qa-provider-mutations",
        action="store_true",
        help="manual staging-only gate; rejected in production",
    )
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_acquisition_runtime_cli.py -v`
Attendu : PASS, y compris tous les tests préexistants du fichier.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/acquisition_runtime/cli.py tests/test_acquisition_runtime_cli.py
git commit -m "feat(acquisition): refuser la porte de mutation QA hors staging"
```

---

### Task 4 : prouver qu'aucun destinataire de repli n'est constructible en production

**Files:**
- Test: `tests/test_acquisition_runtime_transport.py` *(étendu)*
- Modify: aucun fichier source. `transport.py` reste tel quel.

**Interfaces:**
- Consomme : `StagingQaRecipientOverride` (existant), configuration de production (tâches 1 et 2).
- Produit : rien. Cette tâche ne livre qu'une preuve.

Cette tâche n'ajoute aucun comportement. Elle verrouille l'invariant nº 1 de la spec pour que toute régression future casse la suite.

- [ ] **Étape 1 : écrire le test**

Ajouter à la fin de `tests/test_acquisition_runtime_transport.py`, en réutilisant `_transport_keyring()` déjà défini ligne 17 de ce fichier :

```python
def test_production_configuration_cannot_build_a_recipient_override(tmp_path) -> None:
    import json

    from signals.acquisition_runtime.config import load_runtime_config
    from signals.acquisition_runtime.contracts import (
        ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    )

    path = tmp_path / "acquisition-production.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": ACQUISITION_PRODUCTION_SCHEMA_VERSION,
                "mode": "SHADOW",
                "qa_scope": {
                    "country": "FR",
                    "language": "fr",
                    "wedge": "construction",
                },
                "limits": {
                    "maximum_cycle_cost": "10.00",
                    "maximum_suppliers": 1,
                    "maximum_contacts": 1,
                    "maximum_provider_operations": 4,
                    "maximum_wall_seconds": 900,
                    "lease_seconds": 1200,
                },
            }
        ),
        encoding="utf-8",
    )
    config = load_runtime_config(
        {
            "KIVOU_ACQUISITION_ENVIRONMENT": "PRODUCTION",
            "KIVOU_ACQUISITION_RUNTIME_CONFIG": str(path),
        }
    )
    with pytest.raises(ValueError, match="staging QA runtime"):
        StagingQaRecipientOverride(config, transport_keyring=_transport_keyring())
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il passe immédiatement**

Commande : `uv run pytest tests/test_acquisition_runtime_transport.py -v`
Attendu : PASS sans modifier une seule ligne de code source. Si le test échoue, `transport.py` a une faille réelle : arrêter, signaler, et traiter cela comme une correction avant de poursuivre.

- [ ] **Étape 3 : commit**

```bash
git add tests/test_acquisition_runtime_transport.py
git commit -m "test(acquisition): verrouiller l'absence de destinataire de repli en production"
```

---

### Task 5 : sélection déterministe de l'opportunité du cycle

**Files:**
- Create: `src/signals/acquisition_runtime/selection.py`
- Test: `tests/test_acquisition_runtime_selection.py` *(créé)*

**Interfaces:**
- Consomme : `opportunity_representation`, `contract_award`, `source_event`, `acquisition_runtime_cycle` — toutes définies dans `signals.persistence.schema`.
- Produit :

```python
def select_production_opportunity_key(
    engine: Engine, *, country: str, observed_at: dt.datetime
) -> str | None
```

Le chemin de jointure est établi : `opportunity_representation.award_key` → `contract_award.award_key`, puis `contract_award.event_key` → `source_event.event_key`. Le pays vit dans `source_event.source_country`, la date dans `source_event.published_on` (type `Date`). Les cycles déjà joués vivent dans `acquisition_runtime_cycle.opportunity_key`.

Une opportunité porte plusieurs représentations : la requête regroupe donc par `opportunity_key` et retient la publication la plus récente du groupe.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_acquisition_runtime_selection.py
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.acquisition_runtime.selection import select_production_opportunity_key
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    contract_award,
    opportunity_representation,
    source_event,
)

NOW = dt.datetime(2026, 8, 31, 12, tzinfo=dt.UTC)


def _engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'selection.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    METADATA.create_all(
        engine,
        tables=[
            source_event,
            contract_award,
            opportunity_representation,
            acquisition_runtime_cycle,
        ],
    )
    return engine


def _seed(engine, *, key: str, country: str, published_on: dt.date) -> None:
    """Insère une opportunité minimale : un événement, un award, une représentation."""

    with engine.begin() as connection:
        connection.execute(
            sa.insert(source_event).values(
                event_key=f"event-{key}",
                source_system="BOAMP",
                source_notice_id=f"notice-{key}",
                source_country=country,
                event_type="AWARD",
                published_on=published_on,
                procedure_buyers=[],
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key=f"award-{key}",
                event_key=f"event-{key}",
                cpv_additional=[],
            )
        )
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key=f"award-{key}", opportunity_key=key
            )
        )


def _seed_cycle(engine, *, opportunity_key: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_runtime_cycle).values(
                cycle_ref=f"cycle-{opportunity_key}",
                opportunity_key=opportunity_key,
                config_fingerprint="f" * 64,
                status="SUCCEEDED",
                spent_cost=0,
                started_at=NOW,
                updated_at=NOW,
            )
        )


def test_no_eligible_opportunity_returns_none(tmp_path) -> None:
    assert (
        select_production_opportunity_key(
            _engine(tmp_path), country="FR", observed_at=NOW
        )
        is None
    )


def test_the_most_recent_french_opportunity_is_selected(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="ch-newest", country="CH", published_on=dt.date(2026, 8, 31))
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-newer"
    )


def test_an_opportunity_already_taken_by_a_cycle_is_never_selected_again(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-newer", country="FR", published_on=dt.date(2026, 8, 30))
    _seed(engine, key="fr-older", country="FR", published_on=dt.date(2026, 8, 28))
    _seed_cycle(engine, opportunity_key="fr-newer")
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        == "fr-older"
    )


def test_a_publication_in_the_future_is_not_selected(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-future", country="FR", published_on=dt.date(2026, 9, 30))
    assert (
        select_production_opportunity_key(engine, country="FR", observed_at=NOW)
        is None
    )


def test_selection_is_stable_across_two_reads(tmp_path) -> None:
    engine = _engine(tmp_path)
    _seed(engine, key="fr-one", country="FR", published_on=dt.date(2026, 8, 30))
    first = select_production_opportunity_key(engine, country="FR", observed_at=NOW)
    second = select_production_opportunity_key(engine, country="FR", observed_at=NOW)
    assert first == second == "fr-one"


def test_a_naive_timestamp_is_refused(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        select_production_opportunity_key(
            _engine(tmp_path),
            country="FR",
            observed_at=dt.datetime(2026, 8, 31, 12),
        )
```

> Si une colonne `nullable=False` sans valeur par défaut manque à l'un des trois `insert` ci-dessus, SQLite le signalera à l'exécution. Compléter alors le `values(...)` avec la valeur minimale plausible relevée dans `signals/persistence/schema.py` — ne pas rendre la colonne nullable.

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_runtime_selection.py -v`
Attendu : ÉCHEC avec `ModuleNotFoundError: No module named 'signals.acquisition_runtime.selection'`.

- [ ] **Étape 3 : implémenter**

```python
# src/signals/acquisition_runtime/selection.py
"""Sélection déterministe d'une opportunité de production par cycle."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    acquisition_runtime_cycle,
    contract_award,
    opportunity_representation,
    source_event,
)


def select_production_opportunity_key(
    engine: Engine, *, country: str, observed_at: dt.datetime
) -> str | None:
    """La plus récente opportunité du pays jamais retenue par un cycle.

    Déterministe : à base identique, deux appels rendent la même clé. Le
    départage se fait sur la clé elle-même, pour que deux publications de même
    date ne dépendent jamais de l'ordre de lecture du moteur.

    La preuve qu'une opportunité a déjà servi est l'enregistrement durable des
    cycles, jamais un fichier ni une mémoire de processus.
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("selection timestamp must be timezone-aware")
    horizon = observed_at.astimezone(dt.UTC).date()
    already_played = sa.select(acquisition_runtime_cycle.c.opportunity_key)
    latest = sa.func.max(source_event.c.published_on).label("latest")
    statement = (
        sa.select(opportunity_representation.c.opportunity_key, latest)
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            ).join(
                source_event,
                contract_award.c.event_key == source_event.c.event_key,
            )
        )
        .where(
            source_event.c.source_country == country,
            source_event.c.published_on.isnot(None),
            source_event.c.published_on <= horizon,
            opportunity_representation.c.opportunity_key.notin_(already_played),
        )
        .group_by(opportunity_representation.c.opportunity_key)
        .order_by(latest.desc(), opportunity_representation.c.opportunity_key.asc())
        .limit(1)
    )
    with engine.connect() as connection:
        row = connection.execute(statement).first()
    return None if row is None else str(row.opportunity_key)


__all__ = ["select_production_opportunity_key"]
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_acquisition_runtime_selection.py -v`
Attendu : six tests PASS.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/acquisition_runtime/selection.py tests/test_acquisition_runtime_selection.py
git commit -m "feat(acquisition): sélectionner une opportunité de production par cycle"
```

---

### Task 6 : câbler la sélection dans la composition de production

**Files:**
- Modify: `src/signals/acquisition_runtime/execution.py:483-700`
- Test: `tests/test_acquisition_runtime_execution_production.py` *(créé)*

**Interfaces:**
- Consomme : `select_production_opportunity_key` (tâche 5), configuration de production (tâche 2).
- Produit : `build_runtime_execution_composition()` acceptant une configuration de production ; code d'erreur `NO_ELIGIBLE_OPPORTUNITY` ; `RuntimeCapabilityEvidence` portant `environment="PRODUCTION"` et `qa_only=False`.

> Étape préparatoire obligatoire : ouvrir `tests/test_acquisition_runtime_execution.py` et relever le montage complet d'appel à `build_runtime_execution_composition` — doublures Apollo, Instantly, Hermes, `links`, `webhook_configuration`, moteur, horloge. Le réutiliser tel quel. Ne pas réinventer un montage : les préconditions de cette fonction sont nombreuses et un montage approximatif produira des échecs sans rapport avec la tâche.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_acquisition_runtime_execution_production.py
from __future__ import annotations

import pytest

from signals.acquisition_runtime.execution import (
    RuntimeExecutionConfigurationError,
    build_runtime_execution_composition,
)


def test_production_without_eligible_opportunity_fails_closed(
    production_arguments,
) -> None:
    with pytest.raises(RuntimeExecutionConfigurationError) as error:
        build_runtime_execution_composition(**production_arguments)
    assert "NO_ELIGIBLE_OPPORTUNITY" in str(error.value)


def test_production_composition_uses_the_selected_opportunity(
    production_arguments, seeded_french_opportunity
) -> None:
    composition = build_runtime_execution_composition(**production_arguments)
    assert composition.capability.environment == "PRODUCTION"
    assert composition.capability.qa_only is False
    assert composition.runner.allowed_opportunity_keys == (seeded_french_opportunity,)


def test_staging_composition_is_unchanged(staging_arguments) -> None:
    composition = build_runtime_execution_composition(**staging_arguments)
    assert composition.capability.environment == "STAGING"
    assert composition.capability.qa_only is True
```

> `production_arguments`, `staging_arguments` et `seeded_french_opportunity` sont des fixtures locales à écrire dans ce fichier, à partir du montage relevé à l'étape préparatoire. Le contrôle Policy que ce montage installe doit porter `allowed_countries=("FR",)`, `allowed_languages=("fr",)` et `allowed_wedges=("construction",)`, faute de quoi `_exact_scope` lèvera `POLICY_SCOPE_NOT_EXACT` avant d'atteindre la sélection.

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_runtime_execution_production.py -v`
Attendu : ÉCHEC avec `QA_SIGNAL_SCOPE_NOT_EXACT`, puisqu'une configuration de production n'a aucune allowlist.

- [ ] **Étape 3 : implémenter**

Dans `build_runtime_execution_composition`, remplacer le contrôle d'exactitude de l'allowlist (aujourd'hui ligne 547) par :

```python
    if runtime_config.deployment.is_production:
        selected = select_production_opportunity_key(
            engine,
            country=runtime_config.deployment.qa_scope.country,
            observed_at=observed_at,
        )
        if selected is None:
            raise RuntimeExecutionConfigurationError("NO_ELIGIBLE_OPPORTUNITY")
        opportunity_keys: tuple[str, ...] = (selected,)
    else:
        if len(runtime_config.deployment.allowed_opportunity_keys) != 1:
            raise RuntimeExecutionConfigurationError("QA_SIGNAL_SCOPE_NOT_EXACT")
        opportunity_keys = runtime_config.deployment.allowed_opportunity_keys
```

Remplacer ensuite les deux lectures directes de l'allowlist par `opportunity_keys` :

```python
        qa_signal_ref="procurement-opportunity:" + opportunity_keys[0],
```

```python
        allowed_opportunity_keys=opportunity_keys,
```

Faire porter l'environnement réel à l'évidence de capacité :

```python
def _runtime_capability(
    registry: AcquisitionActionRegistry,
    *,
    dependencies: tuple[RuntimeStageDependency, ...],
    runtime_config: AcquisitionRuntimeConfig,
) -> RuntimeCapabilityEvidence:
    pin = load_hermes_pin()
    return RuntimeCapabilityEvidence(
        environment=runtime_config.environment,
        mode="SHADOW",
        qa_only=runtime_config.deployment.qa_only,
        ...
    )
```

et son appel, aujourd'hui ligne 673 :

```python
    capability = _runtime_capability(
        registry, dependencies=dependencies, runtime_config=runtime_config
    )
```

Ajouter l'import en tête de `execution.py` :

```python
from signals.acquisition_runtime.selection import select_production_opportunity_key
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_acquisition_runtime_execution_production.py tests/test_acquisition_runtime_execution.py tests/test_acquisition_runtime_execution_policy.py -v`
Attendu : tout passe, y compris les tests d'exécution du staging, non modifiés.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/acquisition_runtime/execution.py tests/test_acquisition_runtime_execution_production.py
git commit -m "feat(acquisition): composer un cycle de production sur l'opportunité sélectionnée"
```

---

### Task 7 : verrouiller les invariants 5 et 6 de la spec

**Files:**
- Test: `tests/test_acquisition_runtime_production_invariants.py` *(créé)*
- Modify: aucun fichier source attendu. Si un test échoue, la correction fait partie de cette tâche.

**Interfaces:**
- Consomme : le montage de composition de production (tâche 6), `configure_acquisition_runtime_logging` (existant).
- Produit : rien. Deux preuves.

Ces deux invariants sont énoncés dans la spec comme vérifiés par des tests. Sans cette tâche, ils ne sont que des intentions.

> Étape préparatoire obligatoire : relever dans `tests/test_acquisition_runtime_events.py` la manière dont le journal est capturé et relu, et dans `tests/test_acquisition_runtime_execution.py` le nom des doublures fournisseur et la façon dont elles enregistrent leurs appels. Réutiliser les deux.

- [ ] **Étape 1 : écrire le test de l'invariant 5 — aucune mutation commerciale**

```python
# tests/test_acquisition_runtime_production_invariants.py
from __future__ import annotations

import sqlalchemy as sa

from signals.persistence.schema import acquisition_provider_operation


def test_a_production_cycle_emits_no_commercial_mutation(
    production_composition, production_engine, instantly_double
) -> None:
    """Invariant 5 : tout delta de mutation fournisseur vaut zéro."""

    production_composition.runner.run_once()
    assert instantly_double.mutating_calls == []
    with production_engine.connect() as connection:
        operations = connection.execute(
            sa.select(sa.func.count()).select_from(acquisition_provider_operation)
        ).scalar_one()
    assert operations == 0
```

> `instantly_double.mutating_calls` doit être la liste d'appels mutants qu'expose déjà la doublure Instantly des tests d'exécution. Si elle ne l'expose pas, l'ajouter à la doublure — pas au code de production. `production_composition.runner.run_once()` doit être remplacé par le nom réel de l'entrée du runner, relevé dans `src/signals/acquisition_runtime/runner.py`.

- [ ] **Étape 2 : écrire le test de l'invariant 6 — journal muet sur les secrets**

```python
def test_the_production_journal_never_carries_a_secret_or_an_address(
    production_composition, captured_journal
) -> None:
    """Invariant 6 : ni secret, ni adresse, ni objet fournisseur, ni prompt."""

    production_composition.runner.run_once()
    journal = captured_journal.text
    assert "@" not in journal
    for forbidden in ("api_key", "Bearer ", "password", "prompt", "completion"):
        assert forbidden not in journal.lower()
```

- [ ] **Étape 3 : lancer les tests**

Commande : `uv run pytest tests/test_acquisition_runtime_production_invariants.py -v`
Attendu : les deux PASS sans modification du code de production. Un échec est une découverte à traiter ici, et non à reporter : c'est le seul endroit du plan où ces invariants sont vérifiés.

- [ ] **Étape 4 : commit**

```bash
git add tests/test_acquisition_runtime_production_invariants.py
git commit -m "test(acquisition): verrouiller l'absence de mutation et de fuite en production"
```

---

### Task 8 : amorcer le premier contrôle Policy

**Files:**
- Create: `src/signals/operations/policy_bootstrap.py`
- Modify: `src/signals/operations/cli.py`
- Test: `tests/test_operations_policy_bootstrap.py` *(créé)*

**Interfaces:**
- Consomme : `PolicyStore.append_control`, `PolicyControlSnapshot`, `AutonomyMode`, `canonical_fingerprint` (`signals.operations.contracts`), `RUNTIME_COMMANDS` (`signals.operations.qa_policy_window`).
- Produit :

```python
class PolicyBootstrapError(RuntimeError): ...


def bootstrap_policy_control(
    engine: Engine,
    *,
    at: dt.datetime,
    actor_ref: str,
    reason_code: str,
    daily_cost_cap: Decimal,
    country: str,
    language: str,
    wedge: str,
) -> PolicyControlSnapshot
```

et la sous-commande `python -m signals.operations bootstrap-policy-control`.

**Le contrôle doit porter exactement un pays, une langue et un wedge.** `_exact_scope` dans `execution.py:311` refuse toute autre forme avec `POLICY_SCOPE_NOT_EXACT`, et un contrôle sans langue ni wedge ferait échouer chaque cycle de production. C'est la raison de la signature ci-dessus.

- [ ] **Étape 1 : écrire le test qui échoue**

```python
# tests/test_operations_policy_bootstrap.py
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from signals.operations.policy_bootstrap import (
    PolicyBootstrapError,
    bootstrap_policy_control,
)
from signals.persistence.schema import METADATA, acquisition_policy_snapshot
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore

NOW = dt.datetime(2026, 8, 31, 12, tzinfo=dt.UTC)


def _engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'policy.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    METADATA.create_all(engine, tables=[acquisition_policy_snapshot])
    return engine


def _bootstrap(engine):
    return bootstrap_policy_control(
        engine,
        at=NOW,
        actor_ref="operator:rodrigue",
        reason_code="ACQUISITION_PRODUCTION_SHADOW",
        daily_cost_cap=Decimal("30.00"),
        country="FR",
        language="fr",
        wedge="construction",
    )


def test_the_first_control_is_a_non_executable_shadow_authority(tmp_path) -> None:
    control = _bootstrap(_engine(tmp_path))
    assert control.control_revision == 1
    assert control.autonomy_mode is AutonomyMode.SHADOW
    assert control.shadow_target_mode is AutonomyMode.ASSISTED
    assert control.read_only is True
    assert control.kill_switch is True
    assert control.daily_volume_cap == 0
    assert control.currency == "CHF"
    assert control.daily_cost_cap == Decimal("30.00")
    assert control.created_by_actor_type == "HUMAN"


def test_the_scope_is_exact_so_a_cycle_can_compose(tmp_path) -> None:
    control = _bootstrap(_engine(tmp_path))
    assert control.allowed_countries == ("FR",)
    assert control.allowed_languages == ("fr",)
    assert control.allowed_wedges == ("construction",)
    assert control.allowed_commands != ()


def test_the_control_becomes_the_effective_one(tmp_path) -> None:
    engine = _engine(tmp_path)
    _bootstrap(engine)
    assert PolicyStore(engine).get_effective_control(NOW).control_revision == 1


def test_bootstrapping_twice_is_refused(tmp_path) -> None:
    engine = _engine(tmp_path)
    _bootstrap(engine)
    with pytest.raises(PolicyBootstrapError, match="CONTROL_ALREADY_EXISTS"):
        _bootstrap(engine)


def test_a_naive_timestamp_is_refused(tmp_path) -> None:
    with pytest.raises(PolicyBootstrapError, match="TIMESTAMP_NOT_AWARE"):
        bootstrap_policy_control(
            _engine(tmp_path),
            at=dt.datetime(2026, 8, 31, 12),
            actor_ref="operator:rodrigue",
            reason_code="ACQUISITION_PRODUCTION_SHADOW",
            daily_cost_cap=Decimal("30.00"),
            country="FR",
            language="fr",
            wedge="construction",
        )
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_operations_policy_bootstrap.py -v`
Attendu : ÉCHEC avec `ModuleNotFoundError: No module named 'signals.operations.policy_bootstrap'`.

- [ ] **Étape 3 : implémenter**

```python
# src/signals/operations/policy_bootstrap.py
"""Écriture explicite du tout premier contrôle Policy d'un environnement."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.operations.contracts import canonical_fingerprint
from signals.operations.qa_policy_window import RUNTIME_COMMANDS
from signals.policy.contracts import (
    AutonomyMode,
    PolicyControlSnapshot,
    PolicyControlUnavailable,
)
from signals.policy.store import PolicyStore


class PolicyBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(f"policy bootstrap error: {code}")
        self.code = code


def bootstrap_policy_control(
    engine: Engine,
    *,
    at: dt.datetime,
    actor_ref: str,
    reason_code: str,
    daily_cost_cap: Decimal,
    country: str,
    language: str,
    wedge: str,
) -> PolicyControlSnapshot:
    """Pose une autorité NON exécutable. Ce n'est pas un levier d'activation.

    Le mode reste SHADOW, la lecture seule et le coupe-circuit sont armés, et le
    plafond de volume vaut zéro. Le coupe-circuit n'entrave pas le cycle
    d'observation : il laisse passer les classes READ_ONLY, PREPARATORY,
    RISK_REDUCTION et HUMAN_REVIEW, et tout le cycle est PREPARATORY.
    """

    if at.tzinfo is None or at.utcoffset() is None:
        raise PolicyBootstrapError("TIMESTAMP_NOT_AWARE")
    if country not in {"CH", "FR"} or language not in {"fr", "en"} or not wedge:
        raise PolicyBootstrapError("SCOPE_INVALID")
    if not daily_cost_cap.is_finite() or daily_cost_cap <= 0:
        raise PolicyBootstrapError("COST_CAP_INVALID")
    store = PolicyStore(engine)
    try:
        store.get_latest_control()
    except PolicyControlUnavailable:
        pass
    else:
        raise PolicyBootstrapError("CONTROL_ALREADY_EXISTS")
    observed_at = at.astimezone(dt.UTC)
    fingerprint = canonical_fingerprint(
        "acquisition-policy-bootstrap:v1",
        {
            "control_revision": 1,
            "autonomy_mode": AutonomyMode.SHADOW.value,
            "shadow_target_mode": AutonomyMode.ASSISTED.value,
            "country": country,
            "language": language,
            "wedge": wedge,
            "currency": "CHF",
            "daily_cost_cap": str(daily_cost_cap),
            "effective_at": observed_at.isoformat(),
            "actor_ref": actor_ref,
            "reason_codes": (reason_code,),
        },
    )
    try:
        control = PolicyControlSnapshot(
            policy_snapshot_id=fingerprint,
            control_revision=1,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.ASSISTED,
            read_only=True,
            kill_switch=True,
            allowed_commands=RUNTIME_COMMANDS,
            allowed_countries=(country,),
            allowed_languages=(language,),
            allowed_wedges=(wedge,),
            currency="CHF",
            daily_cost_cap=daily_cost_cap,
            daily_volume_cap=0,
            effective_at=observed_at,
            snapshot_fingerprint=fingerprint,
            created_at=observed_at,
            created_by_actor_type="HUMAN",
            created_by_actor_ref=actor_ref,
            reason_codes=(reason_code,),
        )
    except (ValidationError, ValueError):
        raise PolicyBootstrapError("CONTROL_INVALID") from None
    store.append_control(control)
    return control


__all__ = ["PolicyBootstrapError", "bootstrap_policy_control"]
```

> Vérifier que `PolicyStore.get_latest_control()` lève bien `PolicyControlUnavailable` sur une table vide. Si elle renvoie `None`, remplacer le `try/except` par un test d'identité — l'important est de refuser dès qu'un contrôle existe.

Dans `src/signals/operations/cli.py`, ajouter la sous-commande :

```python
    bootstrap = commands.add_parser(
        "bootstrap-policy-control",
        help="append the very first non-executable Policy authority",
    )
    bootstrap.add_argument("--reason-code", required=True)
    bootstrap.add_argument("--actor", required=True)
    bootstrap.add_argument("--daily-cost-cap", required=True)
    bootstrap.add_argument("--country", required=True, choices=("CH", "FR"))
    bootstrap.add_argument("--language", required=True, choices=("fr", "en"))
    bootstrap.add_argument("--wedge", required=True)
```

et la branche correspondante dans `main`, avant la branche `activate-kill-switch` :

```python
    if arguments.command == "bootstrap-policy-control":
        from decimal import Decimal

        from signals.operations.policy_bootstrap import (
            PolicyBootstrapError,
            bootstrap_policy_control,
        )

        try:
            control = bootstrap_policy_control(
                engine,
                at=now,
                actor_ref=arguments.actor,
                reason_code=arguments.reason_code,
                daily_cost_cap=Decimal(arguments.daily_cost_cap),
                country=arguments.country,
                language=arguments.language,
                wedge=arguments.wedge,
            )
        except PolicyBootstrapError as error:
            print(f"acquisition_ops bootstrap status=REFUSED reason={error.code}")
            return 1
        print(
            "acquisition_ops bootstrap status=APPENDED "
            f"revision={control.control_revision} "
            f"autonomy={control.autonomy_mode.value} "
            "read_only=true kill_switch=true volume_cap=0"
        )
        return 0
```

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

Commande : `uv run pytest tests/test_operations_policy_bootstrap.py tests/test_acquisition_runtime_qa_policy_window.py -v`
Attendu : tout passe. La fenêtre QA du staging n'est pas affectée.

- [ ] **Étape 5 : commit**

```bash
git add src/signals/operations/policy_bootstrap.py src/signals/operations/cli.py tests/test_operations_policy_bootstrap.py
git commit -m "feat(operations): amorcer le premier contrôle Policy d'un environnement"
```

---

### Task 9 : unités, gabarits et runbook de production

**Files:**
- Create: `ops/systemd/kivou-acquisition-production.service`
- Create: `ops/systemd/kivou-acquisition-production.timer`
- Create: `ops/examples/acquisition-production.env.example`
- Create: `ops/examples/acquisition-production.json.example`
- Create: `docs/runbooks/12-acquisition-production-shadow.md`
- Test: `tests/test_acquisition_runtime_units.py` *(étendu)*

**Interfaces:**
- Consomme : tout ce qui précède.
- Produit : les artefacts installables. Aucune API Python.

- [ ] **Étape 1 : écrire le test qui échoue**

Ajouter à `tests/test_acquisition_runtime_units.py` :

```python
def test_the_production_unit_never_reads_a_staging_environment_file() -> None:
    from pathlib import Path

    unit = Path("ops/systemd/kivou-acquisition-production.service").read_text(
        encoding="utf-8"
    )
    assert "EnvironmentFile=/etc/kivou/production.env" in unit
    assert "EnvironmentFile=/etc/kivou/acquisition-production.env" in unit
    for forbidden in (
        "staging.env",
        "acquisition-shadow.env",
        "acquisition-runtime.env",
        "--allow-qa-provider-mutations",
    ):
        assert forbidden not in unit
    for hardening in (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "PrivateTmp=true",
        "RestrictSUIDSGID=true",
        "UMask=0077",
    ):
        assert hardening in unit


def test_the_production_example_declares_production_and_no_fallback_recipient() -> None:
    from pathlib import Path

    example = Path("ops/examples/acquisition-production.env.example").read_text(
        encoding="utf-8"
    )
    assert "KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION" in example
    assert "QA_RECIPIENT" not in example


def test_the_production_document_example_carries_no_qa_binding() -> None:
    import json
    from pathlib import Path

    document = json.loads(
        Path("ops/examples/acquisition-production.json.example").read_text(
            encoding="utf-8"
        )
    )
    assert document["schema_version"] == "acquisition-production-v1"
    for forbidden in (
        "qa_only",
        "qa_recipient_identity_hmac",
        "qa_recipient_key_version",
        "qa_provider_mutations_capable",
        "allowed_opportunity_keys",
    ):
        assert forbidden not in document
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Commande : `uv run pytest tests/test_acquisition_runtime_units.py -v`
Attendu : ÉCHEC avec `FileNotFoundError` sur l'unité de production.

- [ ] **Étape 3 : écrire les artefacts**

`ops/systemd/kivou-acquisition-production.service` — copie de `kivou-acquisition.service` avec trois différences seulement : la description, les `EnvironmentFile`, et `ReadWritePaths`.

```ini
[Unit]
Description=Kivou — cycle Acquisition PRODUCTION/SHADOW borné
Documentation=file:/srv/kivou/app/docs/runbooks/12-acquisition-production-shadow.md
Wants=network-online.target
After=network-online.target postgresql.service

[Service]
Type=oneshot
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/production.env
EnvironmentFile=/etc/kivou/acquisition-production.env
RuntimeDirectory=kivou
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 /run/kivou/acquisition.lock /srv/kivou/app/.venv/bin/python -m signals.acquisition_runtime run-once
TimeoutStartSec=25min
TimeoutStopSec=90s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-acquisition-production
UMask=0077

NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=/run/kivou /var/lib/kivou/hermes
```

`ops/systemd/kivou-acquisition-production.timer` :

```ini
[Unit]
Description=Kivou — déclenchement horaire Acquisition PRODUCTION/SHADOW

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300
AccuracySec=60
Unit=kivou-acquisition-production.service

[Install]
WantedBy=timers.target
```

`ops/examples/acquisition-production.env.example` :

```bash
# Gabarit de production. Aucune valeur réelle ici.
# Aucune boîte de repli : le runtime refuse de démarrer si l'une des variables
# KIVOU_ACQUISITION_QA_RECIPIENT* est seulement présente dans l'environnement.
KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION
KIVOU_ACQUISITION_RUNTIME_CONFIG=/etc/kivou/acquisition-production.json
KIVOU_APOLLO_API_KEY=
KIVOU_INSTANTLY_API_KEY=
KIVOU_HERMES_PYTHON=/opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python
KIVOU_HERMES_HOME=/var/lib/kivou/hermes
KIVOU_HERMES_CWD=/var/lib/kivou/hermes/work
```

`ops/examples/acquisition-production.json.example` :

```json
{
  "schema_version": "acquisition-production-v1",
  "mode": "SHADOW",
  "qa_scope": {
    "country": "FR",
    "language": "fr",
    "wedge": "construction"
  },
  "limits": {
    "maximum_cycle_cost": "10.00",
    "maximum_suppliers": 1,
    "maximum_contacts": 1,
    "maximum_provider_operations": 4,
    "maximum_wall_seconds": 900,
    "lease_seconds": 1200
  }
}
```

> Ouvrir `src/signals/acquisition_connectivity/config.py` et relever la liste **complète** des variables fournisseur réellement lues, puis compléter le gabarit `.env`. Une variable manquante ne se voit qu'au premier démarrage sur l'hôte, c'est-à-dire trop tard.

`docs/runbooks/12-acquisition-production-shadow.md` reprend la structure du runbook 10 et couvre, dans cet ordre :

1. préconditions et SHA approuvé issu de `main`, CI verte ;
2. **vérification que les clés Apollo et Instantly diffèrent de celles du staging**, par empreinte de clé, référence de workspace et références de mailbox — le runbook 07 l'exige, et la confusion Kivou/Turiya sur Stripe montre que ce contrôle n'est pas théorique ;
3. installation du runtime Hermes épinglé sous `/opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade`, en `root:root`, avec vérification de la version `0.20.4` ;
4. provisionnement des fichiers protégés par `sudoedit` — `acquisition-production.env` en `0600 root:kivou`, `acquisition-production.json` en `0640 root:kivou` ;
5. `python -m signals.operations bootstrap-policy-control --reason-code ACQUISITION_PRODUCTION_SHADOW --actor <ref> --daily-cost-cap 30.00 --country FR --language fr --wedge <wedge>` ;
6. `python -m signals.acquisition_runtime check-dependencies` ;
7. premier cycle manuel, puis lecture du journal ;
8. activation du timer et observation du premier tir automatique ;
9. le retour arrière de la spec, à l'identique.

- [ ] **Étape 4 : lancer les tests et vérifier qu'ils passent**

```bash
uv run pytest tests/test_acquisition_runtime_units.py -v
systemd-analyze verify ops/systemd/kivou-acquisition-production.service ops/systemd/kivou-acquisition-production.timer
```

Attendu : tests PASS ; `systemd-analyze verify` sans erreur. Sur une machine sans systemd, noter la vérification comme restant à faire sur l'hôte avant installation — et ne pas la déclarer faite.

- [ ] **Étape 5 : commit**

```bash
git add ops/systemd/kivou-acquisition-production.service ops/systemd/kivou-acquisition-production.timer ops/examples/acquisition-production.env.example ops/examples/acquisition-production.json.example docs/runbooks/12-acquisition-production-shadow.md tests/test_acquisition_runtime_units.py
git commit -m "ops(acquisition): livrer les unités, gabarits et runbook de production"
```

---

### Task 10 : vérification d'ensemble avant installation

**Files:** aucun. Cette tâche ne produit que des preuves.

- [ ] **Étape 1 : suite complète**

```bash
uv run pytest
```

Attendu : la suite entière passe. Relever le nombre de tests et le comparer au décompte d'avant le chantier : il doit avoir augmenté, jamais diminué.

- [ ] **Étape 2 : lint et types**

```bash
uv run ruff check
```

Attendu : aucun diagnostic. `mypy` n'est pas installé dans ce projet et n'est pas exécuté.

- [ ] **Étape 3 : prouver que le chemin staging n'a pas bougé**

```bash
git diff --stat origin/main -- \
  tests/test_acquisition_runtime_execution.py \
  src/signals/acquisition_runtime/transport.py \
  src/signals/operations/qa_policy_window.py
```

Attendu : **aucune ligne modifiée** dans ces trois fichiers. `tests/test_acquisition_runtime_config.py` a été retiré de cette liste : il porte `test_runtime_is_staging_only`, un test de périmètre que la phase 1 rend caduc par conception. Une différence signifie que le chemin staging a été touché, contrairement aux contraintes globales — arrêter et corriger.

- [ ] **Étape 4 : vérifier l'absence de migration**

```bash
git diff --stat origin/main -- src/signals/persistence/migrations/
```

Attendu : aucun fichier. La tête reste `0028_card_presentation`.

- [ ] **Étape 5 : ouvrir la pull request**

```bash
gh pr create --base main \
  --title "feat(acquisition): faire naître le mode PRODUCTION en SHADOW" \
  --body-file docs/superpowers/specs/2026-08-31-acquisition-production-shadow-phase1-design.md
```

L'installation sur l'hôte suit le runbook 12 et **n'appartient pas à ce plan** : elle demande une décision de release et l'accès aux secrets de production.
