# Silent bugs: what a passing testbench misses

All numbers in this document are read from `results/corpus_stats.json`
(commit `f86778d`-and-later corpus: fsm, uart, spi_master, fifo — 171
generated tasks). Regenerate with `python scripts/build_stats.py`.

## 1. Claim

**Across 4 designs, 13.6–72.2% of formally-proven real bugs pass the
design's own testbench. The rate varies 5.3x by design.**

There is no single "the silent-bug rate" for this method — there is a
per-design rate, and it moves by more than 5x depending on which design's
testbench is being asked the question.

## 2. Definition

- **SILENT** = a mutant the formal ladder (BMC) proves is a real
  behavioral divergence from golden, where the design's own testbench
  still reports sim **PASS**.
- **Denominator = KEEP + SILENT** ("real bugs" — every mutant formally
  confirmed to actually change behavior), **not** total generated.
- **QUARANTINE is excluded** because the formal ladder could not refute
  it (a bounded `PROVEN-BMC(k)` pass, or `INDETERMINATE`) — it is not a
  confirmed bug, so it cannot be confirmed *silent* or *caught* either.
- **ERROR is excluded** because those candidates never reached simulation
  or formal verification at all — rejected earlier by the fidelity guard
  — so no behavioral claim, silent or otherwise, can be made about them.

## 3. Primary table

| design | tier | LOC | formal k | KEEP | SILENT | real bugs (n) | silent % | DUT-only toggle cov |
|---|---|---|---|---|---|---|---|---|
| fsm | A | 45 | 40 | 5 | 13 | 18 | **72.2%** | 90.0% (18/20) |
| uart | A | 53 | 40 | 17 | 3 | 20 | **15.0%** | 50.0% (26/52) |
| spi_master | A | 58 | 40 | 12 | 13 | 25 | **52.0%** | 67.9% (38/56) |
| fifo | A | 39 | **25** | 19 | 3 | 22 | **13.6%** | 43.6% (82/188) |

fifo's `formal_k=25` (not 40) — its own quarantine bound is weaker than
the other three designs', see §7. That difference travels with the data
in `corpus_stats.json`, never pooled silently with the k=40 designs.

## 4. Pooled figure

**Pooled: 32/85 = 37.6%.** This averages four designs whose rates differ
by ~5.3x (13.6%–72.2%) with n=18–25 each. It is reported once, here, for
comparability with prior work — not as a stable estimate of anything.
Do not quote 37.6% as *the* rate; quote the range, or a specific design.

## 5. Coverage confound

The four (DUT-only toggle coverage, silent %) points, sorted by coverage:

| design | DUT-only toggle cov | silent % |
|---|---|---|
| fsm | 90.0% | 72.2% |
| spi_master | 67.9% | 52.0% |
| uart | 50.0% | 15.0% |
| fifo | 43.6% | 13.6% |

**These move together, monotonically, across all four points: the
design with the highest toggle coverage also has the highest silent-bug
rate, and the design with the lowest coverage has the lowest silent
rate.** That is the opposite of the hopeful reading ("more coverage
means the testbench catches more of what it toggles"). With n=4, no
correlation coefficient or p-value is computed or appropriate — four
points is a description, not a statistical test — but the pattern is
consistent enough across every point, not just the extremes, to say
plainly: **in this sample, DUT-only toggle coverage does not predict a
*safer* testbench, and coverage partly explains the spread in §4's
pooled rate.** The pooled 37.6% is, in part, a function of which
designs (and whose toggle-coverage profile) happened to be in the
sample, not a fixed property of the method.

What toggle coverage cannot see, mechanically: it measures whether a
signal *changed value* during simulation, not whether a mutation's
behavioral effect *propagated to a checked output*. A design can toggle
a signal on every cycle and never assert anything about it. This dataset
does not have the instrumentation to separate "the testbench never
exercised the divergence" from "the testbench exercised it and checked
the wrong thing" — both produce SILENT, and toggle coverage alone cannot
tell them apart. That gap is exactly why this project measures
silent-bug rate directly by formal proof, rather than trusting coverage
as a proxy for testbench quality.

## 6. Per-operator breakdown (across the whole corpus)

| operator | KEEP | SILENT | real bugs (n) | silent % |
|---|---|---|---|---|
| `constant_perturbation` | 21 | 13 | 34 | **38.2%** (n≥30) |
| `signal_substitution` | 14 | 6 | 20 | 30.0% *(n<30, raw counts only)* |
| `next_state_redirect` | 8 | 5 | 13 | 38.5% *(n<30, raw counts only)* |
| `operator_swap` | 10 | 5 | 15 | 33.3% *(n<30, raw counts only)* |
| `blocking_nonblocking_swap` | 0 | 3 | 3 | 100% *(n=3, not interpretable)* |
| `edge_swap` | 0 | 0 | 0 | — *(0 confirmed bugs; all 4 candidates quarantined)* |

Only `constant_perturbation` reaches n≥30. Its 38.2% is close to the
pooled 37.6% almost by coincidence of corpus composition (it is the
largest real-bug-producing operator, 34/85 = 40% of the denominator) —
not independent corroboration.

## 7. Threats to validity

- **n=4 designs.** All Tier A, all self-authored by the same person in
  the same short window. Tier B (picorv32, nerv) is not yet integrated
  into this pipeline (golden-vs-golden formal check unresolved — see
  FINDINGS.md) and contributes nothing here.
- **Testbench quality is a confound and varies across the sample.**
  These are four different testbenches, of different rigor, written by
  the same author. §5's coverage pattern is evidence of exactly this:
  the rate is not a fixed property of the method, it moves with which
  testbench is being asked.
- **`PROVEN-BMC(k)` is a bounded claim, not an unbounded proof — this
  affects which mutants a design's QUARANTINE pool contains, and
  therefore how many mutants were even eligible to become KEEP/SILENT.**
  k=40 for fsm/uart/spi_master, k=25 for fifo (weaker bound, see §3 and
  FINDINGS.md's Day-9 pivot section on why).
- **fsm (72.2%, n=18) drives much of the pooled figure.** Excluding fsm
  entirely: 19/67 = **28.4%** (down from 37.6%). fsm is not an outlier
  being discarded here — it's reported, in full, in §3 — but its
  influence on the single pooled number should be visible, not hidden.
- **Toggle coverage was corrected from raw to DUT-only** (uart: raw
  39/98 = 39.8% → DUT-only 26/52 = 50.0% — the raw figure is deflated by
  testbench-internal declared-but-unused variables that never toggle).
  Every coverage figure in this document is DUT-only; it is not
  comparable to a raw coverage number from another tool or another
  project without the same correction.

## 8. Why it matters

A testbench that reports 100% pass on a mutation-tested design is not
evidence the design is correct — on this data, it can be missing more
than 7 in 10 formally-confirmed real bugs, and *which* fraction it
misses depends on the design, not on a fixed rate anyone can quote once.
