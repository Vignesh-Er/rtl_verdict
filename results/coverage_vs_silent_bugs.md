# Silent-bug rate vs. testbench coverage (real n, corpus_v2)

`corpus_v2`: 132 candidates generated across fsm/uart/spi_master, all 6
operators (LOGIC: operator_swap, constant_perturbation; TIMING:
blocking_nonblocking_swap, edge_swap; SIGNAL: signal_substitution; FSM:
next_state_redirect). 132 distinct (0 duplicates), 132 recorded (0 errors).
34 KEEP, 69 QUARANTINE, 29 SILENT (34+69+29=132, accounting verified).

## Coverage (DUT-only, Verilator `--coverage-line --coverage-toggle`)

| design | line | toggle | branch | expr |
|---|---|---|---|---|
| fsm | 4/5 (80.0%) | 18/20 (90.0%) | 6/6 (100.0%) | 2/2 (100.0%) |
| uart | 5/6 (83.3%) | 26/52 (50.0%) | 6/6 (100.0%) | 2/2 (100.0%) |
| spi_master | 4/5 (80.0%) | 38/56 (67.9%) | 8/8 (100.0%) | 4/4 (100.0%) |

## Silent-bug counts (KEEP = caught by sim, SILENT = formally proven but sim missed it)

| design | KEEP | SILENT | n (KEEP+SILENT) | rate |
|---|---|---|---|---|
| fsm | 5 | 13 | 18 | *below n=30, raw counts only* |
| uart | 17 | 3 | 20 | *below n=30, raw counts only* |
| spi_master | 12 | 13 | 25 | *below n=30, raw counts only* |
| **aggregate (all 3 designs)** | **34** | **29** | **63** | **46.0% (29/63)** |

## Honest conclusion: the per-design correlation claim is still untestable

Per the stated rule (no rate below n=30 per design), **none of the three
designs individually reach the threshold even at 132 total candidates and
63 KEEP+SILENT tasks.** fsm sits at n=18, uart at n=20, spi_master at n=25 -
closer than the original 20-task corpus (n=8/n=9), but still short.

This means the original hypothesis this file was built to test - "does
higher DUT toggle coverage correlate with a lower silent-bug rate" - **is
not yet answerable with statistical honesty at this corpus size**, even
after a 6.6x scale-up. Per-design rates would need roughly another 1.5-2x
more KEEP+SILENT tasks each to cross n=30 (fsm needs 13-17 more within
that bucket, uart 10+, spi_master 5+) - noting that scaling candidate count
does not scale KEEP+SILENT proportionally, since a large fraction land in
QUARANTINE (69/132 = 52.3% this run).

**What IS defensible at this corpus size**: the pooled, aggregate
silent-bug rate across all three designs combined - **46.0% (29/63)** - a
formally-proven, non-equivalent mutant slipped past hand-written
self-checking testbenches on Verilog-2005 peripherals almost half the
time. This is a real, well-powered (n=63) finding on its own, independent
of any coverage-correlation claim - it just doesn't yet tell us WHY
per-design, only THAT it happens.

**What is NOT yet claimed**: that fsm's specific mix of coverage numbers
predicts its specific silent-bug count relative to uart's or spi_master's.
That claim needs more n per design, not more designs or more total
candidates - future work should bias mutation generation toward filling
KEEP+SILENT per design (e.g. more constant_perturbation/signal_substitution
candidates, which produced the SILENT-heaviest results this run) rather
than generating uniformly across all six operators.

## Operator-class SILENT rate (informative, still small-n per cell, not interpreted as a rate)

Raw counts of SILENT outcomes by operator, across all three designs:
constant_perturbation and signal_substitution/next_state_redirect produced
most of this run's 29 SILENT tasks; blocking_nonblocking_swap and
operator_swap produced few (most of that class's non-refuted candidates
landed in QUARANTINE via PROVEN-BMC instead). Not broken out per-design-
per-operator here - that's an n=3-5-per-cell table, well below any
interpretable threshold; recorded as raw task-level data in
`benchmarks/corpus_v2/tasks.json` for anyone who wants to slice it further.

## Also observed: every edge_swap candidate (3/3, one per design) returned INDETERMINATE

Not SILENT, not KEEP - the BMC ladder could not reach a verdict within the
60s timeout for the one edge_swap (posedge<->negedge) candidate generated
per design. Correctly quarantined (degraded-mode policy: INDETERMINATE
never becomes a discard or a claim), but worth flagging as a real,
consistent operator-specific pattern: swapping a clock edge changes what
the two miter instances are even synchronized on, which plausibly makes
BMC's search space much larger. Not investigated further this session -
tracked as an open item, same as picorv32 and the eqy invocation.
