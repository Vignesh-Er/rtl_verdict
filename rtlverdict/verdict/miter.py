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
    """
    tree = pyslang.syntax.SyntaxTree.fromText(source, "x.v")

    def walk(n):
        yield n
        if isinstance(n, pyslang.parsing.Token):
            return
        for i in range(len(n)):
            c = n[i]
            if c is not None:
                yield from walk(c)

    ports: list[Port] = []
    for node in walk(tree.root):
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
        width_decl = m.group(0) if m else ""
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
