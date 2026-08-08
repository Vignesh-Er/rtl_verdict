# rtlverdict — PLAN.md

Status: DRAFT for approval. Nothing in `rtlverdict/` has been written yet.
Everything under "Verified" below was actually executed on this machine today
(2026-08-08); nothing is asserted without a real run backing it.

---

## 0. Environment verification (executed, not assumed)

Platform: Windows 11 (build 26200), no WSL installed. Shells available: PowerShell 7
and Git Bash / MSYS2 (`C:\Program Files\Git`). Project root: `E:\Hackathon\claude_proj`
(50GB free on E:). Python 3.12.10 at `C:\Program Files\Python312`; project venv created
at `E:\Hackathon\claude_proj\.venv`.

**Toolchain**: no RTL tools were preinstalled. Installed YosysHQ's official
`oss-cad-suite-windows-x64-20260808` build (591.5MB download, 2.1GB extracted, to
`C:\Users\vigne\tools\oss-cad-suite`, outside the repo). Real version strings, captured
just now:

| Tool | Version |
|---|---|
| Yosys | `0.68+40 (git sha1 0f2bcb94b-dirty, Release)` |
| SBY (SymbiYosys) | `v0.68` |
| EQY | `v0.68` |
| MCY | runs (no `--version` flag exposed; CLI responds) |
| Icarus Verilog | `14.0 (devel) (s20260301-349-gf49307688-dirty)` |
| Verilator | `5.051 devel rev v5.050-150-g7e80ea657` |
| Z3 | `4.15.5 - 64 bit` |
| Boolector | `3.2.4` |
| Yices | `2.7.0` |

Every tool required by the brief ships as a native Windows `.exe` in this build —
**no WSL is needed**. One real gotcha found and fixed: `yosys.exe` initially failed
with `libreadline8.dll: cannot open shared object file` because that DLL lives in
`oss-cad-suite/lib/`, not `bin/`. The suite's own `environment.bat` confirms the fix:
PATH must include both `bin` and `lib`. This will be wrapped in one `rtlverdict/env.py`
helper so no module reinvents it (Risk 3 below).

**Python side**: `pyslang==11.0.0` installs cleanly from PyPI on Python 3.12/Windows
(prebuilt wheel, no compiler needed). `ruff`, `pytest`, `matplotlib`, `numpy` all
install cleanly.

**End-to-end smoke test** (`scratchpad/smoketest/`, not part of the repo): wrote a
4-bit counter (`golden.v`) and a one-line mutant (`count+2'b10` instead of `+1'b1`),
built a two-instance miter, and ran the real ladder:

- `sby` + `smtbmc yices`, mode `bmc`, depth 10: golden-vs-mutant → **FAIL** with a real
  counterexample VCD at step 2 (yices genuinely solved it). Golden-vs-golden → **PASS**,
  no counterexample through depth 10.
- Icarus (`iverilog`+`vvp`): golden → **PASS** (8/8 cycles), mutant → **FAIL** at cycle 0
  with wrong count. Same testbench, both paths agree.
- `yosys -p "read_verilog golden.v; synth -top counter"` → clean, 0 problems.

Two real bugs surfaced and were fixed during this test, both of which changed the plan
below, not just the scratch files:

1. **First miter attempt failed golden-vs-golden.** Cause: neither counter register has
   an explicit initial value, so under Yosys's formal/BMC semantics each instance's
   register starts as an *independent* free variable — with no reset assumption, BMC
   trivially picks mismatched initial states and "refutes" two identical modules. Fix:
   the miter needs an explicit `initial assume(!rst_n)` (polarity-correct) before any
   equivalence assertion is active. **This is now a hard requirement in `verdict/miter.py`
   below, not an implementation detail I can skip.**
2. **First testbench reported X on both golden and mutant.** Cause: a classic
   reset-release race — deasserting `rst_n` with a blocking assign at the same posedge
   the DUT samples it is simulator-order-dependent. Fixed by releasing reset on a
   `negedge` instead. This is now a documented rule for every self-authored testbench
   in the corpus (Section 5).

