"""Trajectory logging for agent runs - the full record of what an agent did
on one task: every iteration (assistant text/tool calls/tool results),
token usage, wall time, and the final formal verdict. Written as JSON so
post-hoc arm-A-vs-arm-B analysis never re-derives anything from a live API
response - only from what's on disk, per the standing "never report a
number you didn't produce by running code" rule.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ToolCallRecord:
    tool_name: str
    tool_input: dict
    tool_output: str  # JSON-serialized result, or error text if is_error
    is_error: bool


@dataclass
class IterationRecord:
    iteration: int
    role: str  # "assistant"
    text: str  # assistant's visible text this turn, "" if none
    tool_calls: list[ToolCallRecord]
    input_tokens: int
    output_tokens: int
    wall_time_s: float


@dataclass
class Trajectory:
    task_id: str
    arm: str  # "A" | "B"
    model: str
    provider: str  # "anthropic" | "openai-compatible"
    seed: int
    max_iterations: int
    max_tokens_per_turn: int
    started_at: str
    iterations: list[IterationRecord] = field(default_factory=list)
    patch_submitted: str | None = None
    invalid_patch_reason: str | None = None
    # PROVEN | PLAUSIBLE | REFUTED | INDETERMINATE | INVALID-PATCH | NO-PATCH | ERROR
    final_verdict: str | None = None
    verdict_detail: dict = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    wall_time_s: float = 0.0
    stop_reason: str | None = None
    error: str | None = None

    def add_iteration(self, rec: IterationRecord) -> None:
        self.iterations.append(rec)
        self.total_input_tokens += rec.input_tokens
        self.total_output_tokens += rec.output_tokens

    def finish(self, verdict: str, detail: dict, stop_reason: str, error: str | None = None) -> None:
        self.final_verdict = verdict
        self.verdict_detail = detail
        self.stop_reason = stop_reason
        self.error = error

    def write(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))


def new_trajectory(
    task_id: str, arm: str, model: str, provider: str, seed: int,
    max_iterations: int, max_tokens_per_turn: int,
) -> Trajectory:
    return Trajectory(
        task_id=task_id, arm=arm, model=model, provider=provider, seed=seed,
        max_iterations=max_iterations, max_tokens_per_turn=max_tokens_per_turn,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
