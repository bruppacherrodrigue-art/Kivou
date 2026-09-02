# Page Signaux — lot A (défauts purs) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre la page `/app/signals` lisible par un commercial sans changer le sens du produit : feed complet, acheteur et lieu honnêtes, dates qualifiées, montants et typographie corrects.

**Architecture:** Backend : `feed_page` scanne par lots et compte les candidats affichables ; `view.py` et `factual_display.py` appliquent au buyer la même règle « nom ≠ identifiant » que pour le titulaire, et enrichissent le lieu d'un libellé de département dérivé du code postal. Frontend : adaptateurs et composants affichent ces champs, l'i18n gagne des libellés de statut et de date, le CSS corrige densité, badge et grille.

**Tech Stack:** Python 3.12, SQLAlchemy Core, FastAPI, pytest ; React 19, TypeScript, Vitest, Playwright, CSS modules.

**Spec:** `docs/superpowers/specs/2026-09-02-signals-feed-sales-fixes-design.md`

## Global Constraints

- Base de travail : worktree `.worktrees/signals-feed-sales-fixes`, branche `fix/signals-feed-sales-fixes`, partie de `9de4d0f` (tête de `design/acquisition-production-activation`, ce que staging exécute).
- Aucune migration Alembic. Aucun changement de `copy.py` (`WHY_NOW` est testé mot pour mot).
- Jamais fabriquer un nom depuis un identifiant. Jamais présenter une inférence comme un fait.
- Tout texte utilisateur existe en `fr` et `en` (`frontend/src/i18n/fr.ts`, `en.ts` ; `fr` porte le type `Dictionary`, donc une clé ajoutée en `fr` doit exister en `en`).
- Commandes : backend `uv run pytest -q tests/<fichier>` puis `uv run ruff check .` ; frontend depuis `frontend/` : `npx vitest --run <fichier>`, `npm run typecheck`, `npm run lint`.
- Base connue : `tests/test_acquisition_migration.py::test_projection_has_only_operationally_justified_indexes` échoue déjà sur la base (SQLite/alembic) — ne pas le corriger ici, l'ignorer.
- Les goldens Playwright (`frontend/tests/visual/reference-goldens/dashboard-signals-*.png`, tolérance 0,1 %) cassent dès qu'un pixel de la liste ou du détail change : on ne les régénère qu'UNE fois, en tâche 8. Ne pas lancer `npm run test:visual` entre-temps.
- Commits : messages en français, préfixe conventionnel (`fix(feed): …`), terminés par les deux lignes d'attribution de la session (Co-Authored-By + Claude-Session).

---

### Task 1 : le plafond de lecture compte les candidats affichables

**Files:**
- Modify: `src/signals/feed/query.py` (fonction `feed_page`, lignes ~398-438, et constantes près de `HISTORY_SCAN_BATCH`)
- Test: `tests/test_feed_pagination.py`

**Interfaces:**
- Consumes: `resolve_display_identity(connection, signals)`, `_reassess(row, owned, account_id, as_of)`, `policy.CANDIDATE_SCAN_CAP`.
- Produces: `RECENT_SCAN_BATCH: int = 200`, `RECENT_SCAN_ROW_FACTOR: int = 10` (module `signals.feed.query`), sans changement de signature de `feed_page` ni de `FeedPage`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `tests/test_feed_pagination.py` :

```python
# ─── Le plafond compte les candidats AFFICHABLES, pas les lignes lues ──────────


def _strip_legal_names(award):
    """Le cas DECP 2022 : un SIRET recopié en guise de nom."""
    parties = []
    for party in award.awardee_parties:
        members = [
            member.model_copy(
                update={
                    "organization": member.organization.model_copy(
                        update={"legal_name": member.organization.identifiers[0].value}
                    )
                }
            )
            for member in party.members
        ]
        parties.append(party.model_copy(update={"members": tuple(members)}))
    return award.model_copy(update={"awardee_parties": tuple(parties)})


def test_nameless_rows_do_not_consume_the_scan_cap(client, icp, engine, monkeypatch):
    """Staging, 2026-09-02 : 491 notifications DECP sans nom remplissaient les
    500 lignes lues et cachaient les signaux nommés matérialisés avant elles.
    Le plafond porte désormais sur les candidats qu'on peut montrer."""
    import sqlalchemy as sa

    from signals.feed import query
    from signals.persistence.schema import materialized_signal

    named = seed(engine, icp, count=1)[0]
    nameless: list[str] = []
    with engine.begin() as connection:
        for name in SIMAP_NAMES[1:4]:
            event, awards = simap_award(name)
            award = _strip_legal_names(awards[0].model_copy(update={"award_date": AWARDED_FROM}))
            nameless.append(materialize(connection, event, award, target_icp_id=icp).signal_key)
        # Les lignes sans nom sont les plus récemment matérialisées : c'est
        # exactement la situation qui masquait le signal nommé.
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key.in_(nameless))
            .values(materialized_at=dt.datetime(2026, 8, 18, 10, 0, tzinfo=dt.UTC))
        )
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 2)
    monkeypatch.setattr(query, "RECENT_SCAN_BATCH", 2)

    body = page(client, limit=50)
    assert [item["signal_id"] for item in body["items"]] == [named]
    assert body["excluded"]["without_display_name"] == 3
    assert body["page"]["scan_truncated"] is False


def test_the_row_ceiling_still_announces_truncation(client, icp, engine, monkeypatch):
    """Le plafond absolu de lignes lues borne le coût ; quand il tombe avant la
    fin, la troncature est dite, jamais tue."""
    from signals.feed import query

    seed(engine, icp, count=5)
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 1)
    monkeypatch.setattr(query, "RECENT_SCAN_BATCH", 1)
    monkeypatch.setattr(query, "RECENT_SCAN_ROW_FACTOR", 2)

    body = page(client, limit=50)
    assert body["page"]["scan_truncated"] is True
    assert len(body["items"]) == 1
```

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run pytest -q tests/test_feed_pagination.py -k "nameless_rows or row_ceiling"`
Expected: FAIL — `test_nameless_rows_do_not_consume_the_scan_cap` rend `[]` (le nommé n'est pas lu) ; `test_the_row_ceiling…` échoue sur `AttributeError: RECENT_SCAN_BATCH`.

- [ ] **Step 3: Implémenter le scan par lots**

Dans `src/signals/feed/query.py`, juste avant `def _date_window`, ajouter :

```python
RECENT_SCAN_BATCH = 200
"""Lignes relues par lot dans la vue Récentes, avant résolution d'identité."""

RECENT_SCAN_ROW_FACTOR = 10
"""Plafond absolu de lignes lues = `scan_cap × RECENT_SCAN_ROW_FACTOR`.

Le plafond `CANDIDATE_SCAN_CAP` compte les candidats AFFICHABLES : une
notification DECP sans dénomination sociale ne doit pas consommer la place d'un
signal nommé matérialisé avant elle (staging, 2026-09-02 : 491 lignes sans nom
pour 8 rendues). Le coût reste borné par ce second plafond, et son dépassement
est annoncé comme n'importe quelle troncature.
"""
```

Puis remplacer, dans `feed_page`, le bloc qui va de `# Une ligne de plus que le plafond` jusqu'à `without_name = len(candidates) - len(displayable)` inclus, par :

