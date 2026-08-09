"""Generates a golden-vs-mutant miter from a design's port list (extracted
via pyslang, not hand-written per design) plus its design.yaml reset
polarity. Pattern proven in this session: single reset-assume is sufficient
for every Tier A design (fsm/uart/spi_master/fifo all PASS golden-vs-golden
this way); Tier B (picorv32/nerv) needs more and is not yet supported here -
see FINDINGS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pyslang

SyntaxKind = pyslang.syntax.SyntaxKind

_WIDTH_RE = re.compile(r"\[[^\]]*\]")
_SAFE_ARITH_RE = re.compile(r"^[\d\s+\-*/()]+$")


def _walk(n):
    yield n
    if isinstance(n, pyslang.parsing.Token):
        return
    for i in range(len(n)):
        c = n[i]
        if c is not None:
            yield from _walk(c)


def _extract_numeric_params(source: str) -> dict[str, int]:
    """Default values of every `parameter`/`localparam` declaration with a
    plain integer-literal default (e.g. `parameter WIDTH = 8`). Used to
    resolve parameterized port widths like `[WIDTH-1:0]` into a concrete
    `[7:0]` for the miter, which only ever declares plain wires and cannot
    itself see the design's own parameter scope. Non-numeric defaults
    (expressions referencing another parameter, $clog2, etc.) are skipped -
    left for _resolve_width to fail loud on, never silently guessed.
    """
    tree = pyslang.syntax.SyntaxTree.fromText(source, "x.v")
    params: dict[str, int] = {}
    for node in _walk(tree.root):
        if type(node).__name__ != "ParameterDeclarationSyntax":
            continue
        for d in node.declarators:
            if type(d).__name__ != "DeclaratorSyntax" or d.initializer is None:
                continue
            name = str(d.name).strip()
            expr_text = str(d.initializer.expr).strip()
            if _SAFE_ARITH_RE.match(expr_text):
                params[name] = eval(expr_text, {"__builtins__": {}}, {})  # noqa: S307 - regex-validated digits/arithmetic only
    return params


def _resolve_width(width_decl: str, params: dict[str, int]) -> str:
    """Substitute known parameter names into a port width expression (e.g.
    "[WIDTH-1:0]" with WIDTH=8 -> "[7:0]") so the miter - which has no
    access to the design's own parameter scope - declares a concrete width
    instead of an undefined identifier. Left UNCHANGED (not guessed) if the
    substituted expression still contains an unresolved identifier or
    anything outside plain arithmetic: a stale width_decl fails loudly at
    miter elaboration, never silently produces a wrong-width comparison.
    """
    if not width_decl:
        return width_decl
    inner = width_decl[1:-1]
    for name, value in params.items():
        inner = re.sub(rf"\b{re.escape(name)}\b", str(value), inner)
    resolved = []
    for part in inner.split(":"):
        part = part.strip()
        if not _SAFE_ARITH_RE.match(part):
            return width_decl
        resolved.append(str(eval(part, {"__builtins__": {}}, {})))  # noqa: S307 - regex-validated digits/arithmetic only
    return f"[{':'.join(resolved)}]"


@dataclass
class Port:
    name: str
    direction: str  # "input" | "output"
    width_decl: str  # "" for 1-bit, "[N:0]" for wider - just the bracket part


def extract_ports(source: str, top_module: str) -> list[Port]:
    """Handles both ANSI port header shapes pyslang produces:
    NetPortHeaderSyntax (`input wire [7:0] x`) and VariablePortHeaderSyntax
    (`output reg [3:0] q`). Width is pulled via regex on the header's own
    text rather than trying to enumerate every dataType shape (RegType,
    ImplicitType with/without packed dimensions, etc.) - this only needs the
    bracket portion, never the reg/wire/logic keyword itself, and the miter
    only ever declares plain wires regardless of the original port's type.

    Parameterized widths (e.g. `[WIDTH-1:0]`) are resolved to concrete
    numbers via the module's own parameter defaults (_resolve_width) - the
    miter has no access to the design's parameter scope, so a raw
    `[WIDTH-1:0]` copied verbatim into the miter module would reference an
    undefined identifier. First found on fifo.v (real bug: the original
    naive text-copy silently produced an unelaborable miter for any
    parameterized-width port; fsm/uart/spi_master never had one, so this
    never manifested until a memory-containing design needed one).
    """
    tree = pyslang.syntax.SyntaxTree.fromText(source, "x.v")
    params = _extract_numeric_params(source)

    ports: list[Port] = []
    for node in _walk(tree.root):
        if type(node).__name__ != "ImplicitAnsiPortSyntax":
            continue
        header = node.header
        name = str(node.declarator.name).strip()
        direction_tok = getattr(header, "direction", None)
        if direction_tok is None:
            continue
        direction = str(direction_tok).strip().lower()
        if direction not in ("input", "output"):
            continue
        m = _WIDTH_RE.search(str(header))
        width_decl = _resolve_width(m.group(0), params) if m else ""
        ports.append(Port(name=name, direction=direction, width_decl=width_decl))
    return ports


def generate_miter(
    top_module: str,
    ports: list[Port],
    reset_signal: str,
    reset_active_low: bool,
    ref_module: str | None = None,
    uut_module: str | None = None,
) -> str:
    """`ref_module`/`uut_module` default to `top_module` (the golden-vs-
    golden case, where a single elaboration can instantiate one module type
    twice). Pass the renamed `gold_X`/`mutant_X` module names for golden-vs-
    mutant, where the rename+stash+copy-from merge produces two distinctly-
    named module types.
    """
    ref_module = ref_module or top_module
    uut_module = uut_module or top_module
    lines = []
    inputs = [p for p in ports if p.direction == "input"]
    io_decls = ",\n".join(
        f"\tinput {p.width_decl} {p.name}".replace("  ", " ").rstrip() for p in inputs
    )

    lines.append(f"module miter (\n{io_decls}\n);")

    outputs = [p for p in ports if p.direction == "output"]
    for p in outputs:
        decl = f"\twire {p.width_decl} ref_{p.name}, uut_{p.name};".replace("  ", " ")
        lines.append(decl)

    def conn_list(prefix_outputs: str) -> str:
        parts = []
        for p in ports:
            if p.direction == "input":
                parts.append(f".{p.name}({p.name})")
            else:
                parts.append(f".{p.name}({prefix_outputs}{p.name})")
        return ", ".join(parts)

    lines.append(f"\t{ref_module} ref_i ({conn_list('ref_')});")
    lines.append(f"\t{uut_module} uut_i ({conn_list('uut_')});")

    reset_expr = f"!{reset_signal}" if reset_active_low else reset_signal
    active_expr = reset_signal if reset_active_low else f"!{reset_signal}"
    lines.append(f"\tinitial assume({reset_expr});")

    asserts = "\n".join(f"\t\t\tassert (ref_{p.name} == uut_{p.name});" for p in outputs)
    lines.append("\talways @* begin")
    lines.append(f"\t\tif ({active_expr}) begin")
    lines.append(asserts)
    lines.append("\t\tend")
    lines.append("\tend")
    lines.append("endmodule")
    return "\n".join(lines)
