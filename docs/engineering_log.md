# Engineering log: thirteen times this project checked itself instead of assuming

Eleven of the thirteen episodes below are cases where something — a
static read of RTLIL, a formal tool's own summary, a "timed out"
status, a scratch directory that happened to already exist, a
percentage that looked clean — said one thing, and a cheap,
deliberately-built discriminating test showed it was wrong. That is
this project's actual thesis (a testbench saying PASS is not proof)
turned back on its own tooling, not a separate virtue. A log of caught
mistakes is presented here as a strength because catching them cheaply,
before they became a committed claim, is the entire method. The
twelfth and thirteenth episodes are different in kind, deliberately
included anyway: an API-surface audit and an instrument-validation
episode, respectively, where the point was *verifying* something before
trusting it, not fixing something already known broken — the same
discipline as the other eleven, just applied earlier, before a wrong
conclusion had the chance to get drawn at all.

Fixed structure per episode: **Symptom → Naive reading → Discriminating
test → Result → Rule adopted.**

## 1. Reset-release race: spurious divergence on identical copies

**Symptom.** Two setups showed the same shape of problem around reset
release: (a) a miter comparing two *sequential, identical* golden
instances spuriously reported them non-equivalent — the formal
equivalent of seeing X on both sides of a comparison that should be
trivially true; (b) a trivial counter testbench reported `FAIL` on
correct, unmistakable counting behavior.

**Naive reading.** (a) looked like a genuine miter-construction bug —
maybe the two instances weren't actually wired identically. (b) looked
like a genuine off-by-one or reset bug in the counter DUT itself.

**Discriminating test.** For (a): checked whether an explicit
reset-synchronization constraint was present in the miter at all — it
wasn't. For (b): isolated whether the testbench's own reset-release
edge, relative to the edge the DUT samples reset on, mattered — tried
releasing on the opposite edge.

**Result.** Both were the same underlying class of bug: reset release
was implicit, not an explicit synchronization point. (a) Without an
explicit reset-sync assume, uninitialized registers are independent
free variables per miter instance under Yosys's formal/BMC semantics —
even two byte-identical instances spuriously "refute" without it. (b)
Releasing `rst_n=1` with a blocking assign at the same `posedge clk`
the DUT samples it on is simulator-order-dependent; releasing on
`negedge clk` instead removed the race.

**Rule adopted.** Every miter in this project gets an explicit reset
synchronization assume (`generate_miter`, `verdict/miter.py`). Every
testbench releases reset on `negedge clk`, codified as a hard
requirement in `designs/CONTRACT.md`, not a style preference.

## 2. `initial assume`: RTLIL looked damning, the empirical test disagreed

**Symptom.** Needed to confirm `initial assume(X)` in a miter
constrains only simulation step 0, not every cycle — load-bearing for
episode 1's fix to actually mean what it's supposed to mean.

**Naive reading.** Inspecting the post-`prep` RTLIL directly: every
`initial assume` cell shows its `EN` port as unconditionally `1'1`,
with zero `$initstate` cells anywhere in the design. Read at face
value, this looks exactly like "applied every cycle," which would make
the whole reset-sync fix meaningless (a constraint that never releases
would trivially "solve" everything, not model reset correctly).

**Discriminating test.** Built a cover-mode reachability probe instead
of trusting the static read: `initial assume(q==0)` on a free-running
register, then `cover(q==5)`.

**Result.** `cover(q==5)` was reached at step 1. If the assume held
every cycle, that would be impossible — `q` could never leave 0. The
RTLIL reading was actively misleading; the initial-only semantics are
carried through a mechanism not visible in the single-frame RTLIL
template at all (most likely the SMT2 unrolling's own `PRIORITY`
handling, downstream of `prep`).

**Rule adopted.** When a static tool-internals read and expected
dynamic behavior might disagree, build a discriminating experiment —
never trust the static read on its own. This rule is why episode 3
(below) got caught before becoming a false upstream bug report, not
after.

## 3. eqy's "soundness bug" — the invocation was ours

