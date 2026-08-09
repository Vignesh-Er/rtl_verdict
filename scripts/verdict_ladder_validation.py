"""scripts/verdict_ladder_validation.py

Phase 2B: the Phase 2 plumbing test exercised exactly ONE input class (a
full golden-revert "fix") and got exactly one output class (PLAUSIBLE).
One input, one output is not a discrimination test - it proves the wiring
doesn't crash, not that the formal gate actually tells a real fix apart
from a wrong one. This script adds three more input classes through the
SAME harness (run_task -> check_patch -> check_bmc), on the SAME 12-task
stratified selection used in Phase 2, to make it one.

C1 TRUE FIX (full golden revert) - already run in Phase 2 (arm A rows of
    results/agent_pilot_plumbing_report.json). Not re-run here; read
    directly from the committed transcripts.
C2 TRUE FIX (region-scoped) - splices ONLY golden's text at the task's
    own root_cause_line into the mutant, leaving everything else as the
    mutant. Verified (assert, not assumed) to reconstruct golden
    byte-for-byte for all 12 selected tasks - this corpus's mutations are
    confined to a single line (checked separately before writing this
    script). A tighter-scoped, more literal reading of "true fix" than
    C1's whole-file revert.
C3 WRONG FIX - submits a DIFFERENT task's mutant (same design, a
    different KEEP task, so a real, already formally-confirmed
    divergence from golden) as this task's "fix." Syntactically valid
    (it already passed forge's own fidelity guard when the corpus was
    built), same module/ports (mutations never change the interface),
    and provably still wrong.
C4 INVALID PATCH - a fixed, deliberately unparseable string.

DO NOT edit check_patch/ladder.py to make an expectation come true here.
An unmet expectation is itself the result - see results/verdict_ladder_validation.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rtlverdict import env  # noqa: E402
import rtlverdict.agent.loop as loop_mod  # noqa: E402
from rtlverdict.agent.loop import run_task  # noqa: E402
from rtlverdict.agent.providers import NormalizedResponse  # noqa: E402
from rtlverdict.agent.run_smoke import _build_task_input  # noqa: E402
from scripts.agent_pilot_plumbing import (  # noqa: E402
    STUB_MODEL_NAME,
    _load_all_keep_tasks,
    _stratified_selection,
)

TRANSCRIPTS_DIR = REPO_ROOT / "results" / "verdict_ladder_validation" / "transcripts"
REPORT_PATH = REPO_ROOT / "results" / "verdict_ladder_validation_report.json"
AGENT_PILOT_REPORT_PATH = REPO_ROOT / "results" / "agent_pilot_plumbing_report.json"
AGENT_PILOT_TRANSCRIPTS_DIR = REPO_ROOT / "results" / "agent_pilot" / "transcripts"

INVALID_PATCH_TEXT = "this is not verilog at all {{{ syntax error on purpose"


class FixedPatchProvider:
    """Deterministic stub - submits a fixed, precomputed patch string on
    the first turn, no reasoning, one tool call, every time."""

    name = "stub-fixed-patch"

    def __init__(self, patch_source: str, label: str):
        self._patch_source = patch_source
        self._label = label

    def request(self, model, system, messages, tools, max_tokens, seed, timeout_s=120):
        del model, system, messages, tools, max_tokens, seed, timeout_s
        return NormalizedResponse(
            text=f"(stub {self._label})",
            tool_calls=[{
                "id": "stub_submit_1", "name": "submit_patch",
                "input": {"patched_source": self._patch_source, "explanation": f"stub condition {self._label}"},
            }],
            stop_reason="tool_use", input_tokens=0, output_tokens=0,
            raw={"content": [{"type": "text", "text": f"(stub {self._label})"}]},
        )

    def append_assistant(self, messages, resp):
        messages.append({"role": "assistant", "content": resp.raw["content"]})

    def append_tool_results(self, messages, results):
        messages.append({"role": "user", "content": results})


def _region_true_fix(task: dict) -> str:
    """Replace ONLY the mutated line (task['root_cause_line']) with
    golden's line at that index - not a whole-file revert. Asserted equal
    to full golden text for the tasks this script actually runs (verified
    separately beforehand for all 12 selected tasks); fails loudly rather
    than silently submitting a partial/still-buggy patch if a future
    corpus ever has a multi-line mutation.
    """
    golden_lines = Path(task["golden_path"]).read_text().splitlines(keepends=True)
    mutant_lines = Path(task["mutant_path"]).read_text().splitlines(keepends=True)
    rcl = task["root_cause_line"]
    assert golden_lines != mutant_lines, f"{task['task_id']}: golden and mutant are already identical - nothing to revert"
    reconstructed = mutant_lines.copy()
    reconstructed[rcl - 1] = golden_lines[rcl - 1]
    patch = "".join(reconstructed)
    golden_text = "".join(golden_lines)
    assert patch == golden_text, (
        f"{task['task_id']}: region-scoped revert at line {rcl} did NOT reconstruct golden byte-for-byte - "
        f"this task's mutation is not confined to one line; C2's premise doesn't hold for it"
    )
    return patch


def _pick_donor(task: dict, keep_tasks: list[dict]) -> dict:
    """A different KEEP task, same design - deterministic (lowest task_id,
    excluding self) so the matrix is reproducible."""
    same_design = sorted(
        (t for t in keep_tasks if t["design"] == task["design"] and t["task_id"] != task["task_id"]),
        key=lambda t: t["task_id"],
    )
    assert same_design, f"{task['task_id']}: no other KEEP task on design {task['design']} to use as a wrong-fix donor"
    return same_design[0]


def _run_condition(selected: list[dict], keep_tasks: list[dict], condition: str) -> list[dict]:
    rows = []
    for task in selected:
        task_input = _build_task_input(task)
        golden_source = Path(task_input.golden_path).read_text()

        if condition == "C2_true_fix_region":
            patch = _region_true_fix(task)
        elif condition == "C3_wrong_fix":
            donor = _pick_donor(task, keep_tasks)
            patch = Path(donor["mutant_path"]).read_text()
        elif condition == "C4_invalid_patch":
            patch = INVALID_PATCH_TEXT
        else:
            raise ValueError(condition)

        loop_mod.make_provider = lambda api_key, base_url, _p=patch, _c=condition: FixedPatchProvider(_p, _c)
        work_dir = TRANSCRIPTS_DIR / task["task_id"] / condition
        t0 = time.time()
        traj = run_task(
            task_input, "A", STUB_MODEL_NAME, "stub-no-key-needed", None, work_dir,
            max_iterations=15, max_tokens_per_turn=4096, max_total_tokens=100_000,
            max_wall_time_s=600.0, seed=0,
        )
        wall = round(time.time() - t0, 3)
        data = json.loads((work_dir / "trajectory.json").read_text())
        row = {
            "task_id": task["task_id"], "design": task["design"], "condition": condition,
            "final_verdict": traj.final_verdict,
            "raw_formal_verdict": (data.get("verdict_detail") or {}).get("formal_verdict"),
            "divergence_cycle_found": (data.get("verdict_detail") or {}).get("divergence_cycle"),
            "invalid_patch_reason": data.get("invalid_patch_reason"),
            "wall_time_s": wall,
        }
        if condition == "C3_wrong_fix":
            row["donor_task_id"] = _pick_donor(task, keep_tasks)["task_id"]
        if condition == "C2_true_fix_region":
            row["region_patch_equals_golden"] = (patch == golden_source)
        rows.append(row)
        print(f"  [{condition}] {task['task_id']}: final_verdict={traj.final_verdict} raw={row['raw_formal_verdict']} wall={wall:.2f}s")
    return rows


def _load_c1_rows(selected: list[dict]) -> list[dict]:
    """C1 (full golden revert) was already run in Phase 2 - read its arm-A
    transcripts directly rather than re-running (resumability, same
    principle Phase 2 itself demonstrated - never re-spend on a result
    already on disk)."""
    rows = []
    for task in selected:
        traj_path = AGENT_PILOT_TRANSCRIPTS_DIR / task["task_id"] / "arm_A" / "trajectory.json"
        data = json.loads(traj_path.read_text())
        rows.append({
            "task_id": task["task_id"], "design": task["design"], "condition": "C1_true_fix_full_revert",
            "final_verdict": data["final_verdict"],
            "raw_formal_verdict": (data.get("verdict_detail") or {}).get("formal_verdict"),
            "divergence_cycle_found": (data.get("verdict_detail") or {}).get("divergence_cycle"),
            "invalid_patch_reason": data.get("invalid_patch_reason"),
            "wall_time_s": round(data.get("wall_time_s", 0.0) + (data.get("verdict_detail") or {}).get("runtime_s", 0.0), 3),
        })
    return rows


def main() -> None:
    env.sweep_orphaned_solvers()

    keep_tasks = _load_all_keep_tasks()
    selected = _stratified_selection(keep_tasks, n_per_design=3)
    print(f"Task subset: {len(selected)} tasks (same stratified selection as Phase 2)\n")

    c1_rows = _load_c1_rows(selected)
    print(f"C1 (read from Phase 2 transcripts, not re-run): {len(c1_rows)} rows")
    for r in c1_rows:
        print(f"  [C1] {r['task_id']}: final_verdict={r['final_verdict']} raw={r['raw_formal_verdict']}")

    print("\nRunning C2 (region-scoped true fix)...")
    c2_rows = _run_condition(selected, keep_tasks, "C2_true_fix_region")

    print("\nRunning C3 (wrong fix - donor mutant)...")
    c3_rows = _run_condition(selected, keep_tasks, "C3_wrong_fix")

    print("\nRunning C4 (invalid patch)...")
    c4_rows = _run_condition(selected, keep_tasks, "C4_invalid_patch")

    all_rows = c1_rows + c2_rows + c3_rows + c4_rows

    def _dist(rows):
        d: dict[str, int] = {}
        for r in rows:
            d[r["final_verdict"]] = d.get(r["final_verdict"], 0) + 1
        return d

    report = {
        "purpose": "Phase 2B: prove the formal ladder discriminates across input classes, not just that the harness runs.",
        "stub_model_name": STUB_MODEL_NAME,
        "n_tasks": len(selected),
        "n_conditions": 4,
        "total_rows": len(all_rows),
        "ladder_verdicts_enum": ["REFUTED", "PROVEN-BMC", "INDETERMINATE"],
        "conditions": {
            "C1_true_fix_full_revert": {"expected_final_verdict": "PLAUSIBLE", "distribution": _dist(c1_rows), "n": len(c1_rows)},
            "C2_true_fix_region": {"expected_final_verdict": "PLAUSIBLE", "distribution": _dist(c2_rows), "n": len(c2_rows)},
            "C3_wrong_fix": {"expected_final_verdict": "REFUTED", "distribution": _dist(c3_rows), "n": len(c3_rows)},
            "C4_invalid_patch": {"expected_final_verdict": "INVALID-PATCH", "distribution": _dist(c4_rows), "n": len(c4_rows)},
        },
        "rows": all_rows,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {REPORT_PATH.relative_to(REPO_ROOT)}")
    print("\n=== Distributions ===")
    for cond, d in report["conditions"].items():
        print(f"  {cond}: {d['distribution']} (expected {d['expected_final_verdict']})")


if __name__ == "__main__":
    main()
