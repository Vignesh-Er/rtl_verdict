# rtlverdict

A license-free harness that generates formally-validated RTL bug benchmarks
from Verilog designs, gives AI agents structured hardware debug evidence
instead of raw logs, and renders a formal verdict on every proposed patch.

**"Your testbench says PASS. Can you prove it?"**

Work in progress, actively developed. This README is honest about what's
real and what's parked, not a finished pitch - `FINDINGS.md` has the full
investigation log behind every claim below.

## What works today (real numbers, no placeholders)

- **forge** (`rtlverdict/forge/`): a pyslang-based mutation engine that
  splices the *original source text* at exact token byte-offsets (never
  re-serializes the parse tree), guaranteeing byte-level fidelity outside
  the mutated span by construction. LOGIC (operator swap, constant
  perturbation) and TIMING (blocking/non-blocking swap, edge swap) operator
  classes are implemented and tested. Gate: 103 generated mutants across 3
  designs, 0 diff-fidelity failures.
- **verdict** (`rtlverdict/verdict/`): a formal equivalence ladder,
  currently **BMC-only** (see Known broken/parked below). Given a golden
  design and a mutant, it generates a miter from the module's own port list
  (not hand-written per design) and runs bounded model checking via
  SymbiYosys. Never promotes a bounded BMC pass to "proven equivalent" -
  unrefuted mutants quarantine instead of being discarded.
- **corpus pipeline** (`rtlverdict/forge/corpus.py`): ties mutation
  generation, simulation confirmation, and the formal ladder together in the
  order parse → validate → compile → sim → formal, with formal *never*
  short-circuited on a sim pass. First real run (`benchmarks/corpus_v1/`,
  20 candidates across fsm + uart): **10 KEEP, 4 QUARANTINE, 6 SILENT.**
- **Silent-bug detection**: a SILENT task is a mutant formally proven
  non-equivalent to golden that the design's own testbench does not catch
  (sim still reports PASS). This is a direct, zero-agent-involvement measure
  of testbench blindness. 6/20 in the current corpus - real, but n is too
  small to report as a rate yet (see `results/coverage_vs_silent_bugs.md`).
- **4 Tier A reference designs** (`designs/{fsm,uart,spi_master,fifo}/`):
  self-authored, MIT-licensed, Verilog-2005, each with a self-checking
  testbench conforming to `designs/CONTRACT.md`, a `design.yaml` manifest,
  and a machine-*verified* (not asserted) `reset_covers_all_state` claim.

## Known broken / parked (not hidden, not worked around silently)

- **eqy is not trusted for discard decisions.** A control test (compare
  golden `fsm` against a gate module with every output hardwired to
  constant 0 - i.e. unmistakably non-equivalent) produced a confident
  `PASS`/"Induction step proven: SUCCESS!" from eqy's `sat` strategy. The
  invocation, not eqy the tool, is suspected broken - investigation ongoing,
  see `FINDINGS.md`. Until resolved, the ladder is BMC-only: **BMC-refutes
  always overrides eqy-proves**, and eqy's EQUIVALENT verdict is never used
  to discard a mutant. No upstream issue filed yet - not until the control
  test is understood.
- **picorv32/nerv (Tier B) golden-vs-golden is unresolved.** Extensively
  investigated (manual state-alignment attempts, a reset-hold sweep, running
  MCY's own reference miter structure unmodified) - all ruled out as the
  cause of the remaining divergence. Root cause not found; parked.
- Tier A is fully green on all six per-design checks (sim, synth,
  golden-vs-golden, over-constraint, determinism, reset-coverage). Tier B is
  not required for the current milestone.

## Scope limits (deliberate, not oversights)

- **Verilog-2005 synthesizable subset only.** Open Yosys has weak
  SystemVerilog support; this is a stated design decision, not a gap to be
  filled later.
- **BMC is bounded** (default depth 40). A bounded pass is reported as
  `PROVEN-BMC`, never promoted to an unbounded equivalence claim.
- **Module-granularity formal checking.**

## Install

Toolchain lives outside the repo (not committed - it's ~2GB):

```
# Download YosysHQ's OSS CAD Suite (Windows/Linux/macOS builds available)
# https://github.com/YosysHQ/oss-cad-suite-build/releases
# Extract it somewhere, then:
export RTLVERDICT_OSS_CAD_ROOT=/path/to/oss-cad-suite

python -m venv .venv
.venv/bin/pip install pyslang pytest ruff matplotlib numpy
```

Verify the toolchain (real check, not a placeholder):

```
python -m pytest rtlverdict/tests/test_env.py -v
```

## Reproduce / verify

Full setup (Windows and Linux) is in `docs/REPRODUCE.md`. The short version:

```
python -m rtlverdict.doctor   # every required tool, green or red + a specific remedy
make verify                   # or: python scripts/verify.py
```

`make verify` re-runs the real formal ladder on a fixed 10-task subset
(golden vs. each task's committed mutant) plus one true-fix and one
wrong-fix case through the agent-verdict path, and diffs every result
against a committed golden file — proving the ladder discriminates a
real fix from a wrong one, not just that the scripts run. **Measured
runtime: well under the 5-minute budget** (`results/verify_run_report.json`
has the exact figure from the most recent run). Full accounting of what
it checks and why: `results/verdict_ladder_validation.md`.

## Influences

CirFix, RTL-Repair, MCY, HWE-Bench, RealBench, AssertLLM2 - see `PLAN.md`
for how each shaped this project's design.
