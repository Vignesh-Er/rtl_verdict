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

Cost control (P4): before spending anything, prints a hard-ceiling cost
estimate (task-arms still needing a run x max_total_tokens x output price)
and requires confirmation above --cost-threshold. This is a true ceiling,
not a guess - it's derived from the same max_total_tokens cap loop.py
actually enforces, not a separate estimate that could drift from reality.

Resumability: a trajectory.json already on disk for a given
(task_id, arm, model, seed) is reused rather than re-run - restarting an
interrupted 60-task run never re-spends on the first 40 that already
completed. A cached trajectory from a DIFFERENT model or seed is treated
as absent (never silently reused across configs).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rtlverdict import env  # noqa: E402
from rtlverdict.agent.loop import DEFAULT_MODEL, TaskInput, run_task  # noqa: E402
from rtlverdict.forge.sim_confirm import run_sim  # noqa: E402

DESIGN_INFO = {
    # design -> (top_module, reset_signal, reset_active_low, clock_period)
    "fsm": ("fsm", "rst_n", True, 10000),
    "uart": ("uart", "rst_n", True, 10000),
    "spi_master": ("spi_master", "rst_n", True, 10000),
    "fifo": ("fifo", "rst_n", True, 10000),
}

# Formal-check params for judging an agent's SUBMITTED fix, per design.
# fifo needs memory_map=True and a shallower k - see FINDINGS.md's Day-9
# pivot section (plain BMC hits SMT array-theory blowup on fifo's mem[]
# array; k=25/90s was calibrated empirically, k=40 does not reliably
# complete even with memory_map).
FORMAL_PARAMS = {
    "fsm": (40, 120, False),
    "uart": (40, 120, False),
    "spi_master": (40, 120, False),
    "fifo": (25, 90, True),
}

# output-token price per 1M tokens - used as the (conservative) blended
# rate for the whole max_total_tokens budget, since output is priced
# higher than input and the budget covers both combined. Unknown models
# get no estimate and an explicit "can't estimate" confirmation instead of
# a silently-skipped one.
PRICING_OUTPUT_PER_1M = {
    "claude-haiku-4-5": 5.00,
    "claude-sonnet-5": 15.00,
    "claude-sonnet-4-6": 15.00,
    "claude-opus-5": 25.00,
    "claude-opus-4-8": 25.00,
}


def _load_keep_tasks(corpus_path: Path, n: int) -> list[dict]:
    tasks = json.loads(corpus_path.read_text())
    keep = [t for t in tasks if t["forge_decision"] == "KEEP"]
    return keep[:n]


def _build_task_input(task: dict) -> TaskInput:
    design = task["design"]
    top_module, reset_signal, reset_active_low, clock_period = DESIGN_INFO[design]
    formal_k, formal_timeout_s, formal_memory_map = FORMAL_PARAMS[design]
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
        formal_k=formal_k, formal_timeout_s=formal_timeout_s, formal_memory_map=formal_memory_map,
    )


def _cached_trajectory(work_dir: Path, model: str, seed: int) -> dict | None:
    """A cached trajectory is reused only if it matches this run's model AND
    seed - a cache hit from a different config is treated as absent, never
    silently reused (that would mix results across configurations)."""
    traj_path = work_dir / "trajectory.json"
    if not traj_path.exists():
        return None
    try:
        data = json.loads(traj_path.read_text())
    except json.JSONDecodeError:
        return None  # partially-written file from an interrupted run - treat as absent, re-run
    if data.get("model") != model or data.get("seed") != seed:
        return None
    if data.get("final_verdict") is None:
        return None  # started but never finished - re-run
    return data


