# Equivalent mutants: why forge's formal filter exists

All numbers in this document are read from `results/corpus_stats.json`
(fsm, uart, spi_master, fifo — 171 generated tasks). Regenerate with
`python scripts/build_stats.py`.

## Headline

**49.1% of all generated mutants (84/171) are QUARANTINE — not bugs,
not silently discarded, but formally unrefuted at the depth checked.**
Nearly half of everything a naive mutation-based benchmark would hand an
agent as "a bug to fix" is not a bug at all.

**And the single largest operator class is *usually* equivalent, not
buggy: `blocking_nonblocking_swap` — the `=` vs `<=` mistake every
Verilog textbook warns about — is 95.2% (60/63 evaluated) formally
equivalent to golden on these four designs.** It is also the largest
operator by candidate count (65/171, 38% of the whole corpus). A
benchmark that generated this operator's mutants and shipped them
without a formal filter would be shipping non-bugs as its single biggest
bug class.

## The k=200 check: depth does not explain the QUARANTINE pool

All 69 QUARANTINE mutants from fsm/uart/spi_master (the three designs
with no memories — fifo's own quarantine pool sits at a lower k for a
different, documented reason, see below) were re-checked at k=200 — 5x
the original k=40 — timeout 150s.

**Result: 0 verdicts changed.** 66/69 reconfirmed PROVEN-BMC comfortably
under the 150s timeout (none within 80% of the timeout budget), and 3
(`edge_swap`, one per design) stayed the same INDETERMINATE they were at
k=40.

Five times the search depth surfaced zero additional bugs. **That is
the evidence these mutants are equivalent, not merely "the solver
hasn't found it yet"**: if depth alone explained the QUARANTINE pool, a
5x-deeper search on the exact same mutants would be expected to refute
at least some of them. It refuted none. Full log:
`benchmarks/corpus_v2/deep_bmc_promotions.json`.

fifo's own QUARANTINE pool (15 mutants, k=25) was **not** re-checked at
deep k — its `memory_map`-required BMC ladder is already near its
practical ceiling at k=25 (SMT array-theory blowup on `mem[]`; k=40
alone does not reliably complete even with `memory_map`, see
FINDINGS.md's Day-9 pivot section) — deepening it further was not
attempted and is not claimed.

## Per-operator equivalence rate (n≥30 only)

`equivalent %` = QUARANTINE / (candidates − ERROR). ERROR candidates
never reached formal verification at all (rejected earlier by the
fidelity guard) and are excluded from both numerator and denominator —
they are neither confirmed bugs nor confirmed equivalent.

| operator | candidates | evaluated (n) | equivalent | equivalent % |
|---|---|---|---|---|
| `blocking_nonblocking_swap` | 65 | 63 | 60 | **95.2%** |
| `constant_perturbation` | 40 | 40 | 6 | **15.0%** |
| `operator_swap` | 22 | 22 | 7 | 31.8% *(n<30, raw counts only)* |
| `next_state_redirect` | 16 | 16 | 3 | 18.8% *(n<30, raw counts only)* |
| `signal_substitution` | 24 | 24 | 4 | 16.7% *(n<30, raw counts only)* |
| `edge_swap` | 4 | 4 | 4 | 100% *(n=4; all 4 are INDETERMINATE, not a confirmed-equivalent proof — see below)* |

Two operators reach n≥30: `blocking_nonblocking_swap` (95.2% equivalent)
and `constant_perturbation` (15.0% equivalent, i.e. mostly real bugs —
perturbing a literal constant almost always changes behavior on these
designs). They sit at opposite ends of the equivalent-mutant spectrum,
both well-powered.

**`edge_swap`'s 100% is not the same kind of claim as the others.** All
4 `edge_swap` candidates (one per design in the k=40 corpus, none
generated for fifo) are QUARANTINE via `INDETERMINATE`, not `PROVEN-BMC`
— the ladder could not reach a verdict within the BMC timeout at all, at
either k=40 or k=200. Swapping a clock edge changes what the miter's two
instances are even synchronized on, which plausibly explodes BMC's
search space. This is a real, consistent, unexplained pattern — flagged
as an open item, not investigated further here, and never counted as
"confirmed equivalent" in the headline or the k=200 discussion above.

## What this implies for RTL mutation-testing benchmark design

A naive mutation corpus — generate candidates, hand them to an agent,
score PASS/FAIL against the testbench — would be **49.1% populated by
non-bugs** on this corpus, concentrated almost entirely in one operator
class (`blocking_nonblocking_swap`, 95.2% equivalent). There is no way
to tell which candidates are real without a ground-truth check. **This
is the direct justification for forge's design**: mutation generation
alone is not a benchmark; a formal ground-truth filter (the BMC ladder)
is what turns raw mutants into a corpus of *confirmed* behavioral
changes. Any RTL mutation-testing benchmark that skips the
formal-equivalence filter is, on this evidence, at meaningful risk of
scoring agents against tasks that have no bug to find.
