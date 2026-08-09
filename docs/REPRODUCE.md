# Reproducing rtlverdict's results

This project was built and every committed result was produced on
`Windows 11 Home Single Language, build 10.0.26200` (see
`results/corpus_stats.json`'s `provenance.host_os` field — `win32`, read
live at each corpus-stats build, not typed here). No Linux or macOS run
has produced any committed number in this repo — the Linux install steps
below follow oss-cad-suite's own documented pattern but are **untested by
this project** (see `Dockerfile`'s own untested-header for the same
caveat, one layer further out).

## Toolchain versions

Read from `results/corpus_stats.json`'s `toolchain_versions` field
(itself from a live `--version`/`-V` invocation of every tool, via
`rtlverdict.env.run_doctor()` — the exact same function
`python -m rtlverdict.doctor` runs). This is a snapshot as of that file's
last regeneration; treat `python -m rtlverdict.doctor`'s live output as
authoritative over this table if they ever disagree.

| tool | version output |
|---|---|
| yosys | `Yosys 0.68+40 (git sha1 0f2bcb94b-dirty, Release, GNU /usr/bin/x86_64-w64-mingw32-g++ 15.2.1)` |
| sby | `SBY v0.68` |
| eqy | `EQY v0.68` |
| mcy | `Usage: mcy-script.py [OPTIONS] [COMMAND] [ARGS]...` (no `--version` flag; presence + help text is the only signal — see `rtlverdict/env.py`) |
| iverilog | `Icarus Verilog version 14.0 (devel) (s20260301-349-gf49307688-dirty)` |
| vvp | `Icarus Verilog runtime version 14.0 (devel) (s20260301-349-gf49307688-dirty)` |
| verilator_bin | `Verilator 5.051 devel rev v5.050-150-g7e80ea657 (mod)` |
| z3 | `Z3 version 4.15.5 - 64 bit` |
| boolector | `3.2.4` |
| yices | `Yices 2.7.0` |
| bash | `GNU bash, version 5.2.37(1)-release (x86_64-pc-msys)` |
| make | `GNU Make 4.4.1` |
| python | `3.12.10` |

All of yosys/sby/eqy/mcy/iverilog/vvp/verilator_bin/z3/boolector/yices
came from one **OSS CAD Suite** install
(https://github.com/YosysHQ/oss-cad-suite-build/releases) — a single
download provides all of them at matched, tested-together versions;
installing them individually is not recommended and not what this
project was validated against.

## Install — Windows (tested, this is what produced every result in this repo)

```
# 1. Download an OSS CAD Suite Windows release and extract it, e.g. to
#    C:\Users\you\tools\oss-cad-suite
#    https://github.com/YosysHQ/oss-cad-suite-build/releases

# 2. Point the project at it (every session, or add to your shell profile):
export RTLVERDICT_OSS_CAD_ROOT=/c/Users/you/tools/oss-cad-suite

# 3. make is not bundled in oss-cad-suite on Windows (see rtlverdict/env.py's
#    module docstring) - install one (e.g. MSYS2 `pacman -S make`) and point
#    the project at the directory containing make.exe:
export RTLVERDICT_TOOL_SHIMS=/c/path/to/your/make/shim/dir

# 4. Python environment:
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

## Install — Linux (untested by this project, follows oss-cad-suite's own pattern)

```
# 1. Download an OSS CAD Suite Linux release and extract it
#    https://github.com/YosysHQ/oss-cad-suite-build/releases

export RTLVERDICT_OSS_CAD_ROOT=/path/to/oss-cad-suite

# make and bash are standard on any Linux distro - RTLVERDICT_TOOL_SHIMS
# should not be needed there; rtlverdict/env.py's shim-dir insertion is a
# no-op if the variable is unset.

python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Confirm the toolchain resolves before running anything else, on either OS:

```
python -m rtlverdict.doctor
```

Prints one row per required tool — green with its version, or red with a
specific one-line remedy (not a generic "install X"). Exits 0 if every
tool is green, 1 otherwise, so it's safe to gate a script or CI step on.

## Verify (`make verify`)

```
make verify
# or directly:
python scripts/verify.py
```

Re-runs the real formal ladder (`check_bmc`, the identical function both
`forge/corpus.py` and the agent-verdict path call — see
`results/verdict_ladder_validation.md` §6) on a **fixed 10-task subset**
(golden vs. each task's already-committed mutant, one task per row) and
diffs the raw verdict + divergence cycle against a committed golden file
(`benchmarks/verify_golden.json`). Also runs one **C2** (true fix,
region-scoped) and one **C3** (wrong fix, donor mutant) case from
`results/verdict_ladder_validation.md` through the real
`run_task → check_patch → check_bmc` agent-verdict path with a
deterministic stub — so this reproduction demonstrates the ladder
**discriminating** a real fix from a wrong one, not just re-running
without crashing.

**Measured runtime: read from `results/verify_run_report.json`**, which
`scripts/verify.py` writes to on every run (`elapsed_s`, its own internal
timer around the 10 forge checks + C2 + C3) — never hand-typed here, so
this number can't drift stale the way a copy-pasted figure would. Total
wall time including Python/shell startup (measured with the shell's own
`time` builtin) runs a few seconds higher than the internal figure.
Comfortably under the 5-minute budget either way; the script itself also
asserts this and fails loudly if a future change pushes it over.

Prints `VERIFY: PASS` or `VERIFY: FAIL` loudly, with every individual
mismatch listed if it fails, and exits `0`/`1` accordingly.

To regenerate the golden file after a deliberate, understood change
(never to make a failing diff go away):

```
python scripts/verify.py --freeze
```

## Docker

`Dockerfile` (repo root) is committed but explicitly marked **UNTESTED** in its
own header comment, with the reason (Docker Desktop requires an admin
install this environment does not have — see FINDINGS.md). It is
believed correct by inspection (mirrors the Windows install steps above
onto a Linux base image) but has never actually been built or run. Do
not treat it as validated.

## Confirming a clean clone actually works

The single highest-value check in this document: clone the repo fresh,
run `python -m rtlverdict.doctor`, then `make verify`. Any absolute path,
any directory assumed to already exist, any file that should have been
committed but wasn't, surfaces here — this is exactly the class of bug
that `rtlverdict/agent/loop.py`'s `work_dir` fix (see
`results/agent_pilot.md` §1) was: something that only breaks on a
genuinely fresh checkout, never on a machine that's already been used for
development.
