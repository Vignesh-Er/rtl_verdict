"""The formal verdict ladder. Currently BMC-only: eqy's per-partition SAT
strategy was found to false-prove equivalence on 4/4 tested designs on this
Windows setup (FINDINGS.md) - a soundness problem, not a reporting bug - so
eqy is not wired in for real decisions yet. This is the adopted degraded-mode
operating assumption: unrefuted mutants QUARANTINE instead of being marked
PROVEN-UNBOUNDED equivalent. Sound (no real bug is ever silently discarded),
not a complete ladder.

RULE (permanent, not just for while eqy is broken): if eqy is ever wired
back in, its EQUIVALENT verdict must never be trusted to DISCARD a mutant
unless BMC has already independently failed to refute it first. BMC-refutes
always overrides eqy-proves.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from rtlverdict import env
from rtlverdict.verdict.miter import extract_ports, generate_miter

VERDICTS = (
    "REFUTED",  # BMC found a genuine counterexample - confirmed real divergence
    "PROVEN-BMC",  # no counterexample within k steps - a BOUNDED claim only, never
    # promoted to "equivalent" for discard purposes on its own
    "INDETERMINATE",  # timeout, tool error, or anything else - never a proof either way
)


@dataclass
class VerdictResult:
    verdict: str
    tier: str
    engine: str
    k: int
    runtime_s: float
    divergence_cycle: int | None = None
    failing_assertion_line: int | None = None
    raw_log_tail: str = ""


def _run_sby(sby_path: Path, timeout_s: int) -> tuple[str, float]:
    subprocess_env = env.build_subprocess_env()
    sby_exe = shutil.which("sby.exe", path=subprocess_env["PATH"])
    if sby_exe is None:
        raise RuntimeError("sby.exe not found on PATH built by rtlverdict.env")
    start = time.time()
    proc = subprocess.run(
        [sby_exe, "-f", str(sby_path.name)],
        cwd=sby_path.parent,
        env=subprocess_env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    runtime = time.time() - start
    return proc.stdout + proc.stderr, runtime


def check_bmc(
    golden_path: str | Path,
    mutant_path: str | Path,
    top_module: str,
    reset_signal: str,
    reset_active_low: bool,
    work_dir: str | Path,
    k: int = 40,
    timeout_s: int = 120,
    memory_map: bool = False,
) -> VerdictResult:
    """`memory_map=True` inserts Yosys's `memory_map` pass right after
    `prep -top miter`, converting the design's memories to registers/muxes
    before BMC. Required for designs with real arrays (fifo's `mem[]`):
    plain BMC hits SMT array-theory blowup around depth 12-14 regardless of
    solver backend (measured, see designs/fifo/design.yaml); memory_map
    roughly doubles reachable depth. Recipe matches the hand-verified
    golden-vs-golden run in designs/fifo/fifo_gg_memmap.sby. A no-op for
    memory-free designs (fsm/uart/spi_master) - never enabled for them.
    """
    golden_path = Path(golden_path)
    mutant_path = Path(mutant_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    golden_src = golden_path.read_text()
    ports = extract_ports(golden_src, top_module)
    miter_src = generate_miter(
        top_module,
        ports,
        reset_signal,
        reset_active_low,
        ref_module=f"gold_{top_module}",
        uut_module=f"mutant_{top_module}",
    )

    (work_dir / "golden.v").write_text(golden_src)
    (work_dir / "mutant.v").write_text(mutant_path.read_text())
    (work_dir / "miter.sv").write_text(miter_src)

    # golden.v and mutant.v both declare a module named `top_module` - the
    # rename+stash+copy-from dance merges the two distinct definitions into
    # one design under different names, proven necessary and working in this
    # session (naively reading both directly hits "Re-definition of module").
    sby_content = f"""[options]
mode bmc
depth {k}
expect fail

[engines]
smtbmc yices

[script]
read_verilog -formal golden.v
rename {top_module} gold_{top_module}
design -stash gold

read_verilog -formal mutant.v
rename {top_module} mutant_{top_module}
design -stash mutant

design -copy-from gold -as gold_{top_module} gold_{top_module}
design -copy-from mutant -as mutant_{top_module} mutant_{top_module}

read_verilog -formal -sv miter.sv
prep -top miter
{"memory_map" if memory_map else ""}

[files]
golden.v
mutant.v
miter.sv
"""
    sby_path = work_dir / "check.sby"
    sby_path.write_text(sby_content)
    tier_name = "bmc_memmap" if memory_map else "bmc"

    try:
        log, runtime = _run_sby(sby_path, timeout_s)
    except subprocess.TimeoutExpired:
        return VerdictResult(
            verdict="INDETERMINATE",
            tier=tier_name,
            engine="smtbmc yices",
            k=k,
            runtime_s=float(timeout_s),
            raw_log_tail=f"timed out after {timeout_s}s",
        )

    tail = "\n".join(log.splitlines()[-15:])

    if "DONE (FAIL" in log and "failed assertion" in log:
        # Match the summary line specifically ("failed assertion ... at
        # miter.sv:L.C-L.C step N"), not the per-step progress lines that
        # appear earlier in the same log for every step checked along the way.
        m = re.search(r"failed assertion .* at miter\.sv:(\d+)\S* step (\d+)", log)
        line = int(m.group(1)) if m else None
        cycle = int(m.group(2)) if m else None
        return VerdictResult(
            verdict="REFUTED",
            tier=tier_name,
            engine="smtbmc yices",
            k=k,
            runtime_s=runtime,
            divergence_cycle=cycle,
            failing_assertion_line=line,
            raw_log_tail=tail,
        )
    if "DONE (PASS" in log:
        return VerdictResult(
            verdict="PROVEN-BMC",
            tier=tier_name,
            engine="smtbmc yices",
            k=k,
            runtime_s=runtime,
            raw_log_tail=tail,
        )
    # ERROR, unrecognized shape, or a DONE(FAIL) without a real counterexample
    # (e.g. mutant fails to elaborate) - fail closed, never guess REFUTED or
    # PROVEN from an ambiguous log.
    return VerdictResult(
        verdict="INDETERMINATE",
        tier="bmc",
        engine="smtbmc yices",
        k=k,
        runtime_s=runtime,
        raw_log_tail=tail,
    )
