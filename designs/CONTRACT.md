# Testbench pass/fail contract

Every testbench in `designs/<name>/` must honor this contract so forge/witness
can determine PASS/FAIL identically across all designs without per-design
special-casing.

1. **Exit code**: `$finish` for PASS, or reaching the end of the test normally
   with no failure recorded. A FAIL is signaled explicitly (see 2) before
   `$finish` — Icarus does not distinguish exit codes from `$finish` itself,
   so the marker line (2) is authoritative, not the process exit code alone.
2. **Marker line**: the testbench prints exactly one of these to stdout before
   finishing:
   - `RTLVERDICT_RESULT: PASS`
   - `RTLVERDICT_RESULT: FAIL at cycle <n>: <reason>`
   A run that produces neither line (crash, timeout, hang) is treated as
   `SIM-INVALID`, not FAIL — see forge's ladder (Correction 1).
3. **Bounded**: the testbench must reach a PASS or FAIL determination within a
   fixed, finite number of cycles declared in `design.yaml`'s `max_sim_cycles`.
   No open-ended `forever` waiting on a condition that might never trigger.
4. **Self-checking**: PASS must be conditioned on an actual correctness check
   (comparing observed behavior to an expected value/sequence), never emitted
   unconditionally after N cycles. Unconditional pass-after-N-cycles is not a
   testbench, it is a smoke test — it will not catch mutants.
5. **Reset release on `negedge clk`**, never on the same edge the DUT samples
   reset. Releasing on `posedge clk` (same edge the DUT's `always @(posedge
   clk)` block samples reset) is a race condition, simulator-order-dependent —
   found and fixed once already during toolchain verification (Section 0 of
   PLAN.md). This is a hard rule, not a style preference.

## Upstream designs that don't conform (picorv32, nerv)

Per project rule: wrap, don't edit. Upstream testbenches (`testbench_ez.v`,
nerv's `testbench.sv`) do not self-check (rule 4) — they run a program and
`$finish` unconditionally with no PASS/FAIL determination. A wrapper testbench
must be written that instantiates the *unmodified* upstream DUT and adds the
missing self-check (e.g., for picorv32's `testbench_ez.v`'s hand-assembled
counter-increment program, assert the expected final memory value). The
wrapper is new file, the upstream DUT and its license are untouched. Not yet
implemented for Tier B as of this writing — tracked as an open item.
