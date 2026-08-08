"""Verifies reset_covers_all_state: true (design.yaml) automatically instead
of leaving it an asserted claim. Silent bugs (forge Addition 2) have no
sim_confirm backstop - their entire evidentiary basis is the formal
counterexample - so a silent bug from a state element the reset doesn't
reach would be a FAKE finding (Correction 4's reachability argument, applied
specifically to the silent-bug pool). This check is what makes
"reset_covers_all_state: true" a verified fact instead of an assumption.

Method: within each `always @(posedge clk)`-style block, find every signal
assigned anywhere in the block (the state elements that block drives), and
every signal assigned specifically inside its `if (!reset)`/`if (reset)`
branch. A signal driven by the block but never assigned in the reset branch
fails the check. This does not prove full X-elimination (that would need
4-state simulation, as done manually for picorv32 - see FINDINGS.md) but it
catches the common case directly from source structure.
"""

from __future__ import annotations

import pyslang

from rtlverdict.forge.parser import walk

SyntaxKind = pyslang.syntax.SyntaxKind


def _collect_assigned_names(node) -> set[str]:
    names = set()
    for n in walk(node):
        if not isinstance(n, pyslang.syntax.SyntaxNode):
            continue
        if n.kind not in (
            SyntaxKind.NonblockingAssignmentExpression,
            SyntaxKind.AssignmentExpression,
        ):
            continue
        lhs = n.left
        # Strip bit-select/range-select down to the base identifier so
        # `q[3:0] <= x` and `q <= x` both count as covering `q`.
        while type(lhs).__name__ in (
            "ElementSelectExpressionSyntax",
            "RangeSelectExpressionSyntax",
        ):
            lhs = lhs.left
        if type(lhs).__name__ == "IdentifierNameSyntax":
            names.add(str(lhs.identifier).strip())
    return names


def check_reset_covers_all_state(source: str) -> tuple[bool, list[str]]:
    """Returns (ok, uncovered_signal_names). ok is True iff every signal
    assigned anywhere in a clocked always block is also assigned inside that
    block's top-level reset conditional.
    """
    tree = pyslang.syntax.SyntaxTree.fromText(source, "x.v")
    uncovered: set[str] = set()

    for node in walk(tree.root):
        if type(node).__name__ != "ProceduralBlockSyntax":
            continue
        kw = str(node.keyword).strip()
        if kw != "always":
            continue
        stmt = node.statement
        has_clock_edge = False
        for n in walk(stmt):
            if type(n).__name__ == "SignalEventExpressionSyntax":
                has_clock_edge = True
                break
        if not has_clock_edge:
            continue  # combinational always block, not state-holding

        all_assigned = _collect_assigned_names(stmt)

        # Find the top-level conditional statement (the reset check is
        # expected to be the first `if` inside the block per this project's
        # own convention - see designs/CONTRACT.md and every Tier A design).
        reset_branch_assigned: set[str] = set()
        for n in walk(stmt):
            if type(n).__name__ == "ConditionalStatementSyntax":
                # first (then-)clause only - the reset branch
                clause = n.statement
                reset_branch_assigned = _collect_assigned_names(clause)
                break

        uncovered |= all_assigned - reset_branch_assigned

    return (len(uncovered) == 0, sorted(uncovered))


if __name__ == "__main__":
    import sys

    path = sys.argv[1]
    source = open(path).read()
    ok, uncovered = check_reset_covers_all_state(source)
    print(f"{path}: reset_covers_all_state={ok}")
    if uncovered:
        print(f"  uncovered signals: {uncovered}")