```python
    row_ceiling = scan_cap * RECENT_SCAN_ROW_FACTOR
    rows_read = 0
    displayable: list[FeedSignal] = []
    without_name = 0
    truncated = False
    while True:
        batch_limit = min(RECENT_SCAN_BATCH, row_ceiling - rows_read)
        # Une ligne de plus que le lot : c'est ainsi qu'on SAIT s'il en reste.
        rows = connection.execute(query.limit(batch_limit + 1).offset(rows_read)).all()
        more_rows = len(rows) > batch_limit
        rows = rows[:batch_limit]
        rows_read += len(rows)
        candidates = [_reassess(row, owned, account_id, as_of) for row in rows]
        identities = resolve_display_identity(connection, [item.signal for item in candidates])
        for item in candidates:
            display = identities.get(item.signal.signal_key)
            if display is None:
                without_name += 1
                continue
            if len(displayable) == scan_cap:
                truncated = True
                break
            displayable.append(dataclasses.replace(item, display=display))
        if truncated or not more_rows:
            break
        if rows_read >= row_ceiling:
            truncated = True
            break
```

Le reste de la fonction (`if admitted is not None: …` jusqu'au `return FeedPage(...)`) est inchangé : il lit `displayable`, `without_name`, `truncated`.

- [ ] **Step 4: Vérifier le passage**

Run: `uv run pytest -q tests/test_feed_pagination.py tests/test_feed_identity.py tests/test_feed_history.py tests/test_feed_facts.py`
Expected: tout PASS (les tests existants `test_the_scan_cap_is_announced_rather_than_silent` et `test_a_complete_read_reports_no_truncation` restent verts : 5 nommés pour un plafond de 2 → tronqué ; plafond 500 → complet).

- [ ] **Step 5: Ruff puis commit**

```bash
uv run ruff check src/signals/feed/query.py tests/test_feed_pagination.py
git add src/signals/feed/query.py tests/test_feed_pagination.py
git commit -m "fix(feed): compter les candidats affichables dans le plafond de lecture"
```

---

### Task 2 : acheteur et lieu honnêtes côté API

**Files:**
- Create: `src/signals/feed/french_departments.py`
- Modify: `src/signals/feed/view.py` (`_buyer`, `_location`)
- Modify: `src/signals/feed/factual_display.py` (`_location`, `_buyer`, `_headline`, `factual_display`)
- Modify: `src/signals/connectors/decp/parser.py` (`_place`)
- Test: `tests/test_french_departments.py` (nouveau), `tests/test_feed_factual_display.py`, `tests/test_feed_facts.py`, `tests/test_decp2022_adapter.py`

**Interfaces:**
- Produces: `department_from_postal_code(postal_code: str | None) -> str | None` (rend `"92"`, `"2A"`, `"971"`, ou `None`) ; `department_label(subdivision_code: str | None) -> str | None` (`"FR-92"` → `"Hauts-de-Seine"`) ; `location_subdivision(place: dict | None) -> str | None` (le `subdivision_code` publié, sinon `FR-<dept>` dérivé du code postal français).
- Contrat API : `contract.buyer.name` peut être `null` avec `identifier` renseigné ; `contract.location.subdivision_label: string | null` (nouvelle clé) ; `contract.location.subdivision_code` peut désormais être dérivé (`"FR-92"`).

- [ ] **Step 1: Test du référentiel des départements (échoue)**

Créer `tests/test_french_departments.py` :

```python
"""Le département français se lit dans le code postal ; son nom vient d'une table."""

from signals.feed.french_departments import (
    DEPARTMENTS,
    department_from_postal_code,
    department_label,
    location_subdivision,
)


def test_metropolitan_postal_codes_give_a_two_digit_department():
    assert department_from_postal_code("92350") == "92"
    assert department_from_postal_code("06150") == "06"


def test_corsica_is_split_at_20200():
    assert department_from_postal_code("20000") == "2A"
    assert department_from_postal_code("20167") == "2A"
    assert department_from_postal_code("20200") == "2B"
    assert department_from_postal_code("20600") == "2B"


def test_overseas_postal_codes_give_a_three_digit_department():
    assert department_from_postal_code("97133") == "971"
    assert department_from_postal_code("97400") == "974"


def test_anything_else_is_not_a_department():
    assert department_from_postal_code(None) is None
    assert department_from_postal_code("1234") is None
    assert department_from_postal_code("CH-1000") is None
    assert department_from_postal_code("99999") is None


def test_the_label_needs_the_iso_prefix():
    assert department_label("FR-92") == "Hauts-de-Seine"
    assert department_label("FR-2A") == "Corse-du-Sud"
    assert department_label("FR-971") == "Guadeloupe"
    assert department_label("92") is None
    assert department_label("CH-VD") is None
    assert department_label(None) is None


def test_the_table_covers_the_hundred_and_one_departments():
    assert len(DEPARTMENTS) == 101


def test_the_published_subdivision_wins_over_the_derived_one():
    assert location_subdivision({"country": "FR", "subdivision_code": "FR-75", "postal_code": "92350"}) == "FR-75"
    assert location_subdivision({"country": "FR", "postal_code": "92350"}) == "FR-92"
    assert location_subdivision({"country": "CH", "postal_code": "1000"}) is None
    assert location_subdivision(None) is None
```

- [ ] **Step 2: Vérifier l'échec**

Run: `uv run pytest -q tests/test_french_departments.py`
Expected: FAIL — `ModuleNotFoundError: signals.feed.french_departments`.

- [ ] **Step 3: Créer le référentiel**

Créer `src/signals/feed/french_departments.py` :

```python
"""Départements français : dérivés du code postal, nommés depuis une table.

Le schéma DECP 2022 publie souvent un code postal sans commune ni département.
Le département est une DÉRIVATION déterministe du code postal publié — pas une
devinette sur la forme d'un code dont on ignorerait le type — et son nom est
un libellé de référentiel, pas un fait de l'avis.
"""

from __future__ import annotations

from typing import Any

DEPARTMENTS: dict[str, str] = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure",
    "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine",
    "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines",
    "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne",
    "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}


def department_from_postal_code(postal_code: str | None) -> str | None:
    """« 92350 » → « 92 », « 20167 » → « 2A », « 97133 » → « 971 », sinon `None`."""
    if not postal_code:
        return None
    code = postal_code.strip()
    if len(code) != 5 or not code.isdigit():
        return None
    if code.startswith("20"):
        return "2A" if int(code) < 20200 else "2B"
    candidate = code[:3] if code[:2] in {"97", "98"} else code[:2]
    return candidate if candidate in DEPARTMENTS else None


def department_label(subdivision_code: str | None) -> str | None:
    """« FR-92 » → « Hauts-de-Seine ». Tout autre référentiel rend `None`."""
    if not subdivision_code or not subdivision_code.startswith("FR-"):
        return None
    return DEPARTMENTS.get(subdivision_code[3:])


def location_subdivision(place: dict[str, Any] | None) -> str | None:
    """La subdivision publiée, sinon le département dérivé d'un code postal français."""
    if not place:
        return None
    published = place.get("subdivision_code")
    if published:
        return published
    if place.get("country") != "FR":
        return None
    department = department_from_postal_code(place.get("postal_code"))
    return None if department is None else f"FR-{department}"


__all__ = [
    "DEPARTMENTS",
    "department_from_postal_code",
    "department_label",
    "location_subdivision",
]
```

- [ ] **Step 4: Vérifier le passage**

Run: `uv run pytest -q tests/test_french_departments.py`
Expected: 7 PASS.

- [ ] **Step 5: Tests API acheteur / lieu / complétude (échouent)**

Ajouter à la fin de `tests/test_feed_factual_display.py` (les fixtures `client`, `icp`, `engine`, et les imports `materialize`, `simap_award`, `pin_session_cookie` y existent déjà ; `subscribe` place le compte sur le plan `scale`) :

```python
# ─── Un identifiant n'est pas un nom, un pays n'est pas un lieu ───────────────


def _decp_like(event, award):
    """Le contrat tel que DECP 2022 le publie : SIRET d'acheteur, code postal seul."""
    from signals.domain.values import Location, OrganizationIdentifier, OrganizationRef

    siret = "27920022400012"
    buyer = OrganizationRef(
        legal_name=siret,
        identifiers=(OrganizationIdentifier(scheme="SIRET", value=siret),),
        country="FR",
    )
    return (
        event.model_copy(update={"procedure_buyers": (buyer,)}),
        award.model_copy(
            update={"place_of_performance": Location(country="FR", postal_code="92350")}
        ),
    )


@pytest.fixture
def decp_like_signal(client: TestClient, icp: str, engine):
    event, awards = simap_award("33112-02")
    event, award = _decp_like(event, awards[0])
    with engine.begin() as connection:
        return materialize(connection, event, award, target_icp_id=icp)


def test_a_buyer_known_only_by_its_siret_has_no_name(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    buyer = body["contract"]["buyer"]
    assert buyer["name"] is None
    assert buyer["identifier"] == {"scheme": "SIRET", "value": "27920022400012"}


def test_a_postal_code_yields_a_department_and_its_label(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    location = body["contract"]["location"]
    assert location["locality"] is None
    assert location["postal_code"] == "92350"
    assert location["subdivision_code"] == "FR-92"
    assert location["subdivision_label"] == "Hauts-de-Seine"


def test_completeness_does_not_count_a_siret_as_a_buyer_name(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    display = body["factual_display"]
    assert "buyer" in display["missing_fields"]
    assert "location" not in display["missing_fields"], "un département est un lieu"
    assert display["completeness"] == "partial"


def test_the_headline_names_the_department_rather_than_the_country(client, decp_like_signal):
    body = client.get(f"/signals/{decp_like_signal.signal_key}").json()
    headline = body["factual_display"]["headline"]
    assert "dans le département 92 (Hauts-de-Seine)" in headline
    assert " à FR" not in headline


def test_a_country_alone_is_not_a_location(client, icp, engine):
    from signals.domain.values import Location

    event, awards = simap_award("33112-02")
    award = awards[0].model_copy(update={"place_of_performance": Location(country="FR")})
    with engine.begin() as connection:
        signal = materialize(connection, event, award, target_icp_id=icp)

    display = client.get(f"/signals/{signal.signal_key}").json()["factual_display"]
    assert "location" in display["missing_fields"]
    assert " à FR" not in display["headline"]
```

Ajouter dans `tests/test_decp2022_adapter.py`, après `test_a_postal_code_and_a_department_code_are_not_confused` :

```python
def test_a_postal_code_also_yields_its_department():
    """Le département se lit dans le code postal publié ; le libellé reste au feed."""
    record = dict(RECORDS[NOMINAL])
    record["lieuexecution_typecode"] = "Code postal"
    record["lieuexecution_code"] = "92350"
    _, contract = parse_contract(record, retrieved_at=RETRIEVED_AT)
    place = contract.place_of_performance
    assert place.postal_code == "92350"
    assert place.subdivision_code == "FR-92"
    assert place.subdivision_scheme == "ISO-3166-2"
    assert place.locality is None
```

(Vérifier en tête du fichier que `parse_contract` et `RETRIEVED_AT` sont importés ; sinon reprendre l'import utilisé par `parsed()` dans ce même fichier.)

- [ ] **Step 6: Vérifier l'échec**

Run: `uv run pytest -q tests/test_feed_factual_display.py tests/test_decp2022_adapter.py -k "siret or postal_code or completeness_does_not or headline_names or country_alone or also_yields"`
Expected: 6 FAIL (nom = SIRET, `subdivision_label` absent, `missing_fields` sans `buyer`, « à FR » présent, département absent du parser).

- [ ] **Step 7: Implémenter côté feed**

`src/signals/feed/view.py` — ajouter l'import et réécrire `_buyer` et `_location` :

```python
from signals.feed.french_departments import department_label, location_subdivision
from signals.feed.query import is_customer_display_name
```

```python
def _buyer(procedure_buyers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """L'acheteur tel que publié — et `name: None` quand la source n'a publié
    qu'un identifiant (DECP 2022). La règle §19 vaut pour lui comme pour le
    titulaire : un SIRET n'est pas un nom."""
    if not procedure_buyers:
        return None
    first = procedure_buyers[0]
    identifiers = first.get("identifiers") or []
    identifier = identifiers[0] if identifiers else None
    identifier_value = None if identifier is None else identifier.get("value")
    legal_name = first.get("legal_name")
    return {
        "name": legal_name if is_customer_display_name(legal_name, identifier_value) else None,
        "country": first.get("country"),
        "identifier": (
            None
            if identifier is None
            else {"scheme": identifier.get("scheme"), "value": identifier_value}
        ),
    }


def _location(place: dict[str, Any] | None) -> dict[str, Any] | None:
    if not place:
        return None
    subdivision = location_subdivision(place)
    return {
        "country": place.get("country"),
        "locality": place.get("locality"),
        "postal_code": place.get("postal_code"),
        "subdivision_code": subdivision,
        "subdivision_label": department_label(subdivision),
    }
```

Si `signals.feed.query` importe déjà `signals.feed.view` (import circulaire), déplacer `_IDENTIFIER_LIKE`, `_looks_like_identifier` et `is_customer_display_name` dans un nouveau module `src/signals/feed/identity_policy.py` et les ré-exporter depuis `query.py` (`from signals.feed.identity_policy import is_customer_display_name  # noqa: F401`). Vérifier avec `grep -n "^from signals.feed" src/signals/feed/query.py`.

`src/signals/feed/factual_display.py` — remplacer `_location`, `_buyer`, et la branche « amount and location » de `_headline` :

```python
from signals.feed.french_departments import department_label, location_subdivision
from signals.feed.query import FeedSignal, is_customer_display_name
```

```python
def _location(place: dict[str, Any] | None, *, lang: str) -> str | None:
    """Le complément de lieu du titre court — jamais le seul pays.

    « à Munich » quand la commune est publiée ; sinon « dans le département 92
    (Hauts-de-Seine) » quand un département français est publié ou dérivé du
    code postal ; sinon la subdivision brute ; sinon rien — « à FR » n'est pas
    un lieu qu'un commercial peut lire.
    """
    if not place:
        return None
    locality = _clean(place.get("locality"))
    if locality:
        return f"in {locality}" if lang == "en" else f"à {locality}"
    subdivision = location_subdivision(place)
    if not subdivision:
        return None
    label = department_label(subdivision)
    if label:
        code = subdivision[3:]
        return (
            f"in department {code} ({label})" if lang == "en"
            else f"dans le département {code} ({label})"
        )
    return f"in {subdivision}" if lang == "en" else f"à {subdivision}"


def _buyer(item: FeedSignal) -> str | None:
    for organization in item.signal.event.procedure_buyers or []:
        name = _clean(organization.get("legal_name"))
        identifiers = organization.get("identifiers") or []
        identifier = (identifiers[0] or {}).get("value") if identifiers else None
        if name and is_customer_display_name(name, identifier):
            return name
    return None
```

Dans `_headline`, les deux branches avec lieu deviennent (le paramètre `location` contient déjà la préposition) :

```python
        if amount and location:
            headline = f"{company} wins a {amount} contract {location}"
```
et
```python
    elif amount and location:
        headline = f"{company} remporte un marché de {amount} {location}"
```

Dans `factual_display(...)`, l'appel devient `location = _location(item.signal.award.place_of_performance, lang=lang)`. Le reste (`values`, `missing`, `completeness`) est inchangé : `location` vaut `None` pour un pays seul, `buyer` vaut `None` pour un SIRET, donc `missing_fields` et `completeness` suivent.

Vérifier que le test existant `test_feed_factual_display.py::…` qui attend `« à Villeneuve »`-style reste vert : l'ancienne sortie « à {locality} » est conservée à l'identique. Chercher aussi `grep -rn "remporte un marché de" tests/` et mettre à jour toute attente qui contenait « à FR » ou « à CH ».

`src/signals/connectors/decp/parser.py` — dans `_place`, remplacer la branche `if kind == "Code postal":` par :

```python
    if kind == "Code postal":
        department = department_from_postal_code(code)
        if department is None:
            return Location(country="FR", postal_code=code)
        return Location(
            country="FR",
            postal_code=code,
            subdivision_code=f"FR-{department}",
            subdivision_scheme="ISO-3166-2",
        )
```
avec l'import `from signals.feed.french_departments import department_from_postal_code` (si l'arborescence interdit à un connecteur d'importer `signals.feed`, placer la fonction dans `src/signals/domain/french_departments.py` et faire importer ce chemin par `signals.feed.french_departments` ; le test de la tâche importe depuis `signals.feed.french_departments`, qui doit ré-exporter). Mettre à jour la docstring de `_place` : « Un code postal publié donne aussi son département : c'est une dérivation, pas une devinette sur la forme du code. »

- [ ] **Step 8: Vérifier le passage et l'absence de régression**

Run: `uv run pytest -q tests/test_feed_factual_display.py tests/test_decp2022_adapter.py tests/test_feed_facts.py tests/test_feed_identity.py tests/test_french_departments.py tests/test_france_decp_link.py`
Expected: tout PASS. Si un test existant attend `location["subdivision_code"] is None` pour un enregistrement DECP à code postal, ou compare `contract["location"]` à un dict exact sans `subdivision_label`, mettre l'attente à jour (c'est le nouveau contrat) et le dire dans le commit.

- [ ] **Step 9: Suite backend complète, ruff, commit**

Run: `uv run pytest -q -x --deselect tests/test_acquisition_migration.py::test_projection_has_only_operationally_justified_indexes` puis `uv run ruff check .`
Expected: PASS.

```bash
git add src/signals/feed/french_departments.py src/signals/feed/view.py src/signals/feed/factual_display.py src/signals/connectors/decp/parser.py tests/test_french_departments.py tests/test_feed_factual_display.py tests/test_decp2022_adapter.py tests/test_feed_facts.py
git commit -m "fix(feed): un SIRET n'est pas un nom d'acheteur, un pays n'est pas un lieu"
```

---

### Task 3 : afficher l'acheteur non nommé et le département

**Files:**
- Modify: `frontend/src/api/types.ts` (`Place`)
- Modify: `frontend/src/reference/dashboard/models.ts` (`SignalDetailView.facts`)
- Modify: `frontend/src/reference/dashboard/adapters.ts` (`toSignalDetailView`)
- Modify: `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx` (calcul `location`, `facts`)
- Modify: `frontend/src/pages/SignalsFeed.tsx` (`displayLocation`)
- Modify: `frontend/src/i18n/fr.ts`, `frontend/src/i18n/en.ts` (`signalsPage.buyerUnnamed`)
- Modify: `frontend/src/test/harness.tsx` (fixture `Place`)
- Test: `frontend/src/signals/detail.test.tsx`, `frontend/src/signals/feed.test.tsx`

**Interfaces:**
- Consumes: `contract.buyer.name: string | null`, `contract.location.subdivision_label: string | null` (tâche 2).
- Produces: `Place.subdivision_label: string | null` ; `SignalDetailView.facts.buyerIdentifier: { scheme: string | null; value: string | null } | null` ; `formatOfficialIdentifier(scheme, value)` exporté par `adapters.ts` (`"SIRET" + "27920022400012"` → `"279 200 224 00012"`).

- [ ] **Step 1: Tests (échouent)**

Dans `frontend/src/signals/detail.test.tsx`, ajouter un test dans le `describe` du détail (utiliser `detailFixture` et `renderDetail` déjà définis) :

```tsx
  it('nomme l’absence de nom d’acheteur sans jamais afficher le SIRET comme un nom', async () => {
    renderDetail({
      detail: detailFixture({
        contract: {
          ...UNLOCKED_DETAIL.contract,
          buyer: { name: null, country: 'FR', identifier: { scheme: 'SIRET', value: '27920022400012' } },
          location: { country: 'FR', locality: null, postal_code: '92350', subdivision_code: 'FR-92', subdivision_label: 'Hauts-de-Seine' },
        },
      }),
    })
    const facts = await screen.findByRole('heading', { name: 'Détails du marché' })
    const grid = facts.closest('section')!
    expect(within(grid).getByText('Acheteur non nommé par la source · SIRET 279 200 224 00012')).toBeVisible()
    expect(within(grid).queryByText('27920022400012')).toBeNull()
    expect(within(grid).getByText('92350, Hauts-de-Seine, France')).toBeVisible()
  })
```

Dans `frontend/src/signals/feed.test.tsx`, à côté du test qui vérifie `'1 240 000 €'` (ligne ~172), ajouter :

```tsx
  it('affiche le département dérivé à la place du seul pays', async () => {
    mockApi({
      ...AUTHENTICATED,
      '/signals': feedPage([{
        ...UNLOCKED_ITEM,
        contract: {
          ...UNLOCKED_ITEM.contract,
          location: { country: 'FR', locality: null, postal_code: '92350', subdivision_code: 'FR-92', subdivision_label: 'Hauts-de-Seine' },
        },
      }]),
    })
    renderApp(<AppRoutes />, { route: '/app/signals' })
    const rows = await screen.findAllByRole('button', { name: /Ouvrir le signal/ })
    expect(rows[0].textContent?.replace(/ | /g, ' ')).toContain('92350, Hauts-de-Seine, FR')
  })
```
(Adapter `mockApi`/`feedPage`/`renderApp` à la forme exacte utilisée par les tests voisins de ce fichier : copier la structure du test de la ligne ~160 et ne changer que `location`.)

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest --run src/signals/detail.test.tsx src/signals/feed.test.tsx`
Expected: les deux nouveaux tests FAIL (erreur de type sur `subdivision_label` au typecheck, puis texte absent).

- [ ] **Step 3: Implémenter**

`frontend/src/api/types.ts` — `Place` :
```ts
export interface Place {
  country: string | null
  locality: string | null
  postal_code: string | null
  subdivision_code: string | null
  subdivision_label: string | null
}
```
Mettre à jour tous les littéraux `Place` des fixtures (`frontend/src/test/harness.tsx` ligne ~322, `frontend/tests/visual/fixtures.ts` si un `Place` y est construit) en ajoutant `subdivision_label: null` (ou la valeur adéquate), jusqu'à ce que `npm run typecheck` passe.

`frontend/src/reference/dashboard/models.ts` — dans `SignalDetailView.facts`, ajouter après `buyer: string | null` :
```ts
    buyerIdentifier: { scheme: string | null; value: string | null } | null
```

`frontend/src/reference/dashboard/adapters.ts` — exporter :
```ts
/** « 27920022400012 » → « 279 200 224 00012 ». Les autres schémas restent tels quels. */
export function formatOfficialIdentifier(scheme: string | null, value: string | null): string | null {
  if (!value) return null
  if (scheme === 'SIRET' && /^\d{14}$/.test(value)) {
    return `${value.slice(0, 3)} ${value.slice(3, 6)} ${value.slice(6, 9)} ${value.slice(9)}`
  }
  return value
}
```
et dans `toSignalDetailView`, `facts` : `buyerIdentifier: detail.contract.buyer?.identifier ?? null,`.

`frontend/src/i18n/fr.ts` (`signalsPage`) : `buyerUnnamed: 'Acheteur non nommé par la source',` ; `en.ts` : `buyerUnnamed: 'Buyer not named by the source',`.

`frontend/src/reference/dashboard/ReferenceSignalDetail.tsx` :
```tsx
  const location = detail.facts.location
    ? [
        detail.facts.location.locality,
        detail.facts.location.postal_code,
        detail.facts.location.subdivision_label ?? detail.facts.location.subdivision_code,
        locationTerritory ? territoryLabel(locationTerritory, locale) : detail.facts.location.country,
      ].filter(Boolean).join(', ') || missing
    : missing
  const buyerIdentifier = formatOfficialIdentifier(
    detail.facts.buyerIdentifier?.scheme ?? null,
    detail.facts.buyerIdentifier?.value ?? null,
  )
  const buyer = detail.buyerName
    ?? (buyerIdentifier
      ? `${copy.buyerUnnamed} · ${detail.facts.buyerIdentifier?.scheme ?? ''} ${buyerIdentifier}`.replace(/\s+/g, ' ')
      : missing)
```
et dans `facts` : `{ label: t.reference.fields.signalBuyer, value: buyer },`. Importer `formatOfficialIdentifier` depuis `./adapters`.

`frontend/src/pages/SignalsFeed.tsx` — `displayLocation` :
```tsx
  const displayLocation = (card: SignalCardView) => {
    if (!card.location) return t.reference.missingValue
    return [
      card.location.locality,
      card.location.postal_code,
      card.location.subdivision_label ?? card.location.subdivision_code,
      card.location.country,
    ].filter(Boolean).join(', ') || t.reference.missingValue
  }
```

- [ ] **Step 4: Vérifier**

Run: `cd frontend && npx vitest --run src/signals/detail.test.tsx src/signals/feed.test.tsx src/reference/dashboard/adapters.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/reference/dashboard/models.ts frontend/src/reference/dashboard/adapters.ts frontend/src/reference/dashboard/ReferenceSignalDetail.tsx frontend/src/pages/SignalsFeed.tsx frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/test/harness.tsx frontend/tests/visual/fixtures.ts frontend/src/signals/detail.test.tsx frontend/src/signals/feed.test.tsx
git commit -m "fix(signals): afficher l'acheteur non nommé et le département plutôt qu'un SIRET et un pays"
```

---

### Task 4 : montants lisibles quelle que soit la police

**Files:**
- Modify: `frontend/src/i18n/index.tsx` (`money`, `amount`, `number`)
- Test: `frontend/src/i18n/format.test.tsx` (nouveau)

**Interfaces:**
- Produces: `withRenderableSpaces(text: string): string` exporté par `index.tsx` (remplace U+202F et U+2009 par U+00A0).

- [ ] **Step 1: Test (échoue)**

Créer `frontend/src/i18n/format.test.tsx` :
```tsx
import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nProvider, useI18n, withRenderableSpaces } from './index'

