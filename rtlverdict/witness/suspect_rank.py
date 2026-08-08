"""suspect_rank: COI lines intersected with signals that toggled before the
divergence, ranked by proximity - COI lines are already a sound (if coarse)
over-approximation; toggle-proximity to divergence is a heuristic on top of
that to focus attention, not a soundness claim of its own.

KNOWN LIMITATION (real, not yet solved): a VCD only records when a SIGNAL's
value changed, not which of several source lines that can write it caused
a specific change. Every line that writes the same signal currently ties on
score. Confirmed on real data: for fsm's `busy` (written at lines 13-model-
decl, 16, 20, 22, 23, 26, 37), all seven tie for first place regardless of
which one actually fired. The true root cause is always IN the tied top
group (consistent with the 100% COI containment gate), just not uniquely
first. Breaking these ties needs per-statement execution tracking (e.g. a
$display per branch, or bit-level toggle inspection distinguishing which
case arm ran), not implemented yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from rtlverdict.witness.coi import build_dependency_index, cone_of_influence
from rtlverdict.witness.vcd import VCDTrace


@dataclass
class Suspect:
    file: str
    line: int
    signal: str
    score: float
    reason: str


def suspect_rank(
    source: str,
    diverging_signal: str,
    vcd_path: str,
    divergence_time: int,
    scope_prefix: str = "",
    file_name: str = "x.v",
) -> list[Suspect]:
    coi_lines = cone_of_influence(source, diverging_signal, file_name=file_name)
    dep_index = build_dependency_index(source)

    # invert: line -> signal it belongs to (a line can be an assignment's
    # own line, in which case dep_index tells us directly which signal it
    # writes; condition lines are attributed to whichever signal(s) they
    # gate, which may be more than one - keep all of them).
    line_to_signals: dict[int, set[str]] = {}
    for sig, entries in dep_index.items():
        for own_lines, _reads in entries:
            for l in own_lines:
                line_to_signals.setdefault(l, set()).add(sig)

    trace = VCDTrace(vcd_path)
    suspects: list[Suspect] = []
    for c in coi_lines:
        line = c["line"]
        signals = line_to_signals.get(line, set())
        if not signals:
            continue
        for sig in signals:
            full_path = f"{scope_prefix}.{sig}" if scope_prefix else sig
            try:
                transitions = trace.transitions(full_path, 0, divergence_time)
            except KeyError:
                continue
            before = [t for t, _ in transitions if t < divergence_time]
            if not before:
                continue
            last_toggle = before[-1]
            proximity = divergence_time - last_toggle
            score = 1.0 / (1.0 + proximity)
            suspects.append(
                Suspect(
                    file=file_name,
                    line=line,
                    signal=sig,
                    score=score,
                    reason=f"in COI of {diverging_signal!r}, {sig!r} last toggled {proximity} time units before divergence",
                )
            )

    suspects.sort(key=lambda s: s.score, reverse=True)
    return suspects