**Symptom.** eqy's `sat` strategy returned a confident `PASS` (`Induction
step proven: SUCCESS!`) comparing golden `fsm` against a gate module
with every output hardwired to constant 0 — the most extreme
non-equivalent case constructible.

**Naive reading.** eqy has a soundness bug on this platform; file an
upstream issue.

**Discriminating test.** Applying episode 2's rule directly: before
concluding "eqy is unsound," swept the depth parameter and read the
actual per-partition logs, rather than trusting the aggregate summary
alone.

**Result.** At depth `10`, eqy correctly returned `UNKNOWN` — not a
false pass. Only at depth `40` did it flip to a confident false
`PASS`. Tracing further: `combine.log` confirmed gold and gate
genuinely stayed separate cells (not a name-collision artifact), and
each partition's own `.sby` script runs `setundef -anyseq` before
solving with a documented vacuity escape (`in_gold[i] === 1'bx`) in the
comparator. Leading hypothesis — not fully proven — is an
empty/under-populated partition slice interacting with that escape.
**The invocation is the suspect, not eqy the tool.**

**Rule adopted.** No upstream issue filed until the mechanism is
understood — a false report against a real tool has a cost too, and
episode 2's rule (build a discriminating test before trusting the first
explanation) applies to blaming a dependency exactly as much as it
applies to blaming your own code. Until resolved: BMC-refutes always
overrides eqy-proves, permanently, not as a temporary workaround.

## 4. COI's control-dependency bug, found by its own containment gate

**Symptom.** `cone_of_influence`'s own regression gate (does the
backward slice contain the actual root-cause line, across a set of
known real bugs) was not passing every case in the set.

**Naive reading.** Could be dismissed as "close enough" or an
inherent, acceptable imprecision in a static backward slice.

**Discriminating test.** Inspected the one failing case directly rather
than accepting the aggregate.

**Result.** A real bug: the first version tracked an enclosing
condition's *read signals* but not the condition's *own source line* —
silently dropping control-dependency lines from the slice whenever that
line never itself assigns anything (e.g. `if (bit_index == 3'd7)`
gating an increment in the `else` branch). Fixed; the gate passed every
case in the set afterward.

**Rule adopted.** A regression gate that isn't passing everything is
either a real bug or a documented, deliberate imprecision — never
averaged away as "good enough." The fix and the gate's own history are
recorded together in `docs/coi_soundness.md` — but that figure was
measured on a corpus later superseded by the current one, has not been
re-measured since, and is deliberately not quoted here or anywhere else
in this repo's current results (see `FINDINGS.md`'s "Parked /
unquotable" list and `README.md`'s Limitations).

## 5. Toggle coverage inflated/deflated by testbench-internal variables

**Symptom.** A coverage figure for `uart` looked suspicious relative to
the other three designs.

**Naive reading.** Toggle coverage is toggle coverage — read it as
reported by the raw `coverage.dat`.

