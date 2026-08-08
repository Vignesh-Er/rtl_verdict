"""cone_of_influence(design, signal) - static backward slice via the pyslang
AST, not a Yosys JSON netlist round-trip (PLAN.md Section 6 deviation,
approved: Yosys `src` attributes degrade through proc/opt/techmap and lose
exactly the source-line fidelity localization accuracy is measured against;
an AST slice never round-trips through synthesis at all).

MUST BE A SOUND OVER-APPROXIMATION: never omit a real dependency. Extra
lines are acceptable; a missing root cause is fatal (Addition 3 - the
self-validating containment check - exists specifically to catch this).

Known imprecision sources (see docs/coi_soundness.md for the full list):
hierarchical instance port connections are not yet followed across module
boundaries (this project's Tier A designs are single-module, so this has
not yet been exercised); generate blocks and parameters are not specially
handled; memories/arrays with dynamic indices are treated at whole-array
granularity, not per-element (conservative, so still sound, just coarser
than necessary).
"""

from __future__ import annotations

import pyslang

from rtlverdict.forge.parser import line_of, walk

SyntaxKind = pyslang.syntax.SyntaxKind

_ASSIGN_KINDS = (SyntaxKind.NonblockingAssignmentExpression, SyntaxKind.AssignmentExpression)


def _base_name(ident_node) -> str:
    return str(ident_node.identifier).strip()


def _collect_identifiers(node) -> set[str]:
    names = set()
    for n in walk(node):
        if not isinstance(n, pyslang.syntax.SyntaxNode):
            continue
        if type(n).__name__ == "IdentifierNameSyntax":
            names.add(_base_name(n))
    return names


def _strip_selects(lhs):
    while type(lhs).__name__ in ("ElementSelectExpressionSyntax", "RangeSelectExpressionSyntax"):
        lhs = lhs.left
    return lhs


def _enclosing_conditions(node, stop_at, source: str) -> tuple[set[str], set[int]]:
    """Walk up from `node` collecting every enclosing if/case statement's
    condition, up to (not including) `stop_at` (the containing always
    block) - these are control dependencies: whether an assignment executes
    at all depends on them.

    Returns (read_signals, own_lines). Both matter and are easy to conflate
    (an earlier version of this function only returned read_signals, which
    silently dropped the condition's OWN line from the slice whenever that
    line assigns nothing itself - e.g. `if (bit_index == 3'd7)` gating
    `bit_index <= bit_index + 1` in the else branch: the condition line is
    part of bit_index's cone even though it never appears on an assignment's
    LHS. Caught by the containment gate at 90% before this fix, not by
    inspection - exactly what Addition 3 is for.
    """
    reads: set[str] = set()
    own_lines: set[int] = set()
    cur = node.parent
    while cur is not None and cur is not stop_at:
        kind_name = type(cur).__name__
        if kind_name == "ConditionalStatementSyntax":
            reads |= _collect_identifiers(cur.predicate)
            own_lines.add(line_of(source, cur.predicate.getFirstToken().range.start.offset))
        elif kind_name == "CaseStatementSyntax":
            reads |= _collect_identifiers(cur.expr)
            own_lines.add(line_of(source, cur.expr.getFirstToken().range.start.offset))
        cur = cur.parent
    return reads, own_lines


def build_dependency_index(source: str) -> dict[str, list[tuple[set[int], set[str]]]]:
    """Maps each written signal name to a list of (own_lines, read_signals)
    - one entry per assignment site (a signal can be written from multiple
    places, e.g. different branches of a case statement). own_lines is the
    assignment's line PLUS every enclosing condition's line (control
    dependencies are part of the slice, not just their read-signals - see
    _enclosing_conditions).
    """
    tree = pyslang.syntax.SyntaxTree.fromText(source, "x.v")
    index: dict[str, list[tuple[set[int], set[str]]]] = {}

    for node in walk(tree.root):
        if not isinstance(node, pyslang.syntax.SyntaxNode):
            continue
        if node.kind not in _ASSIGN_KINDS:
            continue

        lhs = _strip_selects(node.left)
        if type(lhs).__name__ != "IdentifierNameSyntax":
            continue
        target = _base_name(lhs)

        # enclosing always block (or generate/initial block) - the boundary
        # for control-dependency collection, so an outer module's unrelated
        # conditionals never leak in.
        stop_at = node.parent
        while stop_at is not None and type(stop_at).__name__ != "ProceduralBlockSyntax":
            stop_at = stop_at.parent

        reads = _collect_identifiers(node.right)
        cond_reads, cond_lines = _enclosing_conditions(node, stop_at, source)
        reads |= cond_reads
        reads.discard(target)

        own_line = line_of(source, node.getFirstToken().range.start.offset)
        own_lines = {own_line} | cond_lines

        index.setdefault(target, []).append((own_lines, reads))

    return index


def cone_of_influence(source: str, signal: str, file_name: str = "x.v") -> list[dict]:
    """Returns a sorted list of {"file", "line"} - every source line that
    can (transitively) affect `signal`, per the dependency index above.
    """
    index = build_dependency_index(source)
    seen_lines: set[int] = set()
    visited_signals: set[str] = set()
    frontier = [signal]

    while frontier:
        sig = frontier.pop()
        if sig in visited_signals:
            continue
        visited_signals.add(sig)
        for own_lines, reads in index.get(sig, []):
            seen_lines |= own_lines
            for r in reads:
                if r not in visited_signals:
                    frontier.append(r)

    return [{"file": file_name, "line": l} for l in sorted(seen_lines)]
