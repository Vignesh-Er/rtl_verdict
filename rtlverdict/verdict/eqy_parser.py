"""Parses eqy's own log/summary output into EQUIVALENT / NON-EQUIVALENT /
INDETERMINATE. Fails closed by construction.

WHY THIS IS DELIBERATELY CONSERVATIVE (2026-08-08 investigation):
Per-partition strategies/*/sat/status files cannot be trusted to construct
a verdict, at any level of the stack. Evidence: a real 1-line FIFO mutant
(wr_ptr increments by 2 instead of 1) produced status:PASS for the
fifo.wr_ptr partition - AND eqy's own inline "run:" log said "Proved
equivalence of partition 'fifo.wr_ptr' using strategy 'sat'" - for a
signal demonstrably different between gold and gate. That is not a parser
bug on our side; eqy's own solving layer said PASS on something false, or
"Proved equivalence"/"PASS" mean something in eqy's internals other than
"gold.X == gate.X for all reachable states" (e.g. a matched-but-different
correspondence). We do not have a confident model of that semantics.

Separately, on native Windows, eqy's *aggregate* summary step has a
reproducible bug: the Makefile's grep-based status lookup fails with
"No such file or directory" on virtually every partition, on every
design tested (including a trivial parameter-free FSM with no memory),
regardless of path length. This has been observed on 100% of eqy runs
attempted on this machine, across five different designs. A clean
"DONE (PASS ...)" aggregate line has never been produced by this tool on
this environment.

CONCLUSION: this parser can recognize a clean PASS if one ever occurs, but
until that is independently verified fixed, treat every eqy invocation on
native Windows as producing INDETERMINATE. This is a Docker-trigger
finding (see project standing rule: any further load-bearing tool failure
on Windows moves the formal ladder to Docker), not a parser-workaround
situation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EqyResult:
    verdict: str  # "EQUIVALENT" | "NON-EQUIVALENT" | "INDETERMINATE"
    reason: str


def parse_eqy_log(log_text: str) -> EqyResult:
    """Fail-closed parser. NON-EQUIVALENT and EQUIVALENT are both narrow,
    high-confidence cases; everything else - including any tool-level
    error text, and any log this function does not explicitly recognize -
    returns INDETERMINATE. Never guess EQUIVALENT.
    """
    if "encountered an error" in log_text:
        return EqyResult(
            "INDETERMINATE",
            "eqy strategy execution hit a tool-level error (the known Windows "
            "partition-file-access bug, reproduced on every design tested), not a "
            "SAT proof outcome.",
        )

    if "DONE (PASS" in log_text:
        # Never independently observed on this machine as of this writing.
        # Kept because a fixed/patched eqy, or a Linux/Docker run, could
        # legitimately produce this, and it should be trusted when clean.
        return EqyResult("EQUIVALENT", "eqy's aggregate summary reports a clean PASS.")

    # Deliberately NOT mapping "Failed to prove equivalence" / "DONE (FAIL"
    # to NON-EQUIVALENT. We have direct evidence eqy's own solving layer can
    # say "Proved equivalence" for a partition that is provably different
    # from source inspection, so the failure direction is not confidently
    # understood either - only that PASS cannot be trusted as EQUIVALENT.
    return EqyResult(
        "INDETERMINATE",
        "eqy log did not match a clean, independently-trusted PASS shape. Per-"
        "partition and aggregate FAIL/PASS wording from eqy has not been reliably "
        "mapped to true equivalence on this environment - failing closed rather "
        "than guessing in either direction.",
    )
