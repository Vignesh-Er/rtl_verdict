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

**Before reading anything else in this section: the four designs'
toggle-coverage denominators are not comparable to each other.** The
total number of toggle points a design exposes is fsm=20, uart=52,
spi_master=56, fifo=188 — the largest denominator (fifo) is **9.4x**
the smallest (fsm), well past the ~3x span where a percentage still
means roughly the same thing across designs. fsm's 90.0% is 18/20 — an
18-point granularity where missing or gaining a single toggled signal
moves the percentage by 5 points. fifo's 43.6% is 82/188 — a far finer
granularity, much more stable to any single signal's behavior. **A
cross-design comparison of these four percentages is not a like-for-like
comparison; it is comparing a coarse 20-bucket measurement against a
fine 188-bucket one and reading the difference as if both had the same
precision.** Any pattern described below inherits this limitation and
should be read as suggestive at most, not as a controlled comparison.

With that caveat stated, the four (DUT-only toggle coverage, silent %)
points, sorted by coverage denominator alongside the raw counts behind
each percentage:

| design | toggle: hit/total (denominator) | DUT-only toggle cov | silent %: SILENT/n (denominator) |
|---|---|---|---|
| fsm | 18/**20** | 90.0% | 13/**18** — 72.2% |
| spi_master | 38/**56** | 67.9% | 13/**25** — 52.0% |
| uart | 26/**52** | 50.0% | 3/**20** — 15.0% |
| fifo | 82/**188** | 43.6% | 3/**22** — 13.6% |

Secondary observation, offered with the above caveat firmly attached:
**the four points happen to move monotonically** — the design with the
highest toggle coverage also has the highest silent-bug rate, and the
design with the lowest coverage has the lowest silent rate. That is the
opposite of the hopeful reading ("more coverage means the testbench
catches more of what it toggles"). At n=4, this exact ordering is one of
**24 possible orderings** of 4 items; exactly **2 of the 24** are
perfectly monotone (fully ascending or fully descending). An ordering
this clean arises by chance with **p = 0.083** (exact two-sided
permutation test; equivalent to Spearman rank correlation = 1.0 at
n = 4) — see
`corpus_stats.json`'s `silent_bug_rate.coverage_rank_correlation`. **This
is suggestive, not evidence** — p=0.083 does not clear a conventional
significance threshold even before accounting for the denominator
problem above, and n=4 is too small for a correlation claim regardless
of the p-value. It is reported because it is the honest strength of the
pattern, not because it settles anything. See §5.1 for whether this
pattern is even about coverage at all, as opposed to which design it
happens to be.

What toggle coverage cannot see, mechanically, independent of the above:
it measures whether a signal *changed value* during simulation, not
whether a mutation's behavioral effect *propagated to a checked output*.
A design can toggle a signal on every cycle and never assert anything
about it. This dataset does not have the instrumentation to separate
"the testbench never exercised the divergence" from "the testbench
exercised it and checked the wrong thing" — both produce SILENT, and
toggle coverage alone cannot tell them apart. That gap is exactly why
this project measures silent-bug rate directly by formal proof, rather
than trusting coverage as a proxy for testbench quality.

## 5.1 Is this a design-class artifact?

Two hypotheses are consistent with §5's monotonic pattern, and this
corpus cannot cleanly separate them:

- **Hypothesis A (general):** toggle coverage does not predict
  bug-catching power, as a property of the *method*, independent of
  which design is being measured. If true, the same pattern should
  reappear on new designs of any size or shape.
- **Hypothesis B (design-class artifact):** fsm specifically is small
  (`dut_signal_count=7`, `cell_count=29` — the smallest of all four
  designs on both measures, see `corpus_stats.json`'s `designs[]`) and
  control-heavy. On a small state machine, toggle coverage saturates
  quickly (most signals *do* toggle in a short simulation) while the
  testbench's actual assertions remain blind to specific state-transition
  bugs — so design class drives both the high coverage number *and* the
  high silent rate independently, and the two are correlated with each
  other only because they're both correlated with "being fsm," not
  because coverage causes or predicts silence.

**To test between them, the per-operator silent rate *within* each
design** (from `corpus_stats.json`'s `silent_rate_by_design_operator`)
is the relevant evidence — hypothesis B predicts fsm's elevated silent
rate should concentrate in state-transition-touching operators
(`next_state_redirect`, `blocking_nonblocking_swap`) rather than being
uniform across operator classes:

| operator | fsm | uart | spi_master | fifo |
|---|---|---|---|---|
| `constant_perturbation` | 70.0% (7/10) | 10.0% (1/10) | 41.7% (5/12) | 0.0% (0/2) |
| `next_state_redirect` | 75.0% (3/4) | 20.0% (1/5) | 25.0% (1/4) | — (not generated) |
| `blocking_nonblocking_swap` | 100% (1/1) | — (0 real bugs) | 100% (2/2) | — (0 real bugs) |
| `signal_substitution` | 50.0% (1/2) | 33.3% (1/3) | 60.0% (3/5) | 10.0% (1/10) |
| `operator_swap` | 100% (1/1) | 0.0% (0/2) | 100% (2/2) | 20.0% (2/10) |

**This does not cleanly support either hypothesis.** If B were true,
fsm's silent rate should be concentrated in the state-transition
operators and closer to the other designs' rates on non-state-touching
operators like `constant_perturbation`. It is not: fsm's
`constant_perturbation` rate (70.0%) is itself the highest of any design
on that operator — elevated even where hypothesis B predicts it
shouldn't be. That leans toward A (a general property of this design,
not concentrated in state logic). But every one of fsm's per-operator
cells has n≤10, several are n=1 or n=2 (100% on a single candidate is
not a rate, it's one data point), and fifo has no `next_state_redirect`
candidates at all and zero real bugs on `blocking_nonblocking_swap`
(0/9 evaluated) — there is no fifo data point to compare fsm's
state-transition operators against on two of the four rows. The cell
counts are too small at this granularity to distinguish "elevated
everywhere" from "elevated on the few operators that happened to get
generated." **This is genuinely
ambiguous at the current sample size. Reporting it as leaning toward one
hypothesis over the other would be overclaiming what four small designs
and per-cell counts as low as 1 can support.**

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