const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider initialLocale="fr">{children}</I18nProvider>

describe('formatage des montants', () => {
  it('ne laisse jamais une espace fine que les polices auto-hébergées ne rendent pas', () => {
    const { result } = renderHook(() => useI18n(), { wrapper })
    for (const text of [result.current.amount('5338215.00', 'EUR')!, result.current.money(533821500, 'chf'), result.current.number(5338215)]) {
      expect(text).not.toMatch(/[  ]/)
      expect(text.replace(/ /g, ' ')).toContain('5 338 215')
    }
  })

  it('remplace U+202F et U+2009 par une espace insécable ordinaire', () => {
    expect(withRenderableSpaces('5 338 215')).toBe('5 338 215')
  })
})
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest --run src/i18n/format.test.tsx`
Expected: FAIL (`withRenderableSpaces` n'existe pas ; `amount` contient U+202F).

- [ ] **Step 3: Implémenter**

Dans `frontend/src/i18n/index.tsx`, avant `I18nProvider` :
```ts
/** `Intl` sépare les milliers par une espace fine (U+202F) en français. Instrument
 *  Sans et Lora, auto-hébergées, n'ont pas ce glyphe : Chrome le rend à largeur
 *  nulle et « 5 338 215 € » devient « 5338215 € ». U+00A0 existe dans les deux
 *  polices et reste insécable. */
