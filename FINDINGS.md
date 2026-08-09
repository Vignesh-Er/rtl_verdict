# FINDINGS.md

Running log of non-obvious things discovered by actually running the tools,
not by reading documentation. Append, don't rewrite — each entry is dated by
session, not edited away when superseded (mark superseded entries explicitly
instead).

**Resume line:** built a formally-gated RTL mutation-testing harness and
found, on real designs, that a design's own testbench misses 13.6%–72.2%
of formally-confirmed bugs depending on the design, and that 49.1% of
naively-generated mutation candidates — including 95.2% of the single
largest operator class, the textbook `=`-vs-`<=` mistake — are formally
equivalent to golden, not bugs at all. Everything below is the log of how
those numbers (and the tooling that produced them) were actually verified,
including every place a first answer turned out to be wrong.

---

## Environment / toolchain

- **yosys.exe fails to load (`libreadline8.dll` not found) unless
  `oss-cad-suite/lib/` is on PATH, not just `bin/`.** The suite's own
  `environment.bat` confirms this. `rtlverdict/env.py` centralizes the fix.
- **eqy and Verilator's `--binary` mode both shell out to `make`**, which is
  not bundled in oss-cad-suite on Windows. Fixed this session with a shim
  copied from an existing `mingw32-make.exe` on the dev machine — not a
  general solution; `setup_env.ps1` must provision one on a clean install.
- **Verilator's path auto-detection has a build-time POSIX path baked in**
  (`/yosyshq/share/verilator/...`) that doesn't exist on Windows. Fixed by
  setting `VERILATOR_ROOT` explicitly.
- **MCY (`mcy run`) is broken on native Windows, not fixable via PATH/env.**
  Its task launcher does `subprocess(cmd, shell=True)` with a bash-syntax
  command string (`export TASK=...; cd ...; bash script.sh`). Windows
  `shell=True` always invokes `<COMSPEC> /c <cmd>` — hardcoded `/c`, not
  bash's `-c`. Pointing `COMSPEC` at bash.exe doesn't help; Python still
  appends `/c`, which bash doesn't understand, producing nonsense argument
  parsing. Requires patching mcy.py's subprocess calls to `["bash", "-c",
  cmd]` explicitly — out of scope. **Cut from this project's scope per
  standing decision rule.**
- **Docker is not installed on the dev machine**, nor is WSL2. Installing
  either is a real system-level change (admin rights, likely reboot) —
  flagged for explicit user go-ahead, not done silently.

## Mutation mechanism (forge)

- pyslang's `SyntaxTree.fromText(src).root` re-stringifies byte-identical to
  input except a trailing-EOF-trivia newline (known, solvable edge case).
- Every `Token` exposes `.range.start.offset`/`.end.offset` — exact byte
  offsets into the original source. Splicing a replacement directly into the
  **original source text** at those offsets (not re-emitting the whole tree)
  guarantees byte-level fidelity outside the mutation window by construction.
  Verified: 0 diagnostics on re-parse, byte-identical prefix/suffix.
- `SyntaxNode.parent` is populated and walkable — needed for context-aware
  mutation operators (e.g. "is this `<=` inside a clocked always block").

## Miter construction / equivalence checking — the big one

- **A miter comparing two sequential instances needs an explicit reset
  synchronization assume** (`initial assume(!resetn)` or polarity-correct
  equivalent). Without it, uninitialized registers are independent free
  variables per instance under Yosys's formal/BMC semantics, and even two
  *identical* instances spuriously "refute." Found via a 4-bit counter
  smoke test early in the project; this is now a hard requirement.
- **`initial assume(X)` genuinely constrains step 0 only** — verified
  empirically (not by reading RTLIL, which was actively misleading; see
  below), via a cover-mode reachability test: `initial assume(q==0)` on a
  free-running register, `cover(q==5)` reachable at step 1. If the assume
  held every cycle, that would be impossible.
  - **Do not trust RTLIL's `$check` cell `EN` port to determine "initial vs
    every-cycle" semantics.** Every `initial assume` cell shows `EN=1'1`
    (unconditional) in the post-`prep` RTLIL, with zero `$initstate` cells
    anywhere in the design. This looks exactly like "applied every cycle."
    It isn't — the initial-only semantics must be carried through a
    different mechanism (likely the `PRIORITY` parameter, all-ones, used
    during `yosys-smtbmc`'s SMT2 unrolling, not visible in the single-frame
    RTLIL template). **Lesson: when static inspection and dynamic behavior
    might disagree, build a discriminating experiment — don't trust the
    static read.**

