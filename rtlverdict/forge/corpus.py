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
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rtlverdict.forge.mutate import apply_candidate, check_fidelity
from rtlverdict.forge.operators import logic, timing
from rtlverdict.forge.parser import parse_file
from rtlverdict.forge.sim_confirm import run_sim
from rtlverdict.verdict.ladder import check_bmc

OPERATORS = [
    logic.operator_swap,
    logic.constant_perturbation,
    timing.blocking_nonblocking_swap,
    timing.edge_swap,
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
    forge_decision: str  # KEEP | DISCARD | QUARANTINE | SILENT
    equivalence_to_golden: str  # REFUTED | PROVEN-BMC | INDETERMINATE
    sim_golden: str
    sim_mutant: str
    divergence_cycle: int | None
    formal_tier: str
    formal_engine: str
    formal_k: int
    formal_runtime_s: float
    discard_reason: str | None


def generate_for_design(
    design_name: str,
    design_dir: Path,
    top_module: str,
    reset_signal: str,
    reset_active_low: bool,
    max_candidates: int | None,
    out_dir: Path,
) -> list[TaskRecord]:
    golden_path = design_dir / f"{design_name}.v"
    testbench_path = design_dir / f"tb_{design_name}.v"
    tree, source = parse_file(golden_path)

    all_candidates = []
    for op in OPERATORS:
        all_candidates.extend(op(tree, source))
    if max_candidates is not None:
        all_candidates = all_candidates[:max_candidates]

    records: list[TaskRecord] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    mutants_dir = out_dir / design_name
    mutants_dir.mkdir(parents=True, exist_ok=True)

    # Sim-confirm golden once, up front - it must PASS or every downstream
    # result for this design is meaningless.
    golden_sim = run_sim(golden_path, testbench_path)
    if golden_sim.outcome != "PASS":
        raise RuntimeError(
            f"{design_name}: golden itself does not PASS its own testbench "
            f"({golden_sim.outcome}: {golden_sim.detail}) - stopping, this is a "
            f"design/testbench bug, not a corpus decision."
        )

    for i, cand in enumerate(all_candidates):
        task_id = f"{design_name}_{cand.operator.split('.')[-1]}_{i:03d}"
        mutant_source = apply_candidate(source, cand)

        fidelity = check_fidelity(source, mutant_source, f"{task_id}.v", cand.line)
        if not fidelity.ok:
            # Addition 4 catching a real splice bug - never silently emit
            # a task from a mutant that failed its own fidelity check.
            raise RuntimeError(f"{task_id}: fidelity check failed: {fidelity.reason}")

        mutant_path = mutants_dir / f"{task_id}.v"
        mutant_path.write_text(mutant_source)

        sim_mutant = run_sim(mutant_path, testbench_path)

        formal_work_dir = out_dir / "formal_work" / task_id
        formal = check_bmc(
            golden_path,
            mutant_path,
            top_module,
            reset_signal,
            reset_active_low,
            formal_work_dir,
            k=40,
            timeout_s=60,
        )

        if sim_mutant.outcome == "SIM-INVALID":
            decision = "DISCARD"
            discard_reason = f"SIM-INVALID: {sim_mutant.detail}"
        elif formal.verdict == "REFUTED" and sim_mutant.outcome == "FAIL":
            decision = "KEEP"
            discard_reason = None
        elif formal.verdict == "REFUTED" and sim_mutant.outcome == "PASS":
            decision = "SILENT"
            discard_reason = None
        elif formal.verdict == "PROVEN-BMC":
            decision = "QUARANTINE"
            discard_reason = f"INCONCLUSIVE-BOUNDED(k={formal.k}): bounded BMC pass is not a proof of equivalence"
        else:  # INDETERMINATE
            decision = "QUARANTINE"
            discard_reason = f"FORMAL_INDETERMINATE: {formal.raw_log_tail[-200:]}"

        records.append(
            TaskRecord(
                task_id=task_id,
                design=design_name,
                tier="A",
                source="self",
                operator=cand.operator,
                bug_class=cand.bug_class,
                mutant_path=str(mutant_path),
                golden_path=str(golden_path),
                root_cause_line=cand.line,
                forge_decision=decision,
                equivalence_to_golden=formal.verdict,
                sim_golden=golden_sim.outcome,
                sim_mutant=sim_mutant.outcome,
                divergence_cycle=formal.divergence_cycle,
                formal_tier=formal.tier,
                formal_engine=formal.engine,
                formal_k=formal.k,
                formal_runtime_s=round(formal.runtime_s, 2),
                discard_reason=discard_reason,
            )
        )
        print(
            f"  [{i + 1}/{len(all_candidates)}] {task_id}: "
            f"sim={sim_mutant.outcome} formal={formal.verdict} -> {decision}"
        )

    return records


def main():
    out_dir = Path("benchmarks/corpus_v1")
    all_records: list[TaskRecord] = []

    designs = [
        ("fsm", Path("designs/fsm"), "fsm", "rst_n", True),
        ("uart", Path("designs/uart"), "uart", "rst_n", True),
    ]

    for design_name, design_dir, top_module, reset_signal, reset_active_low in designs:
        print(f"=== {design_name} ===")
        records = generate_for_design(
            design_name,
            design_dir,
            top_module,
            reset_signal,
            reset_active_low,
            max_candidates=10,
            out_dir=out_dir,
        )
        all_records.extend(records)

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
    print(f"total: {len(all_records)}")
    print(f"wrote {tasks_path}")


if __name__ == "__main__":
    main()
