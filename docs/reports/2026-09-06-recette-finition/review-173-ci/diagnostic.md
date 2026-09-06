# Diagnostic readiness et perimetre des corrections CI

## Cause mesuree avant correction

Les [horodatages du service API](api-boot-before.log) et le [journal du deploiement en echec](../review-173/deploy-18e37b8.log) montrent la sequence suivante, en UTC le 6 septembre 2026 :

| Evenement | Heure |
| --- | --- |
| Service Type=exec demarre | 16:22:36.989309 |
| Superviseur Uvicorn demarre | 16:22:37.311432 |
| Readiness abandonne apres cinq essais | 16:22:41.216376 |
| Premier worker : startup terminee | 16:22:41.568910 |
| Second worker : startup terminee | 16:22:41.575613 |

La fenetre reelle de sondage s'arrete apres 4,23 s. Le premier worker est pret apres 4,58 s, environ 353 ms apres cet abandon. L'etat systemd `active` correspond ici au superviseur execute, pas encore aux workers capables de servir HTTP.

La phase entre lancement du superviseur et demarrage des workers inclut l'import et la construction de l'application. Le [profil d'import](kivou-173-import-diagnostic.log) mesure 2,26 s pour le processus d'import isole. Une seconde [mesure import + construction](kivou-173-boot-diagnostic.log), sur fichiers deja lus, mesure 1,659 s d'import et 0,332 s de construction, soit 1,991 s. Cette mesure isolee ne remplace pas les 4,58 s observes pendant le redemarrage des deux workers.

Les migrations ne sont pas executees par `signals.api.asgi` : le script termine la repetition Alembic puis la migration vive avant la bascule et le redemarrage. La lecture SQL ulterieure, en transaction read-only, trouve la revision `0042_account_deletion` et zero session bloquee. Cette lecture constate l'etat ulterieur ; l'ordre du script et les journaux etablissent l'absence de migration dans le boot ASGI.

Le diagnostic `ss -ltnp "sport = :8000"` identifie un seul socket ecoute par le superviseur Uvicorn et ses deux workers. Aucun message de port deja occupe ni de crash n'apparait au demarrage ; le service a `NRestarts=0`.

## Correction

Le helper trace desormais les echecs de sonde avec statut HTTP, code de sortie curl, numero d'essai et temps ecoule. Il conserve la verification systemd avant chaque requete, son timeout d'une seconde, le timeout HTTP d'une seconde et l'echec immediat si le service s'arrete. Un HTTP 200 issu d'un curl en echec reste refuse.

La fenetre est ensuite portee a 15 essais espaces d'une seconde, sur la base du boot observe. Le nombre d'essais reste fini : au plus 15 controles systemd, 15 sondes HTTP et 14 attentes, soit une borne theorique de 44 s hors cout de lancement des commandes. Aucun parametre d'environnement n'est ajoute.

Les 11 tests du helper passent, dont un nouveau cas ou les cinq premieres connexions sont refusees et le sixieme essai reussit. Les tests couvrent aussi l'epuisement de la borne, un systemd lent, un service qui s'arrete et un curl retourne en erreur malgre le texte `200`.

## Assertions backend expliquees avant modification

`test_an_essential_plan_unlocks_subdivisions_but_not_sectors` est renomme `test_an_essential_plan_unlocks_both_subdivisions_and_sectors`. La decision validee ouvre Secteur en Essentiel. La fixture contient le CPV `45000000` ; le test attend maintenant le prefixe `45`, son libelle francais, les deux permissions a `true` et le plan `essential`. Le test Decouverte reste restrictif et n'est pas modifie.

`test_missing_object_amount_and_place_use_the_published_buyer_fallback` est renomme `test_missing_object_uses_the_cpv_label_and_keeps_other_missing_facts_absent`. La fixture SIMAP `29997-02` conserve son CPV lorsque son titre est efface. Le test attend donc le libelle CPV dans l'objet et le titre compose ; il continue d'exiger que montant et lieu soient absents. Aucun fait de remplacement n'est invente et aucun code metier n'est modifie.

## Goldens : liste fermee

La CI du commit `7117f77` valide les deux corrections ci-dessus et revele une troisieme attente ancienne dans le shard 0 : `test_fallback_never_reads_analysis_or_adds_a_person_or_urgency`. Sa fixture SIMAP `33885-03` conserve aussi son CPV. L'attente generique est alignee sur ce libelle publie, apres explication a l'utilisateur ; les interdictions de nom invente, d'urgence et de besoin infere restent strictement inchangees. Aucun code metier n'est modifie pour faire passer cette assertion.

Les 12 echecs visuels initiaux comprennent 11 images et le test de hauteur Aujourd'hui, sans image. Seuls les goldens suivants ont ete regeneres : Aujourd'hui Essentiel et Decouverte, Signaux, Entreprises et Reglages, chacun desktop/mobile, plus le menu lateral mobile. Ces pages ou leur AppShell figurent dans le diff de la PR.

Le [manifeste SHA-256](kivou-173-golden-scope.json) atteste 11 images modifiees et 21 images identiques octet pour octet, sans modification hors liste. La tolerance reste `maxDiffPixelRatio: 0.001`. La [suite complete sans regeneration](kivou-173-visual-final.log) passe 39/39 tests, y compris tous les ecrans non touches.

## Commandes et instructions emises

```bash
ssh -o ConnectTimeout=10 kivou-staging 'sudo journalctl -u kivou-api.service --since "2026-09-06 16:20:00 UTC" --until "2026-09-06 16:30:00 UTC" --no-pager -o short-iso-precise'
```

Ce journal contient cette instruction standard, non executee :

```text
2026-09-06T16:22:37.311432+00:00 kivou-staging-01 kivou-api[757301]: INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Commandes visuelles depuis `frontend/` :

```bash
npx playwright test --grep '(dashboard-(overview|overview-discovery|signals|companies|account) (desktop|mobile)|dashboard sidebar open mobile)$' --update-snapshots=changed
npx playwright test
```

Les [journaux de regeneration](kivou-173-goldens-update-selected.log) et de suite complete conservent ces instructions exactes, non executees :

```text
[WebServer] (Use `node --trace-warnings ...` to show where the warning was created)
(Use `node --trace-warnings ...` to show where the warning was created)
```

Tests locaux sans chargement des fixtures de base et sans migration :

```bash
.venv/bin/pytest --noconftest tests/test_ops_api_readiness.py -q
.venv/bin/ruff check tests/test_ops_api_readiness.py tests/test_signal_filters_endpoint.py tests/test_feed_factual_display.py
```

Les assertions backend sont executees par la CI sur ses bases de test isolees, pas contre la base staging depuis le poste.

## Deploiement et recette apres correction

Le script serveur termine avec `Result=success`, `ExecMainStatus=0` et le SHA applicatif `7117f7762794544d192f4865cb5c03032537c434` actif. Le [journal integral](deploy-7117f77.log) contient :

```text
api_readiness=waiting unit=kivou-api.service attempt=1 http_status=000 curl_exit=7 elapsed_seconds=0
api_readiness=waiting unit=kivou-api.service attempt=2 http_status=000 curl_exit=7 elapsed_seconds=1
api_readiness=waiting unit=kivou-api.service attempt=3 http_status=000 curl_exit=7 elapsed_seconds=2
api_readiness=ready unit=kivou-api.service port=8000 attempt=4 elapsed_seconds=4
[kivou-deploy] release active : 7117f7762794544d192f4865cb5c03032537c434 (staging)
```

Commande de collecte :

```bash
ssh -o ConnectTimeout=10 kivou-staging 'sudo journalctl -u kivou-173-review-deploy-7117f77 --no-pager -o cat'
```

Les instructions npm/Vite de ce journal sont conservees mot pour mot dans le fichier, avec les memes avertissements deja cites dans les [commandes de la revue precedente](../review-173/commandes.md). Aucune suggestion issue de ces sorties n'est executee.

La [premiere recette](staging-first/results.json) passe 13/14 controles. Le premier panneau Entreprises du compte QA ne devient pas visible avant les 5 secondes attendues par le test. La cause de cet echec ponctuel n'est pas etablie ; il ne doit pas etre efface du compte rendu ni presente comme corrige.

La [reprise complete et inchangee](staging-repeat/results.json) passe 14/14 controles, confirme par le [journal](playwright-repeat.log). Aucun timeout ni comportement applicatif n'est modifie entre ces deux passages. Les deux comptes sont testes a 1440 et 390 px, drawer inclus. Exemples : [Entreprises desktop](staging-repeat/essentiel-1440-companies-switched.png), [Signaux mobile](staging-repeat/decouverte-390-signals.png), [Reglages desktop](staging-repeat/essentiel-1440-settings.png), [Reglages mobile](staging-repeat/essentiel-390-settings.png).

La reprise utilise exactement le meme script de recette :

```bash
ssh -o ConnectTimeout=10 kivou-staging 'sudo systemd-run --no-block --unit=kivou-173-review-after-7117f77-repeat --property=Type=oneshot --property=EnvironmentFile=/etc/kivou/staging.env --property=StandardOutput=journal --property=StandardError=journal /srv/kivou/app/.venv/bin/python -u /srv/kivou/app/ops/validation/recette_review_173.py /srv/kivou/qa-173-review-after-7117f77-repeat'
```