### picorv32 golden-vs-golden: substantial unresolved investigation

State alignment via manual/mechanical name-matched assumes was tried
extensively and **abandoned as a dead end**, not because any single attempt
was wrong, but because the whole approach doesn't generalize to `verdict/`
(golden vs. an *agent's patch* — renamed registers, restructured logic — has
no name correspondence to match against by construction). Sequence of
evidence, in order:

1. `REGS_INIT_ZERO=1` alone (zeroes memory *content* via `\INIT`) — fails at
   step 6.
2. Regfile alignment via `DEBUGREGS` debug-tap wires (Yosys's formal frontend
   rejects hierarchical indexing into a sibling instance's raw memory array —
   `AST_AUTOWIRE` error on `ref_i.cpuregs[gi]` — named wires work, array
   elements don't) — fails, narrowed to a `mem_valid` mismatch.
3. Root cause of *that* traced via a hand-built VCD divergence tool: picorv32
   deliberately assigns `<= 'bx` to ~20 registers (`reg_op1`, `alu_out`,
   etc.) as an intentional don't-care verification hint. Under BMC this makes
   each instance's copy an independent free variable.
4. Mechanically enumerated all 161 real flip-flops via RTLIL inspection
   (not simulation-derived guessing) and aligned all of them at t=0 — **got
   worse**, not better (divergence moved from step 6 to step 1).
5. **T1 (ran MCY's actual upstream reference miter structure, unmodified in
   spirit, against vanilla picorv32.v)**: fails identically at step 6, with
   or without the regfile-latch alignment. This is decisive: it is not a bug
   in this project's miter-construction code, since even the reference
   structure fails the same way against an un-mutated design.
6. Reset-hold sweep (hold `!resetn` for N cycles instead of just step 0,
   the cheapest form of sim-seeding): N=1 matches baseline. **N=2/4/8/16 all
   produce `PREUNSAT`** ("assumptions are unsatisfiable") at step 1 — not a
   real answer. Isolated via three clean tests (hold-counter logic alone in
   cover mode: works; same logic in BMC mode: works; same logic with two
   plain module instances sharing resetn: works) that the PREUNSAT is
   specific to picorv32's own complexity, not the hold-pattern, BMC mode, or
   dual-instantiation in general. **Root cause not found. Time-boxed and
   parked** — nerv is the other Tier B design; Tier B is a "defend against
   easy-designs-only" argument, not required for D7.

**Current status: picorv32/nerv Tier B golden-vs-golden is UNRESOLVED.**
Tier A (fsm, uart, spi_master, fifo) is fully resolved and green — see below.
This is a genuine open problem, not a workaround-in-progress.

## T2: Tier A bisection (fsm → uart → spi_master → fifo)

All four PASS golden-vs-golden with nothing but a plain reset assume, at
BMC depth 40 (fifo at depth 10 — see below). **This resolves the "did we
just write designs our own mutator handles well" objection for the miter
mechanism specifically**: the bisection's actual first failure is nerv, not
any self-authored design, so the open problem is Tier-B-specific, not a
generic defect in how this project builds miters.

## FIFO: BMC + array theory scales exponentially, independent of solver

- BMC step time on an 8-deep×8-bit FIFO (64 bits of array state): steps
  0–10 near-instant, then 12→13: 21s, 13→14: 43s, then stalls. k-induction's
  basecase hits the identical wall (it's BMC-shaped under the hood).
- **Engine swap doesn't fix it**: yices, boolector, z3 all cap out around
  step 13–14 within a 60s budget (boolector fastest, z3 slowest, but none
  escape the wall).
- **`memory_map` (bit-blast to flops+muxes) roughly doubles reachable
  depth**: step 28 in 60s vs. 13–14 for plain array-theory BMC. Still short
  of the standard depth-40 tier, but a real, usable improvement.
- **Practical fix adopted**: `ladder_order: [eqy, bmc40_memory_map, kind,
  bmc200_deep]` for fifo — same principle as Tier B: induction-based
  checking (eqy) is structurally better suited to memory-containing designs
  than deep BMC unrolling.
- Refutation is far cheaper than proving (found the shallow over-constraint
  mutant at step 3, milliseconds) — this blowup affects DISCARD decisions
  (proving equivalence), not KEEP decisions (finding real bugs). Corpus
  stays valid; the quarantine pool gets fatter for this design.

## FIFO: solver non-determinism — resolved, was hashing the wrong thing

Ran the identical over-constraint check (golden vs. known shallow mutant,
`mode bmc`, yices) three times: fsm/uart/spi_master produced byte-identical
VCD hashes across 3 runs; fifo produced **three different hashes**. Initially
logged as an open determinism failure. Re-ran capturing verdict + divergence
step + failing assertion line explicitly instead of hashing the VCD: all 3
runs agree exactly (FAIL, step 3, same assertion line) — only the raw VCD
witness bytes differ (yices choosing different but equally valid values for
free-running inputs it doesn't need to pin down to prove the same point).
**Conclusion: the determinism gate must hash `(verdict, divergence_cycle,
root_cause_line)`, never raw VCD bytes.** Fixed in `fifo/design.yaml`;
`tests/test_determinism.py` must implement it this way from the start, not
retrofit it after a false alarm.

## eqy on Windows: sound proof engine, unreliable aggregation — and one
## observation making it currently unusable as a discard-decider

- **Confirmed reproducible bug, general, not memory-specific**: even a
  trivial memory-free FSM (4 registers, no arrays) fails eqy's *aggregate
  summary* step with `grep: strategies/fsm.state/sat/status: No such file or
  directory` on every partition, in the project's working directory (long
  path under `AppData/Local/Temp/...`). A short working path (`C:\rv\`)
  avoids this specific symptom on picorv32 (ran cleanly to completion, all
  459 partitions attempted).
- **More serious finding**: even with the file-not-found symptom absent
  (short path), eqy's own aggregate summary can still be wrong. Worse: on a
  **known-inequivalent** FIFO mutant (wr_ptr increments by 2 instead of 1,
  confirmed non-equivalent by BMC which refutes it at step 3), eqy's
  per-partition SAT solving *itself* — not just the buggy summary grep —
  logged `Proved equivalence of partition 'fifo.wr_ptr' using strategy
  'sat'`, and the partition's `status` file said `PASS`, for a signal that
  is demonstrably different between gold and mutant. This is eqy being
  **optimistically wrong**, the dangerous direction (would silently discard
  a real bug from the corpus), not just pessimistically wrong (the
  file-not-found symptom, which only causes over-cautious quarantining).
- **Consequence**: neither per-partition status files nor eqy's own
  "Proved equivalence" log lines can be trusted to derive an EQUIVALENT
  verdict. `rtlverdict/verdict/eqy_parser.py` implements this conservatively:
  it never returns EQUIVALENT except from a clean aggregate `DONE (PASS...)`
  line, which has not been observed even once on this machine, on any of
  five tested designs (trivial counter, fsm, uart, spi_master, fifo,
  picorv32) — including cases known to be genuinely equivalent. **The eqy
  discard tier is currently non-functional on this Windows setup**: it can
  quarantine but can never confirm equivalence. This is sound (no real bugs
  silently lost) but not a working ladder tier as shipped.

### Characterized: eqy false-proves on 4/4 Tier A designs, not just fifo

Ran eqy golden-vs-mutant on all four Tier A designs, using the same
known-refutable mutants the over-constraint checks use (BMC-confirmed
refutation at steps 7/3/17/3 for fsm/uart/spi_master/fifo respectively):

| design | BMC verdict | eqy per-partition | eqy aggregate |
|---|---|---|---|
| fsm (no memory) | NON-EQUIV @ step 7 | ALL 4 partitions PASS (false) | FAIL (coincidental, via grep bug) |
| uart (no memory) | NON-EQUIV @ step 3 | ALL 5 partitions PASS (false), incl. the mutated signal `uart.tx` itself | FAIL (coincidental) |
| spi_master (no memory) | NON-EQUIV @ step 17 | 6/7 PASS (false), 1 `UNKNOWN` | FAIL (coincidental) |
| fifo (has memory) | NON-EQUIV @ step 3 | ALL 8 partitions PASS (false) | FAIL (coincidental) |

**4/4. This rules out the memory-array hypothesis entirely** — fsm has zero
memory and still false-proves on every partition, including the literal
mutated signal. Sanity-checked that this isn't a config mistake: `gate.log`
confirms eqy actually read the mutated source file (`fsm_mutant_shallow.v`,
cell names reference the mutated line) for each case, not golden.v twice.

**This is eqy's per-partition SAT strategy being optimistically wrong on
this Windows setup, systematically, not occasionally.** The aggregate
summary happening to say FAIL on all 4 cases is not eqy "getting it right at
the top level" - it's the unrelated grep-file-not-found bug defaulting to
failure, which is safe by accident, not by correct reasoning.

**Ladder rule adopted, permanent, not a Windows-only workaround**: eqy's
EQUIVALENT verdict is never accepted to make a DISCARD decision unless BMC
k=40 has already failed to refute first. BMC-refutes always overrides
eqy-proves, unconditionally. This must be a hard precondition in
`ladder.py`, not a convention someone can accidentally skip.

**Next step**: Docker/Linux cross-validation (planned, blocked on Docker
install - see Environment section) to determine whether this is a
Windows-specific build issue (file upstream with YosysHQ - the FIFO case
alone is already a clean, minimal, reportable bug: 1-line mutation, step-3
BMC counterexample, eqy says proved) or a general eqy `sat` strategy issue
that would also affect a Linux run of record.
- Docker/Linux cross-validation not yet run (Docker unavailable on dev
  machine, see above) — this is the next step to determine whether the
  aggregation bug is Windows-specific (file an upstream YosysHQ issue if so)
  or general (parser stays load-bearing everywhere).
- **Fallback adopted, decided in advance rather than under pressure**: if
  eqy cannot be made trustworthy on either platform, the ladder runs
  BMC-only and everything unrefuted quarantines. Sound, shippable, honestly
  documented as a limitation.

## eqy control test: invocation is broken, not eqy (P0, follow-up session)

Built a control case: golden `fsm` vs. a gate module with every output
hardwired to constant 0 (unmistakably non-equivalent). At depth 10, eqy
correctly returned `UNKNOWN` (not a false PASS). At depth 40, it returned a
confident `PASS`/"Induction step proven: SUCCESS!" - a soundness-level false
proof on the most extreme possible test case. Traced partway into the
mechanism: `combine.log` confirms gold and gate genuinely stay separate
cells (not a name-collision collapse); each partition's `.sby` script runs
`setundef -anyseq gate.fsm.<signal>` before solving, and the comparator has
a documented `in_gold[i] === 1'bx` vacuity escape. Leading hypothesis, not
proven: an empty/under-populated partition slice interacting with that
escape. Per explicit decision: **not filing an upstream issue until this is
better understood** - the invocation is the suspect, not eqy itself.

## D4: witness core (vcd.py, diff_traces.py, run_test.py, wave_query.py)

Hand-rolled VCD parser, verified against real Icarus-generated traces
(exact values confirmed by hand at three timestamps before trusting it for
anything downstream). One real bug found running the actual gate: two
sequential `_compile_and_dump` calls into a shared directory produced an
ambiguous glob match on the second call (it found the first call's
already-renamed output too, since both calls' testbenches dump to the same
filename) - fixed by isolating each call to its own temp directory.

**Gate result: 10/10 real KEEP tasks from corpus_v1 show a genuine,
correctly-detected first divergence** with sensible signal/expected/actual
triples. Sim-side cycle numbers differ from the formal ladder's
`divergence_cycle` by a small constant offset (+1 or +2, one exact match) -
expected, not a bug: BMC's adversarial search and the testbench's own
multi-cycle reset sequence are different notions of "cycle 0."

## D5: coi.py (AST backward slice) + suspect_rank.py

**Real bug found and fixed via the containment gate, not by inspection**:
the first version tracked an enclosing condition's *read signals* but not
the condition's *own source line* - silently dropping control-dependency
lines from the slice whenever that line never itself assigns anything
(e.g. `if (bit_index == 3'd7)` gating an increment in the else branch).
Gate was 90% (9/10) before the fix, 100% (10/10) after. Full detail and the
known-imprecision list in `docs/coi_soundness.md`.

`suspect_rank.py` (COI ∩ pre-divergence toggles, ranked by proximity) has a
confirmed, documented limitation: a VCD records when a signal changed, not
which of several lines that can write it actually fired, so same-signal
writes tie in score. The true root cause is always in the tied top group
(consistent with 100% containment), just not uniquely ranked first -
breaking ties needs per-statement execution tracking, not yet built.

## Testbench self-checking

- **Neither upstream Tier B testbench self-checks.** picorv32's
  `testbench_ez.v` and nerv's `testbench.sv` both just run a program and
  `$finish` unconditionally — no PASS/FAIL determination at all. picorv32's
  *other* testbench, `testbench.v`, does self-check (`"ALL TESTS PASSED."`)
  but requires a compiled `firmware/firmware.hex`, which requires a RISC-V
  GCC cross-compiler toolchain **not currently installed** — a new,
  unverified dependency. Per project rule (wrap, don't edit upstream): a
  wrapper testbench needs writing for Tier B; not yet done.
- **Reset-release race**: setting `rst_n=1` with a blocking assign at the
  same `posedge clk` the DUT samples it is simulator-order-dependent — found
  via a false FAIL on a trivial counter testbench early in the project.
  Fixed by releasing on `negedge clk` instead. Codified as a hard rule in
  `designs/CONTRACT.md`, not a style preference.

## Day-9 pivot: agent-evaluable corpus size, deep-BMC promotion, fifo, SIM-INVALID

Prompted by an external review of the D8 plan: the 132-task corpus_v2 has
only 34 agent-evaluable tasks (KEEP), not 132 — SILENT has no failing test
to hand an agent, QUARANTINE has no confirmed ground-truth bug. 34 (~11 per
design) is too small for a defensible arm-A-vs-arm-B comparison.

**P0 (deep BMC k=200 on all 69 QUARANTINE mutants): 0 promotions — a real
negative result.** `forge/deep_bmc_promote.py` re-ran every QUARANTINE
mutant from fsm/uart/spi_master at k=200 (vs the original k=40), timeout_s
150. 68/69 resolved cleanly well under timeout (mostly PROVEN-BMC; none
near-timeout - the "80%-of-timeout stays QUARANTINE" rule never had to
fire), 1/69 stayed the same INDETERMINATE as before per design (the
`edge_swap` mutants - 3 total across the 3 designs, one each - already
flagged as an open pattern in `coverage_vs_silent_bugs.md`). Total wall
time 862s. Conclusion: these 69 are not solver-timeout victims sitting on
undiscovered deep bugs - deeper search does not change their verdict. The
`blocking_nonblocking_swap` operator in particular dominates this
QUARANTINE pool (roughly two-thirds of the 69) and appears to frequently
produce genuinely-equivalent mutants on these specific designs at these
specific mutation sites - a real instance of the "equivalent mutant"
problem well known in software mutation testing, now observed in RTL.
Deep-BMC promotion contributes 0 toward the 60-task target; more KEEP
tasks have to come from somewhere else (fifo, or more mutants).

**Real bug found while building fifo support: `verdict/miter.py`'s
`extract_ports` did a naive text-copy of a port's width declaration,
which silently breaks for parameterized widths** (e.g. fifo's `[WIDTH-1:0]`
where `WIDTH` is a module parameter) - the generated miter module has no
access to the design's own parameter scope, so a raw `[WIDTH-1:0]` in the
miter references an undefined identifier. Never manifested on fsm/uart/
spi_master because none of them have a parameterized port width. The
earlier hand-verified `designs/fifo/fifo_gg_memmap.sby` worked around this
by hardcoding `[7:0]` directly in a hand-written `fifo_miter.sv`, rather
than fixing the generator - meaning the bug was latent and un-fixed until
this pass. Fixed properly (not per-design special-cased): `extract_ports`
now resolves `parameter`/`localparam` numeric defaults and substitutes them
into the width expression, evaluating simple arithmetic
(`WIDTH-1` with `WIDTH=8` -> `7`); an expression that still references an
unknown identifier after substitution is left unchanged, so a genuinely
unresolvable width fails loudly at miter elaboration rather than silently
producing a wrong-width comparison. Verified: fifo now resolves to `[7:0]`
matching the hand-written version exactly; fsm/uart/spi_master's port
extraction is byte-for-byte unchanged (regression-checked).

**Re-verified the fix did not silently invalidate the already-committed
corpus_v2 (fsm/uart/spi_master).** This is the third latent bug in a row
where a hand-verified workaround (the hardcoded `[7:0]` in
`fifo_gg_memmap.sby`) masked a generator defect - "these three designs have
no parameterized ports so the fix can't affect them" is exactly the kind of
reasoning that let the bug hide for days, so it was checked rather than
assumed. `scratch_verify/reverify_corpus_v2_miter_fix.py` re-ran BMC (same
k=40/timeout_s=60 as the original generation) on 15 sampled tasks (7 KEEP,
8 QUARANTINE, all 3 designs) using the CURRENT miter.py and diffed against
the recorded verdict in `tasks.json`. **15/15 matched exactly.** corpus_v2
does not need regeneration.

**Real bug found live, not by inspection: `subprocess.run(timeout=...)` on
Windows does not kill sby's process tree, only sby.exe itself - a "timed
out" BMC check leaves the real work (`yices-smt2`, spawned via
`sby-script.py` -> `yosys-smtbmc-script.py`) running in the background
indefinitely.** Caught because the first fifo mutation-corpus generation
run (39 candidates, k=25/timeout_s=90) was still going after 22+ minutes
with visibly near-zero CPU on the driving Python processes - `Get-CimInstance
Win32_Process` showed a `yices-smt2.exe` with ~1028s of accumulated CPU
time and a process tree (`sby-script.py` -> `yosys-smtbmc-script.py` ->
`yices-smt2.exe`) whose immediate parent PID no longer existed - i.e. the
top-level `sby.exe` Python's timeout killed HAD already been reaped, while
its own descendants kept running unbounded. Each subsequent candidate's
BMC check then had to compete for CPU with every orphan accumulated so
far, which explains the runaway wall-clock time directly (fifo's checks
are exactly the slow, near-timeout-prone kind where this bug bites hardest
- fsm/uart/spi_master's checks are fast enough that none had timed out yet
in this project's history, so this had never manifested before).

**Already-committed results checked and unaffected**: the k=200 deep-BMC
promotion pass (69 mutants) never hit this path - max observed runtime
across all 69 was 22.5s against a 150s timeout, and the 3 INDETERMINATE
verdicts (the `edge_swap` pattern) resolved in ~1.2s each from an
unrecognized-log-shape fail-closed classification, not a subprocess
timeout. corpus_v2's original generation likewise shows no evidence of
having hit a real timeout. This bug is new-this-session (only triggered by
fifo's memory_map-heavy, near-timeout-prone checks) and does not retroactively
put any already-reported number in question.

**Fixed at the root**: `ladder.py`'s `_run_sby` switched from
`subprocess.run(..., timeout=...)` to `subprocess.Popen` + `.communicate
(timeout=...)`, and on `TimeoutExpired` now calls `taskkill /F /T /PID
<pid>` before re-raising - `/T` kills the whole descendant tree, not just
the one PID Python held a handle to. Verified live: cleaned up the
already-orphaned processes from the aborted fifo run (confirmed zero
`yices`/`yosys`/`sby` processes remaining via `Get-Process`), then
deliberately forced a fast timeout (fifo golden-vs-golden, k=25,
timeout_s=5) and confirmed `check_bmc` returns promptly AND leaves no
surviving solver process behind. Full pytest + agent-module verification
suites re-run clean after the change.

**Added a permanent pre-flight guard (`env.sweep_orphaned_solvers()`), and
immediately made the exact mistake it exists to prevent - which is itself
useful evidence for how this bug class actually bites.** The guard kills
any `yices-smt2`/`yosys-smtbmc`/`boolector`/`z3`/`sby.exe` process found
running, on the reasoning that nothing legitimate should be running yet at
a batch's start. Its own docstring says "never mid-batch, since a
legitimate in-flight check from the same run would look identical to a
stray and get killed too" - and then it was tested by calling it directly
while the (freshly-relaunched, clean) fifo generation run was still
active in the background. It killed that run's own live BMC check,
indistinguishable from a stray by design, because it *is* one from the
sweep's point of view.

**Diagnosed and bounded the damage without guessing.** `check_bmc` fails
closed on anything ambiguous (an abruptly-killed process leaves a partial,
unparseable log; the code never reads that as REFUTED or PROVEN-BMC, only
INDETERMINATE per its own "never guess" rule) - so the reasoning was: (a)
the kill could only have hit a candidate mid-BMC (sim/fidelity checking
uses Icarus, not sby/yosys/yices, so those phases were never at risk), and
(b) the only possible corrupted outcome is a spurious extra INDETERMINATE,
never a fabricated KEEP/SILENT/REFUTED. That narrowed the suspects to
exactly the run's two INDETERMINATE results. Re-checked both fresh:
`fifo_blocking_nonblocking_swap_023` reconfirmed INDETERMINATE (genuine
90s timeout, a real hard case) - `fifo_blocking_nonblocking_swap_026` came
back **PROVEN-BMC in 36.6s**, confirming it was the corrupted one. Corrected
that single record (verdict, runtime, discard_reason); `forge_decision`
was unaffected either way (INDETERMINATE and PROVEN-BMC both map to
QUARANTINE), so the corpus-wide accounting was never wrong, only one
task's internal formal-verdict detail.

**Lesson, stated plainly**: writing the safety mechanism is not the same
as using it safely, and "this is a pre-flight-only function, see the
docstring" is exactly the kind of comment-as-safeguard this project has
learned not to trust. The fix is procedural, not code: never invoke
`sweep_orphaned_solvers()` (or run any other subprocess-spawning script)
while a batch is confirmed to be in flight - the four wired call sites
(inside each batch script's own `main()`) are the only sanctioned call
pattern; ad hoc interactive calls against a live background run are not.

**fifo needs memory_map, and even with it, k=40 is not reliably reachable.**
`design.yaml` already documented the constraint (plain BMC blows up around
depth 12-14 on `mem[]`'s array theory regardless of solver backend; with
Yosys's `memory_map` pass — converting memories to registers/muxes before
BMC — reachable depth roughly doubles but "still short of the standard
depth-40 tier"). Added `memory_map: bool` to `ladder.py`'s `check_bmc`
(inserts `memory_map` right after `prep -top miter`, matching the
hand-verified recipe in `fifo_gg_memmap.sby` exactly). Empirically
confirmed the constraint is real, not just documented: golden-vs-golden at
k=40 with memory_map timed out at 120s without resolving - reaching depth
40 specifically is harder than the yaml's own "depth 28 in 60s" estimate.
fifo's practical corpus-generation depth had to be calibrated down from the
other three designs' k=40, not assumed - see the calibration run and the
depth actually used in the corpus_v2 fifo-addition report.

**P2: SIM-INVALID = 0 across 132 mutants is NOT a wiring bug - confirmed by
direct test, not assumption.** `scratch_verify/sim_invalid_probe/run_probe.py`
deliberately forced (1) a syntactically broken DUT and (2) a DUT+testbench
that hangs via a zero-delay infinite loop (`while(1) #0;`, never advances
simulation time). Both correctly report `SIM-INVALID` with the expected
detail (`"compile failed: ..."` and `"sim exceeded 5s (hang)"`
respectively) - the category fires correctly on both the compile-fail and
timeout paths; neither is silently absorbed into PASS/FAIL. The real
explanation for the 0 count: every mutation operator in this project
(`operator_swap`, `constant_perturbation`, `blocking_nonblocking_swap`,
`edge_swap`, `signal_substitution`, `next_state_redirect`) performs a
surgical, syntax-preserving substitution on an already-valid token/constant/
signal/edge - none of these classes is the *kind* of transformation that
tends to produce a parse error or an infinite hang, and any mutant that
somehow did break parsing would already be caught and rejected by
`check_fidelity`'s "must re-parse with 0 diagnostics" gate before ever
reaching `run_sim` (recorded as ERROR, not silently reclassified as
SIM-INVALID). SIM-INVALID=0 is a property of this operator set, not a
broken code path.

## Parked / unquotable

Figures that must never appear in README, the dashboard, the paper
skeleton, or slides without their scope caveat attached — parked here so
they can't leak by being copied from an old doc without context.

- **COI containment ("10/10 contained").** Both source documents —
  `docs/validation/containment_by_operator_class.md` and
  `docs/validation/coi_soundness.md` — are historical: measured on
  `probe_signal_fsm` (a 10-task probe corpus) and `corpus_v1`
  respectively, neither of which is the current corpus (`corpus_v2` +
  the fifo addition, 171 tasks). Both carry a `stats-scope: historical`
  header and are excluded from the bare-integer sweep in
  `test_stats_consistency.py` for exactly this reason. **COI containment
  has not been re-measured on the current 171-task corpus.** Any claim
  of "COI backward slices contain N/N known-divergence signals" on the
  current corpus is unquotable until that measurement is re-run against
  `corpus_v2`/fifo and produces a fresh, non-historical result.
