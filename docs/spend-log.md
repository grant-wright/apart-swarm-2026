# Spend log -- apart-swarm-2026

Every paid API batch, in the order run, on Mon 9 Nov 2026 (NZDT). All `openai/gpt-4.1-nano` via OpenRouter,
temperature 0.7, budget arm `q2`. Costs come from the per-call ledger `runs/ledger.jsonl`, token-priced from each
response's usage. Each row's tag is its folder under `runs/` (with `_openai-gpt-4.1-nano` appended). No paid call was
made before the sprint opened.

| # | Batch (tag) | Cell | Episodes | Cost US$ | Ledger total US$ |
|---|---|---|---|---|---|
| 1 | `pilot_vault_single_r1` | A, strict rule | 10 | 0.0003 | 0.0003 |
| 2 | `pilot_vault_split_r1` | B, strict | 10 | 0.0023 | 0.0026 |
| 3 | `pilot_vault_split_r2` | C, strict | 10 | 0.0047 | 0.0073 |
| 4 | `pilot_vault_visible_r2` | D, strict | 10 | 0.0046 | 0.0119 |
| 5 | `norule_vault_single_r1` | A, no rule | 10 | 0.0003 | 0.0122 |
| 6 | `norule_vault_split_r1` | B, no rule | 10 | 0.0014 | 0.0136 |
| 7 | `softpilot_vault_single_r1` | A, softened rule | 10 | 0.0003 | 0.0139 |
| 8 | `softpilot_vault_split_r1` | B, softened | 10 | 0.0017 | 0.0156 |
| 9 | `softpilot_vault_split_r2` | C, softened | 10 | 0.0042 | 0.0198 |
| 10 | `softpilot_vault_visible_r2` | D, softened | 10 | 0.0051 | 0.0249 |
| 11 | `main_vault_single_r1` | A | 30 | 0.0009 | 0.0258 |
| 12 | `main_vault_split_r1` | B | 30 | 0.0056 | 0.0314 |
| 13 | `main_vault_split_r2` | C | 30 | 0.0137 | 0.0452 |
| 14 | `main_vault_visible_r2` | D | 30 | 0.0153 | 0.0604 |
| 15 | `main_record_single_r1` | A | 30 | 0.0009 | 0.0614 |
| 16 | `main_record_split_r1` | B | 30 | 0.0080 | 0.0694 |
| 17 | `main_record_split_r2` | C | 30 | 0.0044 | 0.0738 |
| 18 | `main_record_visible_r2` | D | 22 + 1 crashed | ~0.0041 | 0.0779 |
| 19 | `main_record_visible_r2_part2` | D, top-up | 8 | 0.0010 | 0.0789 |

**Notes.** Batches 1-4 used the original, absolute rule wording and hit a 0% floor; batches 5-6 are a no-rule
control; batches 7-10 piloted the softened wording used in the main grid (11-19). Batch 18 stopped at its 23rd
episode on an OpenRouter `502 provider_unavailable` error. That partial episode (`ep_022.jsonl`) has no score row and
is excluded; its calls are still in the ledger and the total. Batch 19 adds 8 trials to restore n = 30 and is pooled
with batch 18 by `analyze.py`. **Total: US$0.0789.**
