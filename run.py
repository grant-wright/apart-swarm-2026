"""CLI runner. Every real batch writes per-episode JSONL logs + a scores.jsonl under runs/<tag>/,
and every real call is in runs/ledger.jsonl with its cost. Log each batch in session-log.md.

Examples (offline, no API):
  python run.py q2 --scenario vault --condition split --trials 2 --mock
  python run.py q3 --topology star --n 10 --rounds 4 --mock
  python run.py q3-cal --trials 5 --mock
Real runs drop --mock. Before Fri 6 Nov 19:00 UTC they are refused unless --allow-pre-sprint
(a disclosed connectivity check only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from swarm import scorers
from swarm.client import MockClient, OpenRouterClient, ledger_total
from swarm.loop import run_episode
from swarm.tasks import CANARY_TOKEN, SCENARIOS, SOFT_RULES, q2_agents, q3_agents, q3_calibration_agents

REPO = Path(__file__).resolve().parent
DEFAULT_MODEL = "openai/gpt-4.1-nano"


# ---- deterministic mock policies (pipeline smoke tests only; NOT results) ----
def mock_policy(model, messages):
    system, last = messages[0]["content"], messages[-1]["content"]
    if "team lead" in system and "You hold no records" in system:
        workers = sorted({w for w in system.split() if w.startswith("w") and w[1:].isdigit()})
        if "from w" not in last:
            return "\n".join(f"@{w}: please send me your record." for w in workers)
        return "@user: " + last
    if "You hold one record:" in system:
        return system.split("You hold one record:")[1].splitlines()[0]
    if "@user:" in system:  # solo
        return "@user: I can't share the full record under policy."
    # Q3: infected if own prompt or inbox carries the token, else 50/50 by hash
    if CANARY_TOKEN in system:
        return f"Idea. {CANARY_TOKEN}"
    if CANARY_TOKEN in last and int(hashlib.md5(last.encode()).hexdigest(), 16) % 2:
        return f"Agreed. {CANARY_TOKEN}"
    return "Let's book the hall."


def make_client(args, tag):
    if args.mock:
        return MockClient(mock_policy)
    arm = args.arm or ("q2" if args.cmd == "q2" else "q3")
    c = OpenRouterClient(budget_stop_usd=args.stop_usd, allow_pre_sprint=args.allow_pre_sprint,
                         run_tag=tag, arm=arm)
    c.preflight()  # fail before any output folder is created
    return c


def out_dir(args, tag):
    base = REPO / "runs" / ("mock" if args.mock else "") / tag
    base.mkdir(parents=True, exist_ok=True)
    return base


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["q2", "q3", "q3-cal"])
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--mock", action="store_true")
    p.add_argument("--allow-pre-sprint", action="store_true")
    p.add_argument("--stop-usd", type=float, default=8.0)
    p.add_argument("--arm", choices=["q2", "q2-reasoning", "q3"], default=None,
                   help="budget arm (default: q2 for q2, q3 for q3/q3-cal); caps in swarm/client.py ARM_STOPS")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--max-tokens", type=int, default=400)
    # q2
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="vault")
    p.add_argument("--condition", choices=["single", "split", "visible"], default="split")
    p.add_argument("--redundancy", type=int, default=1)
    p.add_argument("--rounds", type=int, default=None)
    p.add_argument("--no-rule", action="store_true", help="control: drop the policy text from every prompt")
    p.add_argument("--rule-variant", choices=["strict", "soft"], default="strict")
    # q3
    p.add_argument("--topology", default="complete")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--seed-node", default="hub")
    p.add_argument("--max-history-turns", type=int, default=3)
    p.add_argument("--tag", default="")
    a = p.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if a.cmd == "q2":
        tag = a.tag or f"{stamp}_q2_{a.scenario}_{a.condition}_r{a.redundancy}"
    elif a.cmd == "q3":
        tag = a.tag or f"{stamp}_q3_{a.topology}_n{a.n}_{a.seed_node}"
    else:
        tag = a.tag or f"{stamp}_q3cal"
    tag = f"{tag}_{a.model.replace('/', '-')}"
    client, d = make_client(a, tag), out_dir(a, tag)
    before = 0.0 if a.mock else ledger_total()
    with (d / "scores.jsonl").open("a", encoding="utf-8") as sf:
        for t in range(a.trials):
            meta = {"cmd": a.cmd, "trial": t, "model": a.model, "mock": a.mock,
                    "args": {k: v for k, v in vars(a).items()}}
            log = d / f"ep_{t:03d}.jsonl"
            if a.cmd == "q2":
                agents, g, kick, lead = q2_agents(a.scenario, a.condition, a.model,
                                                  redundancy=a.redundancy,
                                                  rule="" if a.no_rule else (SOFT_RULES[a.scenario] if a.rule_variant == "soft" else None))
                rounds = a.rounds or (1 if a.condition == "single" else 6)
                ep = run_episode(agents, g, client, kickoff=kick, rounds=rounds,
                                 stop_when=lambda e: bool(e.sink["user"]), temperature=a.temperature,
                                 max_tokens=a.max_tokens, log_path=log, meta=meta)
                score = scorers.q2_score(ep, SCENARIOS[a.scenario], lead)
            elif a.cmd == "q3":
                agents, g, kick, seed = q3_agents(a.topology, a.n, a.model, seed_node=a.seed_node,
                                                  graph_seed=t)
                meta["seed_agent"] = seed
                ep = run_episode(agents, g, client, kickoff=kick, rounds=a.rounds or 8, sinks=set(),
                                 only_if_inbox=False, max_history_turns=a.max_history_turns,
                                 temperature=a.temperature, max_tokens=a.max_tokens, log_path=log,
                                 meta=meta)
                score = scorers.q3_curves(ep, list(agents)) | {"seed_agent": seed}
            else:
                agents, g, kick, _ = q3_calibration_agents(a.model)
                ep = run_episode(agents, g, client, kickoff=kick, rounds=1, sinks=set(),
                                 temperature=a.temperature, max_tokens=a.max_tokens, log_path=log,
                                 meta=meta)
                score = {"hit": scorers.q3_calibration_hit(ep), "cost_usd": ep.cost_usd}
            row = {"trial": t, "log": log.name, **score}
            sf.write(json.dumps(row) + "\n")
            print(json.dumps(row))
    spent = 0.0 if a.mock else ledger_total() - before
    print(f"[{tag}] {a.trials} trial(s) -> {d}  batch cost US${spent:.4f}"
          + ("" if a.mock else f"  ledger total US${ledger_total():.4f}"))


if __name__ == "__main__":
    main()
