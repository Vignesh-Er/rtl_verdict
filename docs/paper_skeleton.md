# Paper skeleton (IEEE headings)

Bullets only — a scaffold for drafting, not prose. Every number below
is read from `results/corpus_stats.json` unless otherwise noted;
regenerate with `python scripts/build_stats.py` before drafting from
this skeleton.

## Abstract

- Problem: RTL debugging benchmarks and formal-verification-gated agent
  evaluation both typically depend on commercial EDA (JasperGold, VCS)
  for the formal backend — license-gated, unavailable to most
  academic/independent work.
- Contribution: an end-to-end, 100%-open-source-toolchain harness that
  formally filters out equivalent mutants before they reach an agent
  and formally refutes incorrect fixes on the patch path (mutation
  generation → formal ground-truth filtering → agent debug tooling →
  formal patch verdict), built entirely on Yosys/SymbiYosys/Icarus/
  Verilator/Z3/Boolector/Yices, no commercial tool anywhere in the
  pipeline. A bounded pass on a proposed fix is reported `PLAUSIBLE`,
  never promoted to a proof — the method demonstrably refutes wrong
  fixes and filters non-bugs; it does not claim to prove a fix correct
  (see Threats to Validity).
- Headline empirical findings: a design's own testbench misses between
  13.6% and 72.2% of formally-confirmed real bugs depending on the
  design (no single rate); 49.1% of naively-generated mutation
  candidates are formally proven equivalent to golden, not bugs at all;
  the most textbook-canonical RTL mistake (`blocking_nonblocking_swap`)
  is 95.2% behaviourally harmless on this corpus.
- Scope statement: n = 4 self-authored Tier A designs, BMC-bounded
  formal checking, no live LLM agent evaluation completed (harness
  validated end-to-end with a deterministic stub only) — stated
  up front, not discovered in Section VI.

## Introduction

- Motivating claim: "the testbench passes" is treated as ground truth
  in most RTL-repair/agent-debugging literature, without an independent
  check that the testbench itself is adequate — this project measures
  that gap directly instead of assuming it away.
- Framing: mutation-based RTL bug benchmarks are only as trustworthy as
  their equivalent-mutant filter; a formal filter is the mechanism that
  turns "mutated code" into "a benchmark with ground truth," and this
  paper reports what that filter actually removes (49.1% of candidates)
  on real designs.
- Positioning: this is not a claim that any agent can debug RTL well —
  no live agent evaluation is reported (see Results, Threats to
  Validity) — it is a claim about the measurement infrastructure that
  would be needed to evaluate that question honestly, license-free.
- Contributions listed explicitly: (1) an open, formally-gated mutation
  corpus with a documented equivalent-mutant rate per operator; (2) a
  direct, agent-independent measurement of testbench blindness
  (silent-bug rate) per design; (3) a validated formal verdict ladder,
  demonstrated to discriminate a true fix from a wrong one on real
  input classes; (4) a fully reproducible, sub-5-minute verification
  path with no commercial dependency.

## Related Work

- **The stated opening gap**: RTLFixer, HDLdebugger, CraftRTL, UVLLM,
  HWE-Bench, RealBench, and AssertLLM2 each address some slice of
  LLM-assisted RTL debugging, repair, or verification — but the formal
  or simulation backend each ultimately leans on is, in the general
  case, commercial (JasperGold-class formal, VCS-class simulation) or
  assumes access to one; this project asks what the same class of
  method looks like with zero commercial dependency, license-free
  end to end.
- RTLFixer / HDLdebugger / UVLLM: LLM-driven iterative RTL bug
  localization and repair loops — this project's `witness` toolbelt and
  agent loop occupy the same design space (structured debug evidence,
  iterative patch proposal), but every verdict on a proposed patch here
  is formally gated (BMC), not simulation-only.
- CraftRTL: correct-by-construction / synthesis-correctness-focused RTL
  generation with LLMs — orthogonal goal (generation vs. this project's
  debugging-an-existing-bug framing), but shares the concern that a
  passing testbench is not sufficient evidence of correctness.
- HWE-Bench / RealBench: RTL benchmark construction for agent
  evaluation — this project's differentiator is the formally-gated
  equivalent-mutant filter (49.1% of naive candidates removed) and the
  direct, agent-independent silent-bug-rate measurement, neither of
  which either benchmark construction methodology is documented as
  performing.
- AssertLLM2: LLM-assisted assertion/property generation for
  verification — complementary rather than competing; an assertion
  generator could plausibly sit upstream of this project's formal
  ladder as an alternative or additional check, not evaluated here.

## Method

- **forge**: token-byte-offset mutation on the original source text
  (never re-serializes the parse tree — fidelity outside the mutated
  span guaranteed by construction), LOGIC and TIMING operator classes,
  pipeline order parse → validate → compile → sim → formal with formal
  never short-circuited on a sim pass.
- **The formal ladder**: BMC-only in the current (degraded-mode)
  configuration via SymbiYosys/`smtbmc yices`, generating a miter from
  each module's own port list (never hand-written per design); a
  bounded pass is reported `PROVEN-BMC(k)`, never promoted to an
  unbounded equivalence claim; per-design `k`: `40` for
  `fsm`/`uart`/`spi_master`, `25` (with `memory_map`) for `fifo`.
