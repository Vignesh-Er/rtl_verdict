"""ARM A / ARM B configuration: system prompts and tool availability. Per
the brief - ARM A gets buggy RTL + raw failing test log only (no tools
beyond submitting a patch); ARM B gets the same plus the full witness
toolbelt. Two arms is enough for the headline chart (explicit instruction)
- no third arm, no tool subsetting within B.
"""

from __future__ import annotations

from dataclasses import dataclass

from rtlverdict.agent.tools import SUBMIT_PATCH_SCHEMA, TOOL_SCHEMAS

_COMMON_PREAMBLE = """You are debugging a Verilog-2005 RTL module that fails its own testbench.
You are given the buggy source and the testbench's failure output. Find the bug and submit a fix.

Submit your fix by calling submit_patch with the COMPLETE corrected source for the module - the
whole file with your fix applied, not a diff.

Rules:
- Keep the same module name and the same port list (names, directions, widths) - the fix must be
  a drop-in replacement, not a redesign.
- Verilog-2005 synthesizable subset only.
- You have a limited number of turns. When you believe you have the fix, submit it - do not keep
  exploring past the point of diminishing returns."""

_ARM_A_SUFFIX = """

You have no tools available except submit_patch. Work from the buggy source and the failing-test
output alone."""

_ARM_B_SUFFIX = """

You also have witness tools available: run_test (find the first point where the buggy design's
behavior diverges from a golden reference), wave_query (inspect the buggy design's own waveform),
diff_traces (re-run the divergence check with a different signal scope), cone_of_influence (every
source line that can affect a given signal), and suspect_rank (cone_of_influence lines ranked by
how recently they toggled before the divergence). Use them to localize the bug before proposing a
fix, rather than guessing from the log alone."""


@dataclass(frozen=True)
class Arm:
    name: str
    system_prompt: str
    tools: list[dict]


def arm_a() -> Arm:
    return Arm(name="A", system_prompt=_COMMON_PREAMBLE + _ARM_A_SUFFIX, tools=[SUBMIT_PATCH_SCHEMA])


def arm_b() -> Arm:
    return Arm(name="B", system_prompt=_COMMON_PREAMBLE + _ARM_B_SUFFIX, tools=[SUBMIT_PATCH_SCHEMA, *TOOL_SCHEMAS])


ARMS = {"A": arm_a, "B": arm_b}
