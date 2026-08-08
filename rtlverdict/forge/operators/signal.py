"""SIGNAL mutation operator: substitute an in-scope signal read for another
in-scope signal of identical width. The brief calls this out as the hardest
class for LLM-based repair (a plausible-looking, type-correct wrong-name
bug), and it's a different graph shape for witness/coi.py than every other
operator implemented so far: the root cause is a READ site, not a WRITE, so
it probes a different path through the dependency graph than LOGIC/TIMING's
operator/assignment mutations or FSM's next-state writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pyslang

from rtlverdict.forge.candidate import MutationCandidate
from rtlverdict.forge.parser import line_of, walk

SyntaxKind = pyslang.syntax.SyntaxKind
_WIDTH_RE = re.compile(r"\[[^\]]*\]")


@dataclass
class _Decl:
    name: str
    width: str  # "" for 1-bit, "[N:0]" text otherwise


def _collect_declared_signals(tree, source: str) -> list[_Decl]:
    decls: list[_Decl] = []
    seen = set()
    for node in walk(tree.root):
        if not isinstance(node, pyslang.syntax.SyntaxNode):
            continue
        tn = type(node).__name__

        if tn == "DataDeclarationSyntax":
            width_m = _WIDTH_RE.search(str(node.type))
            width = width_m.group(0) if width_m else ""
            for d in node.declarators:
                if type(d).__name__ != "DeclaratorSyntax":
                    continue
                name = str(d.name).strip()
                if name and name not in seen:
                    seen.add(name)
                    decls.append(_Decl(name=name, width=width))

        elif tn == "ImplicitAnsiPortSyntax":
            header = node.header
            direction_tok = getattr(header, "direction", None)
            if direction_tok is None:
                continue
            name = str(node.declarator.name).strip()
            width_m = _WIDTH_RE.search(str(header))
            width = width_m.group(0) if width_m else ""
            if name and name not in seen:
                seen.add(name)
                decls.append(_Decl(name=name, width=width))

    return decls


def _is_lhs_of_assignment(node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.kind in (
        SyntaxKind.NonblockingAssignmentExpression,
        SyntaxKind.AssignmentExpression,
    ):
        return parent.left is node
    return False


def signal_substitution(tree, source: str) -> list[MutationCandidate]:
    decls = _collect_declared_signals(tree, source)
    by_width: dict[str, list[str]] = {}
    for d in decls:
        by_width.setdefault(d.width, []).append(d.name)
    names_by_width = {w: names for w, names in by_width.items() if len(names) >= 2}
    name_to_width = {d.name: d.width for d in decls}

    candidates: list[MutationCandidate] = []
    for node in walk(tree.root):
        if type(node).__name__ != "IdentifierNameSyntax":
            continue
        name = str(node.identifier).strip()
        if name not in name_to_width:
            continue
        if _is_lhs_of_assignment(node):
            continue  # only substitute READS, never the signal being written
        width = name_to_width[name]
        peers = names_by_width.get(width, [])
        replacement = next((p for p in peers if p != name), None)
        if replacement is None:
            continue

        start = node.sourceRange.start.offset
        end = node.sourceRange.end.offset
        candidates.append(
            MutationCandidate(
                start_offset=start,
                end_offset=end,
                original_text=source[start:end],
                replacement_text=replacement,
                bug_class="SIGNAL",
                operator="signal.signal_substitution",
                description=f"read of {name!r} (width {width or '1-bit'}) -> {replacement!r}",
                line=line_of(source, start),
            )
        )
    return candidates
