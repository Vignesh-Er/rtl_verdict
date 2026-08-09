"""P1: generate fifo's mutation corpus, using the SAME 6 operators and the
SAME `generate_for_design` pipeline as fsm/uart/spi_master, but with
fifo-specific formal-check params: memory_map=True (required - fifo's
`mem[]` array causes SMT array-theory blowup without it, see design.yaml
and FINDINGS.md's Day-9 pivot section) and k=25/timeout_s=90 (calibrated
empirically - golden-vs-golden runtimes were 5.3s/11.4s/33.9s at
k=15/20/25; k=40 does not reliably complete even with memory_map, timing
out at 120s in the calibration probe).

Writes to a SEPARATE directory (benchmarks/corpus_v2_fifo_addition/) rather
than merging into corpus_v2/tasks.json directly - inspect first, merge as
an explicit separate step, same discipline as deep_bmc_promote.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from rtlverdict.forge.corpus import generate_for_design

FIFO_K = 25
FIFO_TIMEOUT_S = 90


def main() -> None:
    repo_root = Path(__file__).parent.parent.parent
    out_dir = repo_root / "benchmarks" / "corpus_v2_fifo_addition"

    print("=== fifo ===")
    records, stats = generate_for_design(
        "fifo", repo_root / "designs" / "fifo", "fifo", "rst_n", True,
        max_candidates=None, out_dir=out_dir,
        formal_k=FIFO_K, formal_timeout_s=FIFO_TIMEOUT_S, formal_memory_map=True,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = out_dir / "tasks.json"
    tasks_path.write_text(json.dumps([asdict(r) for r in records], indent=2))

    by_decision: dict[str, int] = {}
    for r in records:
        by_decision[r.forge_decision] = by_decision.get(r.forge_decision, 0) + 1

    print()
    print("=== SUMMARY ===")
    for decision, count in sorted(by_decision.items()):
        print(f"  {decision}: {count}")
    print(f"generated: {stats['generated']}  distinct: {stats['distinct']}  recorded: {len(records)}")
    assert sum(by_decision.values()) == len(records) == stats["distinct"], "accounting mismatch"
    print(f"wrote {tasks_path}")


if __name__ == "__main__":
    main()