export function withRenderableSpaces(text: string): string {
  return text.replace(/[  ]/g, ' ')
}
```
et envelopper les trois `format(...)` : `withRenderableSpaces(new Intl.NumberFormat(...).format(...))` dans `money`, `amount`, `number`.

- [ ] **Step 4: Vérifier**

Run: `cd frontend && npx vitest --run src/i18n src/signals src/billing 2>/dev/null || npx vitest --run`
Expected: PASS. Les tests existants normalisent déjà ` | ` avant comparaison (`feed.test.tsx:172`, `:570`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/index.tsx frontend/src/i18n/format.test.tsx
git commit -m "fix(i18n): remplacer l'espace fine des montants par une espace insécable rendue"
```

---

### Task 5 : dates qualifiées et âge au pluriel

**Files:**
- Modify: `frontend/src/i18n/fr.ts`, `frontend/src/i18n/en.ts` (`signalsPage.datedOn`, `ageDaysOne`, `ageDaysOther`)
- Modify: `frontend/src/pages/SignalsFeed.tsx` (rendu de `<small>` dans la carte)
- Modify: `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx` (chip d'âge)
- Test: `frontend/src/signals/feed.test.tsx`, `frontend/src/signals/detail.test.tsx`

**Interfaces:**
- Consumes: `SignalCardView.eventDateKind: 'award' | 'notification' | 'publication' | 'unknown'`, `SignalDetailView.eventAgeDays: number | null`, `plural(count, one, other)` et `interpolate` de `../../i18n`.
- Produces: clés i18n `signalsPage.datedOn: { award, notification, publication }`, `signalsPage.ageDaysOne`, `signalsPage.ageDaysOther` (la clé `ageDays` est supprimée).

- [ ] **Step 1: Tests (échouent)**

`feed.test.tsx`, à côté du test de la ligne ~172 :
```tsx
  it('dit de quelle date il s’agit sur la carte', async () => {
    mockApi({ ...AUTHENTICATED, '/signals': feedPage([{
      ...UNLOCKED_ITEM,
      factual_display: { ...UNLOCKED_ITEM.factual_display, date: { value: '2026-08-19', kind: 'notification' } },
    }]) })
    renderApp(<AppRoutes />, { route: '/app/signals' })
    const rows = await screen.findAllByRole('button', { name: /Ouvrir le signal/ })
    expect(rows[0].textContent).toContain('Notifié le 19 août 2026')
  })
```
`detail.test.tsx` :
```tsx
  it('accorde l’âge du signal', async () => {
    renderDetail({ detail: detailFixture({ event: { ...UNLOCKED_DETAIL.event, age_days: 1 } }) })
    expect(await screen.findByText('Il y a 1 jour')).toBeVisible()
  })
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest --run src/signals/feed.test.tsx src/signals/detail.test.tsx -t "date il s|accorde"`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

`fr.ts` (`signalsPage`) — remplacer `ageDays: '{count} jours',` par :
```ts
      ageDaysOne: 'Il y a {count} jour',
      ageDaysOther: 'Il y a {count} jours',
      datedOn: {
        award: 'Attribué le {date}',
        notification: 'Notifié le {date}',
        publication: 'Publié le {date}',
      },
```
`en.ts` :
```ts
      ageDaysOne: '{count} day ago',
      ageDaysOther: '{count} days ago',
      datedOn: {
        award: 'Awarded on {date}',
        notification: 'Notified on {date}',
        publication: 'Published on {date}',
      },
```

`SignalsFeed.tsx` — ajouter près de `displayDate` :
```tsx
  const displayDatedOn = (card: SignalCardView) => {
    const formatted = date(card.eventDate)
    if (!formatted || card.eventDateKind === 'unknown') return t.reference.signalsPage.unknownDate
    return interpolate(t.reference.signalsPage.datedOn[card.eventDateKind], { date: formatted })
  }
```
et dans la carte remplacer `{displayAmount(award)} · {displayLocation(award)} · {displayDate(award.eventDate)}` par `{displayAmount(award)} · {displayLocation(award)} · {displayDatedOn(award)}`. Supprimer `displayDate` si plus utilisé.

`ReferenceSignalDetail.tsx` — importer `plural` depuis `'../../i18n'` et remplacer la chip d'âge :
```tsx
            {detail.eventAgeDays !== null ? (
              <span>{interpolate(plural(detail.eventAgeDays, copy.ageDaysOne, copy.ageDaysOther), { count: detail.eventAgeDays })}</span>
            ) : null}
```

- [ ] **Step 4: Vérifier**

Run: `cd frontend && npx vitest --run src/signals && npm run typecheck`
Expected: PASS (si un test existant attendait « 15 jours », le passer à « Il y a 15 jours »).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/pages/SignalsFeed.tsx frontend/src/reference/dashboard/ReferenceSignalDetail.tsx frontend/src/signals/feed.test.tsx frontend/src/signals/detail.test.tsx
git commit -m "fix(signals): qualifier la date affichée et accorder l'âge du signal"
```

---

### Task 6 : statuts en clair, chips courtes, filtres lisibles

**Files:**
- Modify: `frontend/src/i18n/fr.ts`, `en.ts` (`signalsPage.statusLabels`, `signalsPage.restrictedShort`)
- Modify: `frontend/src/pages/SignalsFeed.tsx` (options du select, filtre CPV, note restreinte)
- Modify: `frontend/src/pages/SignalsFeed.module.css` (`.filterGrid`, `:disabled`, `.lockHint`)
- Modify: `frontend/src/reference/dashboard/ReferenceSignalDetail.tsx` (chip statut + `why_now` en paragraphe)
- Test: `frontend/src/signals/feed.test.tsx`, `frontend/src/signals/detail.test.tsx`

**Interfaces:**
- Consumes: `HISTORY_STATUSES` (7 valeurs, `SignalsFeed.tsx`), `SignalDetailView.brief.whyNow`, `detail.eventStatus` — **à ajouter** : `SignalDetailView.eventStatus: EventStatus` renseigné dans `toSignalDetailView` par `detail.event.status`.
- Produces: `signalsPage.statusLabels: Record<EventStatus, string>`.

- [ ] **Step 1: Tests (échouent)**

`feed.test.tsx` :
```tsx
  it('propose des statuts temporels en français, pas des identifiants', async () => {
    mockApi({ ...AUTHENTICATED, '/signals': feedPage([UNLOCKED_ITEM]) })
    renderApp(<AppRoutes />, { route: '/app/signals?view=history' })
    const select = await screen.findByLabelText('Statut temporel')
    expect(within(select).getByRole('option', { name: 'Attribution récente' })).toBeVisible()
    expect(within(select).queryByRole('option', { name: 'recent_award' })).toBeNull()
  })

  it('explique un filtre verrouillé sur le champ lui-même', async () => {
    mockApi({ ...AUTHENTICATED, '/signals': feedPage([UNLOCKED_ITEM], { filter_access: { date_range: true, country: true, subdivision: true, status: true, sector: false } }) })
    renderApp(<AppRoutes />, { route: '/app/signals?view=history' })
    const cpv = await screen.findByLabelText('Secteur (préfixe CPV)')
    expect(cpv).toBeDisabled()
    expect(cpv).toHaveAccessibleDescription('Ce filtre n’est pas inclus dans votre accès actuel.')
  })
```
(Si `feedPage` n'accepte pas de surcharge de `filter_access`, construire la page à la main : `{ ...feedPage([UNLOCKED_ITEM]), filter_access: {...} }`.)

`detail.test.tsx` :
```tsx
  it('résume le statut en chip courte et garde la phrase complète en clair', async () => {
    renderDetail({ detail: detailFixture({ event: { ...UNLOCKED_DETAIL.event, status: 'recently_published_award', why_now: 'Publication récente d’une attribution dont la date de décision est inconnue.' } }) })
    const strip = await screen.findByLabelText('Contexte commercial du signal')
    expect(within(strip).getByText('Publication récente')).toBeVisible()
    expect(within(strip).queryByText(/date de décision est inconnue/)).toBeNull()
    expect(screen.getByText('Publication récente d’une attribution dont la date de décision est inconnue.')).toBeVisible()
  })
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest --run src/signals -t "statuts temporels|filtre verrouillé|chip courte"`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

`fr.ts` (`signalsPage`) :
```ts
      restrictedShort: 'Non inclus dans votre accès',
      statusLabels: {
        recent_award: 'Attribution récente',
        recently_notified_contract: 'Notification récente',
        recently_published_award: 'Publication récente',
        aging_award: 'Attribution vieillissante',
        stale_award: 'Attribution ancienne',
        award_date_unknown: 'Date d’attribution inconnue',
        invalid_award_date: 'Date d’attribution invalide',
      },
```
`en.ts` :
```ts
      restrictedShort: 'Not included in your access',
      statusLabels: {
        recent_award: 'Recent award',
        recently_notified_contract: 'Recent notification',
        recently_published_award: 'Recent publication',
        aging_award: 'Aging award',
        stale_award: 'Old award',
        award_date_unknown: 'Award date unknown',
        invalid_award_date: 'Award date invalid',
      },
```

`models.ts` — `SignalDetailView` : ajouter `eventStatus: EventStatus` (importer `EventStatus` depuis `'../../api/types'`). `adapters.ts` `toSignalDetailView` : `eventStatus: detail.event.status,`.

`SignalsFeed.tsx` :
- options : `{HISTORY_STATUSES.map((status) => <option value={status} key={status}>{t.reference.signalsPage.statusLabels[status]}</option>)}`
- filtre CPV : ajouter `aria-describedby={filterAccess?.sector === false ? 'history-filter-restricted' : undefined}` ; sous l'`<input>` dans le même `<label>` : `{filterAccess?.sector === false ? <small className={styles.lockHint}><LockKeyhole aria-hidden="true" /> {t.reference.signalsPage.restrictedShort}</small> : null}`
- note : `<p id="history-filter-restricted" className={styles.restrictedNote}>…</p>`.

`SignalsFeed.module.css` :
```css
.filterGrid { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.filterGrid :disabled { cursor: not-allowed; border-style: dashed; background: var(--surface-soft); color: var(--text-muted); opacity: 1; }
.lockHint { display: inline-flex; align-items: center; gap: 4px; color: var(--text-muted); font-size: 11px; font-weight: 600; }
.lockHint svg { width: 12px; height: 12px; }
```
(remplacer la règle existante `.filterGrid { grid-template-columns: repeat(2, …) }` et `.filterGrid :disabled { … opacity: 0.55 }` ; supprimer le `@media (max-width: 620px) { .filterGrid … }` devenu inutile.)

`ReferenceSignalDetail.tsx` — dans la strip, remplacer `<span>{detail.brief.whyNow}</span>` par `<span>{copy.statusLabels[detail.eventStatus]}</span>`, puis après la `div.signal-context-strip` ajouter `<p className="detail-summary signal-why-now">{detail.brief.whyNow}</p>`. Dans `dashboard-reference.css`, après `.signal-context-strip span { … }` : `.signal-why-now { margin: 10px 0 0; font-size: 13px; }`.

- [ ] **Step 4: Vérifier**

Run: `cd frontend && npx vitest --run src/signals && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/pages/SignalsFeed.tsx frontend/src/pages/SignalsFeed.module.css frontend/src/reference/dashboard/ReferenceSignalDetail.tsx frontend/src/reference/dashboard/models.ts frontend/src/reference/dashboard/adapters.ts frontend/src/reference/dashboard/dashboard-reference.css frontend/src/signals/feed.test.tsx frontend/src/signals/detail.test.tsx
git commit -m "fix(signals): statuts en clair, chips courtes et filtre verrouillé expliqué"
```

---

### Task 7 : densité de la liste, compteur, grille de faits, messages de fin

**Files:**
- Modify: `frontend/src/pages/SignalsFeed.tsx` (compteur, « attribution(s) », messages de fin)
- Modify: `frontend/src/pages/SignalsFeed.module.css` (tailles, clamp)
- Modify: `frontend/src/reference/dashboard/dashboard-reference.css` (`.signal-item-head`, `.signal-count`, `.signal-fact-grid`, `.text-link`, `.market-amount-note`, `.signal-note-state`)
- Modify: `frontend/src/i18n/fr.ts`, `en.ts` (`signalsPage.signalCountOne/Other`, `feed.truncatedNote`)
- Test: `frontend/src/signals/feed.test.tsx`

**Interfaces:**
- Consumes: `feed.data.page.has_more`, `feed.data.page.scan_truncated`, `plural`, `interpolate`, `t.reference.companiesPage.contractOne/Other`.

- [ ] **Step 1: Tests (échouent)**

`feed.test.tsx` :
```tsx
  it('compte les signaux sans coller le nom du plan', async () => {
    mockApi({ ...AUTHENTICATED, '/signals': feedPage([UNLOCKED_ITEM]) })
    renderApp(<AppRoutes />, { route: '/app/signals' })
    expect(await screen.findByText('1 signal')).toBeVisible()
    expect(screen.queryByText(/· (Essentiel|Pro|Découverte)/)).toBeNull()
  })

  it('ne dit pas « fin de liste » quand la lecture a été bornée', async () => {
    mockApi({ ...AUTHENTICATED, '/signals': { ...feedPage([UNLOCKED_ITEM]), page: { ...feedPage([UNLOCKED_ITEM]).page, has_more: false, scan_truncated: true } } })
    renderApp(<AppRoutes />, { route: '/app/signals' })
    expect(await screen.findByRole('status')).toHaveTextContent(/bornée/)
    expect(screen.queryByText('Fin des attributions accessibles.')).toBeNull()
  })

  it('n’écrit « 1 attribution » sur aucune carte', async () => {
    mockApi({ ...AUTHENTICATED, '/signals': feedPage([UNLOCKED_ITEM]) })
    renderApp(<AppRoutes />, { route: '/app/signals' })
    const rows = await screen.findAllByRole('button', { name: /Ouvrir le signal/ })
    expect(rows[0].textContent).not.toContain('1 attribution')
  })
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd frontend && npx vitest --run src/signals/feed.test.tsx -t "compte les signaux|bornée|1 attribution"`
Expected: FAIL.

- [ ] **Step 3: Implémenter**

`fr.ts` (`signalsPage`) : `signalCountOne: '{count} signal', signalCountOther: '{count} signaux',` ; `en.ts` : `signalCountOne: '{count} signal', signalCountOther: '{count} signals',`. `fr.ts` (`feed`) : `truncatedNote: 'La lecture a été bornée : consultez l’Historique pour les signaux plus anciens.'` ; `en.ts` : `truncatedNote: 'The read was capped: open History for older signals.'`.

`SignalsFeed.tsx` — compteur :
```tsx
  const signalCount = feed.data
    ? interpolate(
        plural(discoveryGrantCount ?? items.length, t.reference.signalsPage.signalCountOne, t.reference.signalsPage.signalCountOther),
        { count: `${discoveryGrantCount ?? items.length}${discoveryGrantCount === null && feed.data.page.has_more ? '+' : ''}` },
      )
    : t.reference.loading
```
(supprimer `planLabel` si plus utilisé ; importer `plural`). Le badge de plan reste dans l'en-tête de l'application.

Carte — remplacer le bloc `<span className={styles.awardCount}>{companyRow.cards.length} attribution…</span>` par :
```tsx
                {companyRow.cards.length > 1 ? (
                  <span className={styles.awardCount}>
                    {interpolate(t.reference.companiesPage.contractOther, { count: companyRow.cards.length })}
                  </span>
                ) : null}
```

Messages de fin — remplacer la ligne `endOfList` :
```tsx
        ) : feed.data && companyRows.length > 0 && !feed.data.page.scan_truncated ? <p className="signal-limit">{t.reference.signalsPage.endOfList}</p> : null}
