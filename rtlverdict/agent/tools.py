"""Wraps witness's Python functions as tool-use schemas for ARM B, called
in-process (not shelled out) - more efficient and there's no CLI to shell
out to anyway. Golden/testbench paths are bound into ToolContext by the
harness per-task and are NEVER exposed as agent-suppliable parameters: the
agent supplies only what it could legitimately know while debugging (a
signal name it read from evidence, a wave_query op/args), never a path to
the reference design's source. This mirrors giving a debugging engineer
access to a golden reference model's simulated BEHAVIOR (as in real
co-simulation verification flows), not its source code - run_test and
diff_traces report where behavior diverges, never what the golden source
says.

wave_query and cone_of_influence/suspect_rank operate only on the buggy
design's OWN trace/source - inspecting your own DUT is unambiguously fair
and needs no golden access at all.

All wave_query time arguments (t, t0, t1, step) are raw VCD simulation
time units, not cycle numbers - run_test's result includes clock_period so
the agent can convert (cycle * clock_period) if it wants to reason in
cycles. Deliberately NOT auto-converted here: transition times in a VCD
aren't guaranteed to land on exact multiples of clock_period, so silently
dividing back to a "cycle" would sometimes floor away real information.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from rtlverdict.witness.coi import cone_of_influence
from rtlverdict.witness.diff_traces import diff_traces
from rtlverdict.witness.run_test import run_test
from rtlverdict.witness.suspect_rank import suspect_rank
from rtlverdict.witness.wave_query import wave_query


@dataclass
class ToolContext:
    golden_path: str
    mutant_path: str
    testbench_path: str
    clock_period: int
    work_dir: Path
    last_signal: str | None = field(default=None, init=False)
    last_divergence_time: int | None = field(default=None, init=False)
    last_vcd_path: str | None = field(default=None, init=False)


SUBMIT_PATCH_SCHEMA = {
    "name": "submit_patch",
    "description": (
        "Submit your fix. Provide the COMPLETE corrected Verilog source for the module - "
        "the whole file with your fix applied, not a diff. This ends the task - only call "
        "this when you are done investigating."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "patched_source": {"type": "string", "description": "the complete fixed Verilog source, full file"},
            "explanation": {"type": "string", "description": "brief explanation of the bug and the fix"},
        },
        "required": ["patched_source"],
    },
}

TOOL_SCHEMAS = [
    {
        "name": "run_test",
        "description": (
            "Run the buggy RTL against its testbench with waveform dumping and compare it to "
            "a golden reference implementation's execution on the same stimulus. Returns the "
            "FIRST point where any DUT-internal signal's value diverges from the reference - "
            "not a raw simulation log. Result includes clock_period (time units per cycle), "
            "for use with wave_query. Call this first to find where behavior goes wrong."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "wave_query",
        "description": (
            "Inspect the buggy design's own waveform trace (from the most recent run_test "
            "call - calls run_test automatically first if you haven't yet). op='value_at' "
            "needs args={signal, t}; op='transitions' needs args={signal, t0, t1} and returns "
            "every value change of that signal in [t0, t1]; op='window' needs "
            "args={signals: [...], t, k, step} and returns a table of 2k+1 samples centered "
            "on t, 'step' time units apart, one column per listed signal. t/t0/t1/step are "
            "raw simulation time units, not cycle numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["value_at", "transitions", "window"]},
                "args": {"type": "object", "description": "op-specific arguments, see description"},
            },
            "required": ["op", "args"],
        },
    },
    {
        "name": "diff_traces",
        "description": (
            "Re-run the golden-vs-buggy trace comparison with an explicit scope filter "
            "(default 'dut' restricts to DUT-internal signals; pass an empty string to compare "
            "every signal, including testbench-internal bookkeeping variables). Returns the "
            "first divergence found in the overlapping trace window, or null if none."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"scope_filter": {"type": "string", "default": "dut"}},
            "required": [],
        },
    },
    {
        "name": "cone_of_influence",
        "description": (
            "Static backward slice over the buggy RTL's own source: every source line that "
            "can possibly affect the given signal's value, including control-dependent lines "
            "(enclosing if/case conditions). A sound over-approximation - the true root cause "
            "is always in this set, though the set may include unrelated lines too."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"signal": {"type": "string", "description": "signal name, e.g. from run_test's first_divergence"}},
            "required": ["signal"],
        },
    },
    {
        "name": "suspect_rank",
        "description": (
            "Ranks cone_of_influence lines by proximity: how recently the line's signal "
            "toggled before the divergence found by the last run_test/diff_traces call. "
            "Higher score = toggled closer to the divergence = more likely the root cause. "
            "KNOWN LIMITATION: lines that write the same signal currently tie on score - the "
            "true root cause is always in the top tied group, just not always uniquely first. "
            "Uses the last known diverging signal (from run_test/diff_traces) if none is given."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"signal": {"type": "string", "description": "defaults to the last known diverging signal"}},
            "required": [],
        },
    },
]


def _ensure_run(ctx: ToolContext) -> None:
    if ctx.last_vcd_path is None:
        dispatch_run_test(ctx)


def dispatch_run_test(ctx: ToolContext) -> dict:
    rd = ctx.work_dir / "run_test"
    r = run_test(ctx.golden_path, ctx.mutant_path, ctx.testbench_path, ctx.clock_period, str(rd))
    ctx.last_vcd_path = str(rd / "mutant.vcd")
    if r.first_divergence:
        ctx.last_signal = r.first_divergence["signal"]
        ctx.last_divergence_time = r.first_divergence["cycle"] * ctx.clock_period
    return {
        "pass": r.pass_, "first_divergence": r.first_divergence, "summary": r.summary,
        "clock_period": ctx.clock_period,
    }


def dispatch_wave_query(ctx: ToolContext, op: str, args: dict) -> dict:
    _ensure_run(ctx)
    return wave_query(ctx.last_vcd_path, op, args)


def dispatch_diff_traces(ctx: ToolContext, scope_filter: str = "dut") -> dict:
    _ensure_run(ctx)
    rd = ctx.work_dir / "run_test"
    div = diff_traces(str(rd / "golden.vcd"), str(rd / "mutant.vcd"), ctx.clock_period, scope_filter or None)
    if div is None:
        return {"divergence": None}
    ctx.last_signal = div.signal
    ctx.last_divergence_time = div.cycle * ctx.clock_period
    return {"divergence": {"cycle": div.cycle, "signal": div.signal, "expected": div.expected, "actual": div.actual}}


def dispatch_cone_of_influence(ctx: ToolContext, signal: str) -> dict:
    source = Path(ctx.mutant_path).read_text()
    return {"lines": cone_of_influence(source, signal)}


def dispatch_suspect_rank(ctx: ToolContext, signal: str | None = None) -> dict:
    _ensure_run(ctx)
    sig = signal or ctx.last_signal
    if sig is None or ctx.last_divergence_time is None:
        return {"error": "no diverging signal known yet - call run_test first"}
    source = Path(ctx.mutant_path).read_text()
    suspects = suspect_rank(source, sig, ctx.last_vcd_path, ctx.last_divergence_time, scope_prefix="dut")
    return {
        "suspects": [
            {"file": s.file, "line": s.line, "signal": s.signal, "score": round(s.score, 4), "reason": s.reason}
            for s in suspects
        ]
    }


DISPATCH = {
    "run_test": lambda ctx, **kw: dispatch_run_test(ctx),
    "wave_query": dispatch_wave_query,
    "diff_traces": dispatch_diff_traces,
    "cone_of_influence": dispatch_cone_of_influence,
    "suspect_rank": dispatch_suspect_rank,
}


def call_tool(ctx: ToolContext, name: str, tool_input: dict) -> tuple[str, bool]:
    """Returns (output_text, is_error). Never raises - a tool exception
    becomes an is_error tool_result so the agent can see and recover from
    it (the API's documented error-handling pattern), rather than crashing
    the whole run on one bad tool call.
    """
    fn = DISPATCH.get(name)
    if fn is None:
        return f"unknown tool: {name!r}", True
    try:
        result = fn(ctx, **tool_input)
        return json.dumps(result), False
    except Exception as e:  # noqa: BLE001 - tool errors must reach the agent, not crash the loop
        return f"{type(e).__name__}: {e}", True
