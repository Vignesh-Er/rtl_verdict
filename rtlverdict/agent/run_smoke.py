"""CLI driver: run arms A and B across N tasks from corpus_v2, one trajectory
per (task, arm). Explicit instruction: run 10 tasks first and verify the
trajectory logs and verdict assignment look right BEFORE running the full
matrix - this script's default `--n 10` is exactly that first step, not a
shortcut past it.

Only forge_decision=="KEEP" tasks are usable here: KEEP means "formally
REFUTED and sim FAIL" - i.e. a real, confirmed bug the testbench actually
catches, which is the only case where there IS a failing log to show ARM A
in the first place. SILENT/QUARANTINE/DISCARD/ERROR tasks have no failing
log (SILENT), no confirmed bug (QUARANTINE), or are unusable by
construction (DISCARD/ERROR) - never sampled here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rtlverdict.agent.loop import DEFAULT_MODEL, TaskInput, run_task  # noqa: E402
from rtlverdict.forge.sim_confirm import run_sim  # noqa: E402

DESIGN_INFO = {
    # design -> (top_module, reset_signal, reset_active_low, clock_period)
    "fsm": ("fsm", "rst_n", True, 10000),
    "uart": ("uart", "rst_n", True, 10000),
    "spi_master": ("spi_master", "rst_n", True, 10000),
}


def _load_keep_tasks(corpus_path: Path, n: int) -> list[dict]:
    tasks = json.loads(corpus_path.read_text())
    keep = [t for t in tasks if t["forge_decision"] == "KEEP"]
    return keep[:n]


def _build_task_input(task: dict) -> TaskInput:
    design = task["design"]
    top_module, reset_signal, reset_active_low, clock_period = DESIGN_INFO[design]
    testbench_path = REPO_ROOT / "designs" / design / f"tb_{design}.v"
    mutant_path = task["mutant_path"]

    sim = run_sim(mutant_path, testbench_path)
    failing_log = f"RTLVERDICT_RESULT: {sim.outcome}" + (f" - {sim.detail}" if sim.detail else "")

    return TaskInput(
        task_id=task["task_id"], design=design,
        golden_path=str(REPO_ROOT / "designs" / design / f"{design}.v"),
        mutant_path=mutant_path, testbench_path=str(testbench_path),
        top_module=top_module, reset_signal=reset_signal, reset_active_low=reset_active_low,
        clock_period=clock_period, failing_log=failing_log,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Run arms A/B smoke test across N corpus_v2 KEEP tasks.")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--arms", nargs="+", default=["A", "B"], choices=["A", "B"])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint; omit for Anthropic")
    ap.add_argument("--api-key", default=None, help="defaults to ANTHROPIC_API_KEY or OPENAI_API_KEY env var")
    ap.add_argument("--corpus", default=str(REPO_ROOT / "benchmarks" / "corpus_v2" / "tasks.json"))
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "results" / "agent_runs"))
    ap.add_argument("--max-iterations", type=int, default=15)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print(
            "No API key found. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY with --base-url), "
            "or pass --api-key. Nothing was run.",
            file=sys.stderr,
        )
        sys.exit(1)

    tasks = _load_keep_tasks(Path(args.corpus), args.n)
    if not tasks:
        print(f"No KEEP tasks found in {args.corpus}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(tasks)} KEEP tasks from {args.corpus}")

    out_root = Path(args.out_dir)
    results = []
    for task in tasks:
        task_input = _build_task_input(task)
        for arm in args.arms:
            work_dir = out_root / task["task_id"] / f"arm_{arm}"
            print(f"[{task['task_id']}] arm {arm} ...", end=" ", flush=True)
            traj = run_task(
                task_input, arm, args.model, api_key, args.base_url, work_dir,
                max_iterations=args.max_iterations, seed=args.seed,
            )
            print(f"{traj.final_verdict} ({len(traj.iterations)} iters, "
                  f"{traj.total_input_tokens}+{traj.total_output_tokens} tok, {traj.wall_time_s:.1f}s)")
            results.append({
                "task_id": task["task_id"], "arm": arm, "verdict": traj.final_verdict,
                "iterations": len(traj.iterations), "input_tokens": traj.total_input_tokens,
                "output_tokens": traj.total_output_tokens, "wall_time_s": round(traj.wall_time_s, 2),
            })

    summary_path = out_root / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {len(results)} trajectory summaries to {summary_path}")

    by_verdict: dict[str, int] = {}
    for r in results:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
    print("=== VERDICT COUNTS ===")
    for v, c in sorted(by_verdict.items()):
        print(f"  {v}: {c}")


if __name__ == "__main__":
    main()
