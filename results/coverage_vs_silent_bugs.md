# Silent-bug rate vs. testbench coverage

Real numbers from `corpus_v1` (20 tasks: 10 fsm + 10 uart candidates, LOGIC +
TIMING operator classes only). Coverage measured via `verilator --coverage
--coverage-line --coverage-toggle`, parsed from the raw `coverage.dat`
(`verilator_coverage`, the bundled analysis tool, is a Perl script requiring
`Pod::Usage`, unavailable in this environment - parsed the documented text
format directly instead, see `rtlverdict/eval/coverage.py`).

Silent-bug rate defined as `SILENT / (KEEP + SILENT)`: among mutants formally
proven non-equivalent (REFUTED), what fraction did the testbench's own
simulation fail to catch (sim=PASS instead of FAIL).

| design | line cov | toggle cov | branch cov | expr cov | KEEP | SILENT | silent-bug rate |
|---|---|---|---|---|---|---|---|
| fsm  | 86.7% | 90.0% | 90.0% | 58.3% | 4 | 4 | 50.0% |
| uart | 88.2% | 39.8% | 87.5% | 66.7% | 8 | 1 | 11.1% |

**Both `reset_covers_all_state: true` claims are machine-verified** (not
asserted), via `rtlverdict/forge/reset_coverage.py` checking that every
signal assigned anywhere in each design's clocked always block is also
assigned inside that block's reset branch - the soundness precondition for
trusting any silent-bug finding at all (a silent bug from an unreachable
state would be a fake finding, not a real one).

**Observation, stated carefully given n=20 total, n=1 for uart's SILENT
bucket specifically**: fsm has *higher* line/toggle/branch coverage than
uart yet a *higher* silent-bug rate (50% vs 11%). This is the opposite of
what "more coverage catches more bugs" would predict, and it's the actual
interesting claim: statement/branch/toggle coverage measures whether code
*executed*, not whether the specific *value* a mutation changes was ever
checked against an expected result. fsm's testbench (`tb_fsm.v`) checks
`busy`/`done` at a few specific points but doesn't check `counter`'s value at
all, despite `counter` toggling fully (90% toggle coverage) - so a mutation
to the counter's comparison logic can toggle every bit correctly while its
*behavioral effect* (transitioning one cycle early/late) goes unverified.

**This is not yet a statistically meaningful result** - one silent case for
uart, four for fsm. It becomes one once the corpus scales past 20 (in
progress, target 150+) and spans all six operator classes, not just LOGIC +
TIMING. Recorded now as the first real data point, to be re-measured at
scale rather than redone from scratch.
