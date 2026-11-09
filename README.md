# apart-swarm-2026

Code, prompts, run logs and report for **"Split pieces, one gatekeeper: written no-composition rules in
coordinator-worker LLM teams"**, an entry to the Apart Research / AI Alignment Foundation *Swarm Alignment
Hackathon* (6-8 Nov 2026), Track 2 (The Science of Agent Networks). Author: Grant C. Wright (independent researcher).

**Question.** Every agent in a star-shaped team (a lead plus 3-8 workers) carries the same written rule against
assembling a forbidden whole (a three-part vault code, or a fictional employee's full record). Each worker holds one
piece. Does the team still hand the whole to a requester? All content is synthetic; leaks are scored by exact string
matching, with no judge model.

**Result in one line** (gpt-4.1-nano, 30 episodes per cell): rule wording moved leak rates from about 90% (no rule)
to 0% (absolute rule); splitting the pieces across a team raised leaks slightly and not significantly; workers
handed their pieces over freely, so the lead was the only checkpoint. See `docs/report.pdf`.

## Layout
| Path | What |
|---|---|
| `docs/report.pdf` | The submitted report |
| `docs/q2-design.md` | The experimental design, fixed before any run (with a preface on what changed) |
| `docs/spend-log.md` | Every paid API batch and its cost (total US$0.0789) |
| `swarm/` | Agent loop (`loop.py`), graphs, scenarios and prompts (`tasks.py`), string-match scorers, OpenRouter client with spend caps |
| `run.py` | CLI that runs episodes and writes `runs/<tag>/ep_NNN.jsonl` (every call and delivery) and `scores.jsonl` |
| `analyze.py` | Per-cell rates with Wilson 95% CIs and Fisher's exact tests |
| `runs/` | Every real run: pilot (`pilot_*`), no-rule control (`norule_*`), softened-wording pilot (`softpilot_*`), main grid (`main_*`); `runs/ledger.jsonl` is the per-call cost ledger |
| `tests/` | Offline tests (no API) |

## Reproduce
Python 3.11 and `requests`. Offline: `python -m unittest -v`, then
`python run.py q2 --scenario vault --condition split --trials 2 --mock`.
The analysis tables come from the committed runs: `python analyze.py --phase main` (and `--phase pilot`,
`--phase softpilot`, `--phase norule`).
Real runs need an OpenRouter key in `OPENROUTER_API_KEY` (or a `.env` file), e.g.
`python run.py q2 --scenario vault --condition visible --redundancy 2 --trials 30 --rule-variant soft --tag main_vault_visible_r2`.
The client refuses real calls before the sprint start (a sprint rule) and stops at a US$8 ledger total (US$3 for the `q2` arm); edit
`swarm/client.py` to change these. Model outputs vary run to run (temperature 0.7).

## Pre-existing code
The harness (`swarm/`, `run.py`, `tests/`) was written on 5 Nov 2026, before the sprint, as set-up only; no
result-producing call was made before the sprint opened. Written during the sprint (9 Nov): `analyze.py`, the
`--no-rule` / `--rule-variant` flags and the softened rule texts. This public repository has fresh history; the
private working repository is not published.

## Cite
Wright, G. C. (2026). *Split pieces, one gatekeeper: written no-composition rules in coordinator-worker LLM teams.*
Apart Research Swarm Alignment Hackathon. https://github.com/grant-wright/apart-swarm-2026

## Licence
Code MIT, docs and data CC BY 4.0. See `NOTICE.md`.
