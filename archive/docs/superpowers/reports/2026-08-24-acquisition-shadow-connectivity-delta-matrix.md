# Acquisition SHADOW connectivity — delta matrix

Date: 2026-08-24
Design authority: `53f0aae01077c33af1382887c396b4e9eecb27ac`

| Domain | Existing reused | Small addition | Missing implementation |
| --- | --- | --- | --- |
| Apollo | `ApolloOrganizationSearchClient`, `ApolloContactDiscoveryClient`, `ApolloCompanyResearchClient` and their bounded transports | Construct all three from the protected deployment key | Zero-credit `auth/health` and `users/api_profile` identity probe with an opaque acting-user fingerprint |
| Instantly | `HttpInstantlyProvider`, `InstantlyMailboxReadinessSource`, `normalize_mailbox_readiness`, and `CampaignWorker` as the sole business worker | Read-only current-workspace method and safe account-email path encoding | Workspace binding plus exactly-three-mailbox smoke orchestration; no second provider or worker |
| Hermes/OpenRouter | `HermesSupervisorAdapter`, `SubprocessHermesTransport`, bridge, CLI, strict supervisor contracts, and immutable TOML pin | Validate the exact non-secret deployment `config.yaml`; make the existing bridge enforce one zero-retry OpenRouter request with request-level fallback disabled and return route evidence | Compose existing health and advisory-plan calls in the smoke; no new Hermes engine or plan contract |
| Policy and operations | `PolicyStore.get_effective_control`, `AutonomyMode`, `OperationsStore`, and SPEC-031 execution controls | Bounded read of unresolved positive provider operations | Aggregate STAGING/SHADOW/read-only/kill-switch/zero-cap preflight |
| Persistence | Existing `CampaignStore` and the four acquisition campaign/provider tables | One read-only bounded counter method on the existing store | Before/after snapshot and exact delta; no new store, table, or migration |
| Deployment | Existing Python CLI conventions and systemd/runbook conventions | Seven protected settings plus one closed three-binding JSON document | Connectivity composition root, disabled manual oneshot, redacted examples, and VPS runbook |
| Business execution | `CampaignWorker` remains the sole campaign execution path | None | The smoke never starts it and never invokes a mutating worker/provider method |

The bridge adjustment is required because pinned Hermes `run_oneshot()` selects an
auxiliary route that owns transient retries and provider/model fallback. That real
upstream behavior conflicts with this smoke's no-retry/no-fallback contract. Kivou
therefore keeps the existing bridge and pinned Hermes client construction, but calls
the exact OpenRouter route once with SDK retries set to zero and
`allow_fallbacks=false`; the existing adapter rejects missing or different route
evidence.

The existing document-classification architecture test originally permitted provider
names only in files named `providers.py` or `openrouter.py`. The deployment contract
must name the approved OpenRouter provider/model explicitly, so its allowlist is
extended only to the exact Hermes adapter/bridge and connectivity config/contract/CLI
files. Provider names remain forbidden everywhere else in the domain.

## Non-duplication boundary

The connectivity package may define only its deployment document, bounded smoke result,
identity probe, orchestration, and CLI contracts. It must not define another Apollo
search/research client, Instantly provider, mailbox normalizer, campaign worker, Hermes
adapter/bridge/plan, Policy implementation, operations store, or persistence schema.
