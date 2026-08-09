# Verdict ladder validation: does the formal gate discriminate?

Phase 2's plumbing test exercised exactly one input class (a full
golden-revert "fix") and got exactly one output class (`PLAUSIBLE`).
One input, one output proves the wiring doesn't crash — it does not
prove the formal gate can tell a real fix apart from a wrong one. This
document adds three more input classes through the identical harness
(`run_task` → `check_patch` → `check_bmc`), on the identical 12-task
stratified selection used in Phase 2, to make it an actual
discrimination test.

All numbers below are read from
`results/verdict_ladder_validation_report.json` (this doc's own run) and
`results/agent_pilot_plumbing_report.json` (C1, reused from Phase 2, not
re-run — see §1). Regenerate with
`python scripts/verdict_ladder_validation.py`. **No agent ran here
either** — every condition is a fixed, deterministic stub, same
disclaimer as `results/agent_pilot.md`.

## Answers, up front (full reasoning in §5–§8)

**Which verdict classes has the agent-verdict path now demonstrably
emitted?** `PLAUSIBLE` (24/24 — 12 from C1, 12 from C2), `REFUTED`
(12/12, C3), and `INVALID-PATCH` (12/12, C4) — all observed in this
document, on real submitted patches through the real
`check_patch`/`check_bmc` pipeline. `NO-PATCH` was separately
demonstrated in Phase 2's cap-trip demo. **`PROVEN-BMC` and
`PROVEN-UNBOUNDED` are NOT in this list and never will be from this
code path** — see the next answer and §5/§7's table.

**Which remain unreached?** `INDETERMINATE` and `ERROR`. Neither is a
gap in the ladder itself — both code paths are exercised elsewhere
(`INDETERMINATE` via `edge_swap`'s pattern in
`results/equivalent_mutant_rate.md`; `ERROR` via a unit-level
provider-exception test) — but neither has been produced by a real
patch going through `run_task`/`check_patch` specifically. Open.

**Is the P0 forge-path `PROVEN-BMC` result produced by the same code
path as `check_patch`, or a different one?** **The same code, literally
the same function** — `forge/corpus.py` and `agent/loop.py` both import
and call `verdict.ladder.check_bmc()` directly, no wrapper, no second
implementation. What differs is caller-side only: which
k/timeout/memory_map parameters are used, what gets passed as the
"mutant" argument, and which label vocabulary (`forge_decision` vs.
`final_verdict`) is built on top of the same three raw outcomes. See §6.

**Were the C2/C3 "expected" verdicts semantically derived or captured
from output — and do the two independent sources agree?** Both, by
design, from two different documents — and they agree. This document's
own `expected_final_verdict` values (`PLAUSIBLE` for C1/C2, `REFUTED`
for C3, `INVALID-PATCH` for C4) were **hardcoded in
`scripts/verdict_ladder_validation.py` before the script was ever run**,
derived from `verdict/ladder.py`'s own pre-existing `VERDICTS` semantics
(written for an unrelated, earlier phase of this project, not tuned for
this test) — not reverse-engineered from a completed run's output.
`benchmarks/verify_golden.json` (Phase 3's regression-check golden file)
is different: it is **captured from output by construction** —
`scripts/verify.py --freeze` mechanically serializes whatever the stub
produced, which is the correct design for a regression check ("does
this machine reproduce the same result as before") but is not on its
own independent evidence of correctness. Re-checked directly (§8): the
two sources use the identical underlying stub logic on the identical
two tasks, and their values agree exactly —
`fsm_constant_perturbation_005` (C2) is `PLAUSIBLE`/raw `PROVEN-BMC` in
both; `uart_constant_perturbation_005` (C3) is `REFUTED`/raw `REFUTED`
with a real counterexample (`divergence_cycle=2`) in both. No
disagreement — nothing to stop for.

## 1. The four input classes

| condition | what's submitted | expected `final_verdict` |
|---|---|---|
| **C1** true fix (full revert) | the entire golden file, verbatim (Phase 2's original stub — read from its transcripts, not re-run here) | `PLAUSIBLE` |
| **C2** true fix (region-scoped) | the mutant, with ONLY the mutated line (`root_cause_line`) replaced by golden's line at that index | `PLAUSIBLE` |
| **C3** wrong fix | a *different* KEEP task's mutant from the same design (a real, already formally-confirmed divergence from golden) submitted as this task's "fix" | `REFUTED` |
| **C4** invalid patch | a fixed unparseable string | `INVALID-PATCH` |

C2 is asserted (not assumed) to reconstruct golden byte-for-byte before
it's ever submitted — checked programmatically for all 12 tasks before
this script was written, and re-asserted inside the script itself
(`region_patch_equals_golden` in every C2 row of the report JSON, all
`true`). C3's donor mutant is chosen deterministically (lowest
`task_id`, same design, excluding self) and is syntactically valid by
construction — it already passed forge's own fidelity guard when the
corpus was built.

## 2. Result matrix (summary)

| condition | n | expected | observed distribution | wall-clock range | verdict |
|---|---|---|---|---|---|
| C1 true fix (full revert) | 12 | PLAUSIBLE | PLAUSIBLE: 12/12 | 1.91s – 35.15s | **PASS** |
| C2 true fix (region) | 12 | PLAUSIBLE | PLAUSIBLE: 12/12 | 2.17s – 34.47s | **PASS** |
| C3 wrong fix | 12 | REFUTED | REFUTED: 12/12 | 1.58s – 1.87s | **PASS** |
| C4 invalid patch | 12 | INVALID-PATCH | INVALID-PATCH: 12/12 | 0.00s – 0.07s | **PASS** |

Every row's `final_verdict` matched what a correct ladder must produce
for that input, and — this is the important part, not just the label —
**every row's *raw* ladder verdict (`verdict_detail.formal_verdict` /
`ladder.py`'s own `VerdictResult.verdict`) matched too**: C1/C2 are
`PROVEN-BMC` underneath, C3 is `REFUTED` underneath (with a real
counterexample cycle recorded — see §4), C4 never reaches the ladder at
all (caught by `check_patch`'s parse gate, first of its four checks).

C3's uniformly fast wall-clock (1.58s–1.87s, including fifo, which
normally needs ~34s to complete a full-depth `PROVEN-BMC` search) is a
side-effect worth noting: `REFUTED` runs stop as soon as BMC finds a
counterexample, which for donor mutants happens at their own shallow
recorded `divergence_cycle` (1–2 steps, see §4) — they never search the
full bound. `PROVEN-BMC` runs (C1/C2) have no counterexample to stop
early on, so they must exhaust the full depth, which is why fifo's
`memory_map`-required search dominates their wall-clock and not C3's.
This asymmetry is itself evidence the ladder is doing real per-step BMC
search, not returning a constant.

## 3. Full per-task detail

| task_id | design | C1 verdict | C2 verdict | C2 region=golden | C3 verdict | C3 donor | C4 verdict |
|---|---|---|---|---|---|---|---|
| fifo_operator_swap_004 | fifo | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | fifo_constant_perturbation_016 | INVALID-PATCH |
| fifo_signal_substitution_037 | fifo | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | fifo_constant_perturbation_016 | INVALID-PATCH |
| fifo_signal_substitution_033 | fifo | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | fifo_constant_perturbation_016 | INVALID-PATCH |
| fsm_constant_perturbation_005 | fsm | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | fsm_constant_perturbation_006 | INVALID-PATCH |
| fsm_constant_perturbation_008 | fsm | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | fsm_constant_perturbation_005 | INVALID-PATCH |
| fsm_next_state_redirect_032 | fsm | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | fsm_constant_perturbation_005 | INVALID-PATCH |
| spi_master_constant_perturbation_003 | spi_master | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | spi_master_constant_perturbation_005 | INVALID-PATCH |
| spi_master_next_state_redirect_047 | spi_master | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | spi_master_constant_perturbation_003 | INVALID-PATCH |
| spi_master_next_state_redirect_048 | spi_master | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | spi_master_constant_perturbation_003 | INVALID-PATCH |
| uart_constant_perturbation_005 | uart | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | uart_constant_perturbation_006 | INVALID-PATCH |
| uart_signal_substitution_037 | uart | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | uart_constant_perturbation_005 | INVALID-PATCH |
| uart_next_state_redirect_041 | uart | PLAUSIBLE | PLAUSIBLE | yes | REFUTED | uart_constant_perturbation_005 | INVALID-PATCH |

12/12 rows PASS on every condition. Raw per-row wall-clock and
`invalid_patch_reason` (`"parse failed: 5 diagnostics"` for every C4
row — the fixed nonsense string fails pyslang parsing identically each
time) are in `results/verdict_ladder_validation_report.json`.

## 4. What actually discriminates C1/C2 from C3

Not just the label — the underlying formal claim differs in kind. C1/C2
(`PROVEN-BMC`) mean BMC searched every step up to `k` and found **no**
counterexample. C3 (`REFUTED`) means BMC found a **real** counterexample
trace — `divergence_cycle_found` is recorded for every C3 row (1–2
steps for every donor used here, matching those donors' own
already-known `divergence_cycle` from when they were originally
formally confirmed as real bugs during corpus generation). That
agreement — the SAME divergence step recorded twice, once when the
donor mutant was first formally confirmed as a real bug against its own
design's golden, and again here when it's resubmitted as a wrong "fix"
— is itself a cross-check that the ladder is finding the *same* real
counterexample both times, not two unrelated failures.

## 5. Does `PLAUSIBLE` (not `PROVEN-BMC` / `PROVEN-UNBOUNDED`) mean the top of the ladder is unreachable?

Yes and no — and the precise answer is more useful than either word
alone.

**Yes, in the sense the question was asked:** every true-fix row here
(C1 and C2, 24/24) resolves to `final_verdict=PLAUSIBLE`, never to a
raw `PROVEN-BMC` label surfacing at the trajectory level, and never to
anything resembling `PROVEN-UNBOUNDED`. `rtlverdict/agent/loop.py`'s
`_FORMAL_TO_VERDICT = {"PROVEN-BMC": "PLAUSIBLE", "REFUTED": "REFUTED",
"INDETERMINATE": "INDETERMINATE"}` maps every bounded pass to
`PLAUSIBLE`, unconditionally — there is no code path in `run_task()`
that reports a raw `PROVEN-BMC` (or anything stronger) as the
`final_verdict` a caller sees. The raw ladder verdict is still fully
recorded — `verdict_detail.formal_verdict` shows `PROVEN-BMC` on every
one of these 24 rows — but the *headline* label a caller reads is
always the downgraded one.

**No, in the more important sense: this is not a check_patch-specific
gap, and it is not new information this run discovered.**
`PROVEN-UNBOUNDED` is not merely unreached by `check_patch` — it does
not exist anywhere in this codebase's implementation. `verdict/ladder.py`
defines `VERDICTS = ("REFUTED", "PROVEN-BMC", "INDETERMINATE")` — three
values, full stop — and its own module docstring says why, predating
this validation exercise entirely:

> "Currently BMC-only: eqy's per-partition SAT strategy was found to
> false-prove equivalence on 4/4 tested designs on this Windows setup
> (FINDINGS.md) — a soundness problem, not a reporting bug — so eqy is
> not wired in for real decisions yet. This is the adopted degraded-mode
> operating assumption: unrefuted mutants QUARANTINE instead of being
> marked PROVEN-UNBOUNDED equivalent."

So the honest framing is: **the top tier of the ladder (an unbounded,
non-BMC proof) is not implemented anywhere in this project, for any
caller, forge or agent alike — a known, documented, permanent
consequence of eqy being unsound on this setup, not something this
validation exercise uncovered or something specific to how `check_patch`
calls the ladder.** `check_patch`/`run_task`'s `PROVEN-BMC → PLAUSIBLE`
downgrade is a *second*, independent, deliberate decision on top of
that (never report a bounded pass as more certain than it is — the same
rule forge's own corpus-generation path follows by using `QUARANTINE`
rather than "equivalent" for an unrefuted mutant). Both decisions point
the same direction — never claim more than was actually proven — but
they are two different pieces of code making that choice for two
different reasons, and neither is a defect surfaced by this run.

## 6. Same code path as the P0 forge-path PROVEN-BMC result, or different?

**The same code path — literally the same function, not a parallel
reimplementation.** `rtlverdict/forge/corpus.py:46` and
`rtlverdict/agent/loop.py:28` both do
`from rtlverdict.verdict.ladder import check_bmc` and call that
identical function. The P0 deep-BMC result
(`fifo_blocking_nonblocking_swap_026`, raw ladder verdict `PROVEN-BMC`,
36.6s, k=200 — a forge-path record, surfaced there as `equivalence_to_golden`,
never as a patch-path `final_verdict`) and every C1/C2 row in this
document — surfaced as `PLAUSIBLE`, with raw ladder verdict `PROVEN-BMC`
underneath, per §5 — ran through the exact same `check_bmc()`
implementation, the exact same `sby`/`smtbmc yices` invocation shape,
the exact same three-value `VERDICTS` enum. **Precision matters here:**
no row anywhere in this document is a "`PROVEN-BMC` row" in the sense of
that being its surfaced identity — every C1/C2 row's surfaced
`final_verdict` is `PLAUSIBLE`, full stop; `PROVEN-BMC` only ever
appears as the raw, internal `verdict_detail.formal_verdict` value one
level down. Referring to these as "`PROVEN-BMC` rows" as loose shorthand
would directly contradict §5/§7's own claim that `PROVEN-BMC` is never
surfaced on the patch path — so this document doesn't use that
shorthand, here or anywhere else.

**What differs is entirely caller-side, not ladder-side:**

- **Parameters.** Forge's corpus generation calls `check_bmc` with
  `k`/`timeout_s`/`memory_map` chosen per design for building the
  corpus (e.g. fifo's `k=25`); the agent path calls it with the values
  carried on that task's `TaskInput` (`formal_k`/`formal_timeout_s`/
  `formal_memory_map` — see `rtlverdict/agent/loop.py`'s `TaskInput`
  dataclass, which exists specifically so a fifo task doesn't silently
  get the wrong defaults, see FINDINGS.md's Day-9 pivot section).
- **What gets passed as the "mutant" argument.** Forge passes its own
  generated mutant; the agent path passes whatever the agent (or here,
  the stub) submitted as `patched_source`.
- **The label built on top of the raw verdict.** Forge's
  `forge_decision` taxonomy (`KEEP`/`SILENT`/`QUARANTINE`/`ERROR`) and
  the agent path's `final_verdict` taxonomy
  (`PROVEN-BMC`→`PLAUSIBLE`/`REFUTED`/`INVALID-PATCH`/`NO-PATCH`/`ERROR`)
  are two **different, never-merged** vocabularies built on top of the
  same three raw ladder outcomes — restating the standing project
  invariant that forge's `REFUTED` (keep the mutant, it's a real bug)
  and verdict's `REFUTED` (reject the patch, it's still wrong) are
  different claims that happen to share an English word, not the same
  claim twice.

The README/paper must describe this as "the same formal ladder, called
with different parameters and interpreted through two different
label sets" — never as "two independently-validated systems," which
would overstate how much independent evidence exists. It is one
verified mechanism, exercised twice.

## 7. Which verdict classes has the agent path now demonstrably emitted?

Through `run_task()` (`check_patch` is only reached once a patch is
actually submitted, so classes below `check_patch`'s own scope are
marked as such):

| verdict | demonstrated? | where |
|---|---|---|
| `PLAUSIBLE` | yes | this document, C1 (12/12) and C2 (12/12) |
| `REFUTED` | yes | this document, C3 (12/12) |
| `INVALID-PATCH` | yes | this document, C4 (12/12) — via `check_patch`'s parse gate, before the ladder is ever reached |
| `NO-PATCH` | yes | Phase 2's cap-trip demo (`max_iterations` tripped, no `submit_patch` call ever made) — a `run_task()`-level outcome, not one `check_patch` can produce, since `check_patch` is never called without a submitted patch |
| `INDETERMINATE` | **no** | never observed via `run_task`/`check_patch` in Phase 2 or this document. The `INDETERMINATE` code path in `check_bmc` itself IS exercised and documented elsewhere (e.g. the `edge_swap` operator's pattern in `results/equivalent_mutant_rate.md`, and the deliberate 5s timeout test in `scratch_verify/verify_agent_module.py`'s `patch_check.py` checks) — but not through this specific harness on a real formal timeout. Remains open: a genuine Phase 2 run, or a dedicated test with an artificially tiny `formal_timeout_s`, would close this. |
| `ERROR` | partially | exercised at the unit level in `scratch_verify/verify_agent_module.py` (a provider exception ends the task with `ERROR`) — not through this real 12-task subset, since no provider call in this document can fail (the stub cannot throw). |
| `PROVEN-BMC` (as a surfaced `final_verdict`) | **never — by design** | `_FORMAL_TO_VERDICT` in `rtlverdict/agent/loop.py` maps every raw `PROVEN-BMC` to `final_verdict=PLAUSIBLE`, unconditionally, on every code path. This is not a gap; it is the deliberate "never promote a bounded pass to more certainty than it has" rule, predating this document. Confirmed empirically as well as by reading the code: across every committed `trajectory.json` this project has ever produced (63 records, Phase 2 + this document), `final_verdict` is never once `PROVEN-BMC`. |
| `PROVEN-UNBOUNDED` (anywhere, any path) | **never — does not exist in the codebase** | `verdict/ladder.py`'s `VERDICTS` tuple has exactly three values (`REFUTED`, `PROVEN-BMC`, `INDETERMINATE`); `PROVEN-UNBOUNDED` is not a value this implementation can produce, on the patch path or the forge path, until eqy is trustworthy again (see §5). |

**No expectation failed in a way that required stopping.** Every
condition matched its expected verdict class on every one of 48
rows (12 tasks × 4 conditions). The one genuinely notable finding —
§5's `PROVEN-UNBOUNDED` non-existence — was anticipated by the brief
this document was written against, is not a bug, and nothing was
changed in `check_patch` or `ladder.py` to make any row's result look
different from what it actually was.

## 8. `verify_golden.json`'s C2/C3 values: semantics-derived, or captured from output?

Two genuinely different provenance stories exist for what looks like
the same claim ("C2→`PLAUSIBLE`, C3→`REFUTED`"), and conflating them
would overstate how much independent checking actually happened.

**This document's expectations are semantics-first.**
`scripts/verdict_ladder_validation.py` was written in full — including
the `expected_final_verdict` table — and only then run for the first
time. The expected values are not a guess: they follow directly from
`verdict/ladder.py`'s own `VERDICTS` definitions
(`REFUTED` = "BMC found a genuine counterexample", `PROVEN-BMC` = "no
counterexample within k steps"), code that predates this validation
exercise by an entire prior project phase and was never touched to
produce these results. A true fix mechanically cannot produce a
counterexample against golden (it IS golden, or a byte-identical
reconstruction of it); a wrong fix, built from a mutant already
formally proven to diverge from golden, mechanically must produce one
within the same bound that originally found it. The expectation was
derivable — and was derived — before running anything.

**`benchmarks/verify_golden.json` is captured-from-output, by
construction, and that's the correct design for what it's for.**
`scripts/verify.py --freeze` does exactly one thing: run the stub
conditions and serialize whatever came out as `benchmarks/verify_golden.json`.
There is no hardcoded expectation anywhere in `verify.py` — its job
(Phase 3) is a fast regression check ("does this machine's toolchain
reproduce the same result as before"), not independent semantic
validation. Freezing a golden file from a single run is standard
practice for that job, but it means the golden file, on its own, cannot
tell a reader whether the captured value was ever independently checked
to be *correct*, only that it's *reproducible*.

**Cross-checked directly, not assumed: they agree.**
`verify.py`'s C2 case reuses `fsm_constant_perturbation_005` and
`verdict_ladder_validation.py`'s C2 row uses the same task; `verify.py`'s
C3 case reuses `uart_constant_perturbation_005`, matching this
document's C3 row for that task — both scripts call the identical
`_region_true_fix`/`_pick_donor`/`FixedPatchProvider` functions (`verify.py`
imports them directly from `scripts/verdict_ladder_validation.py` rather
than reimplementing). Compared field-for-field:

| source | task | final_verdict | raw ladder verdict | divergence_cycle |
|---|---|---|---|---|
| `verdict_ladder_validation_report.json` (semantics-first) | fsm_constant_perturbation_005 (C2) | `PLAUSIBLE` | `PROVEN-BMC` | — |
| `verify_golden.json` (captured) | fsm_constant_perturbation_005 (C2) | `PLAUSIBLE` | *(not recorded in this file)* | — |
| `verdict_ladder_validation_report.json` (semantics-first) | uart_constant_perturbation_005 (C3) | `REFUTED` | `REFUTED` | `2` |
| `verify_golden.json` (captured) | uart_constant_perturbation_005 (C3) | `REFUTED` | *(not recorded in this file)* | — |

**No disagreement — nothing to stop for.** The captured golden file's
`final_verdict` values match the independently semantics-derived
expectations exactly, for both tasks. This is expected given both
scripts share the same underlying functions and were run against the
same, unmodified `check_patch`/`check_bmc` — it is not a coincidence,
but it also isn't a substitute for having done the semantics-first
check at all; a future change to the ladder that broke C2/C3 silently
and consistently (e.g., a bug in *both* scripts' shared helper
functions) could still pass `make verify` while being wrong, since a
regression check can only catch drift from its own frozen baseline, not
an error the baseline itself already contains. That is a standing
limitation of `verify.py`'s design, not a defect found here — flagged
so it isn't mistaken for a stronger guarantee than it is.
