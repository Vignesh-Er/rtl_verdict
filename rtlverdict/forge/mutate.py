"""Applies exactly one MutationCandidate to source text via byte-offset
splice on the ORIGINAL source (never tree re-serialization) - see parser.py
and PLAN.md Section 0 for why this guarantees fidelity outside the mutated
span by construction.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

import pyslang

from rtlverdict.forge.candidate import MutationCandidate


def apply_candidate(source: str, candidate: MutationCandidate) -> str:
    return (
        source[: candidate.start_offset]
        + candidate.replacement_text
        + source[candidate.end_offset :]
    )


@dataclass
class FidelityResult:
    ok: bool
    reason: str


def check_fidelity(
    golden_source: str, mutant_source: str, mutant_path: str, expected_line: int
) -> FidelityResult:
    """Addition 4 from the brief: every generated mutant must (a) re-parse
    with 0 diagnostics, (b) differ from golden by EXACTLY ONE diff hunk,
    (c) that hunk's line == root_cause_line. Catches splice-offset bugs
    immediately instead of as a mysterious downstream localization failure.
    """
    tree = pyslang.syntax.SyntaxTree.fromText(mutant_source, mutant_path)
    diags = list(tree.diagnostics)
    if diags:
        engine = pyslang.DiagnosticEngine(tree.sourceManager)
        client = pyslang.TextDiagnosticClient()
        engine.addClient(client)
        for d in diags:
            engine.issue(d)
        return FidelityResult(False, f"{len(diags)} parse diagnostics: {client.report}")

    golden_lines = golden_source.splitlines(keepends=True)
    mutant_lines = mutant_source.splitlines(keepends=True)
    diff = list(difflib.unified_diff(golden_lines, mutant_lines, n=0))
    hunks = [l for l in diff if l.startswith("@@")]
    if len(hunks) != 1:
        return FidelityResult(False, f"expected exactly 1 diff hunk, got {len(hunks)}: {hunks}")

    # unified_diff hunk header: "@@ -start,count +start,count @@"
    import re

    m = re.match(r"@@ -(\d+)", hunks[0])
    if not m:
        return FidelityResult(False, f"could not parse hunk header: {hunks[0]!r}")
    hunk_line = int(m.group(1))
    if hunk_line != expected_line:
        return FidelityResult(
            False, f"hunk at line {hunk_line}, expected root_cause_line {expected_line}"
        )

    return FidelityResult(True, "ok")
