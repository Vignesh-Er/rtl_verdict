"""scripts/agent_pilot_plumbing.py

Phase 2 was specified as a live agent pilot (n>=10 KEEP tasks, both arms,
Claude Haiku 4.5, real API calls). No ANTHROPIC_API_KEY or OPENAI_API_KEY
is present in this environment - confirmed by `run_smoke.py`'s own check
before this script does anything. Per the explicit contingency for this
case: do not stall waiting for a key. Run the REAL harness - real task
stratification, real run_task() control flow, the real INVALID-PATCH
pre-check, the real BMC formal ladder, real trajectory writing, the real
resumability cache-check - with only the LLM call itself replaced by a
fixed, deterministic stub. This proves the plumbing executes end-to-end
and that caps/resumability/verdict wiring work. It produces ZERO agent
results - no model ever attempted to find or fix a bug here. See the
mandatory banner at the top of results/agent_pilot.md.

The stub ("golden-revert") always submits the golden source verbatim as
its "fix" - a legitimate, deterministic no-op patch. Every run must
therefore mechanically resolve to PLAUSIBLE (BMC finds golden trivially
equivalent to itself) - that determinism is the point: it lets a reader
verify the wiring produced the ONLY verdict a fixed no-op patch can ever
produce, with no room for a stub to accidentally look like a real result.
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
from rtlverdict.agent.loop import TaskInput, run_task  # noqa: E402
from rtlverdict.agent.providers import NormalizedResponse  # noqa: E402
from rtlverdict.agent.run_smoke import _build_task_input, _cached_trajectory  # noqa: E402

STUB_MODEL_NAME = "stub-golden-revert-v1"  # NOT a real model - labeled explicitly everywhere it's recorded
TRANSCRIPTS_DIR = REPO_ROOT / "results" / "agent_pilot" / "transcripts"
REPORT_PATH = REPO_ROOT / "results" / "agent_pilot_plumbing_report.json"

CORPUS_FILES = [
    REPO_ROOT / "benchmarks" / "corpus_v2" / "tasks.json",
    REPO_ROOT / "benchmarks" / "corpus_v2_fifo_addition" / "tasks.json",
]


class GoldenRevertProvider:
    """Deterministic stub: always submits the golden source, verbatim, as
    the fix - on the first turn, one tool call, every time. Standing in
    for an LLM only to exercise loop.py's control flow, patch_check, and
    check_bmc for real - never a claim about agent capability.
    """

    name = "stub-golden-revert"

    def __init__(self, golden_source: str):
        self._golden_source = golden_source

    def request(self, model, system, messages, tools, max_tokens, seed, timeout_s=120):
        del model, system, messages, tools, max_tokens, seed, timeout_s
        return NormalizedResponse(
            text="(stub) reverting to golden source.",
            tool_calls=[{
                "id": "stub_submit_1", "name": "submit_patch",
                "input": {"patched_source": self._golden_source, "explanation": "stub: golden-revert, no reasoning performed"},
            }],
            stop_reason="tool_use", input_tokens=0, output_tokens=0,
            raw={"content": [{"type": "text", "text": "(stub) reverting to golden source."}]},
        )

    def append_assistant(self, messages, resp):
        messages.append({"role": "assistant", "content": resp.raw["content"]})

    def append_tool_results(self, messages, results):
        messages.append({"role": "user", "content": results})


class CapDemoProvider:
    """Deterministic stub that NEVER submits a patch - always calls the
    real run_test witness tool instead. Used once, with a tiny
    max_iterations, purely to prove max_iterations actually trips inside
    this pilot's own execution (not just in the separate unit-level
    scratch_verify checks) and produces NO-PATCH, not a fabricated verdict.
    """

    name = "stub-cap-demo"

    def request(self, model, system, messages, tools, max_tokens, seed, timeout_s=120):
        del model, system, messages, tools, max_tokens, seed, timeout_s
        return NormalizedResponse(
            text="(stub) investigating, never submits.",
            tool_calls=[{"id": "stub_tool_1", "name": "run_test", "input": {}}],
            stop_reason="tool_use", input_tokens=0, output_tokens=0,
            raw={"content": [{"type": "tool_use", "id": "stub_tool_1", "name": "run_test", "input": {}}]},
        )

    def append_assistant(self, messages, resp):
        messages.append({"role": "assistant", "content": resp.raw["content"]})

    def append_tool_results(self, messages, results):
        messages.append({"role": "user", "content": results})


def _load_all_keep_tasks() -> list[dict]:
    tasks = []
    for p in CORPUS_FILES:
        tasks.extend(json.loads(p.read_text()))
    return [t for t in tasks if t["forge_decision"] == "KEEP"]


def _stratified_selection(keep_tasks: list[dict], n_per_design: int = 3) -> list[dict]:
    """Up to n_per_design tasks per design, spread across low/mid/high
    divergence_cycle within that design (not just the first N in file
    order) - real stratification, not a token gesture at the word."""
    by_design: dict[str, list[dict]] = {}
    for t in keep_tasks:
        by_design.setdefault(t["design"], []).append(t)

    selected = []
    for design in sorted(by_design):
        pool = sorted(by_design[design], key=lambda t: (t.get("divergence_cycle") is None, t.get("divergence_cycle", 0)))
        if len(pool) <= n_per_design:
            selected.extend(pool)
            continue
        idxs = sorted({round(i * (len(pool) - 1) / (n_per_design - 1)) for i in range(n_per_design)})
        selected.extend(pool[i] for i in idxs)
    return selected


def _run_matrix(tasks: list[dict], arms: list[str], model: str) -> tuple[list[dict], int, int]:
    """Returns (results, n_pending_before, n_cached_before) for this pass."""
    results = []
    n_pending, n_cached = 0, 0
    for task in tasks:
        task_input = _build_task_input(task)
        golden_source = Path(task_input.golden_path).read_text()
        loop_mod.make_provider = lambda api_key, base_url, _g=golden_source: GoldenRevertProvider(_g)
        for arm in arms:
            work_dir = TRANSCRIPTS_DIR / task["task_id"] / f"arm_{arm}"
            cached = _cached_trajectory(work_dir, model, seed=0)
            was_cached = cached is not None
            if was_cached:
                n_cached += 1
                verdict = cached["final_verdict"]
            else:
                n_pending += 1
                traj = run_task(
                    task_input, arm, model, "stub-no-key-needed", None, work_dir,
                    max_iterations=15, max_tokens_per_turn=4096, max_total_tokens=100_000,
                    max_wall_time_s=600.0, seed=0,
                )
                verdict = traj.final_verdict

            # Always reconstruct wall time from what's actually on disk, the
            # SAME way whether this row was just written or was already
            # cached - trajectory.json's own wall_time_s covers only the
            # LLM-loop portion (set before the BMC call in loop.py), so a
            # naive time.time() delta on a fresh run and a cache-hit's
            # stored field are NOT the same quantity (the fresh-run delta
            # also includes BMC time, the stored field never does). Adding
            # verdict_detail.runtime_s (the BMC ladder's own measured time,
            # always present whenever check_bmc actually ran) recovers a
            # consistent total for both cases - found by comparing a fresh
            # run's ~34s fifo timing against a same-task cache-hit's ~0s,
            # which should never differ for a deterministic stub.
            data = json.loads((work_dir / "trajectory.json").read_text())
            total_wall = round(data.get("wall_time_s", 0.0) + (data.get("verdict_detail") or {}).get("runtime_s", 0.0), 3)
            results.append({
                "task_id": task["task_id"], "design": task["design"], "arm": arm,
                "divergence_cycle": task.get("divergence_cycle"), "verdict": verdict,
                "wall_time_s": total_wall, "cached": was_cached,
            })
    return results, n_pending, n_cached


def main() -> None:
    env.sweep_orphaned_solvers()  # once, at batch start - never mid-batch

    keep_tasks = _load_all_keep_tasks()
    selected = _stratified_selection(keep_tasks, n_per_design=3)
    print(f"Stratified selection: {len(selected)} KEEP tasks across {len(set(t['design'] for t in selected))} designs")
    for t in selected:
        print(f"  {t['task_id']} (design={t['design']}, divergence_cycle={t.get('divergence_cycle')})")

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    arms = ["A", "B"]

    # ---- Pass 1: real run (or reuse of a prior real run already on disk) ----
    pass1_results, pass1_pending, pass1_cached = _run_matrix(selected, arms, STUB_MODEL_NAME)
    print(f"\nPass 1: {pass1_pending} run fresh, {pass1_cached} already cached on disk")

    # ---- Pass 2: identical call, immediately after - proves resumability's
    # cache-check path fires on freshly-written trajectories, not just on
    # trajectories from a previous process invocation. ----
    pass2_results, pass2_pending, pass2_cached = _run_matrix(selected, arms, STUB_MODEL_NAME)
    print(f"Pass 2 (resumability check): {pass2_pending} run fresh, {pass2_cached} already cached on disk")
    assert pass2_pending == 0, f"resumability broken: pass 2 re-ran {pass2_pending} task-arm(s) that pass 1 already wrote"
    assert pass2_cached == len(selected) * len(arms), "resumability broken: pass 2 did not find every pass-1 trajectory cached"

    verdicts = {}
    for r in pass1_results:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    print(f"\nVerdict distribution (stub golden-revert, all task-arm runs): {verdicts}")
    all_plausible = set(verdicts.keys()) == {"PLAUSIBLE"}
    print(f"All PLAUSIBLE as expected for a golden-revert no-op patch: {all_plausible}")

    # ---- Cap-trip demonstration: one dedicated task-arm run with a
    # never-submits stub and a deliberately tiny max_iterations, inside
    # this same pilot execution. ----
    demo_task = selected[0]
    demo_task_input = _build_task_input(demo_task)
    loop_mod.make_provider = lambda api_key, base_url: CapDemoProvider()
    demo_work_dir = TRANSCRIPTS_DIR / "_caps_demo" / demo_task["task_id"]
    t0 = time.time()
    demo_traj = run_task(
        demo_task_input, "B", STUB_MODEL_NAME, "stub-no-key-needed", None, demo_work_dir,
        max_iterations=3, max_tokens_per_turn=4096, max_total_tokens=100_000, max_wall_time_s=600.0, seed=0,
    )
    demo_wall = time.time() - t0
    print(
        f"\nCap-trip demo: max_iterations=3, stub never submits -> "
        f"stop_reason={demo_traj.stop_reason} verdict={demo_traj.final_verdict} "
        f"iterations={len(demo_traj.iterations)} wall={demo_wall:.3f}s"
    )
    assert demo_traj.stop_reason == "max_iterations", f"cap-trip demo did not trip as expected: {demo_traj.stop_reason}"
    assert demo_traj.final_verdict == "NO-PATCH", f"cap-trip demo produced a non-NO-PATCH verdict: {demo_traj.final_verdict}"

    wall_times = [r["wall_time_s"] for r in pass1_results]
    by_design_wall: dict[str, list[float]] = {}
    for r in pass1_results:
        by_design_wall.setdefault(r["design"], []).append(r["wall_time_s"])
    wall_time_summary = {
        "overall": {"min_s": round(min(wall_times), 2), "max_s": round(max(wall_times), 2), "sum_s": round(sum(wall_times), 2)},
        "by_design": {
            d: {"min_s": round(min(ws), 2), "max_s": round(max(ws), 2), "mean_s": round(sum(ws) / len(ws), 2), "n": len(ws)}
            for d, ws in sorted(by_design_wall.items())
        },
    }

    report = {
        "purpose": "PLUMBING TEST ONLY - proves harness wiring, not agent capability. No API key was available. See results/agent_pilot.md.",
        "stub_model_name": STUB_MODEL_NAME,
        "n_tasks_selected": len(selected),
        "n_designs": len(set(t["design"] for t in selected)),
        "n_per_design_target": 3,
        "arms": arms,
        "caps": {
            "max_iterations": 15, "max_tokens_per_turn": 4096,
            "max_total_tokens": 100_000, "max_wall_time_s": 600.0, "seed": 0,
        },
        "pass1": {"run_fresh": pass1_pending, "cached": pass1_cached},
        "pass2_resumability_check": {"run_fresh": pass2_pending, "cached": pass2_cached},
        "verdict_distribution": verdicts,
        "all_verdicts_plausible_as_expected": all_plausible,
        "cost_usd": 0,
        "wall_time_summary": wall_time_summary,
        "cap_trip_demo": {
            "task_id": demo_task["task_id"], "max_iterations_set": 3,
            "stop_reason": demo_traj.stop_reason, "final_verdict": demo_traj.final_verdict,
            "iterations_run": len(demo_traj.iterations), "wall_time_s": round(demo_wall, 3),
        },
        "example_task": next(r for r in pass1_results if r["task_id"] == "fsm_constant_perturbation_005" and r["arm"] == "A"),
        "results": pass1_results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {REPORT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
