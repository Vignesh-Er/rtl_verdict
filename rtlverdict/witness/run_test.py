"""run_test(design, mutant) -> compact JSON with the FIRST divergence only,
never a raw log - the brief's core requirement, and the direct answer to
HWE-Bench's finding that agents rarely invoke simulation: this tool gives
them one small structured fact instead of a wall of $display output.

Runs the SAME testbench against golden and mutant with VCD dumping enabled,
then diffs the two traces. This is a different (complementary) signal from
sim_confirm's PASS/FAIL marker: sim_confirm asks "did the testbench's own
checks fail," this asks "where do the two implementations' signals first
disagree," which is what an agent actually needs to start debugging from.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rtlverdict import env
from rtlverdict.witness.diff_traces import diff_traces


@dataclass
class RunTestResult:
    pass_: bool
    first_divergence: dict | None
    summary: str


def _compile_and_dump(dut_path: Path, testbench_path: Path, vcd_out: Path, timeout_s: int) -> None:
    """Runs in its OWN fresh temp directory (never vcd_out's shared parent) -
    two sequential calls into a shared directory each dump a file named
    after the testbench's own $dumpfile call (e.g. "tb_fsm.vcd", identical
    both times), so a glob against the shared directory on the second call
    would ambiguously match the first call's already-renamed output too.
    Isolating per-call sidesteps that entirely instead of trying to filter it.
    """
    subprocess_env = env.build_subprocess_env()
    iverilog = shutil.which("iverilog.exe", path=subprocess_env["PATH"])
    vvp = shutil.which("vvp.exe", path=subprocess_env["PATH"])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        vvp_bin = tmp_p / "sim.vvp"
        subprocess.run(
            [iverilog, "-g2005", "-o", str(vvp_bin), str(dut_path), str(testbench_path)],
            env=subprocess_env,
            check=True,
            capture_output=True,
            timeout=timeout_s,
        )
        proc = subprocess.run(
            [vvp, str(vvp_bin), "+vcd"],
            env=subprocess_env,
            cwd=tmp_p,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        produced = list(tmp_p.glob("*.vcd"))
        if not produced:
            raise RuntimeError(f"no VCD produced: {proc.stdout[-300:]}")
        vcd_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(produced[0], vcd_out)


def run_test(
    golden_path: str,
    mutant_path: str,
    testbench_path: str,
    clock_period: int,
    work_dir: str,
    timeout_s: int = 30,
) -> RunTestResult:
    work_dir_p = Path(work_dir)
    work_dir_p.mkdir(parents=True, exist_ok=True)
    gold_vcd = work_dir_p / "golden.vcd"
    mut_vcd = work_dir_p / "mutant.vcd"

    _compile_and_dump(Path(golden_path), Path(testbench_path), gold_vcd, timeout_s)
    _compile_and_dump(Path(mutant_path), Path(testbench_path), mut_vcd, timeout_s)

    div = diff_traces(str(gold_vcd), str(mut_vcd), clock_period, scope_filter="dut")

    if div is None:
        return RunTestResult(pass_=True, first_divergence=None, summary="no divergence found")
    return RunTestResult(
        pass_=False,
        first_divergence={
            "cycle": div.cycle,
            "signal": div.signal,
            "expected": div.expected,
            "actual": div.actual,
        },
        summary=f"diverged at cycle {div.cycle}: {div.signal} expected {div.expected}, got {div.actual}",
    )
