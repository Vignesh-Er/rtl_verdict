"""FSM mutation operator: next-state redirect. Finds an assignment whose
RHS is a state-encoding constant (a localparam, e.g. `state <= RUN;`) and
redirects it to a different constant from the same declaration group.

Deliberately probes a different containment path than LOGIC/TIMING: the
redirected identifier sits inside a `case` item's statement body, so its
enclosing-condition chain (the case's own selector expression, per
coi.py's _enclosing_conditions) is nested control dependency - exactly the
class of bug the COI slicer's fixed soundness gap (FINDINGS.md) was about.
"""

from __future__ import annotations

import pyslang

from rtlverdict.forge.candidate import MutationCandidate
from rtlverdict.forge.parser import line_of, walk

SyntaxKind = pyslang.syntax.SyntaxKind


def _collect_localparam_groups(tree) -> list[list[str]]:
    groups: list[list[str]] = []
    for node in walk(tree.root):
        if type(node).__name__ != "ParameterDeclarationSyntax":
            continue
        names = [
            str(d.name).strip()
            for d in node.declarators
            if type(d).__name__ == "DeclaratorSyntax"
        ]
        if len(names) >= 2:
            groups.append(names)
    return groups


def next_state_redirect(tree, source: str) -> list[MutationCandidate]:
    groups = _collect_localparam_groups(tree)
    name_to_group: dict[str, list[str]] = {}
    for g in groups:
        for n in g:
            name_to_group[n] = g

    candidates: list[MutationCandidate] = []
    for node in walk(tree.root):
        if not isinstance(node, pyslang.syntax.SyntaxNode):
            continue
        if node.kind not in (
            SyntaxKind.NonblockingAssignmentExpression,
            SyntaxKind.AssignmentExpression,
        ):
            continue
        rhs = node.right
        if type(rhs).__name__ != "IdentifierNameSyntax":
            continue
        name = str(rhs.identifier).strip()
        group = name_to_group.get(name)
        if group is None:
            continue
        replacement = next((g for g in group if g != name), None)
        if replacement is None:
            continue

        start = rhs.sourceRange.start.offset
        end = rhs.sourceRange.end.offset
        candidates.append(
            MutationCandidate(
                start_offset=start,
                end_offset=end,
                original_text=source[start:end],
                replacement_text=replacement,
                bug_class="FSM",
                operator="fsm.next_state_redirect",
                description=f"next-state {name!r} -> {replacement!r}",
                line=line_of(source, start),
            )
        )
    return candidates
