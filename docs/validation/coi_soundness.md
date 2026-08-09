<!-- stats-scope: historical, corpus=12bb0c982fe94a816014bb7367748745b9b903a4, date=2026-08-08T17:29:44Z -->

# COI (cone_of_influence) soundness notes

**Historical validation record - not a live figure.** The 10/10 containment
figures below were measured against `corpus_v1` (the original 20-candidate
corpus), superseded by corpus_v2 + the fifo addition. They do not describe
the current 171-task corpus - see `results/corpus_stats.json` for current
figures. Note this note does NOT extend to
`rtlverdict/witness/tests/test_coi.py`'s `TestContainment` class, which
remains a live regression test: its `KNOWN_CASES` are signal/
root_cause_line pairs hardcoded directly from this same corpus_v1 run (not
synthetic fixtures) and continue to run on every test invocation - moving
and annotating this markdown file does not touch that test file or weaken
what it checks.

`rtlverdict/witness/coi.py` computes a static backward slice via the
pyslang AST: given a signal, which source lines can transitively affect it.
It **must be a sound over-approximation** - never omit a real dependency.
Extra lines are acceptable; a missing root cause is fatal (this is what
Addition 3's containment gate checks continuously, not just once).

## Real bug found and fixed during development

The first version tracked, per assignment, the *read signals* of every
enclosing `if`/`case` condition, but not the *condition's own source line*.
This silently dropped control-dependency lines from the slice whenever that
line never itself appears on an assignment's LHS - e.g.
`if (bit_index == 3'd7) ... else bit_index <= bit_index + 1;`: the
condition line gates whether the increment happens, so it belongs in
`bit_index`'s cone, but the old code only added `bit_index`'s own read-set,
not the condition line itself.

Caught by the containment gate dropping to 90% (9/10) on real corpus_v1
tasks, not by inspection. Fixed by having condition-collection return both
the read signals AND the condition's own line; both are now added to the
slice. Gate is 100% (10/10) after the fix. See
`rtlverdict/witness/tests/test_coi.py::test_condition_gating_an_assignment_is_in_the_cone`
for the regression test.

## Known imprecision sources (not yet exercised - Tier A is single-module)

- **Hierarchical instance port connections are not followed across module
  boundaries.** If a signal's value comes from a submodule's output port,
  the slice stops at the port connection rather than continuing into the
  submodule's internal logic. All four Tier A designs are single-module, so
  this has not yet produced an observed failure - it will need addressing
  before any multi-module design (including Tier B) can use COI safely.
- **Generate blocks are not specially handled.** Identifiers inside a
  `generate` block are collected the same as anywhere else; this is
  probably sound (over-inclusive at worst) but not specifically verified.
- **Parameters/localparams are not distinguished from signals.** They show
  up as read-identifiers in the dependency graph but never have their own
  assignment entries, so they're silently dropped from the BFS frontier
  with no ill effect - confirmed harmless in practice (see `IDLE`/`RUN`/
  `FINISH` in fsm.v's dependency index), not a soundness gap, but worth
  documenting since it looks like it could be one.
- **Memories/arrays are treated at whole-array granularity.** A dynamically-
  indexed read/write (`mem[ptr]`) is not resolved per-element - any write
  to any element of an array is treated as affecting the whole array's
  cone, and any read of any element pulls in every write to that array.
  This is conservative (still sound) but coarser than necessary; fifo.v's
  `mem` array has not yet been used to exercise cone_of_influence, so this
  is a documented risk, not yet a measured one.
- **Toggle-based suspect ranking (suspect_rank.py) is a heuristic on top of
  a sound COI, not itself a soundness claim.** Confirmed limitation: a VCD
  only records when a signal changed, not which of several lines that can
  write it actually fired - lines writing the same signal tie in score.
  The true root cause is always within the tied top group (consistent with
  the containment gate), just not uniquely ranked first.

## What "sound" is verified against right now

`rtlverdict/witness/tests/test_coi.py` pins the containment gate's 10/10
real corpus_v1 KEEP-task result (fsm + uart, both single-module, no
memories, no generate blocks, no submodule instances) as a regression test.
This is real evidence for the cases actually exercised, not a general
soundness proof - the imprecision sources above are the honest list of what
hasn't been tested yet, not claims that they're already handled correctly.
