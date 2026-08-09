<!-- stats-scope: historical, corpus=15539b0f928ece4b050084ed3c8933bd1a7905cd, date=2026-08-08T17:39:57Z -->

# COI containment rate by operator class

**Historical validation record - not a live figure.** Measured against the
`probe_signal_fsm` probe corpus (21 candidates, SIGNAL+FSM operators only),
a corpus superseded by corpus_v2 + the fifo addition before this file was
relocated here. The 10/10 below does not describe the current 171-task
corpus and must not be quoted as if it did - see
`results/corpus_stats.json` for current corpus figures instead.

Probe run (per your instruction: test the two hardest classes on a small
sample BEFORE scaling, not after). 21 candidates generated (SIGNAL + FSM
operators only, 7 each across fsm/uart/spi_master), 0 duplicates. 10 KEEP
tasks resulted; containment measured on all 10 via witness's own run_test
(real simulation-detected diverging signal, not the formal ladder's).

| operator class | contained | total | rate |
|---|---|---|---|
| signal_substitution | 5 | 5 | 100.0% |
| next_state_redirect | 5 | 5 | 100.0% |
| **overall** | **10** | **10** | **100.0%** |

Gate (>=95%): **PASS**. The control-dependency slicing fix (FINDINGS.md,
docs/coi_soundness.md) generalizes correctly to both predicted hard cases:
SIGNAL substitution (root cause is a READ site, different graph path than
every previously-tested operator) and FSM next-state redirect (nested
inside a case item - the exact structural pattern the original bug was in).