**picorv32 specifically** (the brief's flagship D1 design): cloned `YosysHQ/picorv32`
(ISC license). `yosys -p "read_verilog picorv32.v; chparam -set REGS_INIT_ZERO 1
-set COMPRESSED_ISA 1 -set ENABLE_IRQ 1 -set ENABLE_IRQ_QREGS 0 -set BARREL_SHIFTER 1
picorv32; synth -top picorv32"` → clean, 11579 cells, 0 problems, using the exact
parameter set MCY's own example uses. `iverilog -g2005 picorv32.v testbench_ez.v`
(public-domain-licensed testbench) compiles clean. Confirmed via GitHub API that
`YosysHQ/mcy`'s own `examples/picorv32_primes/` is a real, working formal config against
this exact file — I fetched and read its `config.mcy`, `eq_bmc.sby`, and `miter.sv`
directly; the mutation semantics, `chparam` pattern, and the
`smtbmc yices / mode bmc / depth 50 / aigsmt none` engine settings in this plan's
`verdict` module are modeled on that real, working reference, not guessed.

**pyslang mutation mechanism** (the core novel piece of `forge`): verified empirically,
not assumed —
- `pyslang.syntax.SyntaxTree.fromText(src).root` re-stringifies byte-identical to the
  input (only a trailing-EOF-trivia newline differs — a known, solvable edge case).
- Every `Token` exposes `.range.start.offset` / `.range.end.offset` — exact byte offsets
  into the original source buffer.
- Splicing a replacement string directly into the **original source text** at a token's
  offset (rather than asking pyslang to re-emit the whole tree) leaves every byte outside
  the mutation window provably untouched, and the result re-parses with 0 diagnostics.
  This means byte-level fidelity (comments, whitespace, formatting) is guaranteed **by
  construction**, not by trusting a reprinter — which sidesteps the trailing-newline
  quirk above entirely, since unchanged regions are never regenerated.
- `SyntaxNode.parent` is populated and walkable (confirmed by locating a
  `ProceduralBlockSyntax` and reading `.parent`), which both the TIMING/FSM mutation
  operators (need to know "is this `<=` inside a clocked always block") and
  `witness.coi` (AST-based backward slicing, see Section 6 deviation) depend on.

Nothing above is a projection — it's what actually happened when I ran it.

---

## 1. Decisions locked in during verification

These aren't in the brief explicitly; I made them while verifying the environment and
am flagging them for your approval rather than burying them in code later.

1. **Toolchain lives outside the repo**: `C:\Users\vigne\tools\oss-cad-suite` (2.1GB,
   not committed). The repo will ship `scripts/setup_env.ps1` and `scripts/setup_env.sh`
   that download+extract it and create `.venv`, so `make demo` from a clean clone still
   works — it just needs that script run once first. I'll say this plainly in the README
   rather than pretending a 2GB binary toolchain ships in git.
2. **Design corpus sourcing**: picorv32 is pulled from upstream `YosysHQ/picorv32`
   (ISC license) as-is — it's the one the brief specifically anchors to MCY's own
   example, and I've now confirmed both halves of that claim for real. For the other
   four (UART, FIFO, SPI master, FSM), I'm **authoring minimal original designs myself**
   (MIT-licensed, ~60-150 lines each) rather than importing third-party repos. Reason:
   it guarantees Verilog-2005-only compliance, guarantees Yosys-clean synthesis,
   guarantees a self-checking testbench I actually trust (see the reset-race bug above —
   I don't want to inherit that class of bug from an unvetted third-party testbench),
   and avoids the exact failure mode the brief's own D1 gate warns about ("if one fights
   you, DROP IT — do not debug someone else's Verilog"). Writing four small peripherals
   from a known-good template is a bounded, controllable task; debugging an unfamiliar
   stranger's UART is not.
3. **`forge`'s formal filter is not a separate implementation** — it's a direct call
   into `verdict`'s ladder (Section 6). The brief describes them as two components with
   overlapping mechanics (miter + sby BMC appears in both); I'm collapsing that into one
   shared code path so there is exactly one place that knows how to build a miter and
   run the ladder. This is both less code and closes the soundness gap discussed as
   "the one thing" below.
4. All subprocess orchestration goes through Git Bash, not raw PowerShell/cmd. Concrete
   reason, not superstition: MCY's own reference example (`config.mcy`) invokes its test
   scripts as `run bash $PRJDIR/sim_simple.sh` — the upstream tooling itself assumes
   `bash` is on PATH, even on the Windows build. Git Bash is already present on this
   machine, so `rtlverdict/env.py` will assert it's resolvable at startup and fail loudly
   if not, rather than mysteriously failing three subprocess calls deep.
5. Timing metric is wall-clock everywhere. `sby`'s own summary output literally prints
   `Elapsed process time unvailable on Windows` [sic, upstream's typo] — CPU-time isn't
   available on this platform, only wall-clock. Every `runtime` field in every schema
   below is wall-clock seconds, consistently, so numbers are comparable across the
   codebase instead of silently mixing metrics.

---

## 2. Repo layout (file-by-file)

```
rtlverdict/
  designs/
    picorv32/            design.yaml, picorv32.v (upstream, ISC), testbench_ez.v (upstream), Makefile
    uart/                design.yaml, uart.v (ours, MIT), tb_uart.v, Makefile
    fifo/                design.yaml, fifo.v (ours, MIT), tb_fifo.v, Makefile
    spi_master/          design.yaml, spi_master.v (ours, MIT), tb_spi_master.v, Makefile
    fsm/                 design.yaml, fsm.v (ours, MIT), tb_fsm.v, Makefile

  rtlverdict/
    __init__.py
    env.py                  # PATH/env setup for oss-cad-suite (bin+lib), asserts bash resolvable
    manifest.py             # loads/validates designs/<name>/design.yaml (shared by forge+verdict+witness)

    forge/
      __init__.py
      parser.py              # pyslang wrapper: parse(path), token/node walkers with parent links
      operators/
        __init__.py           # MutationCandidate dataclass + operator registry
        logic.py               # operator swap, condition inversion, constant perturbation
        timing.py               # blocking<->nonblocking, posedge<->negedge, reset dropped from sensitivity
        spec.py                  # reset polarity flip, reset value change, off-by-one, loop bound < <->
        interface.py              # handshake break, port width truncation
        fsm.py                     # state encoding change, next-state redirect, missing default, dropped branch
        signal.py                   # substitute in-scope signal of identical width
      mutate.py              # seeded pick of 1 candidate, byte-offset splice, write mutant file
      sim_confirm.py          # run design's real testbench on golden (must PASS) and mutant (must FAIL)
      corpus.py               # orchestrator: generate -> verdict.check() filter -> sim_confirm -> task JSON
                               # resumable: cache keyed by (design, operator, candidate_hash)
      cli.py                  # `rtlverdict forge --design X --n-per-operator K --seed S`
      tests/

    witness/
      __init__.py
      vcd.py                  # hand-rolled VCD parser (own format reader, no gtkwave dependency)
      elaborate.py             # modules/ports/hierarchy/always-blocks/inferred clock+reset
      run_test.py               # runs testbench, first-divergence-only summary
      wave_query.py               # value_at / transitions / window over vcd.py
      diff_traces.py                # earliest divergence between two VCDs
      coi.py                          # cone_of_influence: AST-based backward slice (see Section 6)
      suspect_rank.py                  # COI lines ∩ pre-divergence toggles, ranked
      mutation_score.py                 # shells out to real mcy.py, parses its report
      schemas.py               # typed result shapes, single source of truth (also used by mcp/)
      cli.py                  # `rtlverdict witness <tool> --design X ...`, JSON on stdout
      tests/

    verdict/
      __init__.py
      miter.py                # golden+mutant -> merged design (rename/stash/copy-from pattern, proven above)
                               #   + mandatory reset-synchronizing assume (bug #1 above)
      sby_templates.py         # generates .sby for bmc / eqy / k-induction tiers
      ladder.py                # check(golden, mutant, manifest, k=40) -> VerdictResult
                               #   tries BMC (primary) -> eqy -> k-induction, per the brief's order
      counterexample.py        # extracts sby's trace.vcd into witness's wave JSON format
      cli.py                  # `rtlverdict verdict --golden a.v --mutant b.v --design X`
      tests/

    agent/
      __init__.py
      loop.py                 # ~200-line model-agnostic loop (Anthropic default, OpenAI-compatible via base_url)
      arms.py                  # A baseline / B +witness / C +verdict retry / D +suspect_rank proactive
      tools.py                  # tool-use schema wrapping witness's CLI for both API shapes
      trajectory.py              # full logging: iterations, tokens, wall time, seed
      cli.py                  # `rtlverdict agent --task X --arm B --model claude-...`
      tests/

    eval/
      __init__.py
      runner.py                # experiment matrix driver, resumable
      metrics.py                 # plausible@1, proven@1, gap, refuted rate, localization top-1/5, cost
      charts.py                   # matplotlib, breakdowns by bug_class and design
      cli.py                  # `rtlverdict eval --arms A,B,C,D --tasks benchmarks/corpus_v1`
      tests/

    mcp/
      __init__.py
      server.py                # MCP server exposing witness/* as tools
      tests/

  benchmarks/                # generated task corpora (JSON + RTL), checked in once non-empty
  results/                   # experiment CSVs + charts + exact command that produced them
  docs/
    architecture.md            # written at D9
    scope_and_limitations.md    # Verilog-2005-only, BMC bound, module-granularity — rationale, D1
  tests/
    test_env.py                # asserts toolchain on PATH, versions parseable
  scripts/
    setup_env.ps1 / setup_env.sh
  PLAN.md  README.md  Makefile  pyproject.toml  requirements.txt
```

---

## 3. Data schemas

### `designs/<name>/design.yaml` (new — not in the brief, added because I need it)

Every downstream tool (forge, verdict, witness) needs to know a design's top module,
clock, and reset **without re-deriving it via heuristics every time**. `witness.elaborate`
still does heuristic inference (posedge/negedge + name matching) as a cross-check and as
the thing that also has to work on an *agent's rewritten patch* (which won't have a
manifest), but for corpus designs, a small hand-written manifest is authoritative:

```yaml
name: uart
top_module: uart
clock: clk
reset: rst_n
reset_active_low: true
dut_files: [uart.v]
testbench: tb_uart.v
sim: iverilog          # iverilog | verilator
chparams: {}           # e.g. picorv32: REGS_INIT_ZERO=1, COMPRESSED_ISA=1, ...
license: MIT           # or ISC for picorv32 (upstream)
```

### Task JSON (forge output, per benchmark task)

```json
{
  "task_id": "uart_logic_003",
  "design": "uart",
  "operator": "logic.operator_swap",
  "bug_class": "LOGIC",
  "mutant_path": "benchmarks/uart/uart_logic_003/mutant.v",
  "golden_path": "designs/uart/uart.v",
  "ground_truth_diff": "benchmarks/uart/uart_logic_003/mutant.diff",
  "root_cause_file": "uart.v",
  "root_cause_line": 47,
  "failing_test": "tb_uart",
  "formal_status": "REFUTED",
  "formal_tier": "bmc",
  "formal_engine": "smtbmc yices",
  "formal_k": 40,
  "formal_runtime_s": 1.8,
  "discard_reason": null,
  "seed": 20260808
}
```

`formal_status` uses the **same enum verdict/ produces**
(`PROVEN-UNBOUNDED | PROVEN-BMC(k) | PLAUSIBLE(reason) | REFUTED`) — never a bespoke
forge-only status string. `discard_reason` is set (and the task isn't emitted at all,
it goes to the discard table instead) when formal or sim confirmation fails. See
Section 6 for why `formal_status` is never allowed to silently collapse
`PROVEN-BMC(k)` into "proven, discard, don't ask."

### Discard table (forge, per-operator — "itself a result" per the brief)

CSV: `operator, candidates_generated, discarded_formal_equivalent, discarded_formal_tier_breakdown, discarded_sim_no_diff, discarded_sim_golden_fails, kept`. The
`discarded_formal_tier_breakdown` column is the direct fix for Section 6 — it records
*which* tier (BMC-bounded vs eqy/k-induction-unbounded) actually justified each discard,
so the published table doesn't quietly imply every discard was an unbounded proof.

### Witness tool I/O (compact JSON, never raw logs)

```jsonc
// run_test(design, test)
{"pass": false, "first_divergence": {"cycle": 142, "signal": "tx_busy", "expected": "0", "actual": "1"}, "summary": "diverged at cycle 142/500"}

// wave_query(vcd, "window", {"signal": "state", "t": 142, "k": 3})
{"signal": "state", "window": [{"t":139,"v":"3"},{"t":140,"v":"3"},{"t":141,"v":"4"},{"t":142,"v":"4"},{"t":143,"v":"5"}]}

// diff_traces(vcd_a, vcd_b)
{"earliest_divergence": {"cycle": 142, "signal": "tx_busy", "a": "0", "b": "1"}}

// cone_of_influence(design, "tx_busy")
{"signal": "tx_busy", "source_lines": [{"file": "uart.v", "line": 44}, {"file": "uart.v", "line": 47}, {"file": "uart.v", "line": 52}]}

// suspect_rank(design, "tx_busy", vcd)
{"ranked": [{"file": "uart.v", "line": 47, "score": 0.91, "reason": "in COI, toggled 1 cycle pre-divergence"}, ...]}

// mutation_score(design, tb)
{"score": 0.83, "mutants_total": 800, "mutants_killed": 664, "engine": "mcy"}
```

### `verdict.check()` output

```json
{
  "verdict": "REFUTED",
  "tier": "bmc",
  "engine": "smtbmc yices",
  "k": 40,
  "runtime_s": 1.8,
  "counterexample": {"vcd_path": "...", "first_divergence": {"cycle": 2, "signal": "count", "golden": "1", "mutant": "2"}}
}
```

Exactly one of `PROVEN-UNBOUNDED | PROVEN-BMC(k) | PLAUSIBLE(reason) | REFUTED`. A
timeout is always `PLAUSIBLE(TIMEOUT)` — this is a hard constraint from the brief and
it's enforced in `ladder.py`'s return type, not just convention.

### Agent trajectory log

```json
{"task_id": "uart_logic_003", "arm": "C", "model": "claude-sonnet-5", "seed": 20260808,
 "iterations": [{"n": 1, "action": "run_test", "tokens_in": 1200, "tokens_out": 340}, ...],
 "final_verdict": "PROVEN-BMC(40)", "n_iterations": 3, "wall_time_s": 41.2,
 "total_tokens": {"in": 5400, "out": 1100}}
```

### Eval metrics (CSV, per arm × design × bug_class)

`arm, design, bug_class, n_tasks, plausible@1, proven@1, plausible_to_proven_gap, refuted_rate, localization_top1, localization_top5, mean_iterations, mean_wall_time_s, mean_token_cost`

---

## 4. Build order

Following the brief's D1-D10 gates as given, annotated only where verification today
changed what happens at that gate:

- **D1** — Largely de-risked already: toolchain confirmed installed and working
  end-to-end (Section 0), picorv32 confirmed synth-clean and compile-clean. Remaining
  D1 work: write the 4 self-authored peripherals (Decision 2), their `design.yaml`
  manifests, and get all 5 green on both sim and synth. Gate unchanged: drop anything
  that fights back.
- **D2** — 6 operator classes per the brief's list, using the proven byte-splice
  mechanism (Section 0). Gate: 50 syntactically valid mutants.
- **D3** — Formal filter = `verdict.ladder.check()` reused directly (Decision 3), full
  escalating ladder, honest tier-tagged discard table. Gate: ~40 confirmed-bug tasks +
  discard table.
- **D4** — `run_test`, `wave_query`, `diff_traces` on the hand-rolled VCD parser
  (format confirmed against a real sby-generated trace today, Section 0). Gate:
  first-divergence correct on 10 known bugs.
- **D5** — `cone_of_influence` via AST backward slice (Section 6), `suspect_rank`. Gate:
  top-5 localization accuracy measured (real number, not projected).
- **D6** — Verdict ladder + counterexample extraction. Gate: all 4 verdict types
  reproduced — I already have PROVEN(equivalent) and REFUTED(with real counterexample)
  working today; PLAUSIBLE(TIMEOUT) and PROVEN-UNBOUNDED-via-eqy are the two left to
  exercise on hand-written examples.
- **D7 — MVP CUT LINE.** `rtlverdict run --design uart --arm baseline` emits a result
  JSON. Everything above this line is the non-negotiable core; I will protect this gate
  above all else given the 10-day budget (Risk 2 below).
- **D8** — Agent loop + 4 arms, corpus to 150-250, full matrix.
- **D9** — MCP server, README + architecture diagram, charts.
- **D10** — Demo script, writeup skeleton, packaging.

---

## 5. Three risks

### Risk 1 — Formal-filter proof strength gets conflated with a real proof
Covered in depth in Section 6 (it's also my answer to "the one thing"). Short version:
"BMC found no counterexample in k=40 cycles" and "proven equivalent" are not the same
claim, and the brief's forge Step 3 wording ("sby BMC. If proven equivalent, DISCARD")
reads like it could license treating them as the same. **Mitigation**: forge never
discards on a bare BMC pass — it runs the full ladder (Decision 3) and tags every
discard with the tier that actually justified it, surfaced in the per-operator discard
table. Cost: some discards take longer (eqy/k-induction attempts beyond BMC). Given the
corpus sizes here (tens to low hundreds of mutants, not thousands), that cost is
affordable.

### Risk 2 — 10 days solo against 6 subsystems + a 150-250 task corpus + a full 4-arm matrix + MCP + charts + writeup
This is the real scope risk and the brief already anticipates it with the D7 MVP cut
line — my job is to actually honor that line under pressure instead of quietly letting
scope creep push it back. **Mitigation, concretely**: (a) the 4 self-authored designs
use minimal, well-known reference architectures (a UART is a UART; I'm not innovating
there), timeboxed to under a day total; (b) corpus size and matrix breadth are treated
as elastic past D7 — if I'm behind schedule, I ship with 40-60 tasks and arms A/B
instead of 150-250 and A/B/C/D, and say so plainly in results/, rather than silently
padding numbers; (c) every long-running stage is resumable/cacheable (already a brief
requirement) specifically so a bad day doesn't mean redoing D3's formal filtering from
scratch.

### Risk 3 — Windows-native tooling integration friction
Concrete, not hypothetical — found two real instances of this today (Section 0): the
`libreadline8.dll` PATH issue, and MCY's own examples assuming `bash` is on PATH even
in the Windows build. There will be more of these (path separator handling in
subprocess calls, temp-file locking behavior differing from POSIX, CRLF vs LF creeping
into generated files). **Mitigation**: one `rtlverdict/env.py` module owns all
PATH/environment setup and is imported everywhere subprocesses are launched, so a fix
here fixes every caller at once instead of being rediscovered per-module. `tests/test_env.py`
asserts the toolchain is actually reachable before any other test runs, so a broken
environment fails fast and legibly instead of as a confusing downstream error.

---

## 6. The one thing most likely to be technically wrong

**The forge formal filter's discard criterion, as literally written in the brief, risks
treating a bounded result as an unbounded proof.**

Brief's Step 3: *"miter golden vs mutant, sby BMC. If proven equivalent, DISCARD — it is
not a bug."* Taken at face value, this means: run BMC at depth k=40; if it comes back
PASS (no counterexample found within 40 cycles), discard the mutant as "not a bug."

But a bounded-BMC PASS is not a proof of equivalence — it's a proof that no
counterexample exists *within 40 cycles*. A mutation whose behavioral divergence only
manifests after cycle 40 (a deep counter, a rare FSM path reached only via a long input
sequence, an off-by-one that only bites on wraparound) would sail through this filter
and get **wrongly discarded as "not a bug"** — silently shrinking the corpus and
biasing it against exactly the kind of subtle, deep bugs that are most interesting for
an agent-debugging benchmark. This isn't a hypothetical edge case I'm inventing to sound
thorough — it's the literal difference between what SBY's `mode bmc` computes and what
the brief's own verdict taxonomy two sections later calls `PROVEN-UNBOUNDED` vs
`PROVEN-BMC(k)`. The taxonomy already has the right vocabulary; Step 3's prose just
doesn't consistently use it.

I checked this isn't just me being pedantic by reading MCY's actual reference config for
picorv32 (`examples/picorv32_primes/config.mcy`, fetched and read today, Section 0): even
YosysHQ's own tooling treats a depth-50 BMC pass (`eq_bmc`, `smtbmc yices`, depth 50,
timeout 600) as adequate practical evidence for their coverage bookkeeping — so bounded
BMC-as-evidence isn't unreasonable as a pragmatic default. The problem is specifically
**discarding silently** on that basis, i.e., not recording that the equivalence claim
is bounded, which makes "formally-validated benchmark" a slightly false claim for any
task discarded that way.

**What I'd change**: exactly what Decision 3 and Risk 1 already commit to — forge's
discard decision runs the *entire* verdict ladder (BMC → eqy → k-induction), so most
single-statement mutations against small-to-medium designs (where state elements still
correspond 1:1 with golden, which is true for nearly every LOGIC/TIMING/SPEC/SIGNAL
mutation and most FSM/INTERFACE ones) get a genuine `PROVEN-UNBOUNDED` from eqy or
k-induction, not just a bounded BMC pass. For the residual cases where only BMC succeeds
within a time budget, the mutant is still discarded (matching real-world MCY practice),
but `formal_status` records `PROVEN-BMC(40)` — never a bare "proven" — and the
per-operator discard table breaks down counts by tier achieved. That table becomes an
honest, and genuinely interesting, empirical result in its own right ("X% of discards
were only bounded-proven, at these operators specifically") rather than a number I'd
have to caveat later. This costs some extra formal-solver wall-clock time per discard
candidate; given the corpus sizes here, that's a fair trade for not overclaiming.

---

## 7. Open items for your review

- Decision 2 (self-author UART/FIFO/SPI/FSM instead of importing third-party repos) —
  agree, or do you have specific designs you want used instead?
- Section 6's fix (forge always runs the full ladder, tags discard tier) — approve as
  the discard policy?
- `witness.cone_of_influence`: primary implementation via pyslang AST backward slice
  (verified working today, parent-pointers confirmed) rather than the brief's literal
  "Yosys JSON netlist + source line attributes" — with Yosys-JSON as a fallback for
  cases crossing module-instance boundaries the AST slice can't resolve alone. Rationale:
  simpler, avoids `src`-attribute fragility through Yosys optimization passes, and is
  more directly "source line"-oriented since it never round-trips through synthesis.
  Approve this substitution, or do you want the Yosys-JSON path as primary per the
  original spec?

Waiting for approval before writing any code in `rtlverdict/`.
