"""Toolchain environment setup, shared by every module that shells out to
Yosys/sby/eqy/mcy/iverilog/verilator or any bash-based subprocess.

Two real, evidenced Windows issues this centralizes fixes for:
  - yosys.exe fails to load (libreadline8.dll) unless oss-cad-suite's `lib/`
    directory is on PATH, not just `bin/`.
  - eqy and Verilator's --binary mode both shell out to `make`, which is not
    bundled in oss-cad-suite on Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

_MSYS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")

REQUIRED_TOOLS = [
    "yosys",
    "sby",
    "eqy",
    "mcy",
    "iverilog",
    "vvp",
    "verilator_bin",
    "z3",
    "boolector",
    "yices",
    "bash",
    "make",
]

# Tools whose --version flag doesn't behave like the others.
_VERSION_ARGS = {
    "yosys": ["-V"],
    "sby": ["--version"],
    "eqy": ["--version"],
    "mcy": [],  # no --version; presence + help text is the only signal
    "iverilog": ["-V"],
    "vvp": ["-V"],
    "verilator_bin": ["--version"],
    "z3": ["--version"],
    "boolector": ["--version"],
    "yices": ["--version"],
    "bash": ["--version"],
    "make": ["--version"],
}


def to_msys_path(path: str | os.PathLike) -> str:
    """Convert a Windows path (E:\\Hackathon\\x) to a Git-Bash/MSYS2 path
    (/e/Hackathon/x). Passes through paths that are already POSIX-style.

    UNC paths (\\\\server\\share\\...) are not supported and are returned
    unchanged - callers should avoid them for tool invocation.
    """
    s = str(path)
    m = _MSYS_DRIVE_RE.match(s)
    if not m:
        return s.replace("\\", "/")
    drive, rest = m.groups()
    return f"/{drive.lower()}/{rest.replace(chr(92), '/')}"


def oss_cad_root() -> Path:
    """Root of the OSS CAD Suite install. Never hardcoded - must come from
    RTLVERDICT_OSS_CAD_ROOT so a clean clone on a different machine/drive
    works without editing source.
    """
    root = os.environ.get("RTLVERDICT_OSS_CAD_ROOT")
    if not root:
        raise RuntimeError(
            "RTLVERDICT_OSS_CAD_ROOT is not set. Point it at an oss-cad-suite "
            "install root (the directory containing bin/ and lib/), e.g. "
            "C:\\Users\\you\\tools\\oss-cad-suite. Run scripts/setup_env.ps1 "
            "to download and extract one."
        )
    p = Path(root)
    if not (p / "bin").is_dir():
        raise RuntimeError(f"RTLVERDICT_OSS_CAD_ROOT={root} has no bin/ subdirectory")
    return p


def build_subprocess_env() -> dict[str, str]:
    """Return an os.environ-like dict with oss-cad-suite's bin/ and lib/
    prepended to PATH, plus any local shims (e.g. a make.exe shim) directory
    if one is configured. Pass this as `env=` to every subprocess call that
    invokes yosys/sby/eqy/mcy/iverilog/verilator/bash.
    """
    root = oss_cad_root()
    env = dict(os.environ)
    parts = [str(root / "bin"), str(root / "lib")]
    shim_dir = os.environ.get("RTLVERDICT_TOOL_SHIMS")
    if shim_dir:
        parts.insert(0, shim_dir)
    parts.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(p for p in parts if p)
    env["YOSYSHQ_ROOT"] = str(root) + os.sep
    return env


@dataclass
class ToolStatus:
    name: str
    found: bool
    path: str | None = None
    version_output: str | None = None
    error: str | None = None


@dataclass
class DoctorReport:
    tools: list[ToolStatus] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(t.found for t in self.tools)

    def to_dict(self) -> dict:
        return {
            "all_ok": self.all_ok,
            "tools": [
                {
                    "name": t.name,
                    "found": t.found,
                    "path": t.path,
                    "version_output": t.version_output,
                    "error": t.error,
                }
                for t in self.tools
            ],
        }


def run_doctor() -> DoctorReport:
    """Validate every required tool is resolvable and runnable. This is the
    real check `rtlverdict doctor` runs - never assume a tool works because
    it's installed; every one of these has surprised us at least once
    (missing lib/ on PATH, missing make, mcy's shell=True/cmd.exe mismatch).
    """
    env = build_subprocess_env()
    report = DoctorReport()
    for name in REQUIRED_TOOLS:
        found_path = shutil.which(name, path=env["PATH"])
        if not found_path:
            report.tools.append(ToolStatus(name=name, found=False, error="not found on PATH"))
            continue
        args = _VERSION_ARGS.get(name, ["--version"])
        try:
            proc = subprocess.run(
                [found_path, *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            first_line = next((l for l in output.splitlines() if l.strip()), "")
            report.tools.append(
                ToolStatus(name=name, found=True, path=found_path, version_output=first_line)
            )
        except Exception as e:  # noqa: BLE001 - doctor must never crash on a bad tool
            report.tools.append(
                ToolStatus(name=name, found=True, path=found_path, error=str(e))
            )
    return report
