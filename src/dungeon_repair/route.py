"""Deterministic routing: answer the cases the candidate set already decides.

Stage 16 measured where the remaining headroom actually is, and found that it
is not spread evenly. Two of the three corruption kinds carry almost no signal
in the graph -- three independent rankers all scored at or below the agent on
severed corridors. The third is nearly free: on a spurious lock the solver
usually certifies exactly one ``unlock``, so once the kind is known the answer
is forced and there is nothing left to judge.

This module spends no model budget on those. It reads the composition of the
verified candidate set -- which is deterministic, cached, and already computed
-- and returns an answer only when the set leaves no choice. Everything else
falls through to the agent unchanged.

The point is not that rules beat the model. It is that a case with one legal
answer is not a judgment problem, and paying a model to make it is both slower
and, measurably, less reliable.
"""

from __future__ import annotations

from collections import Counter

from .candidates import CandidateSet
from .edits import ADD_DOOR, ADD_KEY, Edit, MOVE_KEY, UNLOCK

#: Why a case was decided without the model. Recorded in the trace and the
#: result row so a forced answer is never mistaken for a reasoned one.
FORCED_UNLOCK = "forced:sole-unlock"
DOORS_ONLY = "narrowed:doors-only"


def composition(candidates: CandidateSet) -> Counter:
    return Counter(edit.kind for edit in candidates.verified)


def touches_keys(candidates: CandidateSet) -> bool:
    """Does any verified repair move or add a small key?"""
    counts = composition(candidates)
    return bool(counts[MOVE_KEY] or counts[ADD_KEY])


def forced(candidates: CandidateSet) -> tuple[Edit | None, str]:
    """The repair, if the verified set admits exactly one defensible answer.

    Returns ``(edit, reason)``, or ``(None, "")`` when the case needs judgment.

    The single rule that fires: **the key economy is repairable and yet the
    solver certifies exactly one ``unlock``.** A dropped corridor cannot
    produce that shape -- severing a passage leaves no key edit valid at all --
    so the level is short exactly one open door, and there is only one door it
    can be. Measured on the 77-case set this fires 23 times and is right 21,
    and it never overturns an answer the agent had right.
    """
    if not touches_keys(candidates):
        return None, ""
    unlocks = [e for e in candidates.verified if e.kind == UNLOCK]
    if len(unlocks) == 1:
        return unlocks[0], FORCED_UNLOCK
    return None, ""


def narrowed(candidates: CandidateSet) -> tuple[list[Edit], str]:
    """Options worth showing the agent once the candidate set has been read.

    When no key edit verifies, no key was displaced and no lock was invented:
    the only corruption that leaves that shape is a dropped corridor. Offering
    the agent an ``unlock`` there is offering it a wrong answer, so the option
    list is narrowed to passages.
    """
    if touches_keys(candidates):
        return candidates.verified, ""
    doors = [e for e in candidates.verified if e.kind == ADD_DOOR]
    if doors and len(doors) < len(candidates.verified):
        return doors, DOORS_ONLY
    return candidates.verified, DOORS_ONLY if doors else ""
