"""Thin pyslang wrapper. Every mutation operator works off of a
(SyntaxTree, source_text) pair from `parse_file` and locates candidates by
walking the tree, never by scanning raw text - Section 0 of PLAN.md verified
that token byte-offsets from this walk let us splice the ORIGINAL source
directly, which is what guarantees byte-level fidelity outside the mutated
span (comments/whitespace untouched), not by trusting a reprinter.
"""

from __future__ import annotations

from pathlib import Path

import pyslang

Token = pyslang.parsing.Token
SyntaxNode = pyslang.syntax.SyntaxNode


def parse_file(path: str | Path) -> tuple[pyslang.syntax.SyntaxTree, str]:
    path = Path(path)
    source = path.read_text()
    tree = pyslang.syntax.SyntaxTree.fromText(source, str(path))
    return tree, source


def walk(node):
    """Yield every node and token in the subtree rooted at `node`, depth-first."""
    yield node
    if isinstance(node, Token):
        return
    for i in range(len(node)):
        child = node[i]
        if child is not None:
            yield from walk(child)


def line_of(source: str, offset: int) -> int:
    """1-indexed source line containing byte offset `offset`."""
    return source.count("\n", 0, offset) + 1
