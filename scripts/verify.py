"""scripts/verify.py - the fast reproducibility check (`make verify`).

Re-runs forge's own check_bmc on a FIXED 10-task subset (golden vs. each
task's already-committed mutant) and diffs the raw ladder verdict against
a committed golden file (benchmarks/verify_golden.json) - proves this
machine's toolchain reproduces the SAME formal result the corpus was
built with, not just that the scripts run without crashing.

Also runs ONE C2 (true fix, region-scoped) and ONE C3 (wrong fix, donor
mutant) case from Phase 2B through the real agent-verdict path
(run_task -> check_patch -> check_bmc), stub-driven, so this 5-minute
reproduction demonstrates the ladder DISCRIMINATING a real fix from a
wrong one - not just re-confirming forge's static corpus.

Target: under 5 minutes. Measured, not assumed - this script prints its
own wall-clock, and that measured number (not a guess) is what belongs
in the README.

Regenerate the golden file (only after a deliberate, understood change -
never to make a failing diff go away): `python scripts/verify.py --freeze`
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rtlverdict import env  # noqa: E402
import rtlverdict.agent.loop as loop_mod  # noqa: E402
from rtlverdict.agent.loop import run_task  # noqa: E402
from rtlverdict.agent.run_smoke import DESIGN_INFO, FORMAL_PARAMS, _build_task_input  # noqa: E402
from rtlverdict.verdict.ladder import check_bmc  # noqa: E402
from scripts.agent_pilot_plumbing import STUB_MODEL_NAME, _load_all_keep_tasks  # noqa: E402
from scripts.verdict_ladder_validation import FixedPatchProvider, _pick_donor, _region_true_fix  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "benchmarks" / "verify_golden.json"
RUN_REPORT_PATH = REPO_ROOT / "results" / "verify_run_report.json"
WORK_DIR = REPO_ROOT / "results" / "verify_work"  # gitignored - regenerable scratch, see .gitignore
MAX_WALL_S = 300.0  # 5 minutes - the hard budget this script is required to fit under

# Fixed, hardcoded (not sampled by seed - a literal list IS the fixed
# subset, no RNG involved to seed) - 10 tasks, 4 designs, mostly fast
# (fsm/spi_master/uart) with exactly one fifo task (memory_map-required,
# the slowest design) so the subset still touches every design without
# the wall-clock cost of fifo's other tasks.
FIXED_TASK_IDS = [
    "fifo_operator_swap_004",
    "fsm_constant_perturbation_005",
    "fsm_constant_perturbation_008",
    "fsm_next_state_redirect_032",
    "spi_master_constant_perturbation_003",
    "spi_master_next_state_redirect_047",
    "spi_master_next_state_redirect_048",
    "uart_constant_perturbation_005",
    "uart_signal_substitution_037",
    "uart_next_state_redirect_041",
]
C2_TASK_ID = "fsm_constant_perturbation_005"  # true fix, region-scoped - reuses a task already in FIXED_TASK_IDS
C3_TASK_ID = "uart_constant_perturbation_005"  # wrong fix, donor mutant - reuses a task already in FIXED_TASK_IDS

CORPUS_FILES = [
    REPO_ROOT / "benchmarks" / "corpus_v2" / "tasks.json",
    REPO_ROOT / "benchmarks" / "corpus_v2_fifo_addition" / "tasks.json",
]


def _load_task_by_id() -> dict[str, dict]:
    tasks = []
    for p in CORPUS_FILES:
        tasks.extend(json.loads(p.read_text()))
    return {t["task_id"]: t for t in tasks}


def _run_forge_checks(by_id: dict[str, dict]) -> list[dict]:
    """golden vs. each task's already-committed mutant, through the SAME
    check_bmc() forge/corpus.py uses to build the corpus - not a
    reimplementation."""
    rows = []
    for tid in FIXED_TASK_IDS:
        task = by_id[tid]
        k, timeout_s, memory_map = FORMAL_PARAMS[task["design"]]
        top_module, reset_signal, reset_active_low, _clock = DESIGN_INFO[task["design"]]
        t0 = time.time()
        result = check_bmc(
            task["golden_path"], task["mutant_path"], top_module, reset_signal, reset_active_low,
            WORK_DIR / "forge" / tid, k=k, timeout_s=timeout_s, memory_map=memory_map,
        )
        rows.append({
            "task_id": tid, "design": task["design"], "raw_verdict": result.verdict,
            "divergence_cycle": result.divergence_cycle, "wall_time_s": round(time.time() - t0, 3),
        })
        print(f"  [forge] {tid}: {result.verdict} (divergence_cycle={result.divergence_cycle}, {time.time() - t0:.2f}s)")
    return rows


def _run_stub_case(by_id: dict[str, dict], keep_tasks: list[dict], task_id: str, condition: str) -> dict:
    task = by_id[task_id]
    task_input = _build_task_input(task)
    if condition == "C2":
        patch = _region_true_fix(task)
        label = "C2_true_fix_region"
    elif condition == "C3":
        donor = _pick_donor(task, keep_tasks)
        patch = Path(donor["mutant_path"]).read_text()
        label = "C3_wrong_fix"
    else:
        raise ValueError(condition)

    loop_mod.make_provider = lambda api_key, base_url, _p=patch, _c=label: FixedPatchProvider(_p, _c)
    work_dir = WORK_DIR / "stub" / task_id / label
    t0 = time.time()
    traj = run_task(
        task_input, "A", STUB_MODEL_NAME, "stub-no-key-needed", None, work_dir,
        max_iterations=15, max_tokens_per_turn=4096, max_total_tokens=100_000, max_wall_time_s=600.0, seed=0,
    )
    return {
        "task_id": task_id, "condition": condition, "final_verdict": traj.final_verdict,
        "wall_time_s": round(time.time() - t0, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast reproducibility check: forge + verdict ladder on a fixed 10-task subset.")
    ap.add_argument("--freeze", action="store_true", help="regenerate benchmarks/verify_golden.json from a live run instead of diffing against it")
    args = ap.parse_args()

    env.sweep_orphaned_solvers()
    by_id = _load_task_by_id()
    keep_tasks = _load_all_keep_tasks()

    print(f"=== scripts/verify.py: {len(FIXED_TASK_IDS)} fixed tasks + 1 C2 + 1 C3 case ===\n")
    t_start = time.time()

    forge_rows = _run_forge_checks(by_id)
    print()
    c2_row = _run_stub_case(by_id, keep_tasks, C2_TASK_ID, "C2")
    print(f"  [C2] {C2_TASK_ID}: final_verdict={c2_row['final_verdict']} ({c2_row['wall_time_s']:.2f}s)")
    c3_row = _run_stub_case(by_id, keep_tasks, C3_TASK_ID, "C3")
    print(f"  [C3] {C3_TASK_ID}: final_verdict={c3_row['final_verdict']} ({c3_row['wall_time_s']:.2f}s)")

    elapsed = time.time() - t_start
    print(f"\nTotal wall-clock: {elapsed:.1f}s (budget: {MAX_WALL_S:.0f}s)")

    current = {"forge": forge_rows, "c2": c2_row, "c3": c3_row}

    def _write_run_report(passed: bool, failures: list[str]) -> None:
        RUN_REPORT_PATH.write_text(json.dumps({
            "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_s": round(elapsed, 1),
            "max_wall_s_budget": MAX_WALL_S,
            "n_forge_checks": len(forge_rows),
            "passed": passed,
            "n_failures": len(failures),
        }, indent=2))

    if args.freeze:
        GOLDEN_PATH.write_text(json.dumps(current, indent=2))
        print(f"\nWrote {GOLDEN_PATH.relative_to(REPO_ROOT)} (--freeze, no diff performed)")
        _write_run_report(passed=True, failures=[])
        return 0

    if not GOLDEN_PATH.exists():
        print(f"\nFAIL: {GOLDEN_PATH.relative_to(REPO_ROOT)} does not exist - run with --freeze first.")
        return 1

    golden = json.loads(GOLDEN_PATH.read_text())
    golden_forge = {r["task_id"]: r for r in golden["forge"]}
    failures = []

    for row in forge_rows:
        exp = golden_forge.get(row["task_id"])
        if exp is None:
            failures.append(f"{row['task_id']}: not in golden file")
            continue
        if row["raw_verdict"] != exp["raw_verdict"] or row["divergence_cycle"] != exp["divergence_cycle"]:
            failures.append(
                f"{row['task_id']}: expected verdict={exp['raw_verdict']} div={exp['divergence_cycle']}, "
                f"got verdict={row['raw_verdict']} div={row['divergence_cycle']}"
            )

    if c2_row["final_verdict"] != golden["c2"]["final_verdict"]:
        failures.append(f"C2 {C2_TASK_ID}: expected {golden['c2']['final_verdict']}, got {c2_row['final_verdict']}")
    if c3_row["final_verdict"] != golden["c3"]["final_verdict"]:
        failures.append(f"C3 {C3_TASK_ID}: expected {golden['c3']['final_verdict']}, got {c3_row['final_verdict']}")

    print()
    if failures:
        print("=" * 60)
        print(f"VERIFY: FAIL ({len(failures)} mismatch(es))")
        print("=" * 60)
        for f in failures:
            print(f"  - {f}")
        _write_run_report(passed=False, failures=failures)
        return 1

    print("=" * 60)
    print(f"VERIFY: PASS - {len(forge_rows)} forge checks + C2 + C3 all match {GOLDEN_PATH.relative_to(REPO_ROOT)}")
    print("=" * 60)
    if elapsed > MAX_WALL_S:
        print(f"WARNING: {elapsed:.1f}s exceeds the {MAX_WALL_S:.0f}s budget - shrink the subset.")
        _write_run_report(passed=False, failures=["exceeded MAX_WALL_S budget"])
        return 1
    _write_run_report(passed=True, failures=[])
    return 0


if __name__ == "__main__":
    sys.exit(main())
