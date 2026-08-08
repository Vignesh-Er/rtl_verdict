"""TIMING mutation operators: blocking<->non-blocking, posedge<->negedge.

Async-reset-removed-from-sensitivity-list is not implemented yet - it
requires removing an entire `or negedge rst_n` clause (a deletion spanning
a separator token, not a same-width token replacement like everything else
here). Tracked as a follow-up, not silently skipped.
"""

from __future__ import annotations

import pyslang

from rtlverdict.forge.candidate import MutationCandidate
from rtlverdict.forge.parser import line_of, walk

SyntaxKind = pyslang.syntax.SyntaxKind
TokenKind = pyslang.parsing.TokenKind


def blocking_nonblocking_swap(tree, source: str) -> list[MutationCandidate]:
    candidates = []
    for node in walk(tree.root):
        if not isinstance(node, pyslang.syntax.SyntaxNode):
            continue
        if node.kind == SyntaxKind.NonblockingAssignmentExpression:
            replacement = "="
        elif node.kind == SyntaxKind.AssignmentExpression:
            replacement = "<="
        else:
            continue
        tok = node.operatorToken
        start = tok.range.start.offset
        end = tok.range.end.offset
        candidates.append(
            MutationCandidate(
                start_offset=start,
                end_offset=end,
                original_text=source[start:end],
                replacement_text=replacement,
                bug_class="TIMING",
                operator="timing.blocking_nonblocking_swap",
                description=f"{node.kind.name}: {source[start:end]!r} -> {replacement!r}",
                line=line_of(source, start),
            )
        )
    return candidates


def edge_swap(tree, source: str) -> list[MutationCandidate]:
    candidates = []
    for node in walk(tree.root):
        if type(node).__name__ != "SignalEventExpressionSyntax":
            continue
        tok = node.edge
        if tok is None:
            continue
        if tok.kind == TokenKind.PosEdgeKeyword:
            replacement = "negedge"
        elif tok.kind == TokenKind.NegEdgeKeyword:
            replacement = "posedge"
        else:
            continue
        start = tok.range.start.offset
        end = tok.range.end.offset
        candidates.append(
            MutationCandidate(
                start_offset=start,
                end_offset=end,
                original_text=source[start:end],
                replacement_text=replacement,
                bug_class="TIMING",
                operator="timing.edge_swap",
                description=f"{source[start:end]!r} -> {replacement!r}",
                line=line_of(source, start),
            )
        )
    return candidates
