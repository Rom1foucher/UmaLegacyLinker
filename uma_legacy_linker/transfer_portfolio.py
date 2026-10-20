"""Bounded minimum set cover for a local collection, without extra dependencies.

The incumbent is always feasible. Exhausting the node budget affects the
cardinality proof, never the coverage constraints or mandatory veterans.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PortfolioSelection:
    selected: frozenset[int]
    optimal: bool
    nodes: int
    greedy_count: int


def minimum_portfolio(
    candidates: Iterable[int],
    requirements: Iterable[Iterable[int]],
    mandatory: Iterable[int] = (),
    *,
    priorities: dict[int, tuple] | None = None,
    node_budget: int = 50000,
) -> PortfolioSelection:
    pool = set(candidates)
    forced = set(mandatory)
    if not forced <= pool:
        raise ValueError("Mandatory veterans must belong to the candidate pool")
    constraints = {frozenset(set(values) & pool) for values in requirements}
    if frozenset() in constraints:
        raise ValueError("A portfolio requirement has no candidate")
    # Removing supersets preserves set-cover feasibility and greatly reduces
    # thousands of equivalent same-Ace performance requirements.
    minimal: list[frozenset[int]] = []
    for values in sorted(constraints, key=lambda v: (len(v), tuple(sorted(v)))):
        if not any(smaller <= values for smaller in minimal):
            minimal.append(values)
    for values in minimal:
        if len(values) == 1:
            forced.update(values)
    pending = [values for values in minimal if not values & forced]
    priorities = priorities or {}

    def rank(index: int, remaining: list[frozenset[int]]) -> tuple:
        return (sum(index in values for values in remaining),
                priorities.get(index, ()), -index)

    greedy = set(forced)
    remaining = list(pending)
    while remaining:
        index = max(set().union(*remaining), key=lambda i: rank(i, remaining))
        greedy.add(index)
        remaining = [values for values in remaining if index not in values]
    incumbent = set(greedy)
    nodes = 0
    exhausted = False
    memo: dict[tuple[frozenset[int], ...], int] = {}

    def visit(selection: set[int], todo: list[frozenset[int]]) -> None:
        nonlocal incumbent, nodes, exhausted
        if nodes >= max(1, node_budget):
            exhausted = True
            return
        nodes += 1
        if not todo:
            if len(selection) < len(incumbent):
                incumbent = set(selection)
            return
        if len(selection) >= len(incumbent):
            return
        state = tuple(todo)
        if memo.get(state, len(pool) + 1) <= len(selection):
            return
        memo[state] = len(selection)
        # Disjoint carrier sets need different veterans. This is an admissible
        # lower bound, unlike weighted coverage or average performance.
        disjoint: set[int] = set()
        lower_bound = 0
        for values in sorted(todo, key=len):
            if not values & disjoint:
                disjoint.update(values)
                lower_bound += 1
        if len(selection) + lower_bound >= len(incumbent):
            return
        choices = min(todo, key=lambda v: (len(v), tuple(sorted(v))))
        for index in sorted(choices, key=lambda i: rank(i, todo), reverse=True):
            visit(selection | {index}, [v for v in todo if index not in v])
            if exhausted:
                return

    visit(set(forced), pending)
    if not all(values & incumbent for values in constraints):
        raise AssertionError("Portfolio solver lost a requirement")
    return PortfolioSelection(frozenset(incumbent), not exhausted, nodes, len(greedy))
