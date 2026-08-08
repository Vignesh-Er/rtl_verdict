# COI containment rate by operator class

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
