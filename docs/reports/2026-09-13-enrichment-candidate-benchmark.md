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
