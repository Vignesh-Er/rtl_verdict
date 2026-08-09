"""python -m rtlverdict.doctor - the real environment check.

Prints one row per required tool: found or not, its version (if it ran),
and - for every red row - a one-line remedy specific to what's actually
wrong (not found at all, vs. found but crashed running --version). Exits
0 if everything is green, 1 otherwise, so `make verify`/CI can gate on it.

All the actual detection logic lives in rtlverdict.env.run_doctor() -
this module is presentation only, so the same detection this project
already depends on elsewhere (build_stats.py's toolchain_versions field,
every batch script's pre-flight) is exactly what a user sees here, never
a second, drifting implementation.
"""

from __future__ import annotations

import sys

from rtlverdict import env

_GREEN = "\033[92m"
_RED = "\033[91m"
_RESET = "\033[0m"

# One remedy per tool - specific to what this project actually needs from
# it, not a generic "install X" - each line names the real, previously
# hit failure mode (see rtlverdict/env.py's own module docstring and
# FINDINGS.md) so a red row tells you what to actually go do, not just
# that something's wrong.
_OSS_CAD_TOOLS = {
    "yosys", "sby", "eqy", "mcy", "iverilog", "vvp", "verilator_bin", "z3", "boolector", "yices",
}
_NOT_FOUND_REMEDIES = {
    **{t: (
        "not on PATH - set RTLVERDICT_OSS_CAD_ROOT to an oss-cad-suite install "
        "(the dir containing bin/ and lib/); see docs/REPRODUCE.md for the exact "
        "release and install steps"
    ) for t in _OSS_CAD_TOOLS},
    "bash": "not on PATH - install Git for Windows (ships bash.exe) or WSL, and ensure it's on PATH",
    "make": (
        "not on PATH - oss-cad-suite does not bundle make on Windows; install a make.exe "
        "(e.g. MSYS2 'pacman -S make') and point RTLVERDICT_TOOL_SHIMS at its directory"
    ),
}
_CRASH_REMEDY = (
    "found on PATH but failed to run --version - if this is a yosys-family tool, "
    "confirm oss-cad-suite's lib/ (not just bin/) is on PATH (libreadline8.dll load "
    "failure is the known cause, see rtlverdict/env.py's module docstring)"
)


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text  # no ANSI codes into a redirected/piped log - keep it plain there
    return f"{code}{text}{_RESET}"


def main() -> int:
    report = env.run_doctor()

    name_w = max(len(t.name) for t in report.tools) + 2
    status_w = 8
    print(f"{'tool':<{name_w}}{'status':<{status_w}}version / remedy")
    print("-" * 100)

    for t in report.tools:
        if t.found and t.error is None:
            status = _color("OK", _GREEN)
            detail = t.version_output or "(no version output)"
        else:
            status = _color("FAIL", _RED)
            if not t.found:
                detail = _NOT_FOUND_REMEDIES.get(t.name, f"not found on PATH ({t.error})")
            else:
                detail = f"{_CRASH_REMEDY} - error: {t.error}"
        # pad status BEFORE coloring so ANSI codes don't throw off column width
        status_padded = status + " " * (status_w - (4 if "FAIL" in status else 2))
        print(f"{t.name:<{name_w}}{status_padded}{detail}")

    print("-" * 100)
    if report.all_ok:
        print(_color(f"All {len(report.tools)} required tools OK.", _GREEN))
        return 0
    n_fail = sum(1 for t in report.tools if not (t.found and t.error is None))
    print(_color(f"{n_fail}/{len(report.tools)} tool(s) FAILED - see remedies above.", _RED))
    return 1


if __name__ == "__main__":
    sys.exit(main())
