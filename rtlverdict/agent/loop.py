"""The ~200-line model-agnostic agent loop (P3). Bounded iterations, bounded
output tokens per turn, seeded (passed through - Anthropic's Messages API
has no seed parameter and silently ignores it; the seed is still recorded
in the trajectory for reproducibility bookkeeping, never presented as a
determinism guarantee the harness can't back).

Terminates when the agent calls submit_patch, after max_iterations, or on
an unrecoverable provider error. On submit_patch: runs the INVALID-PATCH
pre-check BEFORE ever building a miter (explicit P3 instruction); if valid,
reuses verdict/ladder.check_bmc for the real formal verdict on the
agent's fix vs golden - same degraded-mode BMC-only ladder and the same
"bounded pass is never promoted to an unbounded proof" rule as
forge/corpus.py, so a submitted fix can reach PLAUSIBLE (BMC bounded pass)
or REFUTED (BMC found a real counterexample), never an unbacked PROVEN.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from rtlverdict.agent.arms import ARMS
from rtlverdict.agent.patch_check import check_patch
from rtlverdict.agent.providers import make_provider
from rtlverdict.agent.tools import ToolContext, call_tool
from rtlverdict.agent.trajectory import IterationRecord, ToolCallRecord, Trajectory, new_trajectory
from rtlverdict.verdict.ladder import check_bmc

# Cheapest current model - a smoke run validates the HARNESS (trajectory
# logging, verdict assignment), not model debugging capability, so the
# default should cost near-nothing. Override --model for a real A/B run.
DEFAULT_MODEL = "claude-haiku-4-5"

# BMC-bounded pass is never promoted to an unbounded equivalence proof
# (ladder.py's permanent rule) - a submitted fix that survives BMC is
# PLAUSIBLE, not PROVEN. REFUTED means BMC found a real counterexample:
# the "fix" is genuinely still wrong.
_FORMAL_TO_VERDICT = {"PROVEN-BMC": "PLAUSIBLE", "REFUTED": "REFUTED", "INDETERMINATE": "INDETERMINATE"}


@dataclass
class TaskInput:
    task_id: str
    design: str
    golden_path: str
    mutant_path: str  # the buggy RTL the agent is asked to fix
    testbench_path: str
    top_module: str
    reset_signal: str
    reset_active_low: bool
    clock_period: int
    failing_log: str  # raw sim_confirm output - what ARM A sees, and ARM B sees too


def run_task(
    task: TaskInput,
    arm_name: str,
    model: str,
    api_key: str,
    base_url: str | None,
    work_dir: Path,
    max_iterations: int = 15,
    max_tokens_per_turn: int = 4096,
    max_total_tokens: int = 100_000,
    max_wall_time_s: float = 600.0,
    seed: int = 0,
) -> Trajectory:
    """Hard caps (enforced here, not by convention): max_iterations bounds
    turn count; max_tokens_per_turn bounds one response; max_total_tokens
    bounds cumulative input+output tokens across the whole task -
    checked after every turn, so a long-running conversation with many
    cheap turns can't quietly outspend a token budget that only looked at
    per-turn cost; max_wall_time_s bounds real elapsed time regardless of
    token/iteration counts, so a slow provider or a stuck tool call can't
    run indefinitely. Any cap tripped ends the task with NO-PATCH and a
    stop_reason naming which cap fired - never a silent runaway loop.
    """
    provider = make_provider(api_key, base_url)
    arm = ARMS[arm_name]()
    traj = new_trajectory(
        task.task_id, arm_name, model, provider.name, seed,
        max_iterations, max_tokens_per_turn, max_total_tokens, max_wall_time_s,
    )

    ctx = ToolContext(
        golden_path=task.golden_path, mutant_path=task.mutant_path,
        testbench_path=task.testbench_path, clock_period=task.clock_period,
        work_dir=work_dir / "tools",
    )

    user_turn = (
        f"Buggy source ({Path(task.mutant_path).name}):\n```verilog\n"
        f"{Path(task.mutant_path).read_text()}\n```\n\n"
        f"Testbench failure output:\n{task.failing_log}"
    )
    messages: list = [{"role": "user", "content": user_turn}]

    wall_start = time.time()
    submitted_patch: str | None = None
    submitted_explanation = ""
    stop_reason = "max_iterations"
    nudged = False

    for i in range(max_iterations):
        elapsed = time.time() - wall_start
        if elapsed >= max_wall_time_s:
            stop_reason = "max_wall_time"
            break
        if traj.total_input_tokens + traj.total_output_tokens >= max_total_tokens:
            stop_reason = "max_total_tokens"
            break

        iter_start = time.time()
        try:
            # Never let a single request outlive the task's remaining wall
            # budget - a stuck/slow request is bounded by whichever is
            # smaller, its own per-request timeout or what's left overall.
            request_timeout = max(1, int(min(120, max_wall_time_s - elapsed)))
            resp = provider.request(
                model=model, system=arm.system_prompt, messages=messages,
                tools=arm.tools, max_tokens=max_tokens_per_turn, seed=seed,
                timeout_s=request_timeout,
            )
        except Exception as e:  # noqa: BLE001 - a provider/network failure ends the task cleanly
            traj.finish(verdict="ERROR", detail={}, stop_reason="provider_error", error=f"{type(e).__name__}: {e}")
            traj.wall_time_s = time.time() - wall_start
            traj.write(work_dir / "trajectory.json")
            return traj

        provider.append_assistant(messages, resp)

        submit_call = next((tc for tc in resp.tool_calls if tc["name"] == "submit_patch"), None)
        other_calls = [tc for tc in resp.tool_calls if tc["name"] != "submit_patch"]

        tool_records: list[ToolCallRecord] = []
        tool_results = []
        for tc in other_calls:
            output, is_error = call_tool(ctx, tc["name"], tc["input"])
            tool_records.append(ToolCallRecord(tc["name"], tc["input"], output, is_error))
            tool_results.append({"tool_call_id": tc["id"], "output": output, "is_error": is_error})

        traj.add_iteration(IterationRecord(
            iteration=i, role="assistant", text=resp.text, tool_calls=tool_records,
            input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
            wall_time_s=time.time() - iter_start,
        ))

        if submit_call is not None:
            submitted_patch = submit_call["input"].get("patched_source", "")
            submitted_explanation = submit_call["input"].get("explanation", "")
            stop_reason = "patch_submitted"
            break

        if not resp.tool_calls:
            # No tool call at all - give one nudge in case the agent just
            # forgot submit_patch exists, then respect a second silence as
            # genuinely done rather than looping forever.
            if not nudged:
                nudged = True
                messages.append({
                    "role": "user",
                    "content": "Call submit_patch with your fix when ready, or continue investigating with a tool call.",
                })
                continue
            stop_reason = "no_patch_submitted"
            break

        if tool_results:
            provider.append_tool_results(messages, tool_results)

    traj.wall_time_s = time.time() - wall_start

    if submitted_patch is None:
        traj.finish(verdict="NO-PATCH", detail={}, stop_reason=stop_reason)
        traj.write(work_dir / "trajectory.json")
        return traj

    traj.patch_submitted = submitted_patch
    golden_source = Path(task.golden_path).read_text()
    check = check_patch(submitted_patch, golden_source, task.top_module, task.testbench_path)
    if not check.ok:
        traj.invalid_patch_reason = check.reason
        traj.finish(
            verdict="INVALID-PATCH",
            detail={"reason": check.reason, "explanation": submitted_explanation},
            stop_reason="patch_submitted",
        )
        traj.write(work_dir / "trajectory.json")
        return traj

    patch_path = work_dir / "submitted_patch.v"
    patch_path.write_text(submitted_patch)
    formal = check_bmc(
        task.golden_path, str(patch_path), task.top_module, task.reset_signal, task.reset_active_low,
        work_dir / "formal", k=40, timeout_s=120,
    )
    traj.finish(
        verdict=_FORMAL_TO_VERDICT[formal.verdict],
        detail={
            "formal_verdict": formal.verdict, "k": formal.k, "engine": formal.engine,
            "runtime_s": round(formal.runtime_s, 2), "divergence_cycle": formal.divergence_cycle,
            "explanation": submitted_explanation,
        },
        stop_reason="patch_submitted",
    )
    traj.write(work_dir / "trajectory.json")
    return traj
