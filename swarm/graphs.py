"""Undirected communication graphs as {node: set(neighbours)}. No networkx dependency."""
from __future__ import annotations

import random


def names(n: int, prefix: str = "a") -> list[str]:
    return [f"{prefix}{i:02d}" for i in range(n)]


def _empty(nodes):
    return {v: set() for v in nodes}


def _link(g, a, b):
    if a != b:
        g[a].add(b)
        g[b].add(a)


def chain(n: int) -> dict[str, set[str]]:
    v = names(n); g = _empty(v)
    for i in range(n - 1):
        _link(g, v[i], v[i + 1])
    return g


def ring(n: int) -> dict[str, set[str]]:
    g = chain(n); v = names(n)
    if n > 2:
        _link(g, v[0], v[-1])
    return g


def star(n: int) -> dict[str, set[str]]:
    """Node a00 is the hub."""
    v = names(n); g = _empty(v)
    for leaf in v[1:]:
        _link(g, v[0], leaf)
    return g


def complete(n: int) -> dict[str, set[str]]:
    v = names(n); g = _empty(v)
    for i in range(n):
        for j in range(i + 1, n):
            _link(g, v[i], v[j])
    return g


def small_world(n: int, k: int = 4, p: float = 0.2, seed: int = 0) -> dict[str, set[str]]:
    """Watts-Strogatz: ring lattice with k nearest neighbours (k even), each edge rewired w.p. p.
    Rewiring retries until the graph is connected (bounded attempts)."""
    if k % 2 or k >= n:
        raise ValueError("k must be even and < n")
    for attempt in range(100):
        rng = random.Random(seed * 1000 + attempt)
        v = names(n); g = _empty(v)
        for i in range(n):
            for j in range(1, k // 2 + 1):
                _link(g, v[i], v[(i + j) % n])
        for i in range(n):
            for j in range(1, k // 2 + 1):
                a, b = v[i], v[(i + j) % n]
                if rng.random() < p and b in g[a]:
                    choices = [c for c in v if c != a and c not in g[a]]
                    if choices:
                        c = rng.choice(choices)
                        g[a].discard(b); g[b].discard(a)
                        _link(g, a, c)
        if is_connected(g):
            return g
    raise RuntimeError("could not build a connected small-world graph")


def is_connected(g: dict[str, set[str]]) -> bool:
    if not g:
        return True
    start = next(iter(g)); seen = {start}; stack = [start]
    while stack:
        for nb in g[stack.pop()]:
            if nb not in seen:
                seen.add(nb); stack.append(nb)
    return len(seen) == len(g)


def degrees(g):
    return {v: len(nb) for v, nb in g.items()}


TOPOLOGIES = {"chain": chain, "ring": ring, "star": star, "complete": complete,
              "small_world": small_world}


def build(name: str, n: int, **kw) -> dict[str, set[str]]:
    return TOPOLOGIES[name](n, **kw)
