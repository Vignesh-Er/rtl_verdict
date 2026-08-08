"""Pre-check run on every agent-submitted patch BEFORE any miter is built
(P3 explicit instruction) - a BMC run costs real wall-clock time up to its
timeout, and a patch that doesn't even parse/elaborate/keep the same
interface can never produce a meaningful formal verdict, so reject it here
instead of burning a BMC run on garbage.

Four checks, in order, first failure wins:
  1. parses (pyslang, 0 diagnostics)
  2. elaborates (iverilog -g2005 compile against the SAME testbench used for
     the task - a patch that pyslang accepts but the elaborator rejects is
     still invalid)
  3. top module name unchanged
  4. port list unchanged (name/direction/width, order-independent - every
     port connection in this codebase's miter generator and testbenches is
     named, never positional, so port ORDER is never semantically
     significant here)
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pyslang

from rtlverdict import env
from rtlverdict.verdict.miter import extract_ports


@dataclass
class PatchCheckResult:
    ok: bool
    reason: str | None = None


def _module_names(source: str) -> set[str]:
    tree = pyslang.syntax.SyntaxTree.fromText(source, "patch.v")
    names: set[str] = set()

    def walk(n):
        yield n
        if isinstance(n, pyslang.parsing.Token):
            return
        for i in range(len(n)):
            c = n[i]
            if c is not None:
                yield from walk(c)

    for node in walk(tree.root):
        if type(node).__name__ == "ModuleHeaderSyntax":
            names.add(str(node.name).strip())
    return names


def _elaborates(patch_path: Path, testbench_path: Path, timeout_s: int) -> tuple[bool, str]:
    subprocess_env = env.build_subprocess_env()
    iverilog = shutil.which("iverilog.exe", path=subprocess_env["PATH"])
    if iverilog is None:
        raise RuntimeError("iverilog not found on PATH built by rtlverdict.env")
    with tempfile.TemporaryDirectory() as tmp:
        vvp_out = Path(tmp) / "elab.vvp"
        try:
            proc = subprocess.run(
                [iverilog, "-g2005", "-o", str(vvp_out), str(patch_path), str(testbench_path)],
                env=subprocess_env, capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return False, f"elaboration exceeded {timeout_s}s"
        if proc.returncode != 0:
            return False, (proc.stderr[-500:] or proc.stdout[-500:])
        return True, ""


def check_patch(
    patch_source: str,
    golden_source: str,
    top_module: str,
    testbench_path: str | Path,
    timeout_s: int = 30,
) -> PatchCheckResult:
    # 1. parses
    tree = pyslang.syntax.SyntaxTree.fromText(patch_source, "patch.v")
    diags = list(tree.diagnostics)
    if diags:
        return PatchCheckResult(False, f"parse failed: {len(diags)} diagnostics")

    # 2. elaborates
    with tempfile.TemporaryDirectory() as tmp:
        patch_path = Path(tmp) / "patch.v"
        patch_path.write_text(patch_source)
        ok, detail = _elaborates(patch_path, Path(testbench_path), timeout_s)
        if not ok:
            return PatchCheckResult(False, f"elaboration failed: {detail}")

    # 3. top module name unchanged
    names = _module_names(patch_source)
    if top_module not in names:
        return PatchCheckResult(
            False, f"top module {top_module!r} not found (patch declares: {sorted(names)})"
        )

    # 4. port list unchanged (name/direction/width, order-independent)
    golden_ports = {(p.name, p.direction, p.width_decl) for p in extract_ports(golden_source, top_module)}
    patch_ports = {(p.name, p.direction, p.width_decl) for p in extract_ports(patch_source, top_module)}
    if golden_ports != patch_ports:
        added = sorted(patch_ports - golden_ports)
        removed = sorted(golden_ports - patch_ports)
        return PatchCheckResult(False, f"port list changed: added={added} removed={removed}")

    return PatchCheckResult(True, None)
