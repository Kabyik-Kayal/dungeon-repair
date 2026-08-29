"""Baseline 3: enumerate the edit vocabulary, ship the first repair that verifies.

This is the baseline that matters. It is deterministic, free, sub-second, and
it clears the solvability gate on every case -- which is exactly why "the
level is now winnable" is the wrong thing to claim credit for. Its enumeration
order is least-invasive-first (unlock, move key, add key, add corridor), which
is the strongest ordering a reasonable engineer would reach for.
"""

from __future__ import annotations

import time

from ..candidates import first_valid
from ..corrupt import Case
from ..metrics import Attempt, score

METHOD = "first_valid"


def run(case: Case, **_: object) -> Attempt:
    started = time.perf_counter()
    edit, considered, _ = first_valid(case.broken)
    return score(
        case,
        METHOD,
        edit,
        time.perf_counter() - started,
        usage={"cost_usd": 0.0, "calls": 0},
        rationale="first edit in least-invasive-first order that the solver verifies",
        extra={"edits_considered": considered},
    )
