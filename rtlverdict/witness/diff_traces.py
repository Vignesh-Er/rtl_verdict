"""Earliest divergence between two VCDs of the same design (golden vs
mutant, run against the same testbench stimulus). Walks common signals in
lockstep by sampled time, per the brief - never dumps a raw log.
"""

from __future__ import annotations

from dataclasses import dataclass

from rtlverdict.witness.vcd import VCDTrace


@dataclass
class Divergence:
    cycle: int
    signal: str
    expected: str  # golden's value
    actual: str  # mutant's value


def diff_traces(
    golden_vcd: str, mutant_vcd: str, clock_period: int, scope_filter: str | None = None
) -> Divergence | None:
    """Samples both traces once per `clock_period` (a VCD has no inherent
    notion of "cycle" - the caller supplies the period, e.g. from
    design.yaml/the testbench's `#N clk = ~clk` half-period doubled).
    `scope_filter` restricts comparison to signals whose path contains it
    (e.g. "dut") so testbench-internal bookkeeping variables like `errors`/
    `i` never produce a spurious "divergence" - only true DUT signals do.
    Returns None if no divergence found in either trace's overlapping range.
    """
    gold = VCDTrace(golden_vcd)
    mut = VCDTrace(mutant_vcd)

    def base_name(path: str) -> str:
        return path.split(".")[-1]

    gold_by_base = {base_name(p): p for p in gold.signals() if not scope_filter or scope_filter in p}
    mut_by_base = {base_name(p): p for p in mut.signals() if not scope_filter or scope_filter in p}
    common = sorted(set(gold_by_base) & set(mut_by_base))

    end_time = min(gold.end_time, mut.end_time)
    t = 0
    while t <= end_time:
        for base in common:
            gv = gold.value_at(gold_by_base[base], t)
            mv = mut.value_at(mut_by_base[base], t)
            if gv != mv:
                return Divergence(cycle=t // clock_period, signal=base, expected=gv, actual=mv)
        t += clock_period
    return None
