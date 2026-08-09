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

**The "DUT-only toggle cov" column is descriptive context only — it is
not comparable across rows.** The four designs' toggle-point
denominators span 9.4x (20 to 188); see §5 for why this column cannot
support any cross-design coverage comparison or any coverage-vs-silence
relationship claim.

## 4. Pooled figure

**Pooled: 32/85 = 37.6%.** This averages four designs whose rates differ
by ~5.3x (13.6%–72.2%) with n=18–25 each. It is reported once, here, for
comparability with prior work — not as a stable estimate of anything.
Do not quote 37.6% as *the* rate; quote the range, or a specific design.

## 5. Toggle coverage is not comparable across these four designs (claim withdrawn)

An earlier draft of this document reported that DUT-only toggle
coverage and silent-bug rate move together monotonically across the
four designs (an exact permutation p=0.083). **That claim is withdrawn,
not softened to "ambiguous."** The reason is the toggle-coverage
denominators themselves — the total number of toggle points each
design exposes:

| design | toggle points (denominator) |
|---|---|
| fsm | 20 |
| uart | 52 |
| spi_master | 56 |
| fifo | 188 |

fifo's denominator (188) is **9.4x** fsm's (20) — far past the ~3x span
within which a percentage still means roughly the same thing across
designs. fsm's 90.0% toggle coverage is 18/20: an 18-point granularity
where missing or gaining a single toggled signal moves the percentage
by 5 points. fifo's 43.6% is 82/188: a far finer granularity, much more
stable to any single signal's behavior. Comparing these four
percentages to each other is comparing a coarse 20-bucket measurement
to a fine 188-bucket one and treating the difference as if both had the
same precision. They do not.

**Consequence: no coverage-vs-silence relationship is claimed here, in
either direction.** Not "coverage predicts silence," not "coverage
fails to predict silence" — the metric that either claim would rest on
is not comparable across this sample. §5.1's per-operator table
(originally framed as a test between two explanatory hypotheses) has
been reframed accordingly: neither hypothesis was testable against a
metric that isn't comparable at this size spread, so the hypotheses are
dropped as conclusions and the underlying data is kept only as raw,
descriptive transparency.

This is also worth stating as a methodological observation independent
of this corpus: **DUT-only toggle-coverage percentage is not a
size-normalized metric, and comparing it across designs whose raw
toggle-point counts differ by nearly an order of magnitude is not
meaningful**, regardless of what project produces the numbers. Making a
cross-design coverage comparison defensible would require a
size-normalized metric — e.g. a per-design normalized/scaled coverage
score, or a coverage measure with a fixed-cardinality denominator. This
project did not have one and did not construct one; that gap is flagged
here as unaddressed future work, not resolved by this document.

What toggle coverage cannot see, mechanically — a separate, standing
limitation, independent of the comparability problem above: it measures
whether a signal *changed value* during simulation, not whether a
mutation's behavioral effect *propagated to a checked output*. A design
can toggle a signal on every cycle and never assert anything about it.
This dataset does not have the instrumentation to separate "the
testbench never exercised the divergence" from "the testbench exercised
it and checked the wrong thing" — both produce SILENT, and toggle
coverage alone cannot tell them apart. That gap is exactly why this
project measures silent-bug rate directly by formal proof rather than
trusting coverage as a proxy for testbench quality — a reason to
measure silent rate independently of coverage that holds even before
the comparability problem above.

## 5.1 Per-operator silent rate within each design (descriptive only, not a test of anything)

Kept for transparency, not as evidence for or against any explanation
of why silent rate varies by design — §5's coverage-based hypotheses
are withdrawn, and this table does not stand in for them or resolve
anything on its own. It answers only a narrower, descriptive question:
within each design, is the silent rate spread evenly across operator
classes, or concentrated in a few?

| operator | fsm | uart | spi_master | fifo |
|---|---|---|---|---|
| `constant_perturbation` | 70.0% (7/10) | 10.0% (1/10) | 41.7% (5/12) | 0.0% (0/2) |
| `next_state_redirect` | 75.0% (3/4) | 20.0% (1/5) | 25.0% (1/4) | — (not generated) |
| `blocking_nonblocking_swap` | 100% (1/1) | — (0 real bugs) | 100% (2/2) | — (0 real bugs) |
| `signal_substitution` | 50.0% (1/2) | 33.3% (1/3) | 60.0% (3/5) | 10.0% (1/10) |
| `operator_swap` | 100% (1/1) | 0.0% (0/2) | 100% (2/2) | 20.0% (2/10) |

Every cell states its own n as the second number in the fraction. At
n≤10 per cell — several cells are n=1 or n=2, and two of fsm's rows
have no fifo counterpart to compare against at all (fifo generated no
`next_state_redirect` candidates, and its `blocking_nonblocking_swap`
candidates produced zero real bugs, 0/9 evaluated) — **no
operator-level comparison is possible from this table, within a design
or across designs.** It is included as raw data for anyone extending
this corpus, not as a finding.

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
  the same author, and the silent rate itself (§1/§3) already shows
  this: it is not a fixed property of the method, it moves by 5.3x with
  which testbench is being asked. (An earlier draft additionally cited
  a toggle-coverage pattern as evidence of this — that citation is
  withdrawn, see §5; the point about testbench-quality variation stands
  on the silent-rate spread alone, without needing coverage as support.)
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
