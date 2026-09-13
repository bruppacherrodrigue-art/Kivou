# Enrichment candidate benchmark — 2026-09-13

## Protocol

- Fixed corpus: 30 supplier records, including the six manual overrides.
- Frozen reduced evidence; no supplier-directory enrichment was executed.
- Maximum input: 3,833 tokens; output allowance: 800 tokens.
- Hidden reasoning disabled, except GPT-5 Mini at mandatory `minimal` effort.
- Pragmatic gate: at least 90% valid JSON, 80% overall agreement, 80% website
  agreement, and 80% email agreement. The cheapest qualifying model wins.

## Results

| Model | Overall | Website | Email | Family | Director | Invalid JSON | Median latency | Cost / 30 | Projected / 20k |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `openai/gpt-5-mini` | 80.83% | 90.00% | 80.00% | 66.67% | 86.67% | 0 | 3,544 ms | $0.01797260 | $11.98 |
| `google/gemini-2.5-flash` | 65.00% | 83.33% | 80.00% | 10.00% | 86.67% | 0 | 1,126 ms | $0.03600930 | $24.01 |
| `moonshotai/kimi-k2.6` | 30.00% | 33.33% | 33.33% | 30.00% | 23.33% | 18 | 5,510 ms | $0.06604464 | $44.03 |
| `x-ai/grok-4.3` | 80.83% | 86.67% | 76.67% | 76.67% | 83.33% | 0 | 2,277 ms | $0.08658290 | $57.72 |

Selected economic judge: `openai/gpt-5-mini`. Sonnet remains the arbiter below
confidence 0.8 or for invalid JSON.

## Corrections made before the valid run

The original invalid-JSON counts were not model-quality results. Two transport
issues were found and corrected:

1. GPT-5 Mini requires reasoning; `minimal` is used so reasoning cannot consume
   the whole completion. Kimi, Gemini, and Grok run without hidden reasoning.
2. OpenRouter reports costs with eight decimal places, while the enrichment
   result contract accepted only six. Valid decisions were therefore rejected
   during cost validation. The contract now matches the persistent journal's
   `NUMERIC(14, 8)` precision.

Reservation / real ratios on the valid run were 1.92 for GPT-5 Mini, 0.96 for
Gemini, 0.52 for Kimi, and 0.40 for Grok. None exceeds 3, so the reservation
estimator does not require a downward adjustment.

## Complément demandé le 13 septembre

### Arbitrage famille et contrôle Mistral Small

Le seuil d'appel de Sonnet inclut désormais `family_confidence < 0.8`, sans
modifier le seuil déterministe de conservation de la famille (`0.7`). Une
nouvelle mesure a rejoué uniquement les décisions LLM sur les 30 paquets de
preuves figés ; elle n'a écrit aucune fiche de l'annuaire.

| Mesure | Résultat |
|---|---:|
| Arbitrage avec site/adresse seulement | 20 / 30 (66.67%) |
| Arbitrage avec site/adresse/famille | 22 / 30 (73.33%) |
| Surcroît dû au seuil famille | 2 / 30 (6.67 points) |
| Coût juge GPT-5 Mini observé / fiche | $0.00118678 |
| Coût Sonnet central projeté / appel | $0.01323350 |
| Coût central juge + arbitrage / fiche | $0.01089135 |

Le coût Sonnet est une projection, pas une dépense observée : aucun appel
arbitre n'a été lancé. Elle utilise le tarif OpenRouter courant de Sonnet 4.6
($3/M tokens d'entrée, $15/M tokens de sortie), 3 200 tokens d'entrée et les
242.23 tokens de sortie moyens observés. L'intervalle bas/haut utilise
respectivement 2 894/150 et 4 000/300 tokens, soit $0.00920358 à $0.01328678
par fiche, juge compris.

`mistralai/mistral-small-2603` était disponible. Il avait été omis de la passe
corrigée lorsque la liste avait été remplacée par GPT/Gemini/Kimi/Grok après
le premier essai, dont les invalides étaient faussés par l'ancien contrat de
coût. Sa mesure corrigée est :

| Model | Overall | Website | Email | Family | Director | Invalid JSON | Median latency | Cost / 30 | Projected / 20k |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mistralai/mistral-small-2603` | 50.83% | 70.00% | 66.67% | 13.33% | 53.33% | 5 | 1,743 ms | $0.01842810 | $12.29 |

Sur cette mesure complémentaire, le ratio réservé/réel vaut 1.87 pour Mistral
et 0.97 pour GPT-5 Mini. Aucun ratio ne dépasse 3 ; l'estimation conservatrice
n'est donc pas abaissée.

### Étape 7 — planification en lecture seule

Instantané SQL de production, sans purge ni passe :

| Population | Lignes | Uniques / chevauchement |
|---|---:|---:|
| `supplier_directory` | 528 | 281 sans jugement |
| `winner_enrichment_job` en attente | 5 490 | 5 482 rattachées à un compte actif |
| Titulaires actifs distincts | 5 482 lignes | 3 181 titulaires |
| Doublons internes à la file active | 2 301 | — |
| Identités actives | — | 3 133 SIREN + 48 empreintes sans SIREN |
| Déjà présents dans l'annuaire | — | 20 : 18 jugés + 2 sans jugement |
| Absents de l'annuaire | — | 3 161 |
| Candidats de purge inactifs | 8 | aucune suppression effectuée |

La séquence produit donc au plus 3 442 jugements économiques : 281 fiches,
puis 3 161 titulaires actifs absents de l'annuaire. Les 2 titulaires actifs
déjà inclus dans les 281 ne sont pas recomptés et les 18 déjà jugés restent en
cache. Les 48 empreintes sans SIREN sont incluses dans la borne haute ; une
résolution impossible les arrêtera avant tout appel LLM.

| Phase | Bas | Central | Haut | Jours à $2/jour (bas / central / haut) |
|---|---:|---:|---:|---:|
| 281 fiches sans jugement | $2.59 | $3.06 | $3.73 | 2 / 2 / 2 |
| 3 161 titulaires actifs supplémentaires | $29.09 | $34.43 | $42.00 | 15 / 18 / 21 |
| Total unique, 3 442 | $31.68 | $37.49 | $45.73 | 16 / 19 / 23 |

Ces jours divisent le coût combiné par $2. Avec les deux plafonds actuellement
séparés (`enrichment_judge` $2/jour et `enrichment_arbiter` $1/jour), Sonnet
est le facteur limitant : le total demanderait respectivement 28, 34 ou 42
jours. Aucun lot n'a été démarré.
