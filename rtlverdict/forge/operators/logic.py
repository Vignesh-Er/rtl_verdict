"""LOGIC mutation operators: operator swap, constant perturbation.

Condition inversion is deliberately not implemented yet - it needs a text
INSERTION (wrapping a condition in `!(...)`), a different shape from every
other operator here (which all replace one existing token with another of
the same width-class). Tracked as a follow-up, not silently skipped.
"""

from __future__ import annotations

import pyslang

from rtlverdict.forge.candidate import MutationCandidate
from rtlverdict.forge.parser import line_of, walk

SyntaxKind = pyslang.syntax.SyntaxKind

# Only pair operators within the same category (bitwise with bitwise, logical
# with logical) so every mutant stays syntactically well-typed at the same
# width. Each pair is tried in both directions.
_OPERATOR_SWAP_PAIRS: dict[SyntaxKind, tuple[SyntaxKind, str]] = {
    SyntaxKind.EqualityExpression: (SyntaxKind.InequalityExpression, "!="),
    SyntaxKind.InequalityExpression: (SyntaxKind.EqualityExpression, "=="),
    SyntaxKind.BinaryAndExpression: (SyntaxKind.BinaryOrExpression, "|"),
    SyntaxKind.BinaryOrExpression: (SyntaxKind.BinaryAndExpression, "&"),
    SyntaxKind.LogicalAndExpression: (SyntaxKind.LogicalOrExpression, "||"),
    SyntaxKind.LogicalOrExpression: (SyntaxKind.LogicalAndExpression, "&&"),
    SyntaxKind.AddExpression: (SyntaxKind.SubtractExpression, "-"),
    SyntaxKind.SubtractExpression: (SyntaxKind.AddExpression, "+"),
    SyntaxKind.LessThanExpression: (SyntaxKind.LessThanEqualExpression, "<="),
    SyntaxKind.GreaterThanExpression: (SyntaxKind.GreaterThanEqualExpression, ">="),
}


def operator_swap(tree, source: str) -> list[MutationCandidate]:
    candidates = []
    for node in walk(tree.root):
        if not isinstance(node, pyslang.syntax.SyntaxNode):
            continue
        if node.kind not in _OPERATOR_SWAP_PAIRS:
            continue
        _, replacement = _OPERATOR_SWAP_PAIRS[node.kind]
        tok = node.operatorToken
        start = tok.range.start.offset
        end = tok.range.end.offset
        candidates.append(
            MutationCandidate(
                start_offset=start,
                end_offset=end,
                original_text=source[start:end],
                replacement_text=replacement,
                bug_class="LOGIC",
                operator="logic.operator_swap",
                description=f"{node.kind.name}: {source[start:end]!r} -> {replacement!r}",
                line=line_of(source, start),
            )
        )
    return candidates


_BASE_RADIX = {"d": 10, "h": 16, "b": 2, "o": 8}


def _parse_verilog_int_literal(raw: str) -> tuple[str, int, int | None] | None:
    """Parse `[size]'[base]digits` (e.g. "3'd5", "'h1F", "42") straight from
    source text - deliberately not using pyslang's Token.value (an SVInt
    whose observed repr did not match the literal it came from in testing;
    not trusted without further investigation this project doesn't have time
    for right now). Returns (prefix_up_to_and_including_base_char, value,
    width_in_bits_or_None) or None if the literal has X/Z bits or an
    unrecognized shape. width is None when no size is given (unsized, e.g.
    plain "42" or "'h1F") - those aren't range-checked against a bit width.
    """
    if "'" not in raw:
        try:
            return "", int(raw.strip()), None
        except ValueError:
            return None
    size_part, rest = raw.split("'", 1)
    rest = rest.strip()
    if not rest:
        return None
    base_char = rest[0].lower()
    if base_char not in _BASE_RADIX:
        return None
    digits = rest[1:].replace("_", "")
    if not digits or any(c in "xXzZ?" for c in digits):
        return None
    try:
        value = int(digits, _BASE_RADIX[base_char])
    except ValueError:
        return None
    width = int(size_part) if size_part.strip().isdigit() else None
    return f"{size_part}'{rest[0]}", value, width


def constant_perturbation(tree, source: str) -> list[MutationCandidate]:
    """Perturb an integer literal's value by +1. Skips parameter/localparam
    declarations (perturbing a bus WIDTH constant produces a mutant that
    won't even elaborate - not a behavioral bug, just noise the sim-confirm
    stage would discard anyway, cheaper to not generate at all) and skips
    literals pyslang doesn't classify as a plain IntegerVectorExpression.
    """
    candidates = []
    for node in walk(tree.root):
        if not isinstance(node, pyslang.syntax.SyntaxNode):
            continue
        if node.kind != SyntaxKind.IntegerVectorExpression:
            continue
        p = node.parent
        skip = False
        while p is not None:
            if p.kind in (
                SyntaxKind.ParameterDeclaration,
                SyntaxKind.TypeParameterDeclaration,
            ):
                skip = True
                break
            p = getattr(p, "parent", None)
        if skip:
            continue

        start = node.sourceRange.start.offset
        end = node.sourceRange.end.offset
        raw = source[start:end]
        parsed = _parse_verilog_int_literal(raw)
        if parsed is None:
            continue
        prefix, value, width = parsed
        # Wrap modulo the literal's declared bit width so the perturbed
        # value stays representable (e.g. 1'b1 -> 1'b0, a bit-flip, not
        # 1'b2, which doesn't parse). Unsized literals are left unwrapped.
        new_value = value + 1
        if width is not None:
            new_value = new_value % (1 << width)
        new_val_str = f"{prefix}{new_value}"

        candidates.append(
            MutationCandidate(
                start_offset=start,
                end_offset=end,
                original_text=raw,
                replacement_text=new_val_str,
                bug_class="LOGIC",
                operator="logic.constant_perturbation",
                description=f"constant {raw!r} -> {new_val_str!r}",
                line=line_of(source, start),
            )
        )
    return candidates
