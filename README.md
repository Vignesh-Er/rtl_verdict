# rtlverdict

**"Your testbench says PASS. Can you prove it?"**

A license-free, 100%-open-source-toolchain harness (Yosys, SymbiYosys,
Verilator, Icarus Verilog, Z3, Boolector, Yices — no commercial EDA, no
FPGA hardware) that mutates Verilog RTL, formally filters out the
equivalent mutants before they ever reach an agent, and formally
refutes incorrect fixes on the patch path — a bounded pass on a
proposed fix is reported `PLAUSIBLE`, never promoted to a claim of
proof (see Limitations). What this tool demonstrably does is catch
mutants that aren't bugs and catch fixes that don't work; it does not
claim to prove a fix correct.

**Resume line:** built a formally-gated RTL mutation-testing harness
and found, on real designs, that a design's own testbench misses
13.6%–72.2% of formally-confirmed bugs depending on the design, and
that 49.1% of naively-generated mutation candidates — including 95.2%
of the single largest operator class, the textbook `=`-vs-`<=` mistake
— are formally equivalent to golden, not bugs at all.

## The findings

Three numbers from the current 171-task corpus (`fsm`, `uart`,
`spi_master`, `fifo` — all read from `results/corpus_stats.json`,
regenerate with `python scripts/build_stats.py`):

- **A design's own testbench misses somewhere between 13.6% and 72.2%
  of the real bugs formally proven to exist in it — and which end of
  that range depends entirely on which design's testbench is asked.**
  There is no single "the silent-bug rate" for this method (pooled
  across all four designs: 37.6% — reported once, here, for
  comparability with prior work, not as a stable estimate of anything;
  see `results/silent_bugs.md` for the full per-design breakdown and
  why a pooled number understates how much this moves).
- **49.1% of all generated mutation candidates (84/171) are formally
  proven equivalent to golden — not bugs at all, not silently
  discarded, but caught by a formal filter before ever reaching an
  agent.** A naive mutation-testing benchmark that skipped this step
  would be handing agents non-bugs as its single largest task class
  (see `results/equivalent_mutant_rate.md`).
- **`blocking_nonblocking_swap` — the `=` vs `<=` mistake every Verilog
  textbook warns about — is 95.2% (60/63 evaluated) formally equivalent
  to golden on these four designs.** It's also the single largest
  operator class in the corpus. On this evidence, the bug every
  textbook singles out is usually behaviourally harmless in practice,
  not usually a bug at all.

## 60-second quickstart

```
git clone <this repo>
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on Linux
export RTLVERDICT_OSS_CAD_ROOT=/path/to/oss-cad-suite   # see docs/REPRODUCE.md

python -m rtlverdict.doctor   # every required tool, green or red + a specific remedy
make verify                   # or: python scripts/verify.py
```

`make verify` re-runs the real formal ladder (the identical `check_bmc`
function both `forge/corpus.py` and the agent-verdict path call) on a
fixed 10-task subset, plus one true-fix and one wrong-fix case through
the real agent-verdict path, and diffs every result against a committed
golden file — proving the ladder discriminates a real fix from a wrong
one, not just that the scripts run.

**Measured runtime: 10.6s** (`results/verify_run_report.json`'s
`elapsed_s` field, written fresh by the script itself on every run —
never hand-typed here), against a 5-minute budget. Full accounting of
what it checks and why: `results/verdict_ladder_validation.md`.

## CI