```

`SignalsFeed.module.css` :
```css
.viewSwitch button, .filterHeading button { font-size: 12px; }
.accessNote, .restrictedNote { font-size: 12px; }
.filterGrid label { font-size: 12px; }
.filterGrid input, .filterGrid select { font-size: 13px; }
.awardCount { font-size: 12px; }
.awardContext strong {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  font-size: 13px;
}
.awardContext small { font-size: 12px; }
```
(modifier les règles existantes en place plutôt que d'en ajouter en double.)

`dashboard-reference.css` :
```css
.signal-item-head strong { min-width: 0; overflow-wrap: anywhere; font-size: 14px; }
.signal-item-head span { flex: 0 0 auto; align-self: flex-start; white-space: nowrap; font-size: 10px; }
.signal-count { font-size: 13px; font-weight: 720; color: var(--ink); }
.text-link { font-size: 13px; }
.market-amount-note { font-size: 12px; }
.signal-note-state { font-size: 12px; }
.signal-fact-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); }
@media (max-width: 1179px) {
  .signal-fact-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .signal-fact-grid > div:last-child:nth-child(3n + 1) { grid-column: 1 / -1; }
}
@media (max-width: 620px) {
  .signal-fact-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .signal-fact-grid > div:last-child:nth-child(odd) { grid-column: 1 / -1; }
}
```
(éditer les sélecteurs existants aux lignes indiquées par `grep -n "^\.signal-item-head span\|^\.signal-count\|^\.signal-fact-grid\|^\.text-link\|^\.market-amount-note\|^\.signal-note-state" frontend/src/reference/dashboard/dashboard-reference.css` ; s'il existe deux déclarations d'un même sélecteur, modifier la dernière, qui gagne.)

- [ ] **Step 4: Vérifier**

Run: `cd frontend && npx vitest --run && npm run typecheck && npm run lint && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SignalsFeed.tsx frontend/src/pages/SignalsFeed.module.css frontend/src/reference/dashboard/dashboard-reference.css frontend/src/i18n/fr.ts frontend/src/i18n/en.ts frontend/src/signals/feed.test.tsx
git commit -m "fix(signals): densité de la liste, compteur, grille de faits et messages de fin"
```

---

### Task 8 : goldens visuels et vérification de bout en bout

**Files:**
- Modify: `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png`, `dashboard-signals-mobile.png` (régénérés)
- Modify (si nécessaire) : `frontend/tests/visual/reference-port.spec.ts` (attentes textuelles de la vue Signaux, lignes ~165-215)

- [ ] **Step 1: Lancer les tests visuels pour constater les écarts**

Run: `cd frontend && npx playwright test reference-port --grep "dashboard-signals" 2>&1 | tail -30`
Expected: FAIL sur les deux goldens `dashboard-signals-*` (et seulement eux). Si un autre golden casse, une tâche précédente a débordé : revenir dessus avant de continuer.

- [ ] **Step 2: Corriger les attentes textuelles du spec**

Dans `reference-port.spec.ts`, bloc `if (golden === 'dashboard-signals')` : mettre à jour les attentes qui lisent la carte (par ex. `'Non publié · Non publié'` pour `.signal-meta`, la date `'Date d’attribution : 18 août 2026'`) selon le nouveau rendu de la tâche 5 (`Attribué le 18 août 2026`) et de la tâche 7 (plus de « 1 attribution »). Ne changer que ce que les captures montrent.

- [ ] **Step 3: Régénérer les deux goldens**

Run: `cd frontend && npm run capture:reference 2>&1 | tail -20`
Si le script exige un état git propre ou un `reference-source.json` particulier, lire son en-tête et suivre ses conditions. À défaut : `npx playwright test reference-port --grep "dashboard-signals" --update-snapshots`.
Expected: `dashboard-signals-desktop.png` et `dashboard-signals-mobile.png` régénérés ; aucun autre golden modifié (`git status --short frontend/tests/visual/reference-goldens` ne liste que ces deux fichiers).

- [ ] **Step 4: Relancer tout**

Run:
```bash
cd frontend && npx playwright test 2>&1 | tail -8
cd frontend && npx vitest --run 2>&1 | tail -4 && npm run typecheck && npm run lint && npm run build
cd .. && uv run pytest -q --deselect tests/test_acquisition_migration.py::test_projection_has_only_operationally_justified_indexes 2>&1 | tail -3 && uv run ruff check .
```
Expected: tout PASS.

- [ ] **Step 5: Contrôle visuel sur données réelles**

Depuis `frontend/`, lancer le serveur de dev pointé sur staging avec la session QA locale et capturer :
```bash
KIVOU_API_PROXY=https://staging.kivou.eu npm run dev -- --host 127.0.0.1 --port 5179
```
puis, dans un autre shell, un script Playwright (`node --input-type=module -`) qui ouvre `http://127.0.0.1:5179/app/signals` avec `storageState: ~/.local/state/kivou-card-qa-browser/storage-state.json` **et le cookie réécrit sur le domaine `127.0.0.1`**, et enregistre `desktop 1440×900`, `laptop 1280×720`, `mobile 390×844`, vues Récentes et Historique, dans le scratchpad de la session. Si le proxy refuse la session (cookie `SameSite`/domaine), capturer à la place les rendus sur fixtures via `installReferenceApi(page, 'connected-pro')` comme au début de la session. Vérifier à l'œil : montants avec séparateurs, « Notifié le … », badge sur une ligne, acheteur « non nommé par la source · SIRET … », lieu avec département, grille sans bloc vide, aucun « 1 attribution », compteur « N signaux ».

- [ ] **Step 6: Commit**

```bash
git add frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png frontend/tests/visual/reference-port.spec.ts
git commit -m "test(visual): régénérer les goldens de la page Signaux après le lot A"
```

---

## Self-review

- **Couverture de la spec :** A1 → T1 ; A2 → T2 + T3 ; A3 → T2 (complétude) ; A4 → T5 ; A5 → T4 ; A6 → T7 ; A7 → T6 ; A8 → T6 (chips) + T7 (grille) ; A9 → T7 ; A10 → T8. Rien du lot B n'est touché : `h2` du détail, `analysis`, tri, retour, casse.
- **Cohérence des types :** `Place.subdivision_label` (T3) ↔ `contract.location.subdivision_label` (T2) ; `SignalDetailView.facts.buyerIdentifier` et `eventStatus` définis (T3, T6) avant usage ; `signalsPage.datedOn`, `ageDaysOne/Other` (T5), `statusLabels`, `restrictedShort` (T6), `signalCountOne/Other` (T7) déclarés en `fr` ET `en`.
- **Risque connu :** l'import de `is_customer_display_name` dans `view.py` peut créer un cycle `query ↔ view` ; la tâche 2 dit quoi faire (module `identity_policy`).