def _estimate_and_confirm(n_pending: int, model: str, max_total_tokens: int, cost_threshold: float, auto_yes: bool) -> None:
    if n_pending == 0:
        return
    price = PRICING_OUTPUT_PER_1M.get(model)
    if price is None:
        print(f"WARNING: no known pricing for model {model!r} - cannot estimate cost.")
        if auto_yes:
            return
        resp = input(f"Proceed with {n_pending} task-arm run(s) with no cost estimate? [y/N] ")
        if resp.strip().lower() != "y":
            print("Aborted - no API calls made.")
            sys.exit(1)
        return

    ceiling = n_pending * max_total_tokens * price / 1_000_000
    print(
        f"Cost ceiling: {n_pending} task-arm run(s) x {max_total_tokens} max_total_tokens "
        f"x ${price:.2f}/1M (output-priced, conservative upper bound) = ${ceiling:.2f} MAX"
    )
    print("(This is the hard ceiling loop.py's max_total_tokens cap actually enforces, not a guess. Typical cost is usually well under it.)")
    if ceiling > cost_threshold and not auto_yes:
        resp = input(f"Ceiling ${ceiling:.2f} exceeds --cost-threshold ${cost_threshold:.2f}. Proceed? [y/N] ")
        if resp.strip().lower() != "y":
            print("Aborted - no API calls made.")
            sys.exit(1)


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
    ap.add_argument("--max-tokens-per-turn", type=int, default=4096)
    ap.add_argument("--max-total-tokens", type=int, default=100_000, help="hard per-task cap, input+output combined")
    ap.add_argument("--max-wall-time-s", type=float, default=600.0, help="hard per-task wall-clock cap")
    ap.add_argument("--cost-threshold", type=float, default=1.00, help="USD ceiling above which confirmation is required")
    ap.add_argument("--yes", action="store_true", help="skip the cost-ceiling confirmation prompt")
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

    env.sweep_orphaned_solvers()  # pre-flight: never start a batch with a stray solver already running

    tasks = _load_keep_tasks(Path(args.corpus), args.n)
    if not tasks:
        print(f"No KEEP tasks found in {args.corpus}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(tasks)} KEEP tasks from {args.corpus}")

    out_root = Path(args.out_dir)

    # Resumability: figure out what's already cached BEFORE estimating cost,
    # so re-running an interrupted batch only prices (and confirms) the work
    # actually left to do.
    pending: list[tuple[dict, str, Path]] = []
    cached_results: list[dict] = []
    for task in tasks:
        for arm in args.arms:
            work_dir = out_root / task["task_id"] / f"arm_{arm}"
            cached = _cached_trajectory(work_dir, args.model, args.seed)
            if cached is not None:
                cached_results.append({
                    "task_id": task["task_id"], "arm": arm, "verdict": cached["final_verdict"],
                    "iterations": len(cached.get("iterations", [])),
                    "input_tokens": cached.get("total_input_tokens", 0),
                    "output_tokens": cached.get("total_output_tokens", 0),
                    "wall_time_s": round(cached.get("wall_time_s", 0.0), 2), "cached": True,
                })
            else:
                pending.append((task, arm, work_dir))

    if cached_results:
        print(f"Resuming: {len(cached_results)} task-arm run(s) already cached for model={args.model} seed={args.seed}, skipping")
    print(f"{len(pending)} task-arm run(s) remaining")

    _estimate_and_confirm(len(pending), args.model, args.max_total_tokens, args.cost_threshold, args.yes)

    results: list[dict] = list(cached_results)
    for task, arm, work_dir in pending:
        task_input = _build_task_input(task)
        print(f"[{task['task_id']}] arm {arm} ...", end=" ", flush=True)
        traj = run_task(
            task_input, arm, args.model, api_key, args.base_url, work_dir,
            max_iterations=args.max_iterations, max_tokens_per_turn=args.max_tokens_per_turn,
            max_total_tokens=args.max_total_tokens, max_wall_time_s=args.max_wall_time_s, seed=args.seed,
        )
        print(f"{traj.final_verdict} ({len(traj.iterations)} iters, "
              f"{traj.total_input_tokens}+{traj.total_output_tokens} tok, {traj.wall_time_s:.1f}s)")
        results.append({
            "task_id": task["task_id"], "arm": arm, "verdict": traj.final_verdict,
            "iterations": len(traj.iterations), "input_tokens": traj.total_input_tokens,
            "output_tokens": traj.total_output_tokens, "wall_time_s": round(traj.wall_time_s, 2),
            "cached": False,
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
