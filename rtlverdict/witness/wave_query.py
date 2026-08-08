"""Thin unified interface over vcd.py's three primitives, matching the
brief's wave_query(vcd, op, args) shape.
"""

from __future__ import annotations

from rtlverdict.witness.vcd import VCDTrace


def wave_query(vcd_path: str, op: str, args: dict) -> dict:
    trace = VCDTrace(vcd_path)
    if op == "value_at":
        return {"signal": args["signal"], "t": args["t"], "value": trace.value_at(args["signal"], args["t"])}
    if op == "transitions":
        t = trace.transitions(args["signal"], args["t0"], args["t1"])
        return {"signal": args["signal"], "transitions": [{"t": x[0], "v": x[1]} for x in t]}
    if op == "window":
        rows = trace.window(args["signals"], args["t"], args["k"], args["step"])
        return {"window": rows}
    raise ValueError(f"unknown wave_query op: {op!r}")
