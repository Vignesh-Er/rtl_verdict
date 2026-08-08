"""Compiles and runs a design's testbench against a given DUT file (golden
or mutant), reading the RTLVERDICT_RESULT marker line per designs/CONTRACT.md
- never trusting exit code alone (Icarus doesn't distinguish PASS/FAIL via
exit code, only $finish).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rtlverdict import env

_RESULT_RE = re.compile(r"RTLVERDICT_RESULT: (PASS|FAIL)(?:\s+at cycle \S+:\s*(.*))?")


@dataclass
class SimResult:
    outcome: str  # "PASS" | "FAIL" | "SIM-INVALID"
    detail: str


def run_sim(dut_path: str | Path, testbench_path: str | Path, timeout_s: int = 30) -> SimResult:
    subprocess_env = env.build_subprocess_env()
    iverilog = shutil.which("iverilog.exe", path=subprocess_env["PATH"])
    vvp = shutil.which("vvp.exe", path=subprocess_env["PATH"])
    if iverilog is None or vvp is None:
        raise RuntimeError("iverilog/vvp not found on PATH built by rtlverdict.env")

    with tempfile.TemporaryDirectory() as tmp:
        vvp_out = Path(tmp) / "sim.vvp"
        compile_proc = subprocess.run(
            [iverilog, "-g2005", "-o", str(vvp_out), str(dut_path), str(testbench_path)],
            env=subprocess_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if compile_proc.returncode != 0:
            return SimResult("SIM-INVALID", f"compile failed: {compile_proc.stderr[:500]}")

        try:
            run_proc = subprocess.run(
                [vvp, str(vvp_out)],
                env=subprocess_env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return SimResult("SIM-INVALID", f"sim exceeded {timeout_s}s (hang)")

        output = run_proc.stdout + run_proc.stderr
        m = _RESULT_RE.search(output)
        if m is None:
            return SimResult("SIM-INVALID", f"no RTLVERDICT_RESULT marker found: {output[-300:]}")
        outcome = m.group(1)
        detail = m.group(2) or ""
        return SimResult(outcome, detail)
