"""LLM clients: a capped OpenRouter client and a scripted mock for offline tests.

Guards enforced in code (not by convention):
  * pre-sprint lock -- real calls before SPRINT_START_UTC raise unless allow_pre_sprint=True
    (anything run before then is prior work and must be disclosed; see CLAUDE.md).
  * spend stop -- every real call is appended to a JSONL ledger with its cost; a call is refused
    once the ledger total reaches budget_stop_usd (default US$8, the repo's stop rule). The
    provider-side US$10 key limit is the hard backstop.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

API = "https://openrouter.ai/api/v1"
# Fri 6 Nov 2026 11:00 PST = 19:00 UTC = Sat 7 Nov 08:00 NZDT (sprint talks open).
SPRINT_START_UTC = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO / "runs" / "ledger.jsonl"
# Per-arm spend caps (USD), enforced on the shared ledger. PROPOSED -- confirm at the design review
# (docs/q2-design.md section 8). Sum = the US$8 global stop; the key's provider limit (US$10) is the backstop.
ARM_STOPS = {"q2": 3.00, "q2-reasoning": 2.50, "q3": 2.50}


class BudgetExceeded(RuntimeError):
    pass


class PreSprintLock(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    gen_id: str | None = None
    latency_s: float = 0.0
    finish_reason: str | None = None


def load_env(path: Path = REPO / ".env") -> None:
    """Minimal .env loader (no python-dotenv dependency). Never prints values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ledger_total(path: Path = DEFAULT_LEDGER, arm: str | None = None) -> float:
    """Sum of logged cost; restricted to one arm if given."""
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if arm is None or row.get("arm") == arm:
                total += float(row.get("cost_usd") or 0.0)
    return total


class OpenRouterClient:
    def __init__(self, *, api_key: str | None = None, ledger: Path = DEFAULT_LEDGER,
                 budget_stop_usd: float = 8.0, allow_pre_sprint: bool = False,
                 run_tag: str = "", arm: str = "q2", arm_stops: dict | None = None, timeout: float = 90.0, max_retries: int = 4):
        load_env()
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set (expected in .env)")
        self.ledger = Path(ledger)
        self.budget_stop_usd = budget_stop_usd
        self.allow_pre_sprint = allow_pre_sprint
        self.run_tag = run_tag
        self.arm_stops = ARM_STOPS if arm_stops is None else arm_stops
        if arm not in self.arm_stops:
            raise ValueError(f"unknown arm {arm!r}; budgeted arms: {sorted(self.arm_stops)}")
        self.arm = arm
        self.timeout = timeout
        self.max_retries = max_retries
        self._prices: dict[str, tuple[float, float]] | None = None

    # -- pricing fallback (only used if the response carries no usage.cost) --
    def _price(self, model: str) -> tuple[float, float]:
        if self._prices is None:
            data = requests.get(f"{API}/models", timeout=30).json()["data"]
            self._prices = {m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
                            for m in data}
        return self._prices.get(model, (0.0, 0.0))

    def preflight(self) -> None:
        """Raise if a real call would be refused now (pre-sprint lock or spend stop)."""
        if datetime.now(timezone.utc) < SPRINT_START_UTC and not self.allow_pre_sprint:
            raise PreSprintLock(
                f"Real API call refused before {SPRINT_START_UTC.isoformat()} (pre-sprint = setup only). "
                "Pass allow_pre_sprint=True only for a disclosed connectivity check.")
        spent = ledger_total(self.ledger)
        if spent >= self.budget_stop_usd:
            raise BudgetExceeded(f"Ledger total US${spent:.4f} >= stop US${self.budget_stop_usd:.2f}; "
                                 "finish the arm and re-plan.")
        arm_spent, arm_stop = ledger_total(self.ledger, self.arm), self.arm_stops[self.arm]
        if arm_spent >= arm_stop:
            raise BudgetExceeded(f"Arm {self.arm!r} spent US${arm_spent:.4f} >= its cap US${arm_stop:.2f}; "
                                 "finish the arm and re-plan.")

    def chat(self, model: str, messages: list[dict], *, temperature: float = 0.7,
             max_tokens: int = 400, seed: int | None = None) -> Reply:
        self.preflight()
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, "usage": {"include": True}}
        if seed is not None:
            body["seed"] = seed
        headers = {"Authorization": f"Bearer {self.api_key}", "X-Title": "apart-swarm"}
        last_err = None
        for attempt in range(self.max_retries):
            t0 = time.time()
            try:
                r = requests.post(f"{API}/chat/completions", json=body, headers=headers,
                                  timeout=self.timeout)
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"API error: {d['error']}")
            choice = d["choices"][0]
            usage = d.get("usage") or {}
            pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            cost = usage.get("cost")
            if cost is None:
                pin, pout = self._price(model)
                cost = pt * pin + ct * pout
            reply = Reply(text=choice["message"].get("content") or "", model=d.get("model", model),
                          prompt_tokens=pt, completion_tokens=ct, cost_usd=float(cost),
                          gen_id=d.get("id"), latency_s=round(time.time() - t0, 3),
                          finish_reason=choice.get("finish_reason"))
            self._record(reply)
            return reply
        raise RuntimeError(f"Gave up after {self.max_retries} attempts: {last_err}")

    def _record(self, reply: Reply) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tag": self.run_tag, "arm": self.arm,
               "model": reply.model, "prompt_tokens": reply.prompt_tokens,
               "completion_tokens": reply.completion_tokens, "cost_usd": reply.cost_usd,
               "gen_id": reply.gen_id}
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


@dataclass
class MockClient:
    """Offline client: `policy(agent_model, messages) -> str`. Records every call, costs nothing."""
    policy: Callable[[str, list[dict]], str]
    calls: list = field(default_factory=list)

    def chat(self, model: str, messages: list[dict], **kw) -> Reply:
        text = self.policy(model, messages)
        self.calls.append({"model": model, "messages": messages, "text": text})
        return Reply(text=text, model=model)
