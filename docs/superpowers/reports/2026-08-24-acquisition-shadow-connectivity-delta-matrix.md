# Acquisition SHADOW connectivity — delta matrix

Date: 2026-08-24
Design authority: `53f0aae01077c33af1382887c396b4e9eecb27ac`

| Domain | Existing reused | Small addition | Missing implementation |
| --- | --- | --- | --- |
| Apollo | `ApolloOrganizationSearchClient`, `ApolloContactDiscoveryClient`, `ApolloCompanyResearchClient` and their bounded transports | Construct all three from the protected deployment key | Zero-credit `auth/health` and `users/api_profile` identity probe with an opaque acting-user fingerprint |
| Instantly | `HttpInstantlyProvider`, `InstantlyMailboxReadinessSource`, `normalize_mailbox_readiness`, and `CampaignWorker` as the sole business worker | Read-only current-workspace method and safe account-email path encoding | Workspace binding plus exactly-three-mailbox smoke orchestration; no second provider or worker |
| Hermes/OpenRouter | `HermesSupervisorAdapter`, `SubprocessHermesTransport`, bridge, CLI, strict supervisor contracts, and immutable TOML pin | Validate the exact non-secret deployment `config.yaml` before invocation | Compose existing health and advisory-plan calls in the smoke; no new Hermes engine or plan contract |
| Policy and operations | `PolicyStore.get_effective_control`, `AutonomyMode`, `OperationsStore`, and SPEC-031 execution controls | Bounded read of unresolved positive provider operations | Aggregate STAGING/SHADOW/read-only/kill-switch/zero-cap preflight |
| Persistence | Existing `CampaignStore` and the four acquisition campaign/provider tables | One read-only bounded counter method on the existing store | Before/after snapshot and exact delta; no new store, table, or migration |
| Deployment | Existing Python CLI conventions and systemd/runbook conventions | Seven protected settings plus one closed three-binding JSON document | Connectivity composition root, disabled manual oneshot, redacted examples, and VPS runbook |
| Business execution | `CampaignWorker` remains the sole campaign execution path | None | The smoke never starts it and never invokes a mutating worker/provider method |

## Non-duplication boundary

The connectivity package may define only its deployment document, bounded smoke result,
identity probe, orchestration, and CLI contracts. It must not define another Apollo
search/research client, Instantly provider, mailbox normalizer, campaign worker, Hermes
adapter/bridge/plan, Policy implementation, operations store, or persistence schema.
