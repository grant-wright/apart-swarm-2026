"""The shared agent loop (Q2 and Q3).

Synchronous rounds over a graph. In round r every agent with a non-empty inbox (or every agent, if
only_if_inbox=False) reads what its neighbours sent in round r-1 and writes one message.

Routing of an agent's output:
  * lines beginning `@name:` open an addressed block that runs until the next `@name:` line; each block
    goes only to `name`, and only if `name` is a neighbour or a sink (e.g. `user`). Text before the
    first block is private (not delivered). Addresses to non-neighbours are logged as `undeliverable`.
  * output with no `@` blocks is broadcast to all agent neighbours (never to sinks).
Sinks are pseudo-nodes that collect output (Q2's `user` = the team's final answer).

Every call and every delivery is written to a JSONL log, so every reported number traces to a line.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ADDR = re.compile(r"^\s*@([A-Za-z0-9_\-]+)\s*:\s?(.*)$")


@dataclass
class Agent:
    name: str
    system: str
    model: str
    history: list[dict] = field(default_factory=list)  # this agent's own user/assistant turns


@dataclass
class Episode:
    deliveries: list[dict] = field(default_factory=list)   # {round, src, dst, text}
    outputs: list[dict] = field(default_factory=list)      # {round, agent, text}
    sink: dict[str, list[str]] = field(default_factory=dict)
    rounds_run: int = 0
    stopped_by: str = "max_rounds"
    cost_usd: float = 0.0
    n_calls: int = 0


def route(text: str, src: str, neighbours: set[str], sinks: set[str]):
    """Return (deliveries [(dst, text)], undeliverable [(dst, text)])."""
    blocks: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = ADDR.match(line)
        if m:
            blocks.append((m.group(1), [m.group(2)]))
        elif blocks:
            blocks[-1][1].append(line)
    if not blocks:
        return [(d, text.strip()) for d in sorted(neighbours)], []
    ok, bad = [], []
    for dst, lines in blocks:
        body = "\n".join(lines).strip()
        (ok if (dst in neighbours or dst in sinks) and dst != src else bad).append((dst, body))
    return ok, bad


def _render_inbox(r: int, inbox: list[tuple[str, str]]) -> str:
    if not inbox:
        return f"[Round {r}] No new messages."
    parts = [f"[Round {r}] Messages received:"]
    parts += [f"--- from {src} ---\n{txt}" for src, txt in inbox]
    return "\n".join(parts)


class JsonlLog:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **data) -> None:
        if not self.path:
            return
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_episode(agents: dict[str, Agent], graph: dict[str, set[str]], client, *,
                kickoff: dict[str, str], rounds: int, sinks: set[str] = frozenset({"user"}),
                only_if_inbox: bool = True, stop_when: Callable[[Episode], bool] | None = None,
                max_history_turns: int | None = None, temperature: float = 0.7,
                max_tokens: int = 400, log_path: Path | None = None, meta: dict | None = None
                ) -> Episode:
    """kickoff: {agent_name: first-round message from the outside world (e.g. the user's request)}."""
    log = JsonlLog(log_path)
    log.write("episode_start", meta=meta or {}, rounds=rounds, sinks=sorted(sinks),
              graph={k: sorted(v) for k, v in graph.items()},
              agents={a.name: {"model": a.model, "system": a.system} for a in agents.values()})
    ep = Episode(sink={s: [] for s in sinks})
    inbox: dict[str, list[tuple[str, str]]] = {n: [] for n in agents}
    for name, msg in kickoff.items():
        inbox[name].append(("user" if "user" in sinks else "environment", msg))

    for r in range(rounds):
        active = [n for n in agents if inbox[n] or not only_if_inbox]
        if not active:
            ep.stopped_by = "quiescent"
            break
        next_inbox: dict[str, list[tuple[str, str]]] = {n: [] for n in agents}
        for name in active:                       # synchronous: everyone reads round r-1 output
            a = agents[name]
            a.history.append({"role": "user", "content": _render_inbox(r, inbox[name])})
            hist = a.history if not max_history_turns else a.history[-(2 * max_history_turns - 1):]
            reply = client.chat(a.model, [{"role": "system", "content": a.system}] + hist,
                                temperature=temperature, max_tokens=max_tokens)
            a.history.append({"role": "assistant", "content": reply.text})
            ep.n_calls += 1
            ep.cost_usd += reply.cost_usd
            ep.outputs.append({"round": r, "agent": name, "text": reply.text})
            log.write("call", round=r, agent=name, model=reply.model, inbox=inbox[name],
                      output=reply.text, prompt_tokens=reply.prompt_tokens,
                      completion_tokens=reply.completion_tokens, cost_usd=reply.cost_usd,
                      gen_id=reply.gen_id, finish_reason=reply.finish_reason)
            ok, bad = route(reply.text, name, graph.get(name, set()), set(sinks))
            for dst, body in ok:
                d = {"round": r, "src": name, "dst": dst, "text": body}
                ep.deliveries.append(d)
                log.write("deliver", **d)
                if dst in sinks:
                    ep.sink[dst].append(body)
                else:
                    next_inbox[dst].append((name, body))
            for dst, body in bad:
                log.write("undeliverable", round=r, src=name, dst=dst, text=body)
        inbox = next_inbox
        ep.rounds_run = r + 1
        if stop_when and stop_when(ep):
            ep.stopped_by = "stop_when"
            break
    log.write("episode_end", rounds_run=ep.rounds_run, stopped_by=ep.stopped_by,
              n_calls=ep.n_calls, cost_usd=ep.cost_usd, sink=ep.sink)
    return ep
