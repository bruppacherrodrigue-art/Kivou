# Stendhal electrical assisted queue — design

> **Statut : remplacé.** La préparation d'un couple unique a été remplacée par la [préparation catalogue ASSISTED](./2026-09-18-assisted-catalog-preparation-design.md). Ne pas implémenter ce document.

## Objective

Replace the exhausted Monod timber targeting pair with the procurement opportunity
`opp_66e58fd25659ae991caefd864382366b8f7e`:

- title: `Réaménagement et réhabilitation thermique des bâtiments Stendhal F et H - Électricité – courants forts – courants faibles`;
- holder: SPIE BUILDING SOLUTIONS, SIREN `440055861`;
- one materialized family only: `electrical`;
- site-published target addresses only;
- at most eight new `pending_review` targets;
- no transport call and no Instantly call.

The preflight found nine fresh site targets. The signal amount is above the large-signal
threshold, so the existing `LARGE_SIGNAL_LIMIT = 8` provides the requested cap without a
global limit change.

## Selection and configuration

The production acquisition document will keep ASSISTED mode and Auvergne-Rhône-Alpes,
while changing both the QA scope and dynamic selection vertical to
`technical_installation`. Selection will be pinned to the Stendhal opportunity with:

- `family_key = electrical`;
- `email_source = site`;
- `pinned_opportunity_key = opp_66e58fd25659ae991caefd864382366b8f7e`.

The resolver must filter the materialized signal to exactly `electrical`; discovery or
display data must not reintroduce another family.

## Holder safety and enrichment

Before preparation, SPIE's directory record will be passed through the existing bounded
company-enrichment path. The goal is to obtain at least one public holder fact among a
website, telephone number, or published e-mail. This enrichment must not call Instantly.

Regardless of enrichment outcome, `ProspectPreparationService` must exclude the exact
holder SIREN from eligible targets. A regression test will first demonstrate that a
confirmed holder in the requested family can currently target itself, then verify that it
is excluded while other suppliers remain eligible.

If SPIE still has no website, telephone, or published e-mail after bounded enrichment, the
queue may still be prepared but delivery must report: `ne pas envoyer tant que titulaire
pauvre`.

## Execution

After deploying the holder-exclusion guard and the production configuration, only one
`prepare-queue --max-signals 1` run is allowed. The acquisition lock remains mandatory.
No send worker is started and no `/send` or Instantly endpoint is called.

Historical exclusions remain active:

- no SIREN previously rejected;
- no SIREN accepted for sending in the last 30 days;
- no currently queued SIREN;
- no exact historical target for this opportunity;
- no SPIE holder SIREN.

## Acceptance checks

The live Founder response and database must jointly prove:

1. `targeting.family_keys == ["electrical"]` and the signal is the Stendhal electrical lot.
2. The queue contains between three and eight `pending_review` rows.
3. Every row has `family_key = electrical` and `email_source = site`.
4. No row has SIREN `440055861`.
5. Each row uses one identical kat1 attribution URL in `attribution_url`, `mail_text`, and
   `mail_html`.
6. Two previews discuss Stendhal electrical work and contain no charpente, bardage, Tzen,
   vestiaires, roofing, or scaffolding leakage.
7. The durable `sent` count is unchanged from the pre-execution snapshot.
8. No send or Instantly operation occurred.

If fewer than three rows survive at execution time, the queue remains empty and the run is
reported as ineligible rather than being filled from model addresses, another family, or
another notice.
