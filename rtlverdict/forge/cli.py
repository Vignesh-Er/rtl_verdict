"""D2 gate driver: generate mutants for a set of designs, verify each with
the diff-fidelity check (Addition 4), report a summary. Not the final
`rtlverdict forge` CLI (no argparse, no corpus.py integration yet - that's
D3) - this is the working generator used to clear the D2 gate for real.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rtlverdict.forge.mutate import apply_candidate, check_fidelity
from rtlverdict.forge.operators import logic, timing
from rtlverdict.forge.parser import parse_file

OPERATORS = [
    logic.operator_swap,
    logic.constant_perturbation,
    timing.blocking_nonblocking_swap,
    timing.edge_swap,
]

DESIGNS = [
    ("fsm", "E:/Hackathon/claude_proj/designs/fsm/fsm.v"),
    ("uart", "E:/Hackathon/claude_proj/designs/uart/uart.v"),
    ("spi_master", "E:/Hackathon/claude_proj/designs/spi_master/spi_master.v"),
]


def main():
    total_candidates = 0
    total_mutants = 0
    total_fidelity_pass = 0
    total_fidelity_fail = 0
    fail_details = []
    by_operator = {}

    for design_name, path in DESIGNS:
        tree, source = parse_file(path)
        all_candidates = []
        for op in OPERATORS:
            cands = op(tree, source)
            all_candidates.extend(cands)
            by_operator.setdefault(op.__module__ + "." + op.__name__, 0)
            by_operator[op.__module__ + "." + op.__name__] += len(cands)

        total_candidates += len(all_candidates)
        print(f"{design_name}: {len(all_candidates)} candidates found")

        for cand in all_candidates:
            mutant_source = apply_candidate(source, cand)
            total_mutants += 1
            result = check_fidelity(source, mutant_source, f"{design_name}_mutant.v", cand.line)
            if result.ok:
                total_fidelity_pass += 1
            else:
                total_fidelity_fail += 1
                fail_details.append((design_name, cand.operator, cand.line, result.reason))

    print()
    print("=== candidates by operator ===")
    for op_name, count in sorted(by_operator.items()):
        print(f"  {op_name}: {count}")
    print()
    print(f"total candidates (= total mutants generated): {total_mutants}")
    print(f"diff-fidelity PASS: {total_fidelity_pass}")
    print(f"diff-fidelity FAIL: {total_fidelity_fail}")
    if fail_details:
        print("\nFAILURES:")
        for d in fail_details[:20]:
            print(f"  {d}")

    gate_pass = total_mutants >= 50 and total_fidelity_fail == 0
    print(f"\nD2 GATE (>=50 mutants, 0 fidelity failures): {'PASS' if gate_pass else 'FAIL'}")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
