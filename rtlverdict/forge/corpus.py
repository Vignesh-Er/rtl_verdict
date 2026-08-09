"""D3: ties forge (mutation generation) + sim_confirm (Icarus) + the formal
ladder (BMC-only, degraded mode - see verdict/ladder.py) into real task JSON.

Stage order (Correction 4): parse+splice -> re-parse validate -> compile
check -> SIM (golden+mutant) -> FORMAL LADDER. Formal always runs, even on
sim-PASS - that's how a SILENT bug (Addition 2) is found: a formally-proven
divergence the testbench doesn't catch. Never short-circuit formal on sim
outcome.

Decision logic (degraded mode: no trustworthy unbounded equivalence prover
available - see FINDINGS.md's eqy section):
  SIM-INVALID (compile fail / hang on golden or mutant) -> DISCARD
  FORMAL=REFUTED, SIM=FAIL  -> KEEP        (normal repair task)
  FORMAL=REFUTED, SIM=PASS  -> SILENT      (proven bug, testbench blind to it)
  FORMAL=PROVEN-BMC (bounded only) -> QUARANTINE, never DISCARD - a bounded
      pass is not a proof of equivalence (PLAN.md Section 6 / Correction 1)
  FORMAL=INDETERMINATE -> QUARANTINE (timeout or tool error)
  anything raising in a per-task stage -> ERROR, recorded, never silently
      dropped (a corpus that silently shrank from a stage crashing looks
      identical to one that worked - both are worth catching, but only if
      the error is recorded, not swallowed)

Mutant deduplication: naive per-candidate generation can regenerate the
same mutation on small designs (e.g. two different traversal orders hitting
the same token). Every mutant's normalized source is hashed; duplicates are
recorded (not silently discarded from the count) and skipped from further
processing - "generated" and "distinct" are both reported, never conflated.
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rtlverdict import env
from rtlverdict.forge.mutate import apply_candidate, check_fidelity
from rtlverdict.forge.operators import fsm, logic, signal, timing
from rtlverdict.forge.parser import parse_file
from rtlverdict.forge.sim_confirm import run_sim
from rtlverdict.verdict.ladder import check_bmc

ALL_OPERATORS = [
    logic.operator_swap,
    logic.constant_perturbation,
    timing.blocking_nonblocking_swap,
    timing.edge_swap,
    signal.signal_substitution,
    fsm.next_state_redirect,
]


@dataclass
class TaskRecord:
    task_id: str
    design: str
    tier: str
    source: str
    operator: str
    bug_class: str
    mutant_path: str
    golden_path: str
    root_cause_line: int
    forge_decision: str  # KEEP | DISCARD | QUARANTINE | SILENT | ERROR
    equivalence_to_golden: str | None
    sim_golden: str | None
    sim_mutant: str | None
    divergence_cycle: int | None
    formal_tier: str | None
    formal_engine: str | None
    formal_k: int | None
    formal_runtime_s: float | None
    discard_reason: str | None
    error: str | None = None


def _normalize(source: str) -> str:
    return "\n".join(line.rstrip() for line in source.splitlines())


def generate_for_design(
    design_name: str,
    design_dir: Path,
    top_module: str,
    reset_signal: str,
    reset_active_low: bool,
    max_candidates: int | None,
    out_dir: Path,
    operators: list | None = None,
    formal_k: int = 40,
    formal_timeout_s: int = 60,
    formal_memory_map: bool = False,
) -> tuple[list[TaskRecord], dict]:
    operators = operators if operators is not None else ALL_OPERATORS
    golden_path = design_dir / f"{design_name}.v"
    testbench_path = design_dir / f"tb_{design_name}.v"
    tree, source = parse_file(golden_path)

    all_candidates = []
    for op in operators:
        all_candidates.extend(op(tree, source))
    if max_candidates is not None:
        all_candidates = all_candidates[:max_candidates]

    out_dir.mkdir(parents=True, exist_ok=True)
    mutants_dir = out_dir / design_name
    mutants_dir.mkdir(parents=True, exist_ok=True)

    golden_sim = run_sim(golden_path, testbench_path)
    if golden_sim.outcome != "PASS":
        raise RuntimeError(
            f"{design_name}: golden itself does not PASS its own testbench "
            f"({golden_sim.outcome}: {golden_sim.detail}) - stopping, this is a "
            f"design/testbench bug, not a corpus decision."
        )

    records: list[TaskRecord] = []
    seen_hashes: dict[str, str] = {}  # normalized-source hash -> first task_id that produced it
    duplicate_count = 0

    for i, cand in enumerate(all_candidates):
        task_id = f"{design_name}_{cand.operator.split('.')[-1]}_{i:03d}"
        mutant_source = apply_candidate(source, cand)

        h = hashlib.sha256(_normalize(mutant_source).encode()).hexdigest()
        if h in seen_hashes:
            duplicate_count += 1
            print(f"  [{i + 1}/{len(all_candidates)}] {task_id}: DUPLICATE of {seen_hashes[h]}, skipped")
            continue
        seen_hashes[h] = task_id

        try:
            fidelity = check_fidelity(source, mutant_source, f"{task_id}.v", cand.line)
            if not fidelity.ok:
                raise RuntimeError(f"fidelity check failed: {fidelity.reason}")

            mutant_path = mutants_dir / f"{task_id}.v"
            mutant_path.write_text(mutant_source)

            sim_mutant = run_sim(mutant_path, testbench_path)

            formal_work_dir = out_dir / "formal_work" / task_id
            formal = check_bmc(
                golden_path, mutant_path, top_module, reset_signal, reset_active_low,
                formal_work_dir, k=formal_k, timeout_s=formal_timeout_s, memory_map=formal_memory_map,
            )

            if sim_mutant.outcome == "SIM-INVALID":
                decision, discard_reason = "DISCARD", f"SIM-INVALID: {sim_mutant.detail}"
            elif formal.verdict == "REFUTED" and sim_mutant.outcome == "FAIL":
                decision, discard_reason = "KEEP", None
            elif formal.verdict == "REFUTED" and sim_mutant.outcome == "PASS":
                decision, discard_reason = "SILENT", None
            elif formal.verdict == "PROVEN-BMC":
                decision = "QUARANTINE"
                discard_reason = f"INCONCLUSIVE-BOUNDED(k={formal.k}): bounded BMC pass is not a proof of equivalence"
            else:
                decision, discard_reason = "QUARANTINE", f"FORMAL_INDETERMINATE: {formal.raw_log_tail[-200:]}"

            records.append(TaskRecord(
                task_id=task_id, design=design_name, tier="A", source="self",
                operator=cand.operator, bug_class=cand.bug_class,
                mutant_path=str(mutant_path), golden_path=str(golden_path),
                root_cause_line=cand.line, forge_decision=decision,
                equivalence_to_golden=formal.verdict, sim_golden=golden_sim.outcome,
                sim_mutant=sim_mutant.outcome, divergence_cycle=formal.divergence_cycle,
                formal_tier=formal.tier, formal_engine=formal.engine, formal_k=formal.k,
                formal_runtime_s=round(formal.runtime_s, 2), discard_reason=discard_reason,
            ))
            print(f"  [{i + 1}/{len(all_candidates)}] {task_id}: sim={sim_mutant.outcome} formal={formal.verdict} -> {decision}")

        except Exception as e:  # noqa: BLE001 - fail loud, never silently drop a task
            records.append(TaskRecord(
                task_id=task_id, design=design_name, tier="A", source="self",
                operator=cand.operator, bug_class=cand.bug_class,
                mutant_path="", golden_path=str(golden_path), root_cause_line=cand.line,
                forge_decision="ERROR", equivalence_to_golden=None, sim_golden=golden_sim.outcome,
                sim_mutant=None, divergence_cycle=None, formal_tier=None, formal_engine=None,
                formal_k=None, formal_runtime_s=None, discard_reason=None,
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}",
            ))
            print(f"  [{i + 1}/{len(all_candidates)}] {task_id}: ERROR - {type(e).__name__}: {e}")

    stats = {
        "generated": len(all_candidates),
        "distinct": len(all_candidates) - duplicate_count,
        "duplicates": duplicate_count,
    }
    return records, stats


def main():
    env.sweep_orphaned_solvers()  # pre-flight: never start a batch with a stray solver already running

    out_dir = Path("benchmarks/corpus_v2")
    all_records: list[TaskRecord] = []
    all_stats: dict[str, dict] = {}

    designs = [
        ("fsm", Path("designs/fsm"), "fsm", "rst_n", True),
        ("uart", Path("designs/uart"), "uart", "rst_n", True),
        ("spi_master", Path("designs/spi_master"), "spi_master", "rst_n", True),
    ]

    for design_name, design_dir, top_module, reset_signal, reset_active_low in designs:
        print(f"=== {design_name} ===")
        records, stats = generate_for_design(
            design_name, design_dir, top_module, reset_signal, reset_active_low,
            max_candidates=None, out_dir=out_dir,
        )
        all_records.extend(records)
        all_stats[design_name] = stats

    out_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = out_dir / "tasks.json"
    tasks_path.write_text(json.dumps([asdict(r) for r in all_records], indent=2))

    by_decision: dict[str, int] = {}
    for r in all_records:
        by_decision[r.forge_decision] = by_decision.get(r.forge_decision, 0) + 1

    print()
    print("=== SUMMARY ===")
    for decision, count in sorted(by_decision.items()):
        print(f"  {decision}: {count}")
    total_generated = sum(s["generated"] for s in all_stats.values())
    total_distinct = sum(s["distinct"] for s in all_stats.values())
    print(f"generated: {total_generated}  distinct: {total_distinct}  recorded: {len(all_records)}")
    assert sum(by_decision.values()) == len(all_records) == total_distinct, "accounting mismatch"
    print(f"wrote {tasks_path}")


if __name__ == "__main__":
    main()
