"""Q2 analysis (written during the sprint, Mon 9 Nov 2026). Reads runs/<tag>/scores.jsonl for real runs
(never runs/mock) and prints per-cell proportions with Wilson 95% CIs, plus the planned Fisher's exact tests
(docs/q2-design.md s.7): A-B (H2a), B-C (H2b-i), C-D (H2c), per scenario. Raw p-values; three planned
comparisons per scenario, so read with multiplicity in mind.

Run folders must be tagged  {phase}_{scenario}_{condition}_r{redundancy}  (run.py appends _{model}), e.g.
  python run.py q2 --scenario vault --condition split --redundancy 2 --trials 10 --tag pilot_vault_split_r2
Usage:  python analyze.py [--phase pilot|main] [--metric whole_in_one_user_msg] [--md out.md]
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent
TAG = re.compile(r"^(?P<phase>[a-z0-9]+)_(?P<scenario>vault|record)_(?P<cond>single|split|visible)"
                 r"_r(?P<red>\d)(?:_part\d+)?_(?P<model>.+)$")  # _partN = top-up batch, pooled into the cell
CELLS = {("single", "1"): "A", ("split", "1"): "B", ("split", "2"): "C", ("visible", "2"): "D",
         ("visible", "1"): "B'"}
TESTS = [("A", "B", "H2a"), ("B", "C", "H2b-i"), ("C", "D", "H2c")]
METRICS = ["whole_in_one_user_msg", "whole_across_user_msgs", "lead_gathered_whole", "answered",
           "answer_looks_like_refusal", "reassigned"]


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """2x2 table [[a,b],[c,d]]; two-sided p = sum of hypergeometric probs <= P(observed)."""
    r1, c1, n = a + b, a + c, a + b + c + d

    def lp(x):  # log P(top-left = x)
        return (math.lgamma(r1 + 1) - math.lgamma(x + 1) - math.lgamma(r1 - x + 1)
                + math.lgamma(n - r1 + 1) - math.lgamma(c1 - x + 1) - math.lgamma(n - r1 - c1 + x + 1)
                - math.lgamma(n + 1) + math.lgamma(c1 + 1) + math.lgamma(n - c1 + 1))

    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    obs = lp(a)
    return min(1.0, sum(math.exp(lp(x)) for x in range(lo, hi + 1) if lp(x) <= obs + 1e-7))


def load(phase: str | None):
    data = defaultdict(list)  # (phase, scenario, model, cell) -> rows
    for d in sorted((REPO / "runs").iterdir()):
        if not d.is_dir() or d.name == "mock" or not (d / "scores.jsonl").exists():
            continue
        m = TAG.match(d.name)
        if not m or (phase and m["phase"] != phase):
            continue
        cell = CELLS.get((m["cond"], m["red"]), f"{m['cond']}_r{m['red']}")
        rows = [json.loads(l) for l in (d / "scores.jsonl").read_text(encoding="utf-8").splitlines() if l]
        data[(m["phase"], m["scenario"], m["model"], cell)].extend(rows)
    return data


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--phase", default=None)
    p.add_argument("--metric", default="whole_in_one_user_msg")
    p.add_argument("--md", default=None, help="also write the tables as markdown here")
    a = p.parse_args(argv)
    data = load(a.phase)
    out = []
    groups = sorted({k[:3] for k in data})
    for g in groups:
        out.append(f"\n### {g[0]} / {g[1]} / {g[2]}  (primary: {a.metric})\n")
        out.append("| cell | n | " + " | ".join(METRICS) + " | refusals/ep | disclosures/ep | cost US$ |")
        out.append("|---|---|" + "---|" * (len(METRICS) + 3))
        cells = sorted(c for (ph, sc, mo, c) in data if (ph, sc, mo) == g)
        for c in cells:
            rows = data[(*g, c)]
            n = len(rows)
            parts = []
            for met in METRICS:
                k = sum(bool(r.get(met)) for r in rows)
                lo, hi = wilson(k, n)
                parts.append(f"{k}/{n} ({k / n:.0%}; {lo:.0%}-{hi:.0%})")
            ref = sum(r.get("worker_refusals", 0) for r in rows) / n
            dis = sum(r.get("worker_disclosures", 0) for r in rows) / n
            cost = sum(r.get("cost_usd", 0) for r in rows)
            out.append(f"| {c} | {n} | " + " | ".join(parts) + f" | {ref:.2f} | {dis:.2f} | {cost:.4f} |")
        out.append("")
        for x, y, h in TESTS:
            if (*g, x) in data and (*g, y) in data:
                rx, ry = data[(*g, x)], data[(*g, y)]
                kx, ky = sum(bool(r.get(a.metric)) for r in rx), sum(bool(r.get(a.metric)) for r in ry)
                pv = fisher_two_sided(kx, len(rx) - kx, ky, len(ry) - ky)
                out.append(f"- {h} ({x} vs {y}): {kx}/{len(rx)} vs {ky}/{len(ry)}, Fisher two-sided p = {pv:.4f}")
        if (*g, "C") in data:  # H2b-ii descriptive
            rc = data[(*g, "C")]
            refep = [r for r in rc if r.get("worker_refusals", 0) > 0]
            reas = [r for r in refep if r.get("reassigned")]
            whole = [r for r in reas if r.get(a.metric)]
            out.append(f"- H2b-ii (cell C): {len(refep)} episodes with >=1 refusal; {len(reas)} reassigned; "
                       f"{len(whole)} of those ended with the whole ({a.metric})")
    text = "\n".join(out) if out else "no tagged real runs found under runs/"
    print(text)
    if a.md:
        fm = (f"---\nname: {Path(a.md).stem.replace('_', '-')}\ndescription: Generated by analyze.py "
              f"(phase={a.phase or 'all'}, metric={a.metric}); do not edit by hand.\nvisibility: private\n"
              f"tier: 1\ntype: report\n---\n")
        Path(a.md).write_text(fm + text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
