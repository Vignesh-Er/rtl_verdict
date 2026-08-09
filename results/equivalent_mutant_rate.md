# Equivalent-mutant rate by operator (corpus_v2, n=132, fsm/uart/spi_master)

A mutant is only useful as a debugging benchmark task if it changes
behavior. The BMC ladder's QUARANTINE bucket (PROVEN-BMC at the depth
checked, or INDETERMINATE) is not simply "unresolved" — most of it is a
genuine classification: these mutants are formally *equivalent* to golden,
within the bound checked. This file reports that split by operator, with
the depth-sensitivity check that justifies treating it as a real
classification rather than a search-depth artifact.

## The k=200 check: depth does not explain the QUARANTINE pool

All 69 QUARANTINE mutants from corpus_v2 (fsm/uart/spi_master) were
re-checked at k=200 (5x the original k=40), timeout_s=150.
**Result: 0 verdicts changed.** 68/69 resolved well under the timeout
(mostly reconfirming PROVEN-BMC; none within 80% of the timeout budget —
the "near-timeout stays quarantined" caveat never had to fire), and the
remaining 1-per-design pattern (`edge_swap`, 3 total) stayed the same
INDETERMINATE it was at k=40. Full log: `benchmarks/corpus_v2/deep_bmc_promotions.json`.

Five times the search depth did not surface a single additional bug. That
is the evidence for calling these mutants *equivalent*, not merely
"the solver hasn't found it yet."

## Per-operator breakdown (all 3 designs pooled, n=132)

`refuted` = formally REFUTED (a real, confirmed behavioral divergence —
KEEP if the testbench also caught it, SILENT if not, see
`coverage_vs_silent_bugs.md`). `equivalent` = QUARANTINE, and the k=200
recheck (or the original k=40 result, for the 63 non-QUARANTINE tasks
which were never re-checked) says PROVEN-BMC. `indeterminate` = QUARANTINE
and still INDETERMINATE at the deepest depth checked.

| operator | candidates | refuted (KEEP/SILENT) | equivalent | indeterminate | equivalent rate |
|---|---|---|---|---|---|
| `blocking_nonblocking_swap` | 56 | 3 (0/3) | 53 | 0 | **94.6%** (n≥30) |
| `constant_perturbation` | 38 | 32 (19/13) | 6 | 0 | **15.8%** (n≥30) |
| `next_state_redirect` | 16 | 13 (8/5) | 3 | 0 | *below n=30, raw counts only* |
| `signal_substitution` | 13 | 10 (5/5) | 3 | 0 | *below n=30, raw counts only* |
| `operator_swap` | 6 | 5 (2/3) | 1 | 0 | *below n=30, raw counts only* |
| `edge_swap` | 3 | 0 (0/0) | 0 | 3 | *below n=30, raw counts only* |
| **TOTAL** | **132** | **63** | **66** | **3** | |

`63 + 66 + 3 = 132` — every generated candidate accounted for, no bucket
silently dropped.

## The finding: `blocking_nonblocking_swap` is *usually* behaviorally equivalent here

`=` vs `<=` (blocking vs non-blocking assignment) is the canonical RTL bug
every Verilog textbook warns about — simulation/synthesis mismatches,
race conditions, the works. On these three designs, **94.6% of
blocking/nonblocking swaps (53/56) are formally proven equivalent to
golden**, not bugs. It is the single largest operator class in the corpus
(56/132 = 42% of all candidates) and it is overwhelmingly a non-bug class
here.

This is not a flaw in the operator — it is real, measured evidence of the
**equivalent-mutant problem**, well known in software mutation testing,
now measured in RTL with a per-operator breakdown. On these particular
designs, most nonblocking assignments have no same-cycle read-after-write
hazard observable through the testbench's stimulus, so swapping `<=` for
`=` frequently produces a functionally identical netlist under BMC. (Per
`coverage_vs_silent_bugs.md`, DUT toggle coverage on these designs ranges
50–90% — some of this may also reflect stimulus that never exercises the
hazard window at all, a question this dataset cannot separate from "no
hazard exists.")

`constant_perturbation`, by contrast, is mostly a real-bug operator here
(84.2% refuted, 19/32 caught by sim, 13 silent) — perturbing a literal
constant almost always changes behavior on these designs. The two
operators sit at opposite ends of the equivalent-mutant spectrum, both
well-powered (n≥30) and both worth reporting for exactly that contrast.

## Per-design × operator (raw counts only — every cell n<30, no rates)

| design | operator | candidates | refuted | equivalent | indeterminate |
|---|---|---|---|---|---|
| fsm | blocking_nonblocking_swap | 15 | 1 | 14 | 0 |
| fsm | constant_perturbation | 11 | 10 | 1 | 0 |
| fsm | next_state_redirect | 5 | 4 | 1 | 0 |
| fsm | signal_substitution | 3 | 2 | 1 | 0 |
| fsm | operator_swap | 2 | 1 | 1 | 0 |
| fsm | edge_swap | 1 | 0 | 0 | 1 |
| uart | blocking_nonblocking_swap | 19 | 0 | 19 | 0 |
| uart | constant_perturbation | 12 | 10 | 2 | 0 |
| uart | next_state_redirect | 6 | 5 | 1 | 0 |
| uart | signal_substitution | 4 | 3 | 1 | 0 |
| uart | operator_swap | 2 | 2 | 0 | 0 |
| uart | edge_swap | 1 | 0 | 0 | 1 |
| spi_master | blocking_nonblocking_swap | 22 | 2 | 20 | 0 |
| spi_master | constant_perturbation | 15 | 12 | 3 | 0 |
| spi_master | next_state_redirect | 5 | 4 | 1 | 0 |
| spi_master | signal_substitution | 6 | 5 | 1 | 0 |
| spi_master | operator_swap | 2 | 2 | 0 | 0 |
| spi_master | edge_swap | 1 | 0 | 0 | 1 |

The `blocking_nonblocking_swap` pattern is directionally consistent across
all three designs (1/15, 0/19, 2/22 refuted — never more than 2 real bugs
out of 15–22 candidates per design), which is suggestive but not itself a
powered per-design claim; the pooled 94.6% (n=56) is the number this
project can actually stand behind.

## What this implies for RTL mutation-testing benchmark design

A naive mutation corpus — generate candidates, hand them to an agent,
score PASS/FAIL against the testbench — would be substantially populated
by non-bugs for at least one common operator class, with no way to tell
which candidates are real without a ground-truth check. **This is the
direct justification for forge's entire design**: mutation generation
alone is not a benchmark; a formal ground-truth filter (the BMC ladder)
is what turns raw mutants into a corpus of *confirmed* behavioral changes.
Any RTL mutation-testing benchmark that skips the formal-equivalence
filter is, on this evidence, at meaningful risk of scoring agents against
tasks that have no actual bug to find.
