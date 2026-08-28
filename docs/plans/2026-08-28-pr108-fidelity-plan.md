# PR 108 staging fidelity implementation plan

1. Add failing frontend tests for the reference public shell, home composition,
   API-backed compact offer summary, connected sidebar/topbar and honest empty
   dashboard states.
2. Align public design tokens, shell, logo treatment, footer and responsive menu
   with the public reference while retaining FR/EN and same-origin routes.
3. Refactor the six public pages to the reference structures and styles; keep
   billing, contact and legal behaviour authoritative.
4. Align the connected shell, route-aware topbar and mobile drawer with the
   dashboard reference.
5. Restyle and, where necessary, restructure dashboard, signals, companies,
   targeting, billing, notifications and settings around their existing API
   states and actions.
6. Run focused tests during each slice, then the full frontend suite, build,
   typecheck and lint. Review the final diff against the protected boundaries.
7. Commit, push and open a PR; merge only after the complete GitHub CI is green.
8. Deploy only the merged frontend SHA to staging, then verify every required
   public and authenticated route in desktop/mobile browser sessions.
