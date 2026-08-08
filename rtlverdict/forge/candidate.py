"""MutationCandidate: the common output shape every operator produces.
A candidate names a byte range in the ORIGINAL source to replace - never a
re-serialized tree - so applying it is a pure string splice (see mutate.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MutationCandidate:
    start_offset: int
    end_offset: int
    original_text: str
    replacement_text: str
    bug_class: str  # "LOGIC" | "TIMING" | "SPEC" | "INTERFACE" | "FSM" | "SIGNAL"
    operator: str  # e.g. "logic.operator_swap"
    description: str
    line: int  # 1-indexed source line of start_offset - becomes root_cause_line