**Discriminating test.** Filtered the same coverage data by source
file (`f` field in Verilator's key format), keeping only entries from
the DUT's own file, and compared against the unfiltered figure.

**Result.** Raw (unfiltered): `39/98` toggled = 39.8%. DUT-only
filtered: `26/52` = 50.0%. The raw figure was deflated by
testbench-internal declared-but-unused variables that never toggle and
were never going to — inflating the denominator with signals that have
nothing to do with the design under test.

**Rule adopted.** Every toggle-coverage figure reported anywhere in
this project is DUT-only filtered (`eval/coverage.py`'s `dut_file`
parameter); it is not comparable to a raw figure from another tool or
project without the same correction, and that caveat travels with every
coverage number this repo reports.

## 6. Orphaned `yices-smt2` surviving a Windows subprocess timeout

**Symptom.** A `fifo` mutation-corpus generation run was still going
after `22+` minutes with visibly near-zero CPU on the Python process
actually driving it.

**Naive reading.** Something is just slow — maybe `fifo`'s BMC checks
are worse than expected at this `k`; wait longer.

**Discriminating test.** Queried live OS process state
(`Get-CimInstance Win32_Process`) instead of guessing from wall-clock
alone.

**Result.** A `yices-smt2.exe` process had `~1028s` of accumulated CPU
time, in a process tree (`sby-script.py` → `yosys-smtbmc-script.py` →
`yices-smt2.exe`) whose immediate parent PID no longer existed —
`subprocess.run(timeout=...)`'s Windows implementation kills only the
top-level child it holds a handle to, not the full descendant tree a
timed-out `sby.exe` actually spawns. Every subsequent candidate's BMC
check was competing for CPU with every orphan accumulated so far,
directly explaining the runaway wall-clock.

**Rule adopted.** Every `sby` invocation goes through `Popen` +
`.communicate(timeout=...)`, with `taskkill /F /T /PID` (the `/T` kills
the whole descendant tree) on `TimeoutExpired`, never plain
`subprocess.run(timeout=...)`. Verified live: forced a fast timeout
after the fix and confirmed zero surviving solver processes.

## 7. Self-inflicted: testing the orphan-sweep guard while a real run was live

**Symptom.** None yet — this episode is the mistake itself, made while
building episode 6's fix.

**Naive reading.** N/A — there was no misleading signal to read here.
This is the case to not sanitize: a genuinely careless action, not a
tool being wrong.

**Discriminating test / what actually happened.** A pre-flight guard
(`env.sweep_orphaned_solvers()`) was added and immediately tested by
calling it directly — while a freshly-relaunched, legitimate `fifo`
generation run was still active in the background. The guard's own
docstring says "never mid-batch, since a legitimate in-flight check
from the same run would look identical to a stray and get killed too."
It was called mid-batch anyway, and killed that run's own live BMC
check, indistinguishable from a stray by design, because from the
sweep's point of view it *was* one.

**Result.** Diagnosed and bounded the damage by reasoning about
`check_bmc`'s own fail-closed behavior, rather than re-running
everything defensively: an abruptly-killed process leaves a partial,
unparseable log, and `check_bmc` never reads that as `REFUTED` or
`PROVEN-BMC` — only `INDETERMINATE`. That narrowed the blast radius to
exactly the run's `INDETERMINATE` results. Re-checked both:
`fifo_blocking_nonblocking_swap_023` reconfirmed genuinely
`INDETERMINATE` (a real `90`s timeout). `fifo_blocking_nonblocking_swap_026`
came back `PROVEN-BMC` in `36.6`s — confirming it was the corrupted
one. One record corrected; `forge_decision` was unaffected either way
(`INDETERMINATE` and `PROVEN-BMC` both map to `QUARANTINE`), so no
corpus-wide accounting was ever wrong, only that single task's internal
formal-verdict detail.

**Rule adopted.** Writing a safety mechanism is not the same as using
it safely. `sweep_orphaned_solvers()` is now called exactly once, at
the very start of a batch entry point's `main()` — never interactively,
never mid-batch, no exceptions — and this episode is the reason cited
for that rule everywhere it appears in code comments.

## 8. `VERILATOR_ROOT` mangled by Make's backslash handling

**Symptom.** Verilator's `--binary --coverage` build (needed to
generate episode 5's raw `coverage.dat` at all) failed to find its own
runtime includes even with `VERILATOR_ROOT` set.

**Naive reading.** The environment variable value itself must be wrong
— re-check the path.

**Discriminating test.** Printed the exact string being passed through
to Make's generated build commands.

**Result.** The path was being built as a `pathlib.Path` (Windows
native, backslash-separated) and passed through Verilator's generated
Makefile, which treats backslash as an escape/line-continuation
character — silently mangling the path into its components concatenated
with no separators at all.

**Rule adopted.** `VERILATOR_ROOT` (and anything else destined for a
Make-invoked command) is built with forward slashes explicitly
(`.replace("\\", "/")`), never a raw `str(Path)`. Validated the fix by
re-running the coverage build and reproducing episode 5's `39.8%`→`50.0%`
figures byte-for-byte — the fix wasn't just "no more error," it was
confirmed to produce the exact previously-documented number, which is a
stronger check than "it ran."

## 9. The coverage-comparability gate fired on a threshold set in advance

**Symptom.** A silent-bug-rate vs. toggle-coverage analysis produced a
clean-looking monotonic pattern across all four designs.

**Naive reading.** Report the pattern as suggestive evidence of a
relationship, caveated but stated.

**Discriminating test.** A comparability check had been specified
*before* looking at the result: if the four designs' toggle-point
denominators span more than roughly 3x, the percentages being compared
aren't measuring the same thing precisely enough to compare. Computed
the actual denominators and checked them against that pre-set
threshold, rather than deciding after seeing how clean the pattern
looked.

**Result.** The denominators span `9.4x` (`20` to `188` toggle
points) — far past the pre-set `~3x` threshold. The comparability gate
failed. Rather than softening the finding to "suggestive, with a
caveat," the relationship claim was withdrawn outright: no
coverage-vs-silence relationship, in either direction, is defensible on
a metric that isn't comparable across the sample in the first place.

**Rule adopted.** Set the invalidating threshold before seeing the
result, and honor it even when the result looks clean — a clean-looking
pattern is exactly the situation where the temptation to keep a caveated
version of a claim is strongest, which is precisely when a pre-committed
threshold is worth the most. See `results/silent_bugs.md` §5.

## 10. `work_dir` written into before it was ever created

**Symptom.** The first real end-to-end run of the agent-verdict
harness against a genuinely fresh output directory crashed with
`FileNotFoundError` writing `submitted_patch.v`.

**Naive reading.** Could have been dismissed as a one-off path issue
specific to that run's configuration.

**Discriminating test.** Checked why every *prior* test of this exact
code path (`run_task`'s success path, several fake-provider unit tests)
had never hit this. 

**Result.** Every earlier test happened to reuse a scratch directory
that already existed from previous manual runs — masking a real,
unconditional bug: `run_task`'s success path wrote the submitted patch
directly into `work_dir` before anything guaranteed that directory
existed (`Trajectory.write()`'s own `mkdir` only runs afterward, and
only on some code paths). Any real Phase 2 agent-pilot run, with a real
API key, against its own fresh output tree, would have crashed on its
very first successfully-formal-checked task.

**Rule adopted.** `work_dir.mkdir(parents=True, exist_ok=True)` now
runs at the very top of `run_task()`, before anything else touches the
directory. More generally: a test suite that always reuses the same
scratch paths across runs can hide exactly this class of bug — a
plumbing test run against a genuinely fresh directory tree is what
actually caught it, not code review, not the existing unit tests.

## 11. The bare-integer sweep catching its own author

**Symptom.** A newly-written reproducibility doc quoted a measured
runtime as `~23 seconds`.

**Naive reading.** It's a real, measured number (it was — timed with
the shell's own `time` builtin, not invented) — plausible to consider
it fine to state directly in prose.

**Discriminating test.** This project's own bare-integer sweep
(`test_stats_consistency.py`, a regression test that every number in
`results/*.md`/`docs/*.md` must trace to a script-generated JSON file,
never be hand-typed) ran against the new doc, as it does against every
doc, automatically.

**Result.** Failed: `23` was not backed by any generated file — the
figure had been read off a terminal and typed into prose directly,
exactly the pattern the sweep exists to catch, applied to a doc written
in this same project by the same process that built the sweep. Fixed at
the source, not by loosening the check: `scripts/verify.py` now
persists its own `elapsed_s` to `results/verify_run_report.json` on
every run, and the doc cites that field instead of a remembered number.

**Rule adopted.** No exception for "but I definitely just measured
this" — if a number isn't in a generated file, it doesn't get to be in
a doc, regardless of how recently or carefully it was actually
measured. This episode is the sweep working exactly as designed, not a
gap in it.

## 12. The verdict taxonomy audit — the API-surface lesson, not a bug

This episode is framed differently from the eleven above on purpose:
nothing here was wrong. It's included because *checking* that, rather
than assuming it, is the same discipline applied to itself one more
time — and because the check could easily have gone the other way.

**Symptom.** The agent-verdict path advertises five verdict classes in
its own type signature and documentation
(`PLAUSIBLE`/`REFUTED`/`INVALID-PATCH`/`NO-PATCH`/`ERROR`), and the
underlying formal ladder has its own three-value `VERDICTS` enum
(`REFUTED`/`PROVEN-BMC`/`INDETERMINATE`) plus a documented, not-yet-
implemented fourth concept (`PROVEN-UNBOUNDED`). Across every document
written about this project so far, the *distribution* of what those
verdict fields actually contained, across every real run ever produced,
had never once been directly inspected.

**Naive reading.** The ladder works because the engine computes the
right thing — `check_bmc()`'s own return value (`VerdictResult.verdict`)
had been read, quoted, and trusted repeatedly (`results/verdict_ladder_validation.md`
is built entirely on it). It would have been easy to assume that value
is also what a consumer of the agent-verdict path actually sees, since
it's the value everything upstream is computed from.

**Discriminating test.** Read the literal string in the
consumer-facing field (`Trajectory.final_verdict`, the attribute
`run_task()` actually returns and every caller actually reads) across
every committed run record, rather than trusting the engine's internal
return value as a proxy for it. Concretely: grepped `final_verdict`
across all `63` committed `trajectory.json` files (every patch-path run
this project has ever produced, Phase 2 + Phase 2B combined) for
`PROVEN-BMC` and `PROVEN-UNBOUNDED`, instead of reasoning from
`_FORMAL_TO_VERDICT`'s source code alone.

**Result.** `0/63` — neither string was ever the surfaced
`final_verdict`, on any record. Both are unreachable on the patch path
by construction: `PROVEN-BMC` is unconditionally remapped to
`PLAUSIBLE` by `_FORMAL_TO_VERDICT`
([`rtlverdict/agent/loop.py:39`](../rtlverdict/agent/loop.py#L39));
`PROVEN-UNBOUNDED` isn't a value the ladder's own enum can produce at
all yet. The mapping is intentional and epistemically correct — it
predates this audit by an entire earlier project phase, and the audit
changed zero lines of `check_patch` or `ladder.py`. It was never wrong;
it had simply never been directly verified, only inferred from reading
the code that computes the internal value.

**Rule adopted.** Verify the surfaced value, not the computed one. A
function's return value and what a downstream consumer actually reads
are different artifacts, and only one of them is the interface a reader
or a caller ever sees — the fact that they're related (one is derived
from the other) is exactly what makes it easy to check the wrong one
and believe the check covered both. This project's own
`results/verdict_ladder_validation.md` now states the surfaced/raw
distinction explicitly, in a table, rather than leaving it to be
inferred from source (see its §7 and the README's "Verdict taxonomy"
section) — a direct product of this episode.

## 13. The instrument was lying, not the layout

**Symptom.** Headless-rendered screenshots of the dashboard at a
narrow window width showed text and tables cut off past the right edge
of the image, across multiple unrelated sections of the page at once
(header, findings cards, the verdict-ladder table).

**Naive reading.** The CSS is broken at narrow widths — go fix
whatever the screenshots show as wrong: add wrapping rules, contain the
tables, adjust the grid. (Several of these fixes were in fact applied,
and were real, independently-correct improvements — but they were
being diagnosed against a measurement that hadn't itself been checked.)

**Discriminating test.** Before trusting any more diagnoses from the
screenshots, checked the measuring instrument itself: rendered a
trivial, content-free HTML page (`<div>` reporting
`window.innerWidth`) at several requested widths via headless Chrome's
`--window-size` flag, from `300px` up to `800px`.

**Result.** Every request below roughly `500px` — `300`, `390`, `400`,
`450`, `480` — reported back the identical `window.innerWidth=504`
(Edge showed the same behavior at `496`). This Windows headless
Chrome/Edge install silently clamps the viewport to a floor around
`500px` regardless of what
`--window-size` requests below that. Every "mobile" screenshot taken
before this check had actually been rendered at `~504px` and then
squeezed into a smaller output image, which is what produced the
cut-off appearance — a capture artifact, not (only) a CSS bug. Built a
minimal Chrome DevTools Protocol client (Node's built-in `WebSocket`,
no npm dependency) to drive `Emulation.setDeviceMetricsOverride`
directly, bypassing OS-level window creation entirely, and got a
genuine `390px` render. Only then were the real CSS bugs (unbreakable
long code spans, table headers wrapping letter-by-letter) diagnosed and
fixed with confidence — against a measurement now known to be
trustworthy instead of merely available.

**Rule adopted.** Validate the instrument before trusting a measurement
it produces. This is the fourth unrelated layer this project has hit
the same rule at: the eqy control test (episode 3 — checked the tool
against a case with a known answer before trusting its verdict on cases
without one), the toggle-coverage denominator check
(`results/silent_bugs.md` §5 — checked whether the *metric itself* was
comparable across designs before trusting a cross-design pattern in
it), the surfaced-vs-computed verdict audit (episode 12 — checked what
a consumer actually reads, not what a function returns), and now the
render viewport itself. Four different kinds of instrument — a formal
tool, a coverage metric, an API's own return value, a browser's
reported window size — same failure mode each time: something
downstream of the instrument looked wrong, and the instrument was the
actual thing that needed checking first.
