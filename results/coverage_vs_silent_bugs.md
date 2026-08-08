# Silent-bug rate vs. testbench coverage

**Status: preliminary data, n too small to interpret. Recorded as a
methodology check and a first data point, not a finding.** Minimum n for
any rate to be reported as a percentage is 30 per design; below that, raw
counts only, no percentage, no claim. `corpus_v1` currently has 10
candidates per design (LOGIC + TIMING operator classes only) - this file
gets re-run and rewritten once the corpus scales past that threshold.

## Coverage measurement

Verilator `--coverage --coverage-line --coverage-toggle`. `verilator_coverage`
(the bundled analysis tool) is a Perl script requiring `Pod::Usage`,
unavailable in this environment - parsed the raw `coverage.dat` format
directly instead (`rtlverdict/eval/coverage.py`).

**Correction from the first pass of this measurement**: the initial numbers
(fsm 90.0% toggle, uart 39.8% toggle) counted every signal in the compiled
unit, including ones declared inside the testbench itself and never used
(e.g. `tb_uart.v` declares a `captured` register that nothing ever assigns -
33 of uart's 59 zero-toggle entries were testbench-internal noise, not DUT
signals). Filtering to DUT-only source lines changes uart's toggle number
materially: **50.0% (26/52), not 39.8% (39/98).** `parse_coverage_dat` now
takes a `dut_file` argument and always filters; report the unfiltered number
never again.

| design | line cov | toggle cov (DUT-only) | branch cov | expr cov |
|---|---|---|---|---|
| fsm  | 4/5 (80.0%) | 18/20 (90.0%) | 6/6 (100.0%) | 2/2 (100.0%) |
| uart | 5/6 (83.3%) | 26/52 (50.0%) | 6/6 (100.0%) | 2/2 (100.0%) |

## Spot-check: are uart's zero-toggle DUT signals genuinely uncoverable, or a measurement artifact?

Picked 5 of the 26 DUT-side zero-toggle entries and traced each by hand
against `tb_uart.v`'s actual stimulus:

| signal | line | transition | why it didn't toggle |
|---|---|---|---|
| `tx_data[1]` | 5 | (constant) | testbench sets `tx_data = 8'hA5` exactly once; bit 1 of `0xA5` is 0, and no second value is ever sent, so this bit is never demonstrated as 1 |
| `tx_data[3]` | 5 | (constant) | same cause - bit 3 of `0xA5` is 0 |
| `shift_reg[1]` | 12 | (constant) | `shift_reg` is loaded once from `tx_data` and never modified again (this uart indexes into it via `bit_index` rather than shifting) - it's structurally a copy of `tx_data`, so it inherits exactly the same gap |
| `bit_index[2]` | 11 | 1->0 | `bit_index` counts 0..7 across the *one* transmission the testbench sends; it reaches 4-7 (bit 2 goes 0->1) but the test ends before a second transmission would reset it back through 0, so the 1->0 edge is never demonstrated |
| `rst_n` | 3 | 1->0 | testbench asserts reset once at the start and never again - the 1->0 edge (a second, later reset pulse) is never exercised |

**All 5 trace to the same root cause: the testbench sends exactly one fixed
byte value, in one transmission, with one reset event.** This is a real,
specific testbench limitation (not a false-positive/uncoverable-signal
artifact of the metric) - it would improve with a second transmission using
a different byte value and a second reset pulse. Toggle coverage is
measuring something real here; the caveat is that it can only be trusted
after filtering to DUT-only signals (see correction above).

## What this does NOT yet show

The original framing of this file ("fsm's higher coverage correlates with a
higher silent-bug rate") is **retracted as stated**. The raw counts behind
it were fsm 4 KEEP / 4 SILENT (n=8) and uart 8 KEEP / 1 SILENT (n=9) -
plausibly 1-of-2 vs 1-of-9 once binomial noise is accounted for, not two
different rates. Presenting that as a percentage-based finding would be the
single most attackable claim in the project. Recorded here only as raw
counts, with no percentage and no interpretation, until the corpus scales
past n=30 per design and this file is re-run for real.

The mechanism argument this project is actually making - that
statement/branch/toggle coverage measures whether code *executed*, not
whether a mutation's specific behavioral effect propagated to a *checked*
output - still stands as the thesis. It just needs real n behind it before
it's a claim instead of a hypothesis.