- **witness**: first-divergence-only simulation comparison against
  golden, backward cone-of-influence static slicing, toggle-proximity
  suspect ranking — designed to give an agent structured evidence
  rather than a raw simulator log.
- **verdict / agent loop**: a model-agnostic agent harness (Anthropic
  and OpenAI-compatible wire formats) with hard per-task token and
  wall-clock caps; every submitted patch passes a pre-check (parses,
  elaborates, unchanged interface) before any formal check runs, then
  the same `check_bmc` ladder used to build the corpus judges it —
  `PLAUSIBLE` (bounded pass), `REFUTED` (counterexample found), or
  `INVALID-PATCH`.

## Results

- Silent-bug rate: 13.6%–72.2% across the four designs (5.3x spread) —
  no single rate for the method; reported per-design, pooled figure
  given once for comparability with prior work, not as the headline.
- Equivalent-mutant rate: 49.1% of all 171 generated candidates
  formally proven equivalent to golden (`QUARANTINE`); the largest
  single operator class, `blocking_nonblocking_swap`, is 95.2%
  equivalent on its own (60/63 evaluated) — the single largest
  mutation-operator class in the corpus is, on this evidence, usually
  not a bug.
- A `k=200` deep-BMC re-check of every `QUARANTINE` mutant from three
  designs promoted zero of them to a confirmed bug — a real negative
  result establishing these are equivalent, not merely "not yet
  refuted at a shallow depth."
- Verdict-ladder discrimination: `48/48` rows across four input classes
  (true fix full-revert, true fix region-scoped, wrong fix, invalid
  patch) matched the expected verdict class, including the underlying
  raw ladder verdict, demonstrating the formal gate actually
  distinguishes a real fix from a wrong one.
- No live agent evaluation is reported: the full agent harness was
  validated end-to-end with a deterministic stub (no API key available
  in this environment) — a plumbing/wiring result, explicitly not an
  agent-capability result, and not presented as one anywhere in this
  paper.

## Threats to Validity

- **External validity**: n = 4 designs, all Tier A, all self-authored
  by the same person in the same short window — no claim generalizes
  beyond this sample without new designs and (ideally) independently-
  authored testbenches.
- **Construct validity (coverage)**: an investigated
  coverage-vs-silent-bug-rate relationship was withdrawn, not
  qualified, after finding the four designs' toggle-coverage
  denominators span 9.4x — cross-design toggle-coverage percentage is
  not a comparable measurement at that spread, and no claim about it
  is made in either direction.
- **Construct validity (formal soundness)**: the formal ladder is
  BMC-only in the current configuration; eqy (the intended second,
  unbounded-capable rung) is disabled for discard decisions after a
  control test produced a false proof — traced to the invocation, not
  a confirmed eqy defect, but unresolved, so no unbounded equivalence
  claim is made anywhere by this method currently. Concretely: neither
  a raw `PROVEN-BMC` nor a `PROVEN-UNBOUNDED` verdict is ever surfaced
  as the verdict on a proposed patch on any run this method has
  produced — a bounded pass is always reported `PLAUSIBLE`, deliberately
  never promoted to a stronger label, and `PROVEN-UNBOUNDED` is not a
  value the current implementation can produce at all, on any code
  path. The same raw result is labeled `PROVEN-BMC` on the corpus-build
  path and `PLAUSIBLE` on the patch path — an intentional asymmetry, not
  an inconsistency: a false "equivalent" on the corpus-build path costs
  one benchmark task and is independently rechecked at 5x depth before
  being trusted; a false "proven correct" on the patch path tells an
  engineer a broken fix is right, a strictly higher-cost error, and gets
  the stricter label accordingly.
- **Internal validity (agent results)**: zero live agent runs are
  reported; every agent-path number in this work describes harness
  correctness (verified with a deterministic stub), never agent
  capability — conflating the two would be the single most damaging
  misreading of this work, and is explicitly guarded against throughout.
- **Measurement validity**: the COI (cone-of-influence) containment
  figure supporting the witness toolbelt's debug-evidence claim was
  validated once, on a superseded corpus, and has not been re-measured
  on the corpus this paper's other results are drawn from — not quoted
  as a current number anywhere in this work for that reason.

## Availability

- Fully open source, no commercial EDA dependency, no FPGA hardware
  requirement — toolchain is Yosys/SymbiYosys/Icarus/Verilator/Z3/
  Boolector/Yices, all license-free.
- Reproducibility: `python -m rtlverdict.doctor` (toolchain check) +
  `make verify` (fixed-subset formal-ladder reproduction, including one
  true-fix and one wrong-fix discrimination case) — sub-5-minute,
  measured runtime persisted to `results/verify_run_report.json` on
  every run, never hand-typed into any document.
- All generated statistics traceable to `results/corpus_stats.json`
  (regenerated by `scripts/build_stats.py`, never hand-edited); every
  number in every results document is enforced, by an automated test,
  to trace to a generated file, not a remembered figure.
- Linux and Docker install paths are documented but untested by this
  project (developed and validated on Windows 11 only) — stated
  explicitly, not implied to work.