[![CI](https://github.com/Vignesh-Er/rtl_verdict/actions/workflows/ci.yml/badge.svg)](https://github.com/Vignesh-Er/rtl_verdict/actions/workflows/ci.yml)

Not wired up yet — placeholder, will go live in Phase 4.5 if/when a
`make verify`-based workflow is added and goes green. Until then this
badge will 404 or show "no status"; that's expected, not a claim.

## What the three components do

**forge** (`rtlverdict/forge/`) mutates Verilog at exact token
byte-offsets in the original source text (never re-serializes the parse
tree, so fidelity outside the mutated span is guaranteed by
construction, not asserted). Every candidate mutant is formally checked
against golden via bounded model checking before it's ever labeled a
bug — unrefuted mutants are quarantined, not discarded, and never
promoted to "proven equivalent" on a bounded pass alone. The output is
a labeled task corpus with ground truth: `KEEP` (real bug, testbench
catches it), `SILENT` (real bug, testbench misses it), `QUARANTINE`
(formally unrefuted at the depth checked), `ERROR` (never reached
verification).

**witness** (`rtlverdict/witness/`) is an agent debug toolbelt operating
on real Icarus-simulated waveforms: `run_test` reports only the *first*
point where a buggy design's behavior diverges from golden (never a
flood of downstream noise), `wave_query`/`diff_traces` inspect the
trace directly, `cone_of_influence` computes a backward static slice of
every source line that can affect a given signal, and `suspect_rank`
orders that slice by proximity to the divergence. It exists to give an
agent structured evidence instead of a raw simulator log.

**verdict** (`rtlverdict/verdict/`) is the formal gate every proposed
patch — human or agent — passes through. A patch that doesn't parse,
doesn't elaborate, or changes the module's interface is rejected before
any formal check runs at all (`INVALID-PATCH`). A patch that survives
bounded model checking against golden is `PLAUSIBLE` (a bounded claim,
never promoted to an unbounded proof); one BMC finds a genuine
counterexample against is `REFUTED`. `results/verdict_ladder_validation.md`
demonstrates this discriminating on four separate input classes, not
just running.

## Verdict taxonomy

- **`PROVEN-BMC(k)` means bounded model checking searched every step up
  to depth `k` and found no counterexample. It is NOT a proof of
  equivalence** — a counterexample could still exist beyond `k`. Stated
  once, plainly, here: nothing in this project ever treats a bounded
  pass as an unbounded guarantee, anywhere.
- **The same underlying formal result is labeled differently depending
  on which path produced it — deliberately, not by accident.** Forge's
  corpus-generation path surfaces the raw result as `PROVEN-BMC`
  (feeding `forge_decision=QUARANTINE`, a "kept but unrefuted" label).
  The agent-verdict/patch path surfaces the identical raw result as
  `PLAUSIBLE` — see `_FORMAL_TO_VERDICT`,
  [`rtlverdict/agent/loop.py:39`](rtlverdict/agent/loop.py#L39), so a
  reader can verify the mapping in one click. The asymmetry is driven
  by a real difference in the cost of being wrong: a false "equivalent"
  call on the forge path costs one benchmark task, and is independently
  rechecked at 5x the original depth before being trusted at all (the
  `k=200` deep-BMC promotion pass, `results/equivalent_mutant_rate.md`)
  — cheap to catch, cheap to fix. A false "proven correct" call on the
  patch path tells an engineer a broken fix is right — the cost of that
  error is a shipped bug someone was told was fixed. The stricter label
  sits on the higher-stakes path on purpose.
- **`PROVEN-UNBOUNDED` is not producible by any code path in this
  project, currently — forge or agent.** It exists only as a documented,
  not-yet-real ceiling: `verdict/ladder.py`'s `VERDICTS` tuple has
  exactly three values (`REFUTED`, `PROVEN-BMC`, `INDETERMINATE`);
  `PROVEN-UNBOUNDED` is named in that module's own docstring as what
  eqy *would* enable if it were trusted, and deliberately left out of
  the enum until it is (see Limitations, eqy). Documented here rather
  than silently dropped from the vocabulary — see
  `docs/engineering_log.md` episode 12 for how this was verified, not
  assumed.

## Results

- `results/silent_bugs.md` — the 13.6–72.2% silent-bug spread, per
  design and per operator, with the coverage-comparability caveat
  (see Limitations).
- `results/equivalent_mutant_rate.md` — the 49.1% equivalent-mutant
  rate and the k=200 deep-BMC negative-result check behind it.
- `results/verdict_ladder_validation.md` — direct evidence the formal
  gate discriminates a true fix from a wrong one across four input
  classes (`48/48` rows matching expectation).
- `results/agent_pilot.md` — **a plumbing test, not an agent result**
  (see Limitations) — proves the agent harness executes end-to-end,
  resumability works, and hard caps trip correctly.
- `results/corpus_stats.json` — the single generated source every
  number above is read from; regenerate with
  `python scripts/build_stats.py`.
- `docs/engineering_log.md` — eleven cases where a machine-generated
  result looked right and a cheap discriminating test caught it wrong.
- `FINDINGS.md` — the full, dated investigation log everything above
  is drawn from.

## Limitations

Prominent on purpose — a claim's scope is part of the claim.

- **n = 4 designs, all Tier A and self-authored by the same person in
  the same short window.** Tier B (`picorv32`, `nerv`) is not
  integrated — their golden-vs-golden formal check has an unresolved
  divergence after extensive investigation (manual state-alignment,
  a reset-hold sweep, running MCY's own reference miter unmodified —
  all ruled out; root cause not found, see `FINDINGS.md`) — and
  contributes zero tasks to every number above.
- **No live agent run happened.** No API key was available in this
  environment. The full harness (task stratification, `run_task`,
  `check_patch`, `check_bmc`, trajectory writing, resumability, hard
  caps) was validated end-to-end with a deterministic stub standing in
  for the LLM — `results/agent_pilot.md` is explicitly a plumbing test
  proving the wiring works, not an agent capability result. Do not read
  a verdict count or wall-clock figure there as evidence about agent
  debugging ability in either direction.
- **The formal ladder is bounded model checking only, currently, and
  every pass it reports is bounded.** `k=40` for `fsm`/`uart`/`spi_master`,
  `k=25` (with `memory_map`, required for its `mem[]` array) for
  `fifo`. **Neither `PROVEN-BMC` nor `PROVEN-UNBOUNDED` is ever surfaced
  as the verdict on a proposed patch, on any run this project has
  produced.** A bounded pass is always reported `PLAUSIBLE` — the raw
  `PROVEN-BMC` result is recorded internally but deliberately never
  promoted to the headline label, so it never reads as more certain
  than it is. `PROVEN-UNBOUNDED` doesn't exist in the implementation at
  all yet, on any code path (eqy point below) — see
  `results/verdict_ladder_validation.md` §5/§7 for the code-level proof
  of both (63/63 committed patch-path records checked; zero surface
  either string).
- **The coverage-vs-silent-bug-rate relationship was investigated and
  WITHDRAWN, not softened.** The four designs' toggle-coverage
  denominators span 9.4x (20 to 188 toggle points) — far past the point
  where a percentage still means the same thing across designs — so no
  claim, in either direction, is made about coverage predicting or
  failing to predict silent bugs. See `results/silent_bugs.md` §5. A
  withdrawn claim, reported plainly, is a credibility gain over quietly
  dropping the analysis.
- **The COI (cone-of-influence) containment figure was validated once,
  on a superseded corpus, and has not been re-measured on the current
  one.** It is not quoted anywhere in this repo's current results for
  that reason — see `FINDINGS.md`'s "Parked / unquotable" list.
- **Linux and Docker install paths are untested by this project.**
  Developed and validated entirely on Windows 11; `docs/REPRODUCE.md`'s
  Linux steps and the repo-root `Dockerfile` are believed correct by
  inspection only. Update this line if Phase 4.5's CI run ever goes
  green on either.
- **eqy (equivalence checking, the intended second rung of the ladder)
  is disabled for real decisions.** A control test (golden `fsm` vs. a
  gate module with every output hardwired to constant 0 — unmistakably
  non-equivalent) got a confident false `PASS` from eqy's `sat`
  strategy at depth 40. Traced partway into the mechanism (an
  under-populated partition slice interacting with a documented
  vacuity escape) — **the invocation is the suspect, not eqy itself**,
  which is why no upstream issue has been filed. Until understood, BMC
  is the only rung that can make a discard-level claim: BMC-refutes
  always overrides eqy-proves.

## Architecture & layout

```
rtlverdict/
  forge/      mutation generation + the corpus pipeline (parse -> validate -> compile -> sim -> formal)
  witness/    the agent debug toolbelt (run_test, wave_query, diff_traces, cone_of_influence, suspect_rank)
  verdict/    the formal gate (miter construction, the BMC ladder, patch pre-checks)
  agent/      the model-agnostic agent loop, arms A/B, trajectory logging, hard caps
  eval/       coverage parsing (Verilator's raw coverage.dat, DUT-only filtering)
  env.py      toolchain PATH/env setup, the Windows-specific fixes it centralizes
  doctor.py   python -m rtlverdict.doctor
designs/      the 4 Tier A reference designs, each with its own testbench + design.yaml manifest
benchmarks/   generated task corpora (tasks.json) + the verify golden file
results/      every generated report + figure, all traceable to corpus_stats.json
scripts/      build_stats.py, make_charts.py, verify.py, the agent-pilot/ladder-validation harnesses
docs/         REPRODUCE.md, engineering_log.md, paper_skeleton.md, docs/validation/ (historical, labeled)
```

No commercial EDA tool, no FPGA hardware, and no closed-source
dependency appears anywhere in this list.

## Citation

Not published anywhere yet. If you use this work, cite the repository
directly for now:

```bibtex
@software{rtlverdict,
  title  = {rtlverdict: formally-validated RTL bug benchmarks for agent debugging},
  author = {Vignesh-Er},
  url    = {https://github.com/Vignesh-Er/rtl_verdict},
  year   = {2026}
}
```

See `docs/paper_skeleton.md` for the intended related-work positioning
against RTLFixer, HDLdebugger, CraftRTL, UVLLM, HWE-Bench, RealBench,
and AssertLLM2.
