"""P0 (day-9 pivot): re-run BMC at k=200 on every QUARANTINE mutant in
corpus_v2, to recover deep-divergence bugs the original k=40 pass couldn't
refute in time. Free corpus growth from compute alone - no new mutants
generated, no new operators.

Promotion rule:
  REFUTED (any runtime)   -> PROMOTE to KEEP, deep_divergence=true, real
                              divergence_cycle recorded. A counterexample is
                              a positive, independently-checkable proof -
                              its validity does not depend on how much of
                              the search budget was spent finding it, unlike
                              an absence-of-counterexample claim.
  PROVEN-BMC/INDETERMINATE -> stays QUARANTINE. Additionally tagged
                              near_timeout=true when runtime >= 80% of the
                              budget - a k=200 run that barely finishes is
                              not trusted as "searched deep enough": the
                              solver may be running out of gas, not
                              confirming absence of a bug. This never
                              changes the decision (QUARANTINE either way),
                              only what confidence gets reported about it.

Only applies to fsm/uart/spi_master mutants: all three designs' design.yaml
documents "No memories" and a plain bmc40->bmc200_deep ladder (no
memory_map special-casing needed). fifo mutants are handled separately
(P1, generate_fifo_corpus.py) because fifo's design.yaml documents real SMT
array-theory blowup at depth 12-14 that a plain deeper BMC pass would not
survive - it needs a memory_map prep step first.

Writes results to benchmarks/corpus_v2/deep_bmc_promotions.json as a
standalone report - does NOT mutate tasks.json itself. Applying promotions
to the corpus is a separate, explicit step (apply_deep_bmc_promotions.py)
so the raw promotion data can be spot-checked before it becomes part of
the corpus of record.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rtlverdict import env
from rtlverdict.verdict.ladder import check_bmc

DESIGN_INFO = {
    "fsm": ("fsm", "rst_n", True),
    "uart": ("uart", "rst_n", True),
    "spi_master": ("spi_master", "rst_n", True),
}

K = 200
TIMEOUT_S = 150
NEAR_TIMEOUT_FRACTION = 0.8


def main() -> None:
    env.sweep_orphaned_solvers()  # pre-flight: never start a batch with a stray solver already running

    repo_root = Path(__file__).parent.parent.parent
    tasks_path = repo_root / "benchmarks" / "corpus_v2" / "tasks.json"
    tasks = json.loads(tasks_path.read_text())
    quarantined = [t for t in tasks if t["forge_decision"] == "QUARANTINE" and t["design"] in DESIGN_INFO]
    skipped_fifo = [t for t in tasks if t["forge_decision"] == "QUARANTINE" and t["design"] not in DESIGN_INFO]
    print(f"Loaded {len(quarantined)} QUARANTINE tasks from {tasks_path} (design in {sorted(DESIGN_INFO)})")
    if skipped_fifo:
        print(f"Skipping {len(skipped_fifo)} QUARANTINE tasks for other designs (handled separately)")

    out_dir = repo_root / "benchmarks" / "corpus_v2" / "deep_bmc_work"
    promotions: list[dict] = []
    start_all = time.time()

    for i, t in enumerate(quarantined):
        design = t["design"]
        top_module, reset_signal, reset_active_low = DESIGN_INFO[design]
        golden_path = repo_root / "designs" / design / f"{design}.v"
        mutant_path = repo_root / t["mutant_path"]
        work_dir = out_dir / t["task_id"]

        formal = check_bmc(
            golden_path, mutant_path, top_module, reset_signal, reset_active_low,
            work_dir, k=K, timeout_s=TIMEOUT_S,
        )

        near_timeout = formal.runtime_s >= NEAR_TIMEOUT_FRACTION * TIMEOUT_S
        decision = "PROMOTE" if formal.verdict == "REFUTED" else "STAY-QUARANTINE"

        rec = {
            "task_id": t["task_id"], "design": design,
            "old_formal_k": t["formal_k"], "old_verdict": t["equivalence_to_golden"],
            "new_verdict": formal.verdict, "new_k": formal.k,
            "new_runtime_s": round(formal.runtime_s, 2), "near_timeout": near_timeout,
            "divergence_cycle": formal.divergence_cycle,
            "failing_assertion_line": formal.failing_assertion_line,
            "decision": decision,
        }
        promotions.append(rec)
        print(
            f"[{i + 1}/{len(quarantined)}] {t['task_id']}: k=40->{t['equivalence_to_golden']}, "
            f"k=200->{formal.verdict} (runtime={formal.runtime_s:.1f}s, near_timeout={near_timeout}) "
            f"-> {decision}"
        )

    out_path = repo_root / "benchmarks" / "corpus_v2" / "deep_bmc_promotions.json"
    out_path.write_text(json.dumps(promotions, indent=2))

    promoted = [r for r in promotions if r["decision"] == "PROMOTE"]
    cycles = sorted(r["divergence_cycle"] for r in promoted if r["divergence_cycle"] is not None)
    shallow = sum(1 for c in cycles if c < 10)
    medium = sum(1 for c in cycles if 10 <= c <= 100)
    deep = sum(1 for c in cycles if c > 100)
    near_timeout_quarantined = sum(1 for r in promotions if r["decision"] == "STAY-QUARANTINE" and r["near_timeout"])

    print()
    print("=== SUMMARY ===")
    print(f"total QUARANTINE re-checked at k={K}: {len(promotions)}")
    print(f"promoted (REFUTED at k=200): {len(promoted)}")
    print(f"stayed QUARANTINE: {len(promotions) - len(promoted)}")
    print(f"  of which near-timeout (runtime >= {NEAR_TIMEOUT_FRACTION * 100:.0f}% of {TIMEOUT_S}s): {near_timeout_quarantined}")
    print(f"divergence_cycle values (promoted): {cycles}")
    print(f"shallow(<10): {shallow}  medium(10-100): {medium}  deep(>100): {deep}")
    print(f"total wall time: {time.time() - start_all:.1f}s")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
