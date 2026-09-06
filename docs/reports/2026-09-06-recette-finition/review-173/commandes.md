# Commandes et sorties conservees

## Deploiement exclusivement sur le serveur

Commande executee depuis le poste, sans migration locale ni ajout de variable :

```bash
ssh -o ConnectTimeout=10 kivou-staging 'sudo -u kivou -H git -c safe.directory=/srv/kivou/source -C /srv/kivou/source fetch --no-tags origin fix/recette-finition && sudo -u kivou -H git -c safe.directory=/srv/kivou/source -C /srv/kivou/source checkout --detach 18e37b8e454150a2e3b0670b9f8f7d150d885b41 && sudo systemd-run --unit=kivou-173-review-deploy-18e37b8 --property=Type=oneshot --property=EnvironmentFile=/etc/kivou/staging.env --property=StandardOutput=journal --property=StandardError=journal /srv/kivou/source/ops/bin/kivou-deploy.sh staging 18e37b8e454150a2e3b0670b9f8f7d150d885b41'
```

Commande de collecte du [journal exact](deploy-18e37b8.log) :

```bash
ssh -o ConnectTimeout=10 kivou-staging 'sudo journalctl -u kivou-173-review-deploy-18e37b8 --no-pager -o cat'
```

Instructions emises dans ce journal, citees telles quelles et non executees :

```text
npm warn deprecated whatwg-encoding@3.1.1: Use @exodus/bytes instead for a more spec-conformant and faster implementation
  run `npm fund` for details
npm warn allow-scripts Run `npm approve-scripts --allow-scripts-pending` to review, or `npm approve-scripts <pkg>` to allow.
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
```

Echec exact du script :

```text
api_readiness=timeout unit=kivou-api.service attempts=5
kivou-173-review-deploy-18e37b8.service: Main process exited, code=exited, status=1/FAILURE
kivou-173-review-deploy-18e37b8.service: Failed with result 'exit-code'.
```

Diagnostic ulterieur, sans redemarrage ni redeploiement :

```bash
ssh -o ConnectTimeout=10 kivou-staging '/srv/kivou/source/ops/bin/kivou-api-readiness.sh kivou-api.service 8000'
```

```text
api_readiness=ready unit=kivou-api.service port=8000 attempt=1
```

Le journal API obtenu par la commande suivante contient aussi une instruction standard de demarrage, non executee :

```bash
ssh -o ConnectTimeout=10 kivou-staging 'systemctl show kivou-api.service -p ActiveState -p SubState -p Result -p ExecMainStatus; sudo journalctl -u kivou-api.service --since "2026-09-06 16:16:00 UTC" --no-pager -o cat -n 65'
```

```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

## Recette staging

```bash
ssh -o ConnectTimeout=10 kivou-staging 'sudo systemd-run --no-block --unit=kivou-173-review-after-18e37b8 --property=Type=oneshot --property=EnvironmentFile=/etc/kivou/staging.env --property=StandardOutput=journal --property=StandardError=journal /srv/kivou/app/.venv/bin/python -u /srv/kivou/app/ops/validation/recette_review_173.py /srv/kivou/qa-173-review-after-18e37b8'
```

Le [journal Playwright](playwright-after.log) et les [resultats JSON](after/results.json) attestent 14 succes et un code de sortie zero. Les secrets existants du serveur sont utilises, jamais copies dans les artefacts.

## CI

Les journaux complets sont joints avec leurs commandes de collecte :

```bash
gh api repos/bruppacherrodrigue-art/Kivou/actions/jobs/101518083837/logs
gh api repos/bruppacherrodrigue-art/Kivou/actions/jobs/101518083868/logs
gh api repos/bruppacherrodrigue-art/Kivou/actions/jobs/101518083904/logs
```

[Frontend](ci-frontend.log) : 12 echecs visuels, dont attente de `Plan` dans le bandeau illimite et differences avec les anciennes captures.

[Backend 2](ci-backend-2.log) : `test_an_essential_plan_unlocks_subdivisions_but_not_sectors` attend une liste vide de secteurs alors que le prefixe `45` est renvoye.

[Backend 3](ci-backend-3.log) : `test_missing_object_amount_and_place_use_the_published_buyer_fallback` attend le nom de l'acheteur alors que le libelle CPV est affiche.

Les instructions PostgreSQL suivantes figurent dans les deux journaux backend, avec horodatages conserves dans les fichiers sources ; elles ne sont pas executees sur staging :

```text
This user must also own the server process.
initdb: hint: You can change this by editing pg_hba.conf or using the option -A, or --auth-local and --auth-host, the next time you run initdb.
Success. You can now start the database server using:
    pg_ctl -D /var/lib/postgresql/data -l logfile start
```

## Validation locale

```bash
cd /home/jaybe/projects/Kivou/frontend
npm run typecheck
npx vitest run --reporter=dot
```

[Sortie Vitest](vitest-final.log) : 49 fichiers, 674 tests reussis. Les avertissements jsdom sur la navigation externe ne font echouer aucun test.
